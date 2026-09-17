"""Regression tests for staff-module low/robustness fixes.

Covers: tutor photo admin gate, case-insensitive tutor matching on
login, emp_code collision retry, course-mapping audit.
"""
from app.extensions import db
from app.models import AuditLog, Course, Tutor, User

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _tid(app, email='staff@guha.test'):
    with app.app_context():
        return Tutor.query.filter_by(email=email).first().id


# ---- Photo gate ----

def test_tutor_photo_reaches_admin(admin_client, app):
    tid = _tid(app)  # seed tutor has no photo
    assert admin_client.get(f'/tutors/photo/{tid}').status_code == 404


def test_tutor_photo_blocked_for_staff(staff_client, app):
    tid = _tid(app)
    resp = staff_client.get(f'/tutors/photo/{tid}')
    assert resp.status_code == 302
    assert resp.location.endswith('/')


# ---- Case-insensitive tutor match on login ----

def test_login_matches_tutor_case_insensitively(client, app):
    with app.app_context():
        User.query.filter_by(username='staff').first().email = 'STAFF@GUHA.TEST'
        db.session.commit()
        assert Tutor.query.count() == 1
    assert client.post('/login', data={'username': 'staff',
                                       'password': 'staff123'}).status_code == 302
    with app.app_context():
        assert Tutor.query.count() == 1  # no ghost duplicate


# ---- emp_code collision retry ----

def test_create_tutor_collision_returns_409(admin_client, app, monkeypatch):
    import app.models.tutor as tutor_model
    with app.app_context():
        taken = Tutor.query.filter_by(email='staff@guha.test').first().emp_code
    monkeypatch.setattr(tutor_model, 'next_code',
                        lambda prefix, model, column: taken)
    resp = admin_client.post('/tutors', data={
        'name': 'Clash', 'email': 'tclash@guha.test', 'phone': '9000000110',
        'status': 'Active',
    }, headers=AJAX)
    assert resp.status_code == 409
    with app.app_context():
        assert Tutor.query.filter_by(email='tclash@guha.test').count() == 0


# ---- Course-mapping audit ----

def test_edit_tutor_courses_audited(admin_client, app):
    tid = _tid(app)
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    admin_client.post(f'/tutors/edit/{tid}', data={
        'name': 'Staff User', 'email': 'staff@guha.test',
        'phone': '9876543210', 'status': 'Active',
    })  # courses omitted -> removed
    with app.app_context():
        logs = AuditLog.query.filter_by(
            entity_type='Tutor', entity_id=tid, action='UPDATE').all()
        assert any(f'{cid}' in (l.changes or '') and 'courses' in (l.changes or '')
                   for l in logs)
        assert Tutor.query.get(tid).courses == []


def test_create_tutor_courses_audited(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    admin_client.post('/tutors', data={
        'name': 'Mapped', 'email': 'mapped@guha.test', 'phone': '9000000111',
        'status': 'Active', 'courses': [str(cid)],
    })
    with app.app_context():
        tid = Tutor.query.filter_by(email='mapped@guha.test').first().id
        log = AuditLog.query.filter_by(
            entity_type='Tutor', entity_id=tid, action='UPDATE').first()
        assert log is not None and f'{cid}' in (log.changes or '')
