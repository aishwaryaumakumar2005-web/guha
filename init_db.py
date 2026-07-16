import os, sqlite3
from datetime import datetime, date, timedelta
from app import create_app
from app.extensions import db
from app.models import (Course, Student, Tutor, Attendance, FeeRecord,
                         Enquiry, User, LeaveRequest, ExpenseCategory,
                         Expense, Exam, AuditLog)
from werkzeug.security import generate_password_hash

BACKUP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup_data.db')


def fetch_backup(table):
    conn = sqlite3.connect(BACKUP_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f'SELECT * FROM "{table}"')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def seed_database():
    print("Starting database seeding from backup...")
    db.drop_all()
    db.create_all()
    print("Tables re-created.")
    _restore_all()
    print("Database restored successfully!")


def seed_if_empty():
    if Course.query.first():
        print("Database already has data, skipping seed.")
        return
    print("Empty database — restoring from backup...")
    db.create_all()
    _restore_all()
    print("Database restored successfully!")


def _restore_all():
    users = fetch_backup('user')
    courses = fetch_backup('course')
    tutors = fetch_backup('tutor')
    students = fetch_backup('student')
    expense_cats = fetch_backup('expense_category')
    expenses = fetch_backup('expense')
    fees = fetch_backup('fee_record')
    enquiries = fetch_backup('enquiry')
    attendance = fetch_backup('attendance')
    leaves = fetch_backup('leave_request')
    exams_data = fetch_backup('exam')
    audits = fetch_backup('audit_log')
    student_courses = fetch_backup('student_courses')
    tutor_courses = fetch_backup('tutor_courses')

    print(f"Loaded: {len(users)} users, {len(courses)} courses, {len(tutors)} tutors, "
          f"{len(students)} students, {len(expense_cats)} expense cats, "
          f"{len(expenses)} expenses, {len(fees)} fees, {len(enquiries)} enquiries, "
          f"{len(attendance)} attendance, {len(leaves)} leaves, "
          f"{len(exams_data)} exams, {len(audits)} audits")

    obj_map = {}

    # Users
    _users = {}
    for u in users:
        obj = User(
            id=u['id'], username=u['username'],
            password_hash=u['password_hash'],
            role=u['role'], name=u['name'], email=u['email'],
            created_at=datetime.fromisoformat(u['created_at']) if u.get('created_at') else None
        )
        db.session.add(obj)
        _users[u['id']] = obj
    db.session.flush()
    obj_map['user'] = _users
    print(f"Restored {len(_users)} users")

    # Courses
    _courses = {}
    for c in courses:
        obj = Course(
            id=c['id'], name=c['name'], code=c['code'],
            description=c.get('description', ''),
            duration_weeks=c['duration_weeks'],
            duration_unit=c.get('duration_unit', 'weeks'),
            fees=c['fees'],
            gst_applicable=bool(c.get('gst_applicable', False)),
            syllabus=c.get('syllabus', '')
        )
        db.session.add(obj)
        _courses[c['id']] = obj
    db.session.flush()
    obj_map['course'] = _courses
    print(f"Restored {len(_courses)} courses")

    # Tutors
    _tutors = {}
    for t in tutors:
        obj = Tutor(
            id=t['id'], name=t['name'], email=t['email'],
            phone=t['phone'], specialization=t.get('specialization', ''),
            status=t.get('status', 'Active'),
            qr_code_uuid=t.get('qr_code_uuid')
        )
        db.session.add(obj)
        _tutors[t['id']] = obj
    db.session.flush()

    # Tutor-Course relationships
    for tc in tutor_courses:
        tid, cid = tc['tutor_id'], tc['course_id']
        if tid in _tutors and cid in _courses:
            _tutors[tid].courses.append(_courses[cid])
    db.session.flush()
    obj_map['tutor'] = _tutors
    print(f"Restored {len(_tutors)} tutors with course assignments")

    # Students
    _students = {}
    for s in students:
        obj = Student(
            id=s['id'], name=s['name'], email=s['email'],
            phone=s['phone'], status=s.get('status', 'Active'),
            enrollment_date=(
                datetime.strptime(s['enrollment_date'], '%Y-%m-%d').date()
                if s.get('enrollment_date') else None
            ),
            qr_code_uuid=s.get('qr_code_uuid')
        )
        db.session.add(obj)
        _students[s['id']] = obj
    db.session.flush()

    # Student-Course relationships
    for sc in student_courses:
        sid, cid = sc['student_id'], sc['course_id']
        if sid in _students and cid in _courses:
            _students[sid].courses.append(_courses[cid])
    db.session.flush()
    obj_map['student'] = _students
    print(f"Restored {len(_students)} students with course enrollments")

    # Expense Categories
    _expense_cats = {}
    for ec in expense_cats:
        obj = ExpenseCategory(id=ec['id'], name=ec['name'], description=ec.get('description'))
        db.session.add(obj)
        _expense_cats[ec['id']] = obj
    db.session.flush()
    obj_map['expense_category'] = _expense_cats

    # Expenses
    for e in expenses:
        obj = Expense(
            id=e['id'], category_id=e['category_id'],
            amount=e['amount'], description=e['description'],
            expense_date=datetime.strptime(e['expense_date'], '%Y-%m-%d').date(),
            created_by=e.get('created_by'),
            created_at=(
                datetime.fromisoformat(e['created_at']) if e.get('created_at') else None
            )
        )
        db.session.add(obj)
    db.session.flush()
    print(f"Restored {len(expense_cats)} expense categories, {len(expenses)} expenses")

    # Fee Records
    for f in fees:
        obj = FeeRecord(
            id=f['id'], student_id=f['student_id'],
            amount_paid=f['amount_paid'],
            payment_date=datetime.strptime(f['payment_date'], '%Y-%m-%d').date(),
            payment_method=f.get('payment_method', ''),
            remarks=f.get('remarks', '')
        )
        db.session.add(obj)
    db.session.flush()
    print(f"Restored {len(fees)} fee records")

    # Enquiries
    for eq in enquiries:
        obj = Enquiry(
            id=eq['id'], student_name=eq['student_name'],
            email=eq.get('email', ''), phone=eq['phone'],
            course_id=eq['course_id'], source=eq.get('source', ''),
            status=eq.get('status', 'New'), notes=eq.get('notes', ''),
            created_at=(
                datetime.fromisoformat(eq['created_at']) if eq.get('created_at') else None
            )
        )
        db.session.add(obj)
    db.session.flush()
    print(f"Restored {len(enquiries)} enquiries")

    # Attendance
    for a in attendance:
        obj = Attendance(
            id=a['id'], person_type=a['person_type'],
            person_id=a['person_id'],
            date=datetime.strptime(a['date'], '%Y-%m-%d').date(),
            status=a.get('status', 'Present'),
            marked_by=a.get('marked_by', 'manual'),
            timestamp=(
                datetime.fromisoformat(a['timestamp']) if a.get('timestamp') else None
            )
        )
        db.session.add(obj)
    db.session.flush()
    print(f"Restored {len(attendance)} attendance records")

    # Leave Requests
    for lr in leaves:
        obj = LeaveRequest(
            id=lr['id'], user_id=lr['user_id'],
            start_date=datetime.strptime(lr['start_date'], '%Y-%m-%d').date(),
            end_date=datetime.strptime(lr['end_date'], '%Y-%m-%d').date(),
            reason=lr['reason'], status=lr['status'],
            created_at=(
                datetime.fromisoformat(lr['created_at']) if lr.get('created_at') else None
            )
        )
        db.session.add(obj)
    print(f"Restored {len(leaves)} leave requests")

    # Exams
    for ex in exams_data:
        obj = Exam(
            id=ex['id'], course_id=ex['course_id'],
            title=ex['title'],
            exam_date=(
                datetime.strptime(ex['exam_date'], '%Y-%m-%d').date()
                if ex.get('exam_date') else date.today()
            ),
            max_marks=ex['max_marks'],
            passing_marks=ex['passing_marks'],
            description=ex.get('description', ''),
            exam_type=ex.get('exam_type', 'manual'),
            num_questions=ex.get('num_questions', 0),
            duration_minutes=ex.get('duration_minutes', 0),
            is_published=bool(ex.get('is_published', False))
        )
        db.session.add(obj)
    print(f"Restored {len(exams_data)} exams")

    # Audit Logs
    for al in audits:
        obj = AuditLog(
            id=al['id'], user_id=al.get('user_id'),
            username=al.get('username', ''),
            action=al['action'], entity_type=al['entity_type'],
            entity_id=al.get('entity_id'),
            changes=al.get('changes'),
            timestamp=datetime.fromisoformat(al['timestamp'])
        )
        db.session.add(obj)
    print(f"Restored {len(audits)} audit logs")

    db.session.commit()
    print("All data committed.")


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        seed_database()
