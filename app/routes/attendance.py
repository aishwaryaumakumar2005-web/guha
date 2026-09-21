from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify, flash, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Attendance, Student, Tutor, AuditLog, student_courses

attendance_bp = Blueprint('attendance', __name__)

ATTENDANCE_STATUSES = ('Present', 'Absent', 'Late', 'Half Day', 'Leave')
DEFAULT_STATUS = 'Present'

STATUS_BADGE = {
    'Present': 'badge-active',
    'Absent': 'badge-danger',
    'Late': 'badge-amber',
    'Half Day': 'badge-cyan',
    'Leave': 'badge-inactive',
}


def _parse_day(raw):
    """Parse a YYYY-MM-DD date for the roster view; None if invalid."""
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _int_person_id(data):
    try:
        person_id = int(data.get('person_id'))
    except (TypeError, ValueError):
        return None
    return person_id if person_id > 0 else None


def _active_student_ids_for_tutor(tutor):
    course_ids = [c.id for c in tutor.courses if (c.status or 'Active') != 'Archived']
    if not course_ids:
        return set()
    rows = db.session.query(student_courses.c.student_id).filter(
        student_courses.c.course_id.in_(course_ids),
        db.or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None))
    ).distinct().all()
    return {row[0] for row in rows}


def _audit_change(record, previous, source):
    if previous == record.status:
        return
    import json
    db.session.add(AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        username=current_user.username if current_user.is_authenticated else 'system',
        action='UPDATE', entity_type='Attendance', entity_id=record.id,
        changes=json.dumps({'person_type': record.person_type,
                            'person_id': record.person_id,
                            'date': record.date.isoformat(),
                            'from': previous, 'to': record.status,
                            'source': source})
    ))


@attendance_bp.route('/attendance')
@login_required
def attendance():
    tutor_id = request.args.get('tutor_id', type=int)

    # If staff user, automatically filter to their courses
    if current_user.role == 'Staff' and not tutor_id:
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            tutor_id = tutor.id

    if tutor_id:
        tutor = Tutor.query.get_or_404(tutor_id)
        course_ids = [c.id for c in tutor.courses if (c.status or 'Active') != 'Archived']
        student_subquery = db.session.query(student_courses.c.student_id).filter(
            student_courses.c.course_id.in_(course_ids),
            db.or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None))
        ).distinct()
        students = Student.query.filter(Student.id.in_(student_subquery), Student.status == 'Active').all()
    else:
        students = Student.query.filter_by(status='Active').all()

    # Tutors list: admin sees all, staff see only themselves
    if current_user.role == 'Admin':
        tutors = Tutor.query.filter_by(status='Active').all()
    else:
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        tutors = [tutor] if tutor else []

    today = date.today()
    day = today
    raw_date = request.args.get('date')
    if raw_date:
        parsed_day = _parse_day(raw_date)
        if parsed_day is None:
            flash(f'Invalid date "{raw_date}" — showing today.', 'warning')
        else:
            day = parsed_day

    marked_records = Attendance.query.filter_by(date=day).all()
    marked_students = {r.person_id: r.status for r in marked_records if r.person_type == 'student'}
    marked_tutors = {r.person_id: r.status for r in marked_records if r.person_type == 'tutor'}

    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)

    nav_query = {'date': day.isoformat()}
    if tutor_id:
        nav_query['tutor_id'] = tutor_id
    today_query = {'date': today.isoformat()}
    if tutor_id:
        today_query['tutor_id'] = tutor_id
    prev_url = url_for('attendance.attendance', **{**nav_query, 'date': prev_day.isoformat()})
    next_url = url_for('attendance.attendance', **{**nav_query, 'date': next_day.isoformat()})
    today_url = url_for('attendance.attendance', **today_query)

    return render_template('attendance.html', students=students, tutors=tutors,
        day=day, today=today, prev_day=prev_day, next_day=next_day,
        prev_url=prev_url, next_url=next_url, today_url=today_url,
        marked_students=marked_students, marked_tutors=marked_tutors,
        current_tutor_id=tutor_id, status_options=ATTENDANCE_STATUSES,
        status_badge=STATUS_BADGE, is_admin=current_user.role == 'Admin')


