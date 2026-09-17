from datetime import datetime, timedelta

from app.extensions import db
from app.models import Course, Enquiry, Student, SystemSetting


def _course_id(app):
    with app.app_context():
        return Course.query.filter_by(code='PY').first().id


def _make_enquiry(app, **kwargs):
    with app.app_context():
        defaults = dict(student_name='Lead', email='lead@guha.test',
                        phone='9000000001', status='New')
        defaults.update(kwargs)
        enq = Enquiry(**defaults)
        db.session.add(enq)
        db.session.commit()
        return enq.id


# ---- Bug 1: deleting a course must not delete its leads ----

def test_course_delete_detaches_instead_of_deleting_enquiries(admin_client, app):
    cid = _course_id(app)
    eid = _make_enquiry(app, course_id=cid)
    resp = admin_client.get(f'/courses/delete/{cid}')
    assert resp.status_code == 302
    with app.app_context():
        enq = Enquiry.query.get(eid)
        assert enq is not None
        assert enq.course_id is None
    page = admin_client.get('/enquiries')
    assert page.status_code == 200
    assert b'Unassigned' in page.data


def test_unassigned_enquiry_renders_without_course(admin_client, app):
    _make_enquiry(app, course_id=None)
    page = admin_client.get('/enquiries')
    assert page.status_code == 200
    assert b'Unassigned' in page.data


def test_migration_rebuilds_legacy_enquiry_table(app):
    from sqlalchemy import text
    from app.services.db_migration import migrate_enquiry_course_nullable
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        db.session.execute(text('DROP TABLE enquiry'))
        db.session.execute(text('''
            CREATE TABLE enquiry (
                id INTEGER NOT NULL PRIMARY KEY,
                student_name VARCHAR(100) NOT NULL,
                email VARCHAR(100),
                phone VARCHAR(20) NOT NULL,
                course_id INTEGER NOT NULL,
                source VARCHAR(50),
                status VARCHAR(20),
                notes TEXT,
                follow_up_date DATE,
                created_at DATETIME,
                FOREIGN KEY(course_id) REFERENCES course (id) ON DELETE CASCADE
            )
        '''))
        db.session.execute(text(
            "INSERT INTO enquiry (student_name, phone, course_id, status, created_at) "
            "VALUES ('Legacy', '9000000009', :c, 'New', :ts)"),
            {'c': cid, 'ts': datetime.utcnow()})
        db.session.commit()

        migrate_enquiry_course_nullable()

        info = {r[1]: r for r in db.session.execute(
            text('PRAGMA table_info(enquiry)')).fetchall()}
        assert not bool(info['course_id'][3])  # NOT NULL dropped
        row = db.session.execute(
            text('SELECT student_name, course_id FROM enquiry')).fetchone()
        assert row[0] == 'Legacy'
        assert row[1] == cid


# ---- Bug 2: editing must not silently rewrite the lead source ----

def test_edit_preserves_google_form_source(admin_client, app):
    eid = _make_enquiry(app, source='Google Form')
    resp = admin_client.post(f'/enquiries/edit/{eid}', data={
        'student_name': 'Lead', 'email': 'lead@guha.test', 'phone': '9000000001',
        'course_id': '', 'source': 'Google Form', 'status': 'Contacted',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.get(eid).source == 'Google Form'


def test_forms_offer_full_source_list(admin_client, app):
    page = admin_client.get('/enquiries')
    assert b'value="Google Form"' in page.data
    assert b'value="Phone"' in page.data
    assert b'value="Other"' in page.data
    kanban = admin_client.get('/enquiries/kanban')
    assert b'value="Google Form"' in kanban.data
    assert b'value="Other"' in kanban.data


# ---- Bug 3: staleness measured from last contact, not creation ----

def test_stale_followup_uses_last_contact(admin_client, app, monkeypatch):
    old = datetime.utcnow() - timedelta(days=10)
    _make_enquiry(app, student_name='Stale', email='stale@guha.test',
                  phone='9000000002', created_at=old)
    _make_enquiry(app, student_name='Fresh', email='fresh@guha.test',
                  phone='9000000003', created_at=old,
                  last_contacted_at=datetime.utcnow() - timedelta(hours=1))
    with app.app_context():
        db.session.add(SystemSetting(key='ADMIN_EMAIL', value='admin@guha.test'))
        db.session.commit()
        monkeypatch.setattr(app.notifier, '_send_email', lambda *a, **k: True)
        assert app.notifier.check_enquiry_followups() == 1


# ---- Bugs 4 & 6: conversion flow, guards and linking ----

def test_convert_creates_student_and_links(admin_client, app):
    eid = _make_enquiry(app, email='convert@guha.test')
    resp = admin_client.post(f'/enquiries/convert/{eid}',
                             headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 201
    with app.app_context():
        enq = Enquiry.query.get(eid)
        assert enq.status == 'Converted'
        assert enq.last_contacted_at is not None
        student = Student.query.filter_by(email='convert@guha.test').first()
        assert student is not None
        assert enq.converted_student_id == student.id

    again = admin_client.post(f'/enquiries/convert/{eid}',
                              headers={'X-Requested-With': 'XMLHttpRequest'})
    assert again.status_code == 400
    with app.app_context():
        assert Student.query.filter_by(email='convert@guha.test').count() == 1


def test_convert_without_email_is_refused(admin_client, app):
    eid = _make_enquiry(app, email='')
    resp = admin_client.post(f'/enquiries/convert/{eid}',
                             headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 400
    with app.app_context():
        assert Enquiry.query.get(eid).status == 'New'


def test_update_status_validates_and_stamps_contact(admin_client, app):
    eid = _make_enquiry(app)
    bad = admin_client.post(f'/enquiries/status/{eid}', data={'status': 'Bogus'},
                            headers={'X-Requested-With': 'XMLHttpRequest'})
    assert bad.status_code == 400
    with app.app_context():
        assert Enquiry.query.get(eid).status == 'New'
    ok = admin_client.post(f'/enquiries/status/{eid}', data={'status': 'Contacted'},
                           headers={'X-Requested-With': 'XMLHttpRequest'})
    assert ok.status_code == 200
    with app.app_context():
        enq = Enquiry.query.get(eid)
        assert enq.status == 'Contacted'
        assert enq.last_contacted_at is not None


# ---- Bug 5: delete must be POST ----

def test_enquiry_delete_requires_post(admin_client, app):
    eid = _make_enquiry(app)
    assert admin_client.get(f'/enquiries/delete/{eid}').status_code == 405
    resp = admin_client.post(f'/enquiries/delete/{eid}')
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.get(eid) is None


# ---- Bug 7: empty-state colspan matches the column count ----

def test_empty_state_colspan_matches_columns(admin_client, app):
    page = admin_client.get('/enquiries')
    assert page.status_code == 200
    assert b'colspan="6"' in page.data


# ---- Bug 8: kanban placeholder is managed and toast-ready ----

def test_kanban_renders_placeholder_and_toast_hooks(admin_client, app):
    page = admin_client.get('/enquiries/kanban')
    assert page.status_code == 200
    assert b'kanban-empty' in page.data
    assert b'refreshColumn' in page.data
    assert b'showToast' in page.data
