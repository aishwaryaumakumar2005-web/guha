"""Regression tests for staff-module critical fixes.

Covers: POST-only delete (+ login-User block), tutor import hardening,
inactive-login gate.
"""
import io

from openpyxl import Workbook

from app.extensions import db
from app.models import Tutor


def _tid(app, email='staff@guha.test'):
    with app.app_context():
        return Tutor.query.filter_by(email=email).first().id


# ---- POST-only delete + login-User block ----

def test_tutor_delete_post_only(admin_client, app):
    with app.app_context():
        t = Tutor(name='Temp', email='temp@guha.test', phone='9000000091',
                  status='Active')
        db.session.add(t)
        db.session.commit()
        tid = t.id
    assert admin_client.get(f'/tutors/delete/{tid}').status_code == 405
    assert admin_client.post(f'/tutors/delete/{tid}').status_code == 302
    with app.app_context():
        assert Tutor.query.get(tid) is None


def test_tutor_delete_blocked_when_login_exists(admin_client, app):
    tid = _tid(app)  # seed tutor shares email with the staff User
    resp = admin_client.post(f'/tutors/delete/{tid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Tutor.query.get(tid) is not None


# ---- Import hardening (ported from students) ----

def _post_import(client, rows, filename='tutors.xlsx', ai_validation='false'):
    wb = Workbook()
    ws = wb.active
    ws.append(['Name', 'Email', 'Phone', 'Specialization', 'Status', 'Courses'])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return client.post(
        '/api/tutors/import-excel',
        data={'excel_file': (buf, filename), 'ai_validation': ai_validation},
        content_type='multipart/form-data')


def test_tutor_import_blank_email_is_not_none_string(admin_client, app):
    # Validation on: blank email is a 400, never an email='None' row.
    resp = _post_import(admin_client, [['NoMail', None, '9000000092', '', 'Active', '']],
                        ai_validation='true')
    assert resp.status_code == 400
    with app.app_context():
        assert Tutor.query.filter_by(email='None').count() == 0
        assert Tutor.query.filter_by(name='NoMail').count() == 0


def test_tutor_import_blank_email_skipped_without_validation(admin_client, app):
    resp = _post_import(admin_client, [['NoMail', None, '9000000092', '', 'Active', '']])
    assert resp.status_code == 200
    assert resp.get_json()['skipped'] == 1
    with app.app_context():
        assert Tutor.query.filter_by(email='None').count() == 0


def test_tutor_import_duplicates_skipped(admin_client, app):
    resp = _post_import(admin_client, [
        ['Dup', 'STAFF@guha.test', '9000000093', '', 'Active', ''],
        ['First', 'twice@guha.test', '9000000094', '', 'Active', ''],
        ['Second', 'TWICE@guha.test', '9000000095', '', 'Active', ''],
    ])
    assert resp.status_code == 200
    data = resp.get_json()
    assert (data['imported'], data['skipped']) == (1, 2)


def test_tutor_import_status_normalized(admin_client, app):
    resp = _post_import(admin_client, [['Low', 'low@guha.test', '9000000096', '', 'active', '']])
    assert resp.status_code == 200
    with app.app_context():
        assert Tutor.query.filter_by(email='low@guha.test').first().status == 'Active'


def test_tutor_import_rejects_legacy_xls(admin_client):
    resp = _post_import(admin_client, [['A', 'a@guha.test', '9000000097', '', 'Active', '']],
                        filename='tutors.xls')
    assert resp.status_code == 400


# ---- Inactive login gate ----

def test_inactive_tutor_cannot_login(client, app):
    with app.app_context():
        t = Tutor.query.filter_by(email='staff@guha.test').first()
        t.status = 'Inactive'
        db.session.commit()
    resp = client.post('/login', data={'username': 'staff', 'password': 'staff123'})
    assert resp.status_code == 200
    assert b'deactivated' in resp.data
    # not authenticated: protected pages bounce to login
    assert client.get('/').status_code == 302


def test_active_tutor_can_login(client, app):
    resp = client.post('/login', data={'username': 'staff', 'password': 'staff123'})
    assert resp.status_code == 302
    assert client.get('/').status_code == 200
