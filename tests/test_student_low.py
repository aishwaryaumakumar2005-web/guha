"""Regression tests for student-module low/robustness fixes.

Covers: next_code column-only scan + commit retry, bounded attendance
history, server-side paging/search, and ORM audit coverage for student
create/edit/delete.
"""
from datetime import date, timedelta

from app.extensions import db
from app.helpers import next_code
from app.models import Attendance, AuditLog, Student
from app.routes.student_lifecycle import (
    _attendance_metrics, _derive_bucket, _enrolled_long_ago,
)


def _sid(app, email='student@guha.test'):
    with app.app_context():
        return Student.query.filter_by(email=email).first().id


# ---- next_code reads codes only; collisions retry then 409 ----

def test_next_code_ignores_malformed(app):
    with app.app_context():
        assert next_code('STU', Student, 'roll_no') == 'STU0002'
        db.session.add(Student(name='Odd', email='odd@guha.test',
                               phone='9000000050', status='Active',
                               roll_no='STUxx'))
        db.session.commit()
        assert next_code('STU', Student, 'roll_no') == 'STU0002'


def test_create_collision_returns_409_not_500(admin_client, app, monkeypatch):
    import app.models.student as student_model
    real = student_model.next_code
    calls = []
    with app.app_context():
        taken = Student.query.filter_by(email='student@guha.test').first().roll_no

    def always_taken(prefix, model, column):
        calls.append(1)
        return taken
    monkeypatch.setattr(student_model, 'next_code', always_taken)
    ajax = {'X-Requested-With': 'XMLHttpRequest'}
    resp = admin_client.post('/students', data={
        'name': 'Clash', 'email': 'clash@guha.test', 'phone': '9000000051',
        'status': 'Active',
    }, headers=ajax)
    assert resp.status_code == 409
    assert len(calls) == 3
    with app.app_context():
        assert Student.query.filter_by(email='clash@guha.test').count() == 0
    # Non-AJAX takes the flash+redirect path with nothing persisted.
    resp = admin_client.post('/students', data={
        'name': 'Clash2', 'email': 'clash2@guha.test', 'phone': '9000000054',
        'status': 'Active',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.filter_by(email='clash2@guha.test').count() == 0


def test_create_collision_then_success(admin_client, app, monkeypatch):
    import app.models.student as student_model
    real = student_model.next_code
    with app.app_context():
        taken = Student.query.filter_by(email='student@guha.test').first().roll_no
    state = {'n': 0}

    def once_taken(prefix, model, column):
        state['n'] += 1
        return taken if state['n'] == 1 else real(prefix, model, column)
    monkeypatch.setattr(student_model, 'next_code', once_taken)
    resp = admin_client.post('/students', data={
        'name': 'Retry', 'email': 'retry@guha.test', 'phone': '9000000052',
        'status': 'Active',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Student.query.filter_by(email='retry@guha.test').count() == 1


# ---- Attendance history is bounded; buckets unchanged ----

def test_ancient_marks_excluded_from_metrics(app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(Attendance(person_type='student', person_id=sid,
                                  date=date.today() - timedelta(days=400),
                                  status='Absent'))
        db.session.commit()
    with app.app_context():
        assert sid not in _attendance_metrics()


def test_ancient_only_student_still_long_absent(app):
    with app.app_context():
        s = Student.query.filter_by(email='student@guha.test').first()
        s.enrollment_date = date.today() - timedelta(days=500)
        db.session.commit()
        sid = s.id
        db.session.add(Attendance(person_type='student', person_id=sid,
                                  date=date.today() - timedelta(days=400),
                                  status='Absent'))
        db.session.commit()
    with app.app_context():
        s = Student.query.get(sid)
        enrolls = [{'status': 'Enrolled',
                    'enrolled_on': date.today() - timedelta(days=500)}]
        att = _attendance_metrics().get(sid, {
            'max_run': 0, 'last_streak': 0, 'att_rate': None,
            'total_marks': 0, 'last_attendance_date': None})
        assert _enrolled_long_ago(s, enrolls) is True
        assert _derive_bucket(s, enrolls, att) == 'Long Absent'


def test_detail_total_counts_unbounded_history(admin_client, app):
    sid = _sid(app)
    with app.app_context():
        for offset in (400, 3, 2, 1):
            db.session.add(Attendance(person_type='student', person_id=sid,
                                      date=date.today() - timedelta(days=offset),
                                      status='Present'))
        db.session.commit()
    data = admin_client.get(f'/students/lifecycle/{sid}/detail').get_json()
    assert data['attendance']['total_recorded'] == 4
    assert len(data['attendance']['series']) == 3


# ---- Server-side paging + search ----

def _seed_many(app, n=21):
    with app.app_context():
        for i in range(n):
            db.session.add(Student(name=f'Page Pupil {i:02d}',
                                   email=f'pupil{i:02d}@guha.test',
                                   phone=f'9000000{i:03d}', status='Active'))
        db.session.commit()


def test_students_paged(admin_client, app):
    _seed_many(app)
    body = admin_client.get('/students').get_data(as_text=True)
    assert 'Page 1 of 2' in body
    assert 'aria-label="Students pages"' in body
    body2 = admin_client.get('/students?page=2').get_data(as_text=True)
    assert 'Page 2 of 2' in body2
    assert 'Page Pupil 00' not in body2


def test_students_search(admin_client, app):
    _seed_many(app)
    body = admin_client.get('/students?q=pupil+01').get_data(as_text=True)
    assert 'Page Pupil 01' in body
    assert 'Page Pupil 02' not in body


def test_staff_page_has_search(staff_client):
    body = staff_client.get('/students').get_data(as_text=True)
    assert 'id="student-search"' in body


# ---- ORM audit already covers student writes; pin it ----

def test_create_student_audited(admin_client, app):
    admin_client.post('/students', data={
        'name': 'Audited', 'email': 'audited@guha.test', 'phone': '9000000053',
        'status': 'Active',
    })
    with app.app_context():
        sid = Student.query.filter_by(email='audited@guha.test').first().id
        log = AuditLog.query.filter_by(
            entity_type='Student', entity_id=sid, action='INSERT').first()
        assert log is not None and log.username == 'admin'


def test_edit_student_audited(admin_client, app):
    sid = _sid(app)
    admin_client.post(f'/students/edit/{sid}', data={
        'name': 'Renamed Audit', 'email': 'student@guha.test',
        'phone': '9876543210', 'status': 'Active',
    })
    with app.app_context():
        log = AuditLog.query.filter_by(
            entity_type='Student', entity_id=sid, action='UPDATE').first()
        assert log is not None and 'Renamed Audit' in (log.changes or '')


def test_delete_student_audited(admin_client, app):
    sid = _sid(app)
    admin_client.post(f'/students/delete/{sid}')
    with app.app_context():
        log = AuditLog.query.filter_by(
            entity_type='Student', entity_id=sid, action='DELETE').first()
        assert log is not None and log.username == 'admin'
