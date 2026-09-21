import csv
import io
import json
from datetime import date, timedelta, datetime
from collections import defaultdict
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models import (Student, Course, Attendance, AuditLog, Enquiry,
                        LifecycleAck, student_courses)
from app.helpers import admin_required, staff_can_view_student

student_lifecycle_bp = Blueprint('student_lifecycle', __name__)

LONG_ABSENT_STREAK = 3        # consecutive missed sessions
LONG_ABSENT_ATT_RATE = 75.0   # percent attendance threshold
ATT_WINDOW_DAYS = 30
MAX_DROP_REASON = 200         # matches student_courses.drop_reason length
# Minimum marks within the window before the rate rule may fire. A student
# only ever marked once who missed that session is, by the data on record,
# 100% absent — hiding behind a "needs 3 marks" gate under-flags exactly the
# at-risk edge cases. Gate of 1 judges students on whatever data exists;
# students with no marks at all are handled separately by the
# enrolled-long-ago / stale-attendance rules.
MIN_MARKS_FOR_RATE = 1
DETAIL_SERIES_LIMIT = 40      # most recent marks returned to the detail drawer
# History bound for attendance scans. The bucket rules only need the window
# rate plus the trailing absence run, so marks older than this never change
# a bucket: a run longer than a year still exceeds any sane streak
# threshold, and window rates ignore older marks by definition. Students
# whose only marks predate the bound are treated as never-marked, which
# resolves to the same bucket via the enrolled-long-ago rule. Display-only
# worst-run counts cap at roughly a year of sessions.
METRICS_LOOKBACK_DAYS = 366

FILTERS = ['all', 'enrolled', 'not_enrolled', 'long_absent', 'completed', 'dropped', 'inactive', 'archived']

# Bulk action buttons only make sense for the statuses the current filter can
# contain. 'not_enrolled' has no enrollments at all, so every bulk button would
# be a guaranteed no-op; 'completed'/'dropped' buckets can only ever be
# reactivated. The route hides the impossible buttons instead of showing them
# and silently doing nothing.
_BULK_VISIBLE = {
    'all': ('complete', 'drop', 'reactivate'),
    'enrolled': ('complete', 'drop', 'reactivate'),
    'long_absent': ('complete', 'drop'),
    'not_enrolled': (),
    'completed': ('reactivate',),
    'dropped': ('reactivate',),
    'inactive': ('complete', 'drop', 'reactivate'),
    'archived': ('complete', 'drop', 'reactivate'),
}

# Sort order for the default table view: students needing attention first.
_BUCKET_ORDER = {'Long Absent': 0, 'Not Enrolled': 1, 'Enrolled': 2,
                 'Dropped': 3, 'Completed': 4, 'Inactive': 5, 'Archived': 6}


def _enrollment_map():
    rows = db.session.query(
        student_courses.c.student_id,
        student_courses.c.course_id,
        student_courses.c.status,
        student_courses.c.enrolled_on,
        student_courses.c.completed_on,
        student_courses.c.drop_reason,
        Course,
    ).join(Course, student_courses.c.course_id == Course.id).order_by(Course.name).all()
    enroll_map = defaultdict(list)
    for row in rows:
        enroll_map[row.student_id].append({
            'course': row.Course,
            'status': row.status or 'Enrolled',
            'enrolled_on': row.enrolled_on,
            'completed_on': row.completed_on,
            'drop_reason': row.drop_reason,
        })
    return enroll_map


# Attendance score per mark: a Half Day counts as half a session. Unknown
# statuses fail open as attended, matching historical behavior.
ATTENDANCE_SCORES = {'Present': 1.0, 'Late': 1.0, 'Half Day': 0.5, 'Absent': 0.0,
                     'Leave': None}

# SystemSetting keys overriding the defaults below (editable on the admin
# console). Absent/invalid values fall back to the constants.
SETTING_STREAK = 'LC_ABSENT_STREAK'
SETTING_RATE = 'LC_ABSENT_RATE'
SETTING_WINDOW = 'LC_ATT_WINDOW_DAYS'


def _default_thresholds():
    return {'streak': LONG_ABSENT_STREAK, 'rate': LONG_ABSENT_ATT_RATE,
            'window': ATT_WINDOW_DAYS}


def _get_thresholds():
    """DB-backed thresholds with sanitization; falls back to defaults."""
    from app.models import SystemSetting
    t = _default_thresholds()
    try:
        streak = SystemSetting.query.filter_by(key=SETTING_STREAK).first()
        rate = SystemSetting.query.filter_by(key=SETTING_RATE).first()
        window = SystemSetting.query.filter_by(key=SETTING_WINDOW).first()
        if streak is not None and streak.value not in (None, ''):
            t['streak'] = max(1, int(float(streak.value)))
        if rate is not None and rate.value not in (None, ''):
            r = float(rate.value)
            if 0 < r <= 100:
                t['rate'] = r
        if window is not None and window.value not in (None, ''):
            t['window'] = max(1, int(float(window.value)))
    except (TypeError, ValueError):
        pass
    return t