@attendance_bp.route('/api/tutor/<int:tutor_id>/attendance/mark', methods=['POST'])
@login_required
def api_tutor_attendance_mark(tutor_id):
    tutor = Tutor.query.get_or_404(tutor_id)
    # Admin, or the staff user whose tutor profile matches this tutor_id.
    if current_user.role != 'Admin':
        own = Tutor.query.filter_by(email=current_user.email).first()
        if not own or own.id != tutor_id:
            return jsonify({"error": "Not authorized for this tutor."}), 403
    data = request.get_json() or {}
    person_type = str(data.get('person_type') or '').lower()
    if person_type != 'student':
        return jsonify({"error": "Tutors can only mark attendance for students."}), 400
    person_id = _int_person_id(data)
    if person_id is None:
        return jsonify({"error": "person_id must be a positive integer."}), 400
    status = data.get('status', DEFAULT_STATUS)
    if status not in ATTENDANCE_STATUSES:
        return jsonify({"error": "Invalid attendance status."}), 400
    course_ids = [c.id for c in tutor.courses if (c.status or 'Active') != 'Archived']
    allowed_student_ids = db.session.query(student_courses.c.student_id).filter(
        student_courses.c.course_id.in_(course_ids)
    ).distinct().all()
    allowed_ids_set = {sid[0] for sid in allowed_student_ids}
    if person_id not in allowed_ids_set:
        return jsonify({"error": "Student not assigned to this tutor's courses."}), 403
    today = date.today()
    record = Attendance.query.filter_by(person_type='student', person_id=person_id, date=today).first()
    if record and record.marked_by == 'manual':
        return jsonify({"error": "Attendance already marked by admin today. Tutor cannot override.", "previous_status": record.status}), 409
    previous = record.status if record else None
    if record:
        record.status = status
        record.timestamp = datetime.utcnow()
        record.marked_by = f'tutor_{tutor_id}'
    else:
        record = Attendance(person_type='student', person_id=person_id, date=today, status=status, marked_by=f'tutor_{tutor_id}')
        db.session.add(record)
    db.session.flush()
    _audit_change(record, previous, 'tutor')
    db.session.commit()
    resp = {"success": True, "message": f"Attendance for student {person_id} marked as {status} by tutor {tutor_id}."}
    if previous and previous != status:
        resp['previous_status'] = previous
    return jsonify(resp)


@attendance_bp.route('/api/attendance/mark', methods=['POST'])
@login_required
def api_attendance_mark():
    data = request.get_json() or {}
    person_type = str(data.get('person_type') or '').lower()
    if person_type not in ('student', 'tutor'):
        return jsonify({"error": "person_type must be 'student' or 'tutor'."}), 400
    person_id = _int_person_id(data)
    if person_id is None:
        return jsonify({"error": "person_id must be a positive integer."}), 400
    status = data.get('status', DEFAULT_STATUS)
    if status not in ATTENDANCE_STATUSES:
        return jsonify({"error": "Invalid attendance status."}), 400
    day = _parse_day(data.get('date'))
    today = date.today()
    if day is None:
        day = today
    if day != today and current_user.role != 'Admin':
        return jsonify({"error": "Only admins can modify attendance for past or future dates."}), 403

    # --- Authorization ---
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor:
            return jsonify({"error": "No tutor profile found for your account."}), 403
        if person_type == 'tutor' and person_id != tutor.id:
            return jsonify({"error": "Staff can only mark their own attendance."}), 403
        if person_type == 'student':
            course_ids = [c.id for c in tutor.courses if (c.status or 'Active') != 'Archived']
            allowed = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids),
                db.or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None))
            ).distinct().all()
            if person_id not in {sid[0] for sid in allowed}:
                return jsonify({"error": "Student not assigned to your courses."}), 403
    else:
        # Admin: reject orphan-person writes that would create junk rows.
        model = Student if person_type == 'student' else Tutor
        if not model.query.get(person_id):
            return jsonify({"error": f"{person_type.capitalize()} not found."}), 404

    # --- Conflict check: admin mark blocks tutor override ---
    record = Attendance.query.filter_by(person_type=person_type, person_id=person_id, date=day).first()
    if record and current_user.role == 'Staff' and record.marked_by == 'manual':
        return jsonify({"error": "Attendance already marked by admin today.", "previous_status": record.status}), 409

    marked_by = 'manual' if current_user.role == 'Admin' else f'tutor_{tutor.id}' if current_user.role == 'Staff' else 'manual'
    previous = record.status if record else None
    if record:
        record.status = status
        record.timestamp = datetime.utcnow()
        record.marked_by = marked_by
    else:
        record = Attendance(person_type=person_type, person_id=person_id, date=day, status=status, marked_by=marked_by)
        db.session.add(record)
    db.session.flush()
    _audit_change(record, previous, marked_by)
    db.session.commit()
    resp = {"success": True, "message": f"{person_type.capitalize()} attendance logged as {status}."}
    # Same-day marks are upserts (one row per person+date): an overwrite that
    # silently flips an earlier status is exactly what bulk marking used to do.
    # Tell the client so it can warn instead of hiding the collapse.
    if previous and previous != status:
        resp['previous_status'] = previous
    return jsonify(resp)


