from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Attendance, Student, Tutor, student_courses, User

attendance_bp = Blueprint('attendance', __name__)

@attendance_bp.route('/attendance')
@login_required
def attendance():
    tutor_id = request.args.get('tutor_id', type=int)
    
    # If staff user, automatically filter to their courses
    if current_user.role == 'Staff' and not tutor_id:
        # Find the tutor record for this staff user
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            tutor_id = tutor.id
    
    if tutor_id:
        tutor = Tutor.query.get_or_404(tutor_id)
        course_ids = [c.id for c in tutor.courses]
        student_subquery = db.session.query(student_courses.c.student_id).filter(
            student_courses.c.course_id.in_(course_ids)
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
    marked_records = Attendance.query.filter_by(date=today).all()
    marked_students = {r.person_id: r.status for r in marked_records if r.person_type == 'student'}
    marked_tutors = {r.person_id: r.status for r in marked_records if r.person_type == 'tutor'}
    history_days = []
    history_students_present = []
    history_tutors_present = []
    seven_days_ago = today - timedelta(days=6)
    att_history = db.session.query(
        Attendance.date, Attendance.person_type,
        db.func.count(Attendance.id).filter(Attendance.status == 'Present').label('present_count')
    ).filter(
        Attendance.date >= seven_days_ago, Attendance.date <= today
    ).group_by(Attendance.date, Attendance.person_type).all()
    att_map = {}
    for r in att_history:
        att_map[(r.date, r.person_type)] = r.present_count
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        history_days.append(day.strftime("%a (%d/%m)"))
        history_students_present.append(att_map.get((day, 'student'), 0))
        history_tutors_present.append(att_map.get((day, 'tutor'), 0))
    return render_template('attendance.html', students=students, tutors=tutors, today=today,
        marked_students=marked_students, marked_tutors=marked_tutors, history_days=history_days,
        history_students_present=history_students_present, history_tutors_present=history_tutors_present,
        current_tutor_id=tutor_id)

@attendance_bp.route('/api/tutor/<int:tutor_id>/attendance/mark', methods=['POST'])
@login_required
def api_tutor_attendance_mark(tutor_id):
    tutor = Tutor.query.get_or_404(tutor_id)
    data = request.get_json() or {}
    person_type = data.get('person_type')
    person_id = int(data.get('person_id', 0))
    status = data.get('status', 'Present')
    if person_type != 'student':
        return jsonify({"error": "Tutors can only mark attendance for students."}), 400
    course_ids = [c.id for c in tutor.courses]
    allowed_student_ids = db.session.query(student_courses.c.student_id).filter(
        student_courses.c.course_id.in_(course_ids)
    ).distinct().all()
    allowed_ids_set = {sid[0] for sid in allowed_student_ids}
    if person_id not in allowed_ids_set:
        return jsonify({"error": "Student not assigned to this tutor's courses."}), 403
    today = date.today()
    record = Attendance.query.filter_by(person_type='student', person_id=person_id, date=today).first()
    # Conflict check: admin mark blocks tutor override
    if record and record.marked_by == 'manual':
        return jsonify({"error": "Attendance already marked by admin today. Tutor cannot override.", "previous_status": record.status}), 409
    if record:
        record.status = status
        record.timestamp = datetime.utcnow()
        record.marked_by = f'tutor_{tutor_id}'
    else:
        record = Attendance(person_type='student', person_id=person_id, date=today, status=status, marked_by=f'tutor_{tutor_id}')
        db.session.add(record)
    db.session.commit()
    return jsonify({"success": True, "message": f"Attendance for student {person_id} marked as {status} by tutor {tutor_id}."})

@attendance_bp.route('/api/attendance/mark', methods=['POST'])
@login_required
def api_attendance_mark():
    data = request.get_json() or {}
    person_type = data.get('person_type')
    person_id = int(data.get('person_id', 0))
    status = data.get('status', 'Present')
    today = date.today()

    # --- Authorization ---
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor:
            return jsonify({"error": "No tutor profile found for your account."}), 403
        if person_type == 'tutor' and person_id != tutor.id:
            return jsonify({"error": "Staff can only mark their own attendance."}), 403
        if person_type == 'student':
            course_ids = [c.id for c in tutor.courses]
            allowed = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids)
            ).distinct().all()
            if person_id not in {sid[0] for sid in allowed}:
                return jsonify({"error": "Student not assigned to your courses."}), 403

    # --- Conflict check: admin mark blocks tutor override ---
    record = Attendance.query.filter_by(person_type=person_type, person_id=person_id, date=today).first()
    if record and current_user.role == 'Staff' and record.marked_by == 'manual':
        return jsonify({"error": "Attendance already marked by admin today.", "previous_status": record.status}), 409

    marked_by = 'manual' if current_user.role == 'Admin' else f'tutor_{tutor.id}' if current_user.role == 'Staff' else 'manual'
    if record:
        record.status = status
        record.timestamp = datetime.utcnow()
        record.marked_by = marked_by
    else:
        record = Attendance(person_type=person_type, person_id=person_id, date=today, status=status, marked_by=marked_by)
        db.session.add(record)
    db.session.commit()
    return jsonify({"success": True, "message": f"{person_type.capitalize()} attendance logged as {status}."})

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
    today = date.today()
    record = Attendance.query.filter_by(person_type=person_type, person_id=person.id, date=today).first()
    is_new = False
    if record:
        if record.status == 'Present':
            return jsonify({"success": True, "duplicate": True, "name": person.name, "role": person_type.capitalize(), "message": f"{person.name} is already marked Present for today."})
        record.status = 'Present'
        record.timestamp = datetime.utcnow()
        record.marked_by = 'qr'
    else:
        record = Attendance(person_type=person_type, person_id=person.id, date=today, status='Present', marked_by='qr')
        db.session.add(record)
        is_new = True
    db.session.commit()
    return jsonify({"success": True, "name": person.name, "role": person_type.capitalize(), "message": f"Successfully marked Present via QR Code for {person.name} ({person_type.capitalize()}).", "is_new": is_new})