def _score_status(status):
    return ATTENDANCE_SCORES.get(status, None)


def _normalize_marks(records):
    """Collapse a student's marks into date -> status.

    Duplicate marks for the same day (e.g. a bulk import racing the upsert
    API) would otherwise resolve by arbitrary row order. Keep the most
    severe status so a recorded absence is never masked.
    """
    by_date = {}
    for r in records:
        existing = by_date.get(r.date)
        score = _score_status(r.status)
        existing_score = _score_status(existing) if existing is not None else None
        if existing is None or (score is not None and (existing_score is None or score < existing_score)):
            by_date[r.date] = r.status
    return by_date


def _metrics_from_marks(by_date, window_start):
    """Derive streak/rate metrics from one student's date -> status map."""
    dates = sorted(by_date)
    # Streaks count consecutive *sessions* (marks in the student's own
    # sequence), not consecutive calendar days — classes don't run every
    # day, so weekend/holiday gaps must not reset the run. Both streak
    # measures use this same definition.
    max_run = 0
    cur = 0
    for d in dates:
        if by_date[d] == 'Absent':
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 0
    last_streak = 0
    for d in reversed(dates):
        if by_date[d] == 'Absent':
            last_streak += 1
        else:
            break
    recent = [d for d in dates if d >= window_start]
    scored_marks = [d for d in recent if _score_status(by_date[d]) is not None]
    total = len(scored_marks)
    scored = sum(_score_status(by_date[d]) for d in scored_marks)
    rate = (scored / total * 100) if total else None
    return {
        'max_run': max_run,
        'last_streak': last_streak,
        'att_rate': rate,
        'total_marks': total,
        'last_attendance_date': dates[-1] if dates else None,
    }


def _attendance_metrics(window_days=ATT_WINDOW_DAYS):
    window_start = date.today() - timedelta(days=window_days)
    # Bound the scan (see METRICS_LOOKBACK_DAYS): the list view used to load
    # every attendance row ever recorded into ORM objects on each page view.
    earliest = date.today() - timedelta(days=max(window_days, METRICS_LOOKBACK_DAYS))
    # Restrict to live students: attendance rows carry a plain person_id
    # (no FK), so rows orphaned by historical deletes are excluded here
    # (and purged by the startup migration in app/__init__.py).
    # Load only the three columns the metrics actually use rather than
    # full ORM objects — the list view previously inflated every row.
    records = db.session.query(
        Attendance.person_id, Attendance.date, Attendance.status
    ).filter(
        Attendance.person_type == 'student',
        Attendance.date >= earliest,
        Attendance.person_id.in_(db.session.query(Student.id))
    ).order_by(Attendance.person_id, Attendance.date).all()
    by_student = defaultdict(list)
    for r in records:
        by_student[r.person_id].append(r)
    return {sid: _metrics_from_marks(_normalize_marks(recs), window_start)
            for sid, recs in by_student.items()}


def _is_long_absent(att, thresholds=None):
    thresholds = thresholds or _default_thresholds()
    return att['last_streak'] >= thresholds['streak'] or (
        att['total_marks'] >= MIN_MARKS_FOR_RATE and att['att_rate'] is not None
        and att['att_rate'] < thresholds['rate']
    )


def _risk_reason(bucket, metrics, thresholds):
    if bucket != 'Long Absent':
        return None
    if metrics.get('last_streak', 0) >= thresholds['streak']:
        return f"{metrics['last_streak']} consecutive absences"
    rate = metrics.get('att_rate')
    if rate is not None and rate < thresholds['rate']:
        return f"Attendance {rate:.0f}% in the last {thresholds['window']} days"
    if metrics.get('last_attendance_date'):
        return f"No attendance recorded in the last {thresholds['window']} days"
    return f"No attendance recorded after {thresholds['window']} days of enrollment"


def _attendance_stale(att, window_days=ATT_WINDOW_DAYS):
    """True when the student's most recent mark predates the window.

    Covers the gap where a student attended a few times, then simply
    stopped being marked (their last mark is Present, so neither the
    streak nor the rate rule fires) — without this they stay "Enrolled"
    forever.
    """
    last = att['last_attendance_date']
    if last is None:
        return False
    return (date.today() - last).days > window_days


