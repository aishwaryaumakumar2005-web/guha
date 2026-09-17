"""Regression tests for student-module medium fixes.

Covers: DOB validation errors, case-insensitive email uniqueness (+ AJAX
contract on edit), course-scoped bulk actions, active-date long-ago rule,
Half Day details bucket, and null enrollment_date guard.
"""
from datetime import date, timedelta

from app.extensions import db
from app.forms import StudentForm
from app.models import Attendance, Course, Student
from app.routes.student_lifecycle import _enrolled_long_ago

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _sid(app, email='student@guha.test'):
    with app.app_context():
        return Student.query.filter_by(email=email).first().id


# ---- Invalid DOB is an error, not a silent drop ----

def test_create_rejects_invalid_dob(admin_client, app):
    resp = admin_client.post('/students', data={
        'name': 'Bad Dob', 'email': 'baddob@guha.test', 'phone': '9000000040',
        'status': 'Active', 'date_of_birth': 'not-a-date',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.filter_by(email='baddob@guha.test').count() == 0


def test_create_stores_valid_dob(admin_client, app):
    admin_client.post('/students', data={
        'name': 'Good Dob', 'email': 'gooddob@guha.test', 'phone': '9000000041',
        'status': 'Active', 'date_of_birth': '2005-04-02',
    })
    with app.app_context():
        s = Student.query.filter_by(email='gooddob@guha.test').first()
        assert s is not None and s.date_of_birth == date(2005, 4, 2)


def test_edit_rejects_invalid_dob_ajax(admin_client, app):
    sid = _sid(app)
    resp = admin_client.post(f'/students/edit/{sid}', data={
        'name': 'Test Student', 'email': 'student@guha.test',
        'phone': '9876543210', 'status': 'Active',
        'date_of_birth': '32-13-2020',
    }, headers=AJAX)
    assert resp.status_code == 400
    assert any('date of birth' in e.lower() for e in resp.get_json()['errors'])


# ---- Email uniqueness is case-insensitive; edit honors AJAX ----

def test_create_blocks_case_variant_email(admin_client, app):
    with app.app_context():
        before = Student.query.count()
    resp = admin_client.post('/students', data={
        'name': 'Dup', 'email': 'STUDENT@guha.test', 'phone': '9000000042',
        'status': 'Active',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Student.query.count() == before


def test_edit_blocks_case_variant_email_ajax(admin_client, app):
    with app.app_context():
        other = Student(name='Other', email='other@guha.test',
                        phone='9000000043', status='Active')
        db.session.add(other)
        db.session.commit()
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.post(f'/students/edit/{sid}', data={
        'name': 'Test Student', 'email': 'OTHER@guha.test',
        'phone': '9876543210', 'status': 'Active',
    }, headers=AJAX)
    assert resp.status_code == 400
    assert 'errors' in resp.get_json()
    with app.app_context():
        assert Student.query.get(sid).email == 'student@guha.test'


def test_edit_same_email_different_case_allowed(admin_client, app):
    sid = _sid(app)
    resp = admin_client.post(f'/students/edit/{sid}', data={
        'name': 'Test Student', 'email': 'STUDENT@guha.test',
        'phone': '9876543210', 'status': 'Active',
    })
    assert resp.status_code == 302


# ---- Bulk actions respect the course filter ----

def _enrollment(app, sid, cid):
    with app.app_context():
        from app.models import student_courses
        return db.session.execute(
            student_courses.select().where(
                student_courses.c.student_id == sid,
                student_courses.c.course_id == cid)
        ).first()


def test_bulk_scoped_to_filtered_course(admin_client, app):
    with app.app_context():
        c2 = Course(name='Second Course', code='SC', description='t',
                    duration_weeks=4, duration_unit='weeks', fees=1000.0)
        db.session.add(c2)
        db.session.flush()
        c2id = c2.id
        sid = Student.query.filter_by(email='student@guha.test').first().id
        c1id = Course.query.filter_by(code='PY').first().id
        s = Student.query.get(sid)
        s.courses.append(c2)
        db.session.commit()
    resp = admin_client.post('/students/enrollment/bulk', data={
        'bulk_action': 'complete', 'filter': 'all', 'course_id': str(c1id),
        'selected': [str(sid)],
    })
    assert resp.status_code == 302
    assert _enrollment(app, sid, c1id).status == 'Completed'
    assert (_enrollment(app, sid, c2id).status or 'Enrolled') == 'Enrolled'


# ---- Long-ago rule judges the active enrollment ----

def _stud():
    s = Student(name='X', email='x@t.t', phone='9000000000', status='Active')
    s.enrollment_date = date.today()
    return s


def test_reenrolled_student_not_judged_by_old_drop():
    old = date.today() - timedelta(days=60)
    new = date.today() - timedelta(days=2)
    enrolls = [{'status': 'Dropped', 'enrolled_on': old},
               {'status': 'Enrolled', 'enrolled_on': new}]
    assert _enrolled_long_ago(_stud(), enrolls) is False
    assert _enrolled_long_ago(
        _stud(), [{'status': 'Enrolled', 'enrolled_on': old}]) is True


# ---- Details API: Half Day bucket + null-date guard ----

def test_details_counts_half_day(admin_client, app):
    sid = _sid(app)
    with app.app_context():
        db.session.add(Attendance(person_type='student', person_id=sid,
                                  date=date.today(), status='Half Day'))
        db.session.commit()
    data = admin_client.get(f'/api/students/{sid}/details').get_json()
    assert data['attendance']['half_day'] == 1
    assert data['attendance']['total_days'] == 1


def test_details_survives_null_enrollment_date(admin_client, app):
    with app.app_context():
        s = Student(name='Null', email='null@guha.test',
                    phone='9000000044', status='Active')
        db.session.add(s)
        db.session.commit()
        sid = s.id
        db.session.execute(
            Student.__table__.update().where(Student.__table__.c.id == sid)
            .values(enrollment_date=None))
        db.session.commit()
    resp = admin_client.get(f'/api/students/{sid}/details')
    assert resp.status_code == 200
    assert resp.get_json()['enrollment_date'] is None


# ---- StudentForm no longer validates the multi-select as an integer ----

def test_student_form_ignores_courses_value():
    form = StudentForm(data={'name': 'A', 'email': 'a@guha.test',
                             'phone': '9112345678', 'courses': 'not-an-int'})
    assert form.validate(), form.errors
