from datetime import date, timedelta
from collections import defaultdict
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models import Student, Course, Attendance, student_courses
from app.helpers import admin_required

student_lifecycle_bp = Blueprint('student_lifecycle', __name__)

LONG_ABSENT_STREAK = 3        # consecutive missed sessions
LONG_ABSENT_ATT_RATE = 75.0   # percent attendance threshold
ATT_WINDOW_DAYS = 30

FILTERS = ['all', 'enrolled', 'long_absent', 'completed', 'dropped', 'inactive', 'archived']


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


def _attendance_metrics():
    today = date.today()
    window_start = today - timedelta(days=ATT_WINDOW_DAYS)
    records = Attendance.query.filter(Attendance.person_type == 'student').order_by(
        Attendance.person_id, Attendance.date
    ).all()
    by_student = defaultdict(dict)
    for r in records:
        by_student[r.person_id][r.date] = r.status
    metrics = {}
    for sid, by_date in by_student.items():
        dates = sorted(by_date)
        max_run = 0
        cur = 0
        prev = None
        for d in dates:
            if by_date[d] == 'Absent':
                cur = cur + 1 if prev is not None and (d - prev).days == 1 else 1
                max_run = max(max_run, cur)
            else:
                cur = 0
            prev = d
        last_streak = 0
        for d in reversed(dates):
            if by_date[d] == 'Absent':
                last_streak += 1
            else:
                break
        recent = [d for d in dates if d >= window_start]
        total = len(recent)
        attended = sum(1 for d in recent if by_date[d] != 'Absent')
        rate = (attended / total * 100) if total else None
        metrics[sid] = {
            'max_run': max_run,
            'last_streak': last_streak,
            'att_rate_30': rate,
            'total_marks_30': total,
            'last_attendance_date': dates[-1] if dates else None,
        }
    return metrics


def _derive_bucket(student, enrollments, att):
    if student.status not in ('Active', None):
        return student.status
    if any(e['status'] == 'Dropped' for e in enrollments):
        return 'Dropped'
    long_absent = att['last_streak'] >= LONG_ABSENT_STREAK or (
        att['total_marks_30'] >= 3 and att['att_rate_30'] is not None
        and att['att_rate_30'] < LONG_ABSENT_ATT_RATE
    )
    if long_absent:
        return 'Long Absent'
    if any(e['status'] == 'Completed' for e in enrollments):
        return 'Completed'
    return 'Enrolled'


@student_lifecycle_bp.route('/students/lifecycle')
@login_required
@admin_required
def lifecycle():
    filter_key = request.args.get('filter', 'all')
    if filter_key not in FILTERS:
        filter_key = 'all'
    enroll_map = _enrollment_map()
    att_metrics = _attendance_metrics()
    data = []
    for s in Student.query.order_by(Student.id).all():
        enrolls = enroll_map.get(s.id, [])
        att = att_metrics.get(s.id, {
            'max_run': 0, 'last_streak': 0, 'att_rate_30': None,
            'total_marks_30': 0, 'last_attendance_date': None,
        })
        data.append({
            'student': s,
            'enrollments': enrolls,
            'metrics': att,
            'bucket': _derive_bucket(s, enrolls, att),
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
        thresholds={'streak': LONG_ABSENT_STREAK, 'rate': LONG_ABSENT_ATT_RATE,
                    'window': ATT_WINDOW_DAYS})


def _target_filter():
    f = request.form.get('filter', 'all')
    return f if f in FILTERS else 'all'


@student_lifecycle_bp.route('/students/enrollment/complete/<int:sid>/<int:cid>', methods=['POST'])
@login_required
@admin_required
def complete(sid, cid):
    db.session.execute(
        student_courses.update().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == cid
        ).values(status='Completed', completed_on=date.today())
    )
    db.session.commit()
    flash("Enrollment marked as Completed.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


@student_lifecycle_bp.route('/students/enrollment/drop/<int:sid>/<int:cid>', methods=['POST'])
@login_required
@admin_required
def drop(sid, cid):
    reason = request.form.get('drop_reason', '').strip()
    db.session.execute(
        student_courses.update().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == cid
        ).values(status='Dropped', completed_on=date.today(), drop_reason=reason or None)
    )
    db.session.commit()
    flash("Enrollment marked as Dropped.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))


@student_lifecycle_bp.route('/students/enrollment/reactivate/<int:sid>/<int:cid>', methods=['POST'])
@login_required
@admin_required
def reactivate(sid, cid):
    db.session.execute(
        student_courses.update().where(
            student_courses.c.student_id == sid,
            student_courses.c.course_id == cid
        ).values(status='Enrolled', completed_on=None, drop_reason=None)
    )
    db.session.commit()
    flash("Enrollment reactivated.", "success")
    return redirect(url_for('student_lifecycle.lifecycle', filter=_target_filter()))