def _enrolled_long_ago(student, enrollments, window_days=ATT_WINDOW_DAYS):
    """True when the active enrollment predates the attendance window.

    Used to flag students who never attended anything despite being
    enrolled for a while (their window rate is None, so the normal
    long-absent rule never fires for them). Judged by the *active*
    enrollment's date: a student re-enrolled yesterday must not inherit
    the age of an old dropped course.
    """
    active = [e.get('enrolled_on') for e in enrollments
              if e.get('status') == 'Enrolled' and e.get('enrolled_on')]
    dates = active or [e.get('enrolled_on') for e in enrollments if e.get('enrolled_on')]
    if not dates and getattr(student, 'enrollment_date', None):
        dates = [student.enrollment_date]
    if not dates:
        return False
    return (date.today() - min(dates)).days > window_days


def _canonical_status(status):
    """Map legacy/unrecognized student.status values onto the bucket vocabulary.

    The forms only ever write Active/Inactive/Archived, but imported or very
    old rows can carry anything ('' or 'Suspended', for example). Folding
    them into 'Inactive' keeps those students visible and actionable instead
    of creating a bucket no filter can match. 'Archived' keeps its own bucket.
    """
    if status in ('Active', None):
        return 'Active'
    if status == 'Archived':
        return 'Archived'
    return 'Inactive'


def _derive_bucket(student, enrollments, att, thresholds=None):
    thresholds = thresholds or _default_thresholds()
    if _canonical_status(student.status) != 'Active':
        return _canonical_status(student.status)
    if not enrollments:
        return 'Not Enrolled'
    statuses = {e['status'] for e in enrollments}
    if 'Enrolled' in statuses:
        # A currently-active enrollment takes precedence over any historic
        # Dropped/Completed rows; still surface attendance risk.
        if _is_long_absent(att, thresholds):
            return 'Long Absent'
        if att['last_attendance_date'] is None:
            # Never marked: flag once they've been enrolled past the window.
            if _enrolled_long_ago(student, enrollments, thresholds['window']):
                return 'Long Absent'
        elif _attendance_stale(att, thresholds['window']) and _enrolled_long_ago(
                student, enrollments, thresholds['window']):
            # Marked, but nothing recent: they stopped showing up.
            return 'Long Absent'
        return 'Enrolled'
    if 'Dropped' in statuses and 'Completed' not in statuses:
        return 'Dropped'
    if 'Completed' in statuses:
        return 'Completed'
    return 'Dropped'


@student_lifecycle_bp.route('/students/lifecycle')
@login_required
def lifecycle():
    is_admin = current_user.role == 'Admin'
    filter_key = request.args.get('filter', 'all')
    if filter_key not in FILTERS:
        filter_key = 'all'
    q = (request.args.get('q') or '').strip()
    selected_course_id = request.args.get('course_id', type=int)
    selected_year = request.args.get('year', type=int)
    risk_filter = request.args.get('risk', 'all')
    review_filter = request.args.get('review', 'all')
    ds = _lifecycle_dataset(filter_key, q, selected_course_id, selected_year,
                            risk_filter, review_filter)
    ack_map = {a.student_id: a for a in LifecycleAck.query.all()}
    for d in ds['data']:
        d['suggest_archive'] = _suggest_archive(d, ds['thresholds'])
    return render_template('student_lifecycle.html', lifecycle=ds['data'],
        counts=ds['counts'], total_all=ds['total_all'], shown=ds['shown'],
        filter_key=filter_key, today=date.today(),
        thresholds=ds['thresholds'], courses=Course.query.order_by(Course.name).all(),
        selected_course_id=selected_course_id, q=q,
        selected_year=selected_year, risk_filter=risk_filter,
        review_filter=review_filter,
        years=_available_years(),
        kpis=_course_kpis(ds['data']),
        is_admin=is_admin, ack_map=ack_map,
        bulk_actions=(_BULK_VISIBLE.get(filter_key, ('complete', 'drop', 'reactivate'))
                      if is_admin else ()))