@attendance_bp.route('/api/attendance/scan', methods=['POST'])
@login_required
def api_attendance_scan():
    data = request.get_json() or {}
    uuid_str = data.get('qr_code_uuid')
    if not uuid_str:
        return jsonify({"success": False, "message": "No QR Code signature detected."}), 400
    student = Student.query.filter_by(qr_code_uuid=uuid_str).first()
    person_type = None
    person = None
    if student:
        person_type = 'student'
        person = student
    else:
        tutor = Tutor.query.filter_by(qr_code_uuid=uuid_str).first()
        if tutor:
            person_type = 'tutor'
            person = tutor
    if not person:
        return jsonify({"success": False, "message": "Invalid QR code signature or record not found."}), 404
    if person.status != 'Active':
        return jsonify({"success": False, "message": f"{person.name} is registered but inactive."}), 400
    if current_user.role == 'Staff':
        own = Tutor.query.filter_by(email=current_user.email).first()
        if person_type == 'tutor' and (not own or own.id != person.id):
            return jsonify({"success": False, "message": "Staff can only scan their own attendance."}), 403
        if person_type == 'student' and (not own or person.id not in _active_student_ids_for_tutor(own)):
            return jsonify({"success": False, "message": "Student is not assigned to your active courses."}), 403
    today = date.today()
    record = Attendance.query.filter_by(person_type=person_type, person_id=person.id, date=today).first()
    # Admin manual marks are authoritative: scanning must not silently override them.
    if record and record.marked_by == 'manual':
        if record.status == 'Present':
            return jsonify({"success": True, "duplicate": True, "name": person.name, "role": person_type,
                            "person_id": person.id, "message": f"{person.name} is already marked Present for today."})
        return jsonify({"success": False, "name": person.name, "role": person_type, "person_id": person.id,
                        "message": f"{person.name} was recorded as {record.status} manually today; scan skipped."}), 409
    is_new = False
    previous = None
    if record:
        if record.status == 'Present':
            return jsonify({"success": True, "duplicate": True, "name": person.name, "role": person_type,
                            "person_id": person.id, "message": f"{person.name} is already marked Present for today."})
        previous = record.status
        record.status = 'Present'
        record.timestamp = datetime.utcnow()
        record.marked_by = 'qr'
    else:
        record = Attendance(person_type=person_type, person_id=person.id, date=today, status='Present', marked_by='qr')
        db.session.add(record)
        is_new = True
    db.session.flush()
    _audit_change(record, previous, 'qr')
    db.session.commit()
    resp = {"success": True, "name": person.name, "role": person_type,
            "person_id": person.id, "message": f"Successfully marked Present via QR Code for {person.name}.",
            "is_new": is_new}
    if previous and previous != 'Present':
        resp['previous_status'] = previous
    return jsonify(resp)
