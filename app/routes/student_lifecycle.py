import json
from datetime import date, timedelta
from collections import defaultdict
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Student, Course, Attendance, AuditLog, student_courses
from app.helpers import admin_required

student_lifecycle_bp = Blueprint('student_lifecycle', __name__)

LONG_ABSENT_STREAK = 3        # consecutive missed sessions
LONG_ABSENT_ATT_RATE = 75.0   # percent attendance threshold
ATT_WINDOW_DAYS = 30
MAX_DROP_REASON = 200         # matches student_courses.drop_reason length
MIN_MARKS_FOR_RATE = 3        # minimum marks before the rate rule can fire
DETAIL_SERIES_LIMIT = 40      # most recent marks returned to the detail drawer

FILTERS = ['all', 'enrolled', 'not_enrolled', 'long_absent', 'completed', 'dropped', 'inactive', 'archived']

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
ATTENDANCE_SCORES = {'Present': 1.0, 'Late': 1.0, 'Half Day': 0.5, 'Absent': 0.0}

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
    return ATTENDANCE_SCORES.get(status, 1.0)


def _normalize_marks(records):
    """Collapse a student's marks into date -> status.

    Duplicate marks for the same day (e.g. a bulk import racing the upsert
    API) would otherwise resolve by arbitrary row order. Keep the most
    severe status so a recorded absence is never masked.
    """
    by_date = {}
    for r in records:
        existing = by_date.get(r.date)
        if existing is None or _score_status(r.status) < _score_status(existing):
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
    total = len(recent)
    scored = sum(_score_status(by_date[d]) for d in recent)
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
    # Restrict to live students: attendance rows carry a plain person_id
    # (no FK), so rows orphaned by historical deletes are excluded here
    # (and purged by the startup migration in app/__init__.py).
    records = Attendance.query.filter(
        Attendance.person_type == 'student',
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


def _derive_bucket(student, enrollments, att, thresholds=None):
    thresholds = thresholds or _default_thresholds()
    if student.status not in ('Active', None):
        return student.status
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
@admin_required
def lifecycle():
    filter_key = request.args.get('filter', 'all')
    if filter_key not in FILTERS:
        filter_key = 'all'
    q = (request.args.get('q') or '').strip()
    selected_course_id = request.args.get('course_id', type=int)
    enroll_map = _enrollment_map()
    thresholds = _get_thresholds()
    att_metrics = _attendance_metrics(thresholds['window'])
    data = []
    for s in Student.query.order_by(Student.id).all():
        enrolls = enroll_map.get(s.id, [])
        att = att_metrics.get(s.id, {
            'max_run': 0, 'last_streak': 0, 'att_rate': None,
            'total_marks': 0, 'last_attendance_date': None,
        })
        data.append({
            'student': s,
            'enrollments': enrolls,
            'metrics': att,
            'bucket': _derive_bucket(s, enrolls, att, thresholds),
        })
    # Counts stay global (unaffected by search/course filters) so the filter
    # pills don't move while the admin types.
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

    if filter_key != 'all':
        if filter_key == 'inactive':
            data = [d for d in data if d['bucket'] in ('Inactive', 'Archived')]
        else:
            target = filter_key.replace('_', ' ')
            data = [d for d in data if d['bucket'].lower() == target]

    # Default view: surface students who need attention first.
    data.sort(key=lambda d: (_BUCKET_ORDER.get(d['bucket'], 99),
                             (d['student'].name or '').lower()))
    shown = len(data)
    return render_template('student_lifecycle.html', lifecycle=data, counts=counts,
        total_all=total_all, shown=shown, filter_key=filter_key, today=date.today(),
        thresholds=thresholds, courses=Course.query.order_by(Course.name).all(),
        selected_course_id=selected_course_id, q=q)


@student_lifecycle_bp.route('/students/lifecycle/<int:sid>/detail')
@login_required
@admin_required
def detail(sid):
    """On-demand payload for the per-student drawer (timeline + sparkline).

    Loaded lazily rather than rendered into every table row so the list
    view stays cheap regardless of how much attendance history exists.
    """
    student = Student.query.get_or_404(sid)
    thresholds = _get_thresholds()
    window_start = date.today() - timedelta(days=thresholds['window'])
    enrolls = _enrollment_map().get(sid, [])
    records = Attendance.query.filter_by(
        person_type='student', person_id=sid).all()
    by_date = _normalize_marks(records)
    metrics = _metrics_from_marks(by_date, window_start)
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
            'total_recorded': len(all_dates),
        },
        'enrollments': timeline,
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
    row = _enrollment_or_404(sid, cid)
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
    row = _enrollment_or_404(sid, cid)
    reason = request.form.get('drop_reason', '').strip()
    if len(reason) > MAX_DROP_REASON:
        flash(f"Drop reason must be at most {MAX_DROP_REASON} characters.", "danger")
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
    row = _enrollment_or_404(sid, cid)
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
    for sid in student_ids:
        rows = db.session.execute(
            student_courses.select().where(student_courses.c.student_id == sid)
        ).all()
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
    flash(f"{updated} enrollment(s) updated.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