def _lifecycle_dataset(filter_key='all', q='', selected_course_id=None,
                       selected_year=None, risk_filter='all', review_filter='all'):
    """Build the (unfiltered) lifecycle rows plus bucket counts.

    Shared by the page view and the CSV export so both honor exactly the same
    filters. The returned rows are plain dicts; the view enriches them for
    display (ack state, archive suggestions).
    """
    enroll_map = _enrollment_map()
    thresholds = _get_thresholds()
    att_metrics = _attendance_metrics(thresholds['window'])
    data = []
    students = Student.query.order_by(Student.id).all()
    for s in students:
        enrolls = enroll_map.get(s.id, [])
        att = att_metrics.get(s.id, {
            'max_run': 0, 'last_streak': 0, 'att_rate': None,
            'total_marks': 0, 'last_attendance_date': None,
        })
        bucket = _derive_bucket(s, enrolls, att, thresholds)
        data.append({
            'student': s,
            'enrollments': enrolls,
            'metrics': att,
            'bucket': bucket,
            'risk_reason': _risk_reason(bucket, att, thresholds),
        })
    if current_user.role == 'Staff':
        data = [d for d in data if staff_can_view_student(d['student'].id)]
    # Counts stay global within the viewer's authorized scope.
    counts = defaultdict(int)
    for d in data:
        counts[d['bucket']] += 1
    total_all = len(data)

    if selected_course_id:
        data = [d for d in data
                if any(e['course'].id == selected_course_id for e in d['enrollments'])]
    if q:
        needle = q.lower()

        def _matches(d):
            s = d['student']
            return any(needle in (field or '').lower() for field in
                       (s.name, s.phone, s.email, s.roll_no))
        data = [d for d in data if _matches(d)]

    if selected_year:
        def _min_year(d):
            years = [e['enrolled_on'].year for e in d['enrollments'] if e['enrolled_on']]
            if d['student'].enrollment_date:
                years.append(d['student'].enrollment_date.year)
            return min(years) if years else None
        data = [d for d in data if _min_year(d) == selected_year]

    if filter_key != 'all':
        if filter_key == 'inactive':
            # B5/B6: legacy statuses are folded into 'Inactive', and the
            # inactive pill intentionally groups Inactive + Archived students.
            data = [d for d in data if d['bucket'] in ('Inactive', 'Archived')]
        else:
            target = filter_key.replace('_', ' ')
            data = [d for d in data if d['bucket'].lower() == target]

    if risk_filter == 'at_risk':
        data = [d for d in data if d['bucket'] == 'Long Absent']
    elif risk_filter == 'watch':
        data = [d for d in data if d['metrics'].get('att_rate') is not None
                and d['metrics']['att_rate'] < thresholds['rate']]
    if review_filter in ('reviewed', 'pending'):
        acknowledged = {a.student_id for a in LifecycleAck.query.all()}
        if review_filter == 'reviewed':
            data = [d for d in data if d['student'].id in acknowledged]
        else:
            data = [d for d in data if d['student'].id not in acknowledged]

    # Default view: surface students who need attention first.
    data.sort(key=lambda d: (_BUCKET_ORDER.get(d['bucket'], 99),
                             (d['student'].name or '').lower()))
    return {'data': data, 'counts': dict(counts), 'total_all': total_all,
            'shown': len(data), 'thresholds': thresholds}


def _available_years():
    """Distinct enrollment years (from association rows + student join dates)."""
    years = {date.today().year}
    for (d,) in db.session.query(student_courses.c.enrolled_on).all():
        if d:
            years.add(d.year)
    for (d,) in db.session.query(Student.enrollment_date).all():
        if d:
            years.add(d.year)
    return sorted(years, reverse=True)


def _suggest_archive(d, thresholds):
    """True when a Long Absent student has vanished long enough to archive.

    Suggestions only: the row shows an Archive? chip, never auto-archives.
    Judged by the same rules that decide Long Absent, stretched to double the
    window so casual gaps don't trigger it.
    """
    if d['bucket'] != 'Long Absent' or d['student'].status != 'Active':
        return False
    att = d['metrics']
    long_window = thresholds['window'] * 2
    last = att.get('last_attendance_date')
    if last is not None:
        return (date.today() - last).days > long_window
    # Never marked: only suggest after an absurdly long silent enrollment.
    return _enrolled_long_ago(d['student'], d['enrollments'], long_window)


def _course_kpis(data):
    """Per-course retention KPIs (enrolled/completed/dropped/long-absent)."""
    stats = defaultdict(lambda: {'enrolled': 0, 'completed': 0, 'dropped': 0,
                                 'long_absent': 0, 'ever': 0})
    this_year = date.today().year
    long_absent_sids = {d['student'].id for d in data if d['bucket'] == 'Long Absent'}
    for d in data:
        sid = d['student'].id
        for e in d['enrollments']:
            cid = e['course'].id
            stats[cid]['ever'] += 1
            if e['status'] == 'Enrolled':
                stats[cid]['enrolled'] += 1
                if sid in long_absent_sids:
                    stats[cid]['long_absent'] += 1
            elif e['status'] == 'Completed':
                stats[cid]['completed'] += 1
            elif e['status'] == 'Dropped':
                stats[cid]['dropped'] += 1
    out = []
    for c in Course.query.order_by(Course.name).all():
        s = stats.get(c.id)
        if not s or not s['ever']:
            continue
        s = dict(s)
        s['course'] = c.name
        s['completion_rate'] = round(s['completed'] / s['ever'] * 100, 1)
        s['dropout_rate'] = round(s['dropped'] / s['ever'] * 100, 1)
        s['retention'] = round(s['enrolled'] / s['ever'] * 100, 1)
        s['joined_this_year'] = sum(
            1 for d in data
            for e in d['enrollments']
            if e['course'].id == c.id and e['enrolled_on']
            and e['enrolled_on'].year == this_year)
        out.append(s)
    return sorted(out, key=lambda r: r['course'])


