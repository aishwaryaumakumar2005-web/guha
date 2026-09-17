"""Regression tests for student-lifecycle fixes #1-#8.

#1: editing a student preserves per-course enrollment history.
#2: enrolled_on is stamped on every enrollment write.
#3: lifecycle buckets prioritize current enrollments correctly.
#4: hardened enquiry conversion.  #5: unified status choices.
#6: validated + audited transitions.  #7: no orphaned attendance rows.
#8: consistent streak math, weighted rate, tunable thresholds.
"""
from datetime import date, timedelta

from app.extensions import db
from app.forms import EnquiryForm
from app.models import (
    Attendance, AuditLog, Course, Enquiry, Student, SystemSetting,
    Tutor, student_courses,
)
from app.routes.student_lifecycle import (
    _attendance_metrics, _derive_bucket, _get_thresholds,
)


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
    return {'max_run': 0, 'last_streak': streak, 'att_rate': rate,
            'total_marks': total, 'last_attendance_date': last}


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


# ---- Fix #4: hardened enquiry conversion ----

def _mk_enquiry(app, name, email, phone='9000000001'):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        enq = Enquiry(student_name=name, email=email, phone=phone,
                      course_id=cid, status='New')
        db.session.add(enq)
        db.session.commit()
        return enq.id, cid


