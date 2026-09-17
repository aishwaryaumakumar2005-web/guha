"""Regression tests for student-lifecycle fixes #1-#3.

#1: editing a student preserves per-course enrollment history.
#2: enrolled_on is stamped on every enrollment write.
#3: lifecycle buckets prioritize current enrollments correctly.
"""
from datetime import date, timedelta

from app.extensions import db
from app.models import Course, Student, student_courses
from app.routes.student_lifecycle import _derive_bucket


def _mk_course(app, code, name='Course'):
    with app.app_context():
        c = Course(name=f'{name} {code}', code=code, description='t',
                   duration_weeks=4, duration_unit='weeks', fees=1000.0)
        db.session.add(c)
        db.session.commit()
        return c.id


def _enrollment(app, sid, cid):
    with app.app_context():
        return db.session.execute(
            student_courses.select().where(
                student_courses.c.student_id == sid,
                student_courses.c.course_id == cid)
        ).first()


def test_edit_preserves_enrollment_history(admin_client, app):
    c2 = _mk_course(app, 'C2')
    with app.app_context():
        c1 = Course.query.filter_by(code='PY').first().id
        s = Student.query.filter_by(email='student@guha.test').first()
        sid = s.id
    # mark PY completed through the lifecycle route
    resp = admin_client.post(f'/students/enrollment/complete/{sid}/{c1}',
                             data={'filter': 'all'})
    assert resp.status_code == 302
    # edit name only, keeping both courses selected
    resp = admin_client.post(f'/students/edit/{sid}', data={
        'name': 'Renamed Again', 'email': 'student@guha.test',
        'phone': '9876543210', 'status': 'Active',
        'courses': [str(c1), str(c2)],
    })
    assert resp.status_code == 302
    row = _enrollment(app, sid, c1)
    assert row is not None
    assert row.status == 'Completed', 'edit wiped the Completed status'
    assert row.completed_on is not None
    with app.app_context():
        assert Student.query.get(sid).name == 'Renamed Again'


def test_edit_add_stamps_enrolled_on(admin_client, app):
    c2 = _mk_course(app, 'C3')
    with app.app_context():
        s = Student.query.filter_by(email='student@guha.test').first()
        sid = s.id
        c1 = Course.query.filter_by(code='PY').first().id
    admin_client.post(f'/students/edit/{sid}', data={
        'name': s.name, 'email': s.email, 'phone': s.phone,
        'status': 'Active', 'courses': [str(c1), str(c2)],
    })
    row = _enrollment(app, sid, c2)
    assert row is not None and row.enrolled_on == date.today()


def test_create_stamps_enrolled_on(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    admin_client.post('/students', data={
        'name': 'Stampy', 'email': 'stampy@guha.test', 'phone': '9123456789',
        'status': 'Active', 'courses': [str(cid)],
    })
    with app.app_context():
        s = Student.query.filter_by(email='stampy@guha.test').first()
        row = _enrollment(app, s.id, cid)
        assert row is not None and row.enrolled_on == date.today()


def test_convert_stamps_enrolled_on(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        from app.models import Enquiry
        enq = Enquiry(student_name='Conv', email='conv@guha.test',
                      phone='9112345678', course_id=cid, status='New')
        db.session.add(enq)
        db.session.commit()
        eid = enq.id
    admin_client.post(f'/enquiries/convert/{eid}')
    with app.app_context():
        s = Student.query.filter_by(email='conv@guha.test').first()
        assert s is not None
        row = _enrollment(app, s.id, cid)
        assert row is not None and row.enrolled_on == date.today()


def _stud(status='Active', enrolled_days_ago=0):
    s = Student(name='X', email='x@t.t', phone='9000000000', status=status)
    s.enrollment_date = date.today() - timedelta(days=enrolled_days_ago)
    return s


def _att(streak=0, rate=None, total=0, last=None):
    return {'max_run': 0, 'last_streak': streak, 'att_rate_30': rate,
            'total_marks_30': total, 'last_attendance_date': last}


def test_bucket_active_enrollment_beats_historic_drop():
    s = _stud()
    enrolls = [{'status': 'Dropped'}, {'status': 'Enrolled'}]
    assert _derive_bucket(s, enrolls, _att()) == 'Enrolled'


def test_bucket_completed_not_masked_by_stale_attendance():
    s = _stud()
    enrolls = [{'status': 'Completed'}]
    assert _derive_bucket(s, enrolls, _att(streak=9)) == 'Completed'


def test_bucket_no_enrollments():
    assert _derive_bucket(_stud(), [], _att()) == 'Not Enrolled'


def test_bucket_never_attended_old_enrollment_is_long_absent():
    s = _stud(enrolled_days_ago=60)
    enrolls = [{'status': 'Enrolled',
                'enrolled_on': date.today() - timedelta(days=60)}]
    assert _derive_bucket(s, enrolls, _att()) == 'Long Absent'


def test_bucket_never_attended_new_enrollment_is_enrolled():
    s = _stud(enrolled_days_ago=2)
    enrolls = [{'status': 'Enrolled',
                'enrolled_on': date.today() - timedelta(days=2)}]
    assert _derive_bucket(s, enrolls, _att()) == 'Enrolled'


def test_bucket_terminal_states():
    s = _stud()
    assert _derive_bucket(s, [{'status': 'Dropped'}], _att()) == 'Dropped'
    assert _derive_bucket(s, [{'status': 'Completed'}], _att()) == 'Completed'
    assert _derive_bucket(
        s, [{'status': 'Completed'}, {'status': 'Dropped'}], _att()) == 'Completed'
    assert _derive_bucket(
        _stud(status='Inactive'), [{'status': 'Enrolled'}], _att()) == 'Inactive'


def test_lifecycle_not_enrolled_filter(admin_client):
    for f in ('all', 'enrolled', 'not_enrolled', 'long_absent',
              'completed', 'dropped', 'inactive', 'archived'):
        resp = admin_client.get(f'/students/lifecycle?filter={f}')
        assert resp.status_code == 200