@student_lifecycle_bp.route('/students/lifecycle/<int:sid>/detail')
@login_required
def detail(sid):
    """On-demand payload for the per-student drawer (timeline + sparkline).

    Loaded lazily rather than rendered into every table row so the list
    view stays cheap regardless of how much attendance history exists.
    """
    if not staff_can_view_student(sid):
        return jsonify({'error': 'You do not have access to this student'}), 403
    student = Student.query.get_or_404(sid)
    thresholds = _get_thresholds()
    window_start = date.today() - timedelta(days=thresholds['window'])
    enrolls = _enrollment_map().get(sid, [])
    earliest = date.today() - timedelta(
        days=max(thresholds['window'], METRICS_LOOKBACK_DAYS))
    records = Attendance.query.filter_by(
        person_type='student', person_id=sid).filter(
        Attendance.date >= earliest).all()
    by_date = _normalize_marks(records)
    metrics = _metrics_from_marks(by_date, window_start)
    total_recorded = db.session.query(db.func.count(Attendance.id)).filter_by(
        person_type='student', person_id=sid).scalar() or 0
    bucket = _derive_bucket(student, enrolls, metrics, thresholds)
    # jsonify renders bare dates in RFC-822 form; the drawer expects ISO.
    json_metrics = dict(metrics)
    if json_metrics['last_attendance_date'] is not None:
        json_metrics['last_attendance_date'] = \
            json_metrics['last_attendance_date'].isoformat()
    all_dates = sorted(by_date)
    series = [{
        'date': d.isoformat(),
        'status': by_date[d],
        'score': _score_status(by_date[d]),
    } for d in all_dates[-DETAIL_SERIES_LIMIT:]]

    timeline = []
    for e in enrolls:
        # Association rows created before the backfill can lack a date; fall
        # back to the student's join date so the timeline stays readable.
        enrolled = e['enrolled_on'] or student.enrollment_date
        completed = e['completed_on']
        if e['status'] == 'Enrolled':
            end_for_duration = date.today()
        else:
            end_for_duration = completed or enrolled
        timeline.append({
            'course_id': e['course'].id,
            'course': e['course'].name,
            'status': e['status'],
            'enrolled_on': enrolled.isoformat() if enrolled else None,
            'completed_on': completed.isoformat() if completed else None,
            'drop_reason': e['drop_reason'],
            'days': (end_for_duration - enrolled).days
            if (enrolled and end_for_duration) else None,
        })
    timeline.sort(key=lambda t: t['enrolled_on'] or '', reverse=True)

    ack = LifecycleAck.query.filter_by(student_id=sid).first()
    ack_payload = None
    if ack:
        ack_payload = {
            'reviewed': True,
            'acknowledged_on': ack.acknowledged_on.isoformat()
            if ack.acknowledged_on else None,
            'acknowledged_by': ack.acknowledged_by,
            'note': ack.note,
        }
    # Lead origin (enquiry pipe) so a reviewer sees how this student came in.
    enquiry = None
    if student.email:
        enquiry = Enquiry.query.filter(
            db.func.lower(Enquiry.email) == student.email.lower()
        ).order_by(Enquiry.id).first()
    if enquiry is None and student.phone:
        enquiry = Enquiry.query.filter_by(phone=student.phone).order_by(Enquiry.id).first()
    enquiry_payload = None
    if enquiry:
        enquiry_payload = {
            'student_name': enquiry.student_name,
            'source': enquiry.source,
            'status': enquiry.status,
            'notes': enquiry.notes,
            'follow_up_date': enquiry.follow_up_date.isoformat()
            if enquiry.follow_up_date else None,
        }
    # Recent activity: this student's audit trail, newest first.
    logs = AuditLog.query.filter_by(
        entity_type='Student', entity_id=sid
    ).order_by(AuditLog.id.desc()).limit(12).all()
    activity = [{
        'action': l.action,
        'username': l.username,
        'changes': l.changes,
        'timestamp': l.timestamp.isoformat() if l.timestamp else None,
    } for l in logs]

    return jsonify({
        'student': {
            'id': student.id,
            'name': student.name,
            'phone': student.phone,
            'email': student.email,
            'roll_no': student.roll_no,
            'status': student.status,
            'enrollment_date': student.enrollment_date.isoformat()
            if student.enrollment_date else None,
            'bucket': bucket,
        },
        'thresholds': thresholds,
        'attendance': {
            'series': series,
            'window': thresholds['window'],
            'metrics': json_metrics,
            'total_recorded': total_recorded,
        },
        'enrollments': timeline,
        'ack': ack_payload,
        'enquiry': enquiry_payload,
        'activity': activity,
        'is_admin': current_user.role == 'Admin',
    })


