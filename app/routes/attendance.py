from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, jsonify, flash, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Attendance, Student, Tutor, AuditLog, student_courses

attendance_bp = Blueprint('attendance', __name__)

# Keep attendance permissions in sync with the rest of the business-domain
# routes.  ``Operator`` is a legacy value still present in some databases,
# while new accounts use ``Operation``.
ATTENDANCE_ADMIN_ROLES = ('Admin', 'Operation', 'Operator')
ATTENDANCE_TIMEZONE = ZoneInfo('Asia/Kolkata')


def _local_today():
    """Return the academy's calendar date, independent of Render's UTC host."""
    return datetime.now(ATTENDANCE_TIMEZONE).date()


def _is_attendance_admin():
    role = str(current_user.role or '').strip().lower()
    return role in {'admin', 'operation', 'operator', 'operative'}


def _is_tutor_user():
    """Support both the legacy Staff role and the Tutor role."""
    role = str(current_user.role or '').strip().lower()
    return role in {'staff', 'tutor'}


def _current_tutor():
    if not _is_tutor_user() or not current_user.email:
        return None
    return Tutor.query.filter(
        db.func.lower(Tutor.email) == current_user.email.strip().lower()
    ).first()

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
    if _is_tutor_user():
        # Never allow a tutor to broaden their roster through query params.
        tutor = _current_tutor()
        tutor_id = tutor.id if tutor else None

    if _is_tutor_user() and not tutor_id:
        # A tutor account without a matching profile must not fall back to
        # the unrestricted admin roster.
        students = []
    elif tutor_id:
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
    if _is_attendance_admin():
        tutors = Tutor.query.filter_by(status='Active').all()
    else:
        tutor = _current_tutor()
        tutors = [tutor] if tutor else []

    today = _local_today()
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
        status_badge=STATUS_BADGE, is_admin=_is_attendance_admin())


@attendance_bp.route('/api/tutor/<int:tutor_id>/attendance/mark', methods=['POST'])
@login_required
def api_tutor_attendance_mark(tutor_id):
    tutor = Tutor.query.get_or_404(tutor_id)
    # Admin, or the staff user whose tutor profile matches this tutor_id.
    if not _is_attendance_admin():
        own = _current_tutor()
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
    today = _local_today()
    day = _parse_day(data.get('date')) or today
    if day != today and not _is_attendance_admin():
        return jsonify({"error": "Only admins can modify attendance for past or future dates."}), 403
    record = Attendance.query.filter_by(person_type='student', person_id=person_id, date=day).first()
    if record and record.marked_by == 'manual':
        return jsonify({"error": "Attendance already marked by admin today. Tutor cannot override.", "previous_status": record.status}), 409
    previous = record.status if record else None
    if record:
        record.status = status
        record.timestamp = datetime.utcnow()
        record.marked_by = f'tutor_{tutor_id}'
    else:
        record = Attendance(person_type='student', person_id=person_id, date=day, status=status, marked_by=f'tutor_{tutor_id}')
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
    today = _local_today()
    if day is None:
        day = today
    if day != today and not _is_attendance_admin():
        return jsonify({"error": "Only admins can modify attendance for past or future dates."}), 403

    # --- Authorization ---
    if _is_tutor_user():
        tutor = _current_tutor()
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
    elif not _is_attendance_admin():
        return jsonify({"error": "This account is not authorized to mark attendance."}), 403
    else:
        # Admin: reject orphan-person writes that would create junk rows.
        model = Student if person_type == 'student' else Tutor
        if not model.query.get(person_id):
            return jsonify({"error": f"{person_type.capitalize()} not found."}), 404

    # --- Conflict check: admin mark blocks tutor override ---
    record = Attendance.query.filter_by(person_type=person_type, person_id=person_id, date=day).first()
    if record and _is_tutor_user() and record.marked_by == 'manual':
        return jsonify({"error": "Attendance already marked by admin today.", "previous_status": record.status}), 409

    marked_by = 'manual' if _is_attendance_admin() else f'tutor_{tutor.id}' if _is_tutor_user() else 'manual'
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


@attendance_bp.route('/api/attendance/bulk-mark', methods=['POST'])
@login_required
def api_attendance_bulk_mark():
    """Mark a roster in one transaction so bulk actions cannot partially fail."""
    data = request.get_json() or {}
    items = data.get('items')
    status = data.get('status', DEFAULT_STATUS)
    day = _parse_day(data.get('date')) or _local_today()
    if not isinstance(items, list) or not items:
        return jsonify({'error': 'items must be a non-empty list.'}), 400
    if len(items) > 1000:
        return jsonify({'error': 'Too many attendance rows in one request.'}), 400
    if status not in ATTENDANCE_STATUSES:
        return jsonify({'error': 'Invalid attendance status.'}), 400
    if day != _local_today() and not _is_attendance_admin():
        return jsonify({'error': 'Only admins can modify attendance for past or future dates.'}), 403

    if not _is_attendance_admin() and not _is_tutor_user():
        return jsonify({'error': 'This account is not authorized to mark attendance.'}), 403

    tutor = None
    if _is_tutor_user():
        tutor = _current_tutor()
        if not tutor:
            return jsonify({'error': 'No tutor profile found for your account.'}), 403
    allowed_student_ids = set()
    if tutor:
        course_ids = [c.id for c in tutor.courses if (c.status or 'Active') != 'Archived']
        allowed_student_ids = {row[0] for row in db.session.query(student_courses.c.student_id).filter(
            student_courses.c.course_id.in_(course_ids),
            db.or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None))
        ).distinct().all()}

    changed = 0
    overwritten = 0
    for item in items:
        person_type = str(item.get('person_type') or '').lower() if isinstance(item, dict) else ''
        person_id = _int_person_id(item) if isinstance(item, dict) else None
        if person_type not in ('student', 'tutor') or person_id is None:
            db.session.rollback()
            return jsonify({'error': 'Each item must contain a valid person_type and person_id.'}), 400
        if tutor and ((person_type == 'tutor' and person_id != tutor.id) or
                      (person_type == 'student' and person_id not in allowed_student_ids)):
            db.session.rollback()
            return jsonify({'error': 'One or more attendance rows are outside your scope.'}), 403
        model = Student if person_type == 'student' else Tutor
        if not model.query.get(person_id):
            db.session.rollback()
            return jsonify({'error': f'{person_type.capitalize()} not found.'}), 404
        record = Attendance.query.filter_by(person_type=person_type, person_id=person_id, date=day).first()
        previous = record.status if record else None
        if record:
            if record.status != status:
                overwritten += 1
            record.status = status
            record.timestamp = datetime.utcnow()
            record.marked_by = 'manual' if _is_attendance_admin() else f'tutor_{tutor.id}'
        else:
            record = Attendance(person_type=person_type, person_id=person_id, date=day,
                                status=status,
                                marked_by='manual' if _is_attendance_admin() else f'tutor_{tutor.id}')
            db.session.add(record)
        changed += 1
        db.session.flush()
        _audit_change(record, previous, record.marked_by)
    db.session.commit()
    return jsonify({'success': True, 'marked': changed, 'overwritten': overwritten,
                    'date': day.isoformat(), 'status': status})


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
    if _is_tutor_user():
        own = _current_tutor()
        if person_type == 'tutor' and (not own or own.id != person.id):
            return jsonify({"success": False, "message": "Staff can only scan their own attendance."}), 403
        if person_type == 'student' and (not own or person.id not in _active_student_ids_for_tutor(own)):
            return jsonify({"success": False, "message": "Student is not assigned to your active courses."}), 403
    today = _local_today()
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
