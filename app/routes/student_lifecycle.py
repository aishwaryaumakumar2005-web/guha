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

FILTERS = ['all', 'enrolled', 'not_enrolled', 'long_absent', 'completed', 'dropped', 'inactive', 'archived']


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


def _attendance_metrics(window_days=ATT_WINDOW_DAYS):
    today = date.today()
    window_start = today - timedelta(days=window_days)
    # Restrict to live students: attendance rows carry a plain person_id
    # (no FK), so rows orphaned by historical deletes are excluded here
    # (and purged by the startup migration in app/__init__.py).
    records = Attendance.query.filter(
        Attendance.person_type == 'student',
        Attendance.person_id.in_(db.session.query(Student.id))
    ).order_by(Attendance.person_id, Attendance.date).all()
    by_student = defaultdict(dict)
    for r in records:
        by_student[r.person_id][r.date] = r.status
    metrics = {}
    for sid, by_date in by_student.items():
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
        metrics[sid] = {
            'max_run': max_run,
            'last_streak': last_streak,
            'att_rate': rate,
            'total_marks': total,
            'last_attendance_date': dates[-1] if dates else None,
        }
    return metrics


def _is_long_absent(att, thresholds=None):
    thresholds = thresholds or _default_thresholds()
    return att['last_streak'] >= thresholds['streak'] or (
        att['total_marks'] >= 3 and att['att_rate'] is not None
        and att['att_rate'] < thresholds['rate']
    )


def _enrolled_long_ago(student, enrollments, window_days=ATT_WINDOW_DAYS):
    """True when the earliest known enrollment predates the attendance window.

    Used to flag students who never attended anything despite being
    enrolled for a while (their window rate is None, so the normal
    long-absent rule never fires for them).
    """
    dates = [e.get('enrolled_on') for e in enrollments if e.get('enrolled_on')]
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
        if att['last_attendance_date'] is None and _enrolled_long_ago(
                student, enrollments, thresholds['window']):
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
    counts = defaultdict(int)
    for d in data:
        counts[d['bucket']] += 1
    total = len(data)
    if filter_key != 'all':
        if filter_key == 'inactive':
            data = [d for d in data if d['bucket'] in ('Inactive', 'Archived')]
        else:
            target = filter_key.replace('_', ' ')
            data = [d for d in data if d['bucket'].lower() == target]
    return render_template('student_lifecycle.html', lifecycle=data, counts=counts,
        total=total, filter_key=filter_key, today=date.today(),
        thresholds=thresholds)


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
        ).values(status='Dropped', completed_on=date.today(), drop_reason=reason or None)
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