def _target_filter():
    f = request.form.get('filter', 'all')
    return f if f in FILTERS else 'all'


def _enrollment_or_404(sid, cid):
    """Fetch the student_courses row or 404 (transitions used to silently
    "succeed" for nonexistent enrollments)."""
    row = db.session.execute(
        student_courses.select().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == cid)
    ).first()
    if row is None:
        abort(404)
    return row


# Which current enrollment statuses each single-row transition is valid from.
# The bulk endpoint scopes by source status; the single-row endpoints must do
# the same, or a stale page / double submit can silently drop a Completed
# enrollment, re-stamp completed_on on an already-completed course, or reset a
# live enrollment's terminal history for no reason.
_TRANSITION_ALLOWED = {
    'complete': ('Enrolled',),
    'drop': ('Enrolled',),
    'reactivate': ('Completed', 'Dropped'),
}


def _guard_transition(sid, cid, action):
    """Return the enrollment row if current status allows the transition, else
    flash a warning and return None (caller redirects back to the console)."""
    row = _enrollment_or_404(sid, cid)
    current = row.status or 'Enrolled'
    if current not in _TRANSITION_ALLOWED[action]:
        flash(f"Cannot {action} — this enrollment is already {current}.", "warning")
        return None
    return row


def _audit_transition(sid, cid, action, detail):
    """Association-table writes bypass the ORM audit events in app/audit.py,
    so lifecycle transitions are logged here explicitly."""
    db.session.add(AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        username=current_user.username if current_user.is_authenticated else 'system',
        action='UPDATE',
        entity_type='Student',
        entity_id=sid,
        changes=json.dumps({'enrollment': {'course_id': cid, action: detail}}),
    ))