def test_convert_without_email_blocked(admin_client, app):
    eid, _ = _mk_enquiry(app, 'NoMail', '')
    with app.app_context():
        before = Student.query.count()
    resp = admin_client.post(f'/enquiries/convert/{eid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.count() == before
        assert Enquiry.query.get(eid).status == 'New'


def test_convert_duplicate_email_case_insensitive(admin_client, app):
    eid, _ = _mk_enquiry(app, 'Dup', 'STUDENT@guha.test')
    with app.app_context():
        before = Student.query.count()
    resp = admin_client.post(f'/enquiries/convert/{eid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.count() == before
        assert Enquiry.query.get(eid).status == 'New'


def test_convert_shared_phone_warns_but_succeeds(admin_client, app):
    # seed student phone is 9876543210
    eid, _ = _mk_enquiry(app, 'SharedPhone', 'shared@guha.test',
                         phone='9876543210')
    resp = admin_client.post(
        f'/enquiries/convert/{eid}',
        headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['success'] is True and 'warning' in data
    with app.app_context():
        assert Enquiry.query.get(eid).status == 'Converted'


# ---- Fix #5: unified status choices ----

def test_enquiry_form_accepts_visited():
    form = EnquiryForm(data={'student_name': 'A', 'phone': '9112345678',
                             'course_id': '1', 'status': 'Visited'})
    assert form.validate(), form.errors


def test_enquiry_form_rejects_unknown_status():
    form = EnquiryForm(data={'student_name': 'A', 'phone': '9112345678',
                             'course_id': '1', 'status': 'Bogus'})
    assert not form.validate()


def test_edit_enquiry_to_visited(admin_client, app):
    eid, cid = _mk_enquiry(app, 'V', 'v@guha.test')
    resp = admin_client.post(f'/enquiries/edit/{eid}', data={
        'student_name': 'V', 'email': 'v@guha.test', 'phone': '9000000001',
        'course_id': str(cid), 'source': 'Walk-in', 'status': 'Visited',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.get(eid).status == 'Visited'


def test_edit_student_to_archived(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.post(f'/students/edit/{sid}', data={
        'name': 'Test Student', 'email': 'student@guha.test',
        'phone': '9876543210', 'status': 'Archived',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.get(sid).status == 'Archived'


# ---- Fix #6: validated + audited transitions ----

def test_transition_missing_enrollment_404(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    assert admin_client.post(
        '/students/enrollment/complete/9999/9999',
        data={'filter': 'all'}).status_code == 404
    assert admin_client.post(
        f'/students/enrollment/drop/{sid}/9999',
        data={'filter': 'all'}).status_code == 404
    assert admin_client.post(
        f'/students/enrollment/reactivate/{sid}/9999',
        data={'filter': 'all'}).status_code == 404


def test_drop_reason_too_long_rejected(admin_client, app):
    with app.app_context():
        s = Student.query.filter_by(email='student@guha.test').first()
        sid = s.id
        cid = Course.query.filter_by(code='PY').first().id
        audits = AuditLog.query.count()
    resp = admin_client.post(f'/students/enrollment/drop/{sid}/{cid}',
                             data={'filter': 'all', 'drop_reason': 'x' * 201})
    assert resp.status_code == 302
    row = _enrollment(app, sid, cid)
    assert (row.status or 'Enrolled') == 'Enrolled'
    with app.app_context():
        assert AuditLog.query.count() == audits


def test_complete_writes_audit_log(admin_client, app):
    with app.app_context():
        s = Student.query.filter_by(email='student@guha.test').first()
        sid = s.id
        cid = Course.query.filter_by(code='PY').first().id
    resp = admin_client.post(f'/students/enrollment/complete/{sid}/{cid}',
                             data={'filter': 'all'})
    assert resp.status_code == 302
    with app.app_context():
        logs = AuditLog.query.filter_by(
            entity_type='Student', entity_id=sid, action='UPDATE').all()
        assert any('complete' in (l.changes or '') for l in logs)
        assert any(l.username == 'admin' for l in logs)


# ---- Fix #7: no orphaned attendance rows ----

def _mark(app, person_type, person_id, day_offset, status='Absent'):
    with app.app_context():
        db.session.add(Attendance(
            person_type=person_type, person_id=person_id,
            date=date.today() - timedelta(days=day_offset), status=status))
        db.session.commit()


def test_delete_student_removes_attendance(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        other = Student(name='Keeper', email='keeper@guha.test',
                        phone='9000000002', status='Active')
        db.session.add(other)
        db.session.commit()
        oid = other.id
    _mark(app, 'student', sid, 1, 'Present')
    _mark(app, 'student', oid, 1, 'Present')
    resp = admin_client.get(f'/students/delete/{sid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Attendance.query.filter_by(
            person_type='student', person_id=sid).count() == 0
        assert Attendance.query.filter_by(
            person_type='student', person_id=oid).count() == 1


def test_delete_tutor_removes_attendance(admin_client, app):
    with app.app_context():
        tid = Tutor.query.filter_by(email='staff@guha.test').first().id
    _mark(app, 'tutor', tid, 1, 'Present')
    resp = admin_client.get(f'/tutors/delete/{tid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Attendance.query.filter_by(
            person_type='tutor', person_id=tid).count() == 0


def test_orphan_attendance_excluded_from_metrics(app):
    _mark(app, 'student', 9999, 1)
    with app.app_context():
        assert 9999 not in _attendance_metrics()


# ---- Fix #8: consistent streak math + weighted rate + tunable thresholds ----

def test_streak_spans_calendar_gaps(app):
    # Absent Fri / Mon / Tue with no weekend marks: 3 consecutive sessions.
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    for offset in (4, 3, 1):
        _mark(app, 'student', sid, offset)
    with app.app_context():
        m = _attendance_metrics()[sid]
        assert m['max_run'] == 3
        assert m['last_streak'] == 3
        s = Student.query.get(sid)
        enrolls = [{'status': 'Enrolled', 'enrolled_on': date.today()}]
        assert _derive_bucket(s, enrolls, m) == 'Long Absent'


def test_half_day_counts_half(app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    for offset in (4, 3, 2):
        _mark(app, 'student', sid, offset, 'Present')
    _mark(app, 'student', sid, 1, 'Half Day')
    with app.app_context():
        m = _attendance_metrics()[sid]
        assert m['att_rate'] == 87.5


def test_thresholds_override_and_fallback(app):
    with app.app_context():
        db.session.add(SystemSetting(key='LC_ABSENT_STREAK', value='10'))
        db.session.add(SystemSetting(key='LC_ABSENT_RATE', value='bogus'))
        db.session.commit()
        t = _get_thresholds()
        assert t['streak'] == 10
        assert t['rate'] == 75.0  # invalid value falls back
        assert t['window'] == 30
        s = Student.query.filter_by(email='student@guha.test').first()
        enrolls = [{'status': 'Enrolled', 'enrolled_on': date.today()}]
        att = {'max_run': 3, 'last_streak': 3, 'att_rate': 100.0,
               'total_marks': 3, 'last_attendance_date': date.today()}
        # streak 3 < overridden streak 10, rate is fine -> Enrolled
        # (with default thresholds this would be Long Absent)
        assert _derive_bucket(s, enrolls, att, t) == 'Enrolled'


def test_admin_saves_lifecycle_thresholds(admin_client, app):
    resp = admin_client.post('/admin', data={
        'action': 'save_lifecycle', 'LC_ABSENT_STREAK': '5',
        'LC_ABSENT_RATE': '60', 'LC_ATT_WINDOW_DAYS': '14',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert SystemSetting.query.filter_by(
            key='LC_ABSENT_STREAK').first().value == '5'
        assert _get_thresholds() == {'streak': 5, 'rate': 60.0, 'window': 14}


def test_admin_rejects_bad_lifecycle_thresholds(admin_client, app):
    resp = admin_client.post('/admin', data={
        'action': 'save_lifecycle', 'LC_ABSENT_STREAK': '0',
        'LC_ABSENT_RATE': '150', 'LC_ATT_WINDOW_DAYS': '-3',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert SystemSetting.query.filter_by(
            key='LC_ABSENT_STREAK').first() is None
        assert _get_thresholds() == {'streak': 3, 'rate': 75.0, 'window': 30}
