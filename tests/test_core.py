from app.extensions import db
from app.models import (
    Student, Course, FeeRecord, Expense, ExpenseCategory, Enquiry,
    Attendance, PayrollRecord, Task, Tutor, User,
)


def test_create_course(admin_client, app):
    resp = admin_client.post('/courses', data={
        'name': 'Advanced Excel', 'code': 'XL', 'description': 'Excel course',
        'duration_weeks': '6', 'duration_unit': 'weeks', 'fees': '3000',
        'gst_applicable': 'on', 'syllabus': 'macros',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Course.query.filter_by(code='XL').first() is not None


def test_create_duplicate_course_blocked(admin_client, app):
    admin_client.post('/courses', data={
        'name': 'Python', 'code': 'PY', 'duration_weeks': '8', 'fees': '5000',
    })
    resp = admin_client.post('/courses', data={
        'name': 'Python Dup', 'code': 'PY', 'duration_weeks': '8', 'fees': '5000',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Course.query.filter_by(code='PY').count() == 1


def test_edit_course(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    resp = admin_client.post(f'/courses/edit/{cid}', data={
        'name': 'Python Pro', 'code': 'PY', 'description': '',
        'duration_weeks': '10', 'duration_unit': 'weeks', 'fees': '6000',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Course.query.get(cid).name == 'Python Pro'


def test_create_student(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    resp = admin_client.post('/students', data={
        'name': 'Alice', 'email': 'alice@guha.test', 'phone': '9123456789',
        'status': 'Active', 'courses': [str(cid)],
    })
    assert resp.status_code == 302
    with app.app_context():
        s = Student.query.filter_by(email='alice@guha.test').first()
        assert s is not None
        assert cid in [c.id for c in s.courses]


def test_create_duplicate_student_blocked(admin_client, app):
    resp = admin_client.post('/students', data={
        'name': 'Dup', 'email': 'student@guha.test', 'phone': '9876543210',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.filter_by(email='student@guha.test').count() == 1


def test_edit_student(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.post(f'/students/edit/{sid}', data={
        'name': 'Renamed', 'email': 'student@guha.test', 'phone': '9876543210',
        'status': 'Active',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.get(sid).name == 'Renamed'


def test_delete_student(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.get(f'/students/delete/{sid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.get(sid) is None


def test_record_fee(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '5000', 'payment_method': 'UPI',
        'payment_date': '2026-01-15', 'remarks': 'first instalment',
    })
    assert resp.status_code == 302
    with app.app_context():
        rec = FeeRecord.query.filter_by(student_id=sid).first()
        assert rec is not None
        assert rec.amount_paid == 5000.0


def test_staff_cannot_add_fee(staff_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = staff_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '100', 'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert FeeRecord.query.count() == 0


def test_add_expense(admin_client, app):
    resp = admin_client.post('/expenses', data={
        'category_id': '1', 'amount': '1500', 'description': 'AC repair',
        'expense_date': '2026-01-10', 'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.count() == 1


def test_create_enquiry(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    resp = admin_client.post('/enquiries', data={
        'student_name': 'Bob', 'email': 'bob@guha.test', 'phone': '9112345678',
        'course_id': str(cid), 'source': 'Walk-in', 'status': 'New',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.filter_by(student_name='Bob').first() is not None


def test_convert_enquiry_to_student(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        enq = Enquiry(student_name='Bob', email='bob@guha.test',
                      phone='9112345678', course_id=cid, status='New')
        db.session.add(enq)
        db.session.commit()
        eid = enq.id
    resp = admin_client.post(f'/enquiries/convert/{eid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.filter_by(email='bob@guha.test').first() is not None
        assert Enquiry.query.get(eid).status == 'Converted'


def test_mark_attendance_admin(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Present',
    })
    assert resp.status_code == 200
    with app.app_context():
        assert Attendance.query.filter_by(person_id=sid, person_type='student').first() is not None


def test_mark_attendance_staff_own_student(staff_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = staff_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Present',
    })
    assert resp.status_code == 200


def test_staff_cannot_mark_unassigned_student(staff_client, app):
    with app.app_context():
        tutor = Tutor.query.filter_by(email='staff@guha.test').first()
        # create a student NOT in the staff tutor's courses
        s = Student(name='Stranger', email='stranger@guha.test',
                    phone='9000000000', status='Active')
        db.session.add(s)
        db.session.commit()
        sid = s.id
    resp = staff_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Present',
    })
    assert resp.status_code == 403


def test_process_payroll(admin_client, app):
    with app.app_context():
        tid = Tutor.query.filter_by(email='staff@guha.test').first().id
    resp = admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '1', 'year': '2026',
    })
    assert resp.status_code == 302
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid).first()
        assert rec is not None
        assert rec.status == 'Draft'


def test_create_task_admin(admin_client, app):
    with app.app_context():
        tid = Tutor.query.filter_by(email='staff@guha.test').first().id
    resp = admin_client.post('/tasks', data={
        'tutor_id': str(tid), 'title': 'Mark attendance', 'description': 'For today',
        'due_date': '2026-02-01',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Task.query.filter_by(title='Mark attendance').first() is not None


def test_staff_sees_only_own_tasks(staff_client, app):
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        tutor = Tutor.query.filter_by(email='staff@guha.test').first()
        other_tutor = Tutor(name='Other', email='other@guha.test',
                            phone='9000000000', status='Active')
        db.session.add(other_tutor)
        db.session.flush()
        db.session.add(Task(tutor_id=tutor.id, title='My Task', assigned_by=admin.id))
        db.session.add(Task(tutor_id=other_tutor.id, title='Other Task', assigned_by=admin.id))
        db.session.commit()
    resp = staff_client.get('/tasks')
    assert resp.status_code == 200
    assert b'My Task' in resp.data
    assert b'Other Task' not in resp.data