@student_lifecycle_bp.route('/students/enrollment/complete/<int:sid>/<int:cid>', methods=['POST'])
@login_required
@admin_required
def complete(sid, cid):
    row = _guard_transition(sid, cid, 'complete')
    if row is None:
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    previous = row.status or 'Enrolled'
    db.session.execute(
        student_courses.update().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == cid
        ).values(status='Completed', completed_on=date.today())
    )
    _audit_transition(sid, cid, 'complete',
                      {'from': previous, 'to': 'Completed',
                       'completed_on': date.today().isoformat()})
    db.session.commit()
    flash("Enrollment marked as Completed.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


@student_lifecycle_bp.route('/students/enrollment/drop/<int:sid>/<int:cid>', methods=['POST'])
@login_required
@admin_required
def drop(sid, cid):
    reason = request.form.get('drop_reason', '').strip()
    if len(reason) > MAX_DROP_REASON:
        flash(f"Drop reason must be at most {MAX_DROP_REASON} characters.", "danger")
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    row = _guard_transition(sid, cid, 'drop')
    if row is None:
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    previous = row.status or 'Enrolled'
    db.session.execute(
        student_courses.update().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == cid
        # NB: completed_on is deliberately left untouched — a dropped
        # enrollment is not a completion, and writing today() there
        # polluted completion dates for anything reading the column.
        ).values(status='Dropped', drop_reason=reason or None)
    )
    _audit_transition(sid, cid, 'drop',
                      {'from': previous, 'to': 'Dropped',
                       'drop_reason': reason or None})
    db.session.commit()
    flash("Enrollment marked as Dropped.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


@student_lifecycle_bp.route('/students/enrollment/reactivate/<int:sid>/<int:cid>', methods=['POST'])
@login_required
@admin_required
def reactivate(sid, cid):
    row = _guard_transition(sid, cid, 'reactivate')
    if row is None:
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    previous = row.status or 'Enrolled'
    db.session.execute(
        student_courses.update().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == cid
        ).values(status='Enrolled', completed_on=None, drop_reason=None)
    )
    _audit_transition(sid, cid, 'reactivate',
                      {'from': previous, 'to': 'Enrolled'})
    db.session.commit()
    flash("Enrollment reactivated.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


# Which enrollment statuses each bulk action applies to, and the resulting
# status. Student-level selection keeps the UI simple (one checkbox per row).
_BULK_SOURCES = {
    'complete': (('Enrolled',), 'Completed'),
    'drop': (('Enrolled',), 'Dropped'),
    'reactivate': (('Completed', 'Dropped'), 'Enrolled'),
}


@student_lifecycle_bp.route('/students/enrollment/bulk', methods=['POST'])
@login_required
@admin_required
def bulk():
    action = request.form.get('bulk_action', '')
    if action not in _BULK_SOURCES:
        flash("Unknown bulk action.", "danger")
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    student_ids = set()
    for raw in request.form.getlist('selected'):
        try:
            student_ids.add(int(raw))
        except (TypeError, ValueError):
            continue
    if not student_ids:
        flash("No students selected.", "warning")
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    reason = ''
    if action == 'drop':
        reason = request.form.get('bulk_reason', '').strip()
        if len(reason) > MAX_DROP_REASON:
            flash(f"Drop reason must be at most {MAX_DROP_REASON} characters.", "danger")
            return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    source_statuses, target = _BULK_SOURCES[action]
    # When the list is course-filtered, only that course's rows are in view —
    # touching every enrollment of a selected student would surprise the admin.
    scoped_cid = request.form.get('course_id', type=int)
    today = date.today()
    updated = 0
    skipped = 0
    for sid in student_ids:
        rows = db.session.execute(
            student_courses.select().where(student_courses.c.student_id == sid)
        ).all()
        # Tally students whose visible rows were all ineligible so the flash
        # explains why some selections weren't touched (opaque "0 updated" is
        # the bug this addresses).
        if not any(
            (r.status or 'Enrolled') in source_statuses
            and (not scoped_cid or r.course_id == scoped_cid)
            for r in rows
        ):
            skipped += 1
        for row in rows:
            if (row.status or 'Enrolled') not in source_statuses:
                continue
            if scoped_cid and row.course_id != scoped_cid:
                continue
            values = {'status': target}
            if action == 'complete':
                values['completed_on'] = today
            elif action == 'drop':
                values['drop_reason'] = reason or None
            else:
                values['completed_on'] = None
                values['drop_reason'] = None
            db.session.execute(
                student_courses.update().where(
                    student_courses.c.student_id == sid,
                    student_courses.c.course_id == row.course_id
                ).values(**values)
            )
            detail = {'from': row.status or 'Enrolled', 'to': target}
            if action == 'complete':
                detail['completed_on'] = today.isoformat()
            if action == 'drop':
                detail['drop_reason'] = reason or None
            _audit_transition(sid, row.course_id, action, detail)
            updated += 1
    db.session.commit()
    flash(f"{updated} enrollment(s) updated"
          + (f", {skipped} selected student(s) had no eligible enrollment." if skipped else "")
          + ".", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


@student_lifecycle_bp.route('/students/lifecycle/<int:sid>/acknowledge', methods=['POST'])
@login_required
@admin_required
def acknowledge(sid):
    """Mark a student as reviewed in the lifecycle console (upsert).

    One ack row per student; re-acking just refreshes who/when. The action is
    also appended to the audit trail (reviewed state is meant to be visible
    to staff, the who/when trail to admins).
    """
    student = Student.query.get_or_404(sid)
    note = (request.form.get('note') or '').strip()[:500]
    ack = LifecycleAck.query.filter_by(student_id=sid).first()
    if ack is None:
        ack = LifecycleAck(student_id=sid)
        db.session.add(ack)
    ack.acknowledged_on = datetime.utcnow()
    ack.acknowledged_by = current_user.username
    ack.note = note or None
    db.session.add(AuditLog(
        user_id=current_user.id,
        username=current_user.username,
        action='UPDATE',
        entity_type='Student',
        entity_id=sid,
        changes=json.dumps({'lifecycle': {'acknowledged': True,
                                          'note': ack.note or ''}}),
    ))
    db.session.commit()
    flash(f"Marked {student.name} as reviewed.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


_STUDENT_STATUSES = ('Active', 'Inactive', 'Archived')


@student_lifecycle_bp.route('/students/lifecycle/<int:sid>/status', methods=['POST'])
@login_required
@admin_required
def set_status(sid):
    """Change a student's overall status (reactivate / set inactive / archive)."""
    student = Student.query.get_or_404(sid)
    target = request.form.get('status', '')
    if target not in _STUDENT_STATUSES:
        flash("Invalid status.", "danger")
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    previous = student.status or 'Active'
    if previous == target:
        flash(f"{student.name} is already {target}.", "info")
        return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
    # The Student before_update audit listener (app/audit.py) records the
    # exact from/to for us — no explicit log here, or status changes would
    # be double-audited (form edits rely on that same listener).
    student.status = target
    db.session.commit()
    flash(f"{student.name} marked as {target}.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


@student_lifecycle_bp.route('/students/enrollment/transfer', methods=['POST'])
@login_required
@admin_required
def transfer():
    """Move an active enrollment while preserving its previous history."""
    sid = request.form.get('student_id', type=int)
    from_cid = request.form.get('from_course_id', type=int)
    to_cid = request.form.get('to_course_id', type=int)
    reason = (request.form.get('reason') or '').strip()[:MAX_DROP_REASON]
    if not sid or not from_cid or not to_cid or from_cid == to_cid:
        flash('Choose a student and two different courses.', 'danger')
        return redirect(url_for('student_lifecycle.lifecycle'))
    source = _guard_transition(sid, from_cid, 'drop')
    student = Student.query.get_or_404(sid)
    target = Course.query.get_or_404(to_cid)
    if source is None:
        return redirect(url_for('student_lifecycle.lifecycle'))
    existing = db.session.execute(student_courses.select().where(
        student_courses.c.student_id == sid,
        student_courses.c.course_id == to_cid)).first()
    if existing and (existing.status or 'Enrolled') == 'Enrolled':
        flash(f'{student.name} is already enrolled in {target.name}.', 'warning')
        return redirect(url_for('student_lifecycle.lifecycle'))
    db.session.execute(student_courses.update().where(
        student_courses.c.student_id == sid,
        student_courses.c.course_id == from_cid
    ).values(status='Dropped', drop_reason=reason or f'Transferred to {target.name}'))
    if existing:
        db.session.execute(student_courses.update().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == to_cid
        ).values(status='Enrolled', enrolled_on=date.today(), completed_on=None,
                 drop_reason=None))
    else:
        db.session.execute(student_courses.insert().values(
            student_id=sid, course_id=to_cid, status='Enrolled',
            enrolled_on=date.today()))
    db.session.add(AuditLog(
        user_id=current_user.id, username=current_user.username, action='UPDATE',
        entity_type='Student', entity_id=sid,
        changes=json.dumps({'enrollment_transfer': {
            'from_course_id': from_cid, 'to_course_id': to_cid,
            'reason': reason or None}})))
    db.session.commit()
    flash(f'{student.name} transferred to {target.name}.', 'success')
    return redirect(url_for('student_lifecycle.lifecycle'))


@student_lifecycle_bp.route('/students/lifecycle/export')
@login_required
def export():
    """CSV of the current (filtered) lifecycle roster — staff can view it too.

    Mirrors the page's filter/q/course/year so "export what I see" holds.
    """
    filter_key = request.args.get('filter', 'all')
    if filter_key not in FILTERS:
        filter_key = 'all'
    q = (request.args.get('q') or '').strip()
    selected_course_id = request.args.get('course_id', type=int)
    selected_year = request.args.get('year', type=int)
    risk_filter = request.args.get('risk', 'all')
    review_filter = request.args.get('review', 'all')
    ds = _lifecycle_dataset(filter_key, q, selected_course_id, selected_year,
                            risk_filter, review_filter)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Name', 'Roll No', 'Phone', 'Email', 'Status', 'Bucket',
                     'Risk reason', 'Courses', 'Attendance %', 'Attendance (window)', 'Last Activity'])
    for d in ds['data']:
        s = d['student']
        m = d['metrics']
        courses = '; '.join(
            f"{e['course'].name} ({e['status']})" for e in d['enrollments']
        )
        writer.writerow([
            s.name or '',
            s.roll_no or '',
            s.phone or '',
            s.email or '',
            s.status or '',
            d['bucket'],
            d.get('risk_reason') or '',
            courses,
            '' if m['att_rate'] is None else f"{m['att_rate']:.1f}",
            m['total_marks'],
            m['last_attendance_date'].isoformat() if m['last_attendance_date'] else '',
        ])
    out = buf.getvalue()
    buf.close()
    filename = f"lifecycle_{filter_key}_{date.today().isoformat()}.csv"
    return send_file(
        io.BytesIO(out.encode('utf-8', errors='replace')),
        mimetype='text/csv', as_attachment=True, download_name=filename)


@student_lifecycle_bp.route('/students/lifecycle/report')
@login_required
def report():
    """Compact reporting payload for dashboards and scheduled monitors."""
    ds = _lifecycle_dataset('all')
    rows = ds['data']
    total = len(rows)
    reviewed = {a.student_id for a in LifecycleAck.query.all()}
    return jsonify({
        'generated_on': date.today().isoformat(),
        'total_students': total,
        'enrolled': sum(d['bucket'] == 'Enrolled' for d in rows),
        'long_absent': sum(d['bucket'] == 'Long Absent' for d in rows),
        'completed': sum(d['bucket'] == 'Completed' for d in rows),
        'dropped': sum(d['bucket'] == 'Dropped' for d in rows),
        'not_enrolled': sum(d['bucket'] == 'Not Enrolled' for d in rows),
        'pending_review': sum(d['bucket'] == 'Long Absent' and
                              d['student'].id not in reviewed for d in rows),
        'thresholds': ds['thresholds'],
    })
