from datetime import datetime, timedelta

from app.extensions import db
from app.models import AuditLog, Course, Enquiry, Student, SystemSetting


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


# ---- Tier 1: status-transition integrity (no Converted without a student) ----

def test_create_rejects_converted_status(admin_client, app):
    resp = admin_client.post('/enquiries', data={
        'student_name': 'Craft', 'phone': '9111111111',
        'source': 'Walk-in', 'status': 'Converted'})
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.filter_by(phone='9111111111').count() == 0


def test_create_allows_only_new_or_contacted(admin_client, app):
    resp = admin_client.post('/enquiries', data={
        'student_name': 'OK Lead', 'phone': '9111111112',
        'source': 'Walk-in', 'status': 'New'})
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.filter_by(phone='9111111112').count() == 1


def test_edit_rejects_manual_conversion(admin_client, app):
    eid = _make_enquiry(app)
    resp = admin_client.post(f'/enquiries/edit/{eid}', data={
        'student_name': 'Lead', 'email': 'lead@guha.test', 'phone': '9000000001',
        'status': 'Converted'})
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.get(eid).status == 'New'


def test_edit_keeps_converted_lead_converted(admin_client, app):
    eid = _make_enquiry(app, email='keep@guha.test')
    admin_client.post(f'/enquiries/convert/{eid}',
                      headers={'X-Requested-With': 'XMLHttpRequest'})
    resp = admin_client.post(f'/enquiries/edit/{eid}', data={
        'student_name': 'Renamed', 'email': 'keep@guha.test',
        'phone': '9000000001', 'status': 'New'})
    assert resp.status_code == 302
    with app.app_context():
        enq = Enquiry.query.get(eid)
        assert enq.status == 'Converted'
        assert enq.student_name == 'Renamed'


def test_update_status_rejects_converted(admin_client, app):
    eid = _make_enquiry(app)
    resp = admin_client.post(f'/enquiries/status/{eid}', data={'status': 'Converted'},
                             headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 400
    with app.app_context():
        assert Enquiry.query.get(eid).status == 'New'


# ---- Tier 1: create-time dedupe on phone/email ----

def test_create_rejects_duplicate_phone(admin_client, app):
    _make_enquiry(app, email='first@guha.test', phone='9876500001')
    resp = admin_client.post('/enquiries', data={
        'student_name': 'Dup Phone', 'phone': '98765 00001',
        'email': 'second@guha.test', 'source': 'Walk-in', 'status': 'New'})
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.count() == 1


def test_create_rejects_duplicate_email_case_insensitive(admin_client, app):
    _make_enquiry(app, email='Dup@Guha.test', phone='9000000101')
    resp = admin_client.post('/enquiries', data={
        'student_name': 'Dup Email', 'phone': '9000000102',
        'email': 'dup@guha.test', 'source': 'Walk-in', 'status': 'New'})
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.count() == 1


def test_edit_rejects_collision_with_other_lead(admin_client, app):
    _make_enquiry(app, email='a@guha.test', phone='9000000201')
    bid = _make_enquiry(app, email='b@guha.test', phone='9000000202')
    resp = admin_client.post(f'/enquiries/edit/{bid}', data={
        'student_name': 'B', 'email': 'a@guha.test', 'phone': '9000000202',
        'status': 'New'})
    assert resp.status_code == 302
    with app.app_context():
        assert Enquiry.query.get(bid).email == 'b@guha.test'


def test_edit_allows_keeping_own_phone(admin_client, app):
    eid = _make_enquiry(app, email='self@guha.test', phone='9000000301')
    resp = admin_client.post(f'/enquiries/edit/{eid}', data={
        'student_name': 'Self Edited', 'email': 'self@guha.test',
        'phone': '9000000301', 'status': 'Contacted'})
    assert resp.status_code == 302
    with app.app_context():
        enq = Enquiry.query.get(eid)
        assert enq.student_name == 'Self Edited'
        assert enq.status == 'Contacted'


# ---- Tier 1: AuditLog coverage (already provided by app/audit.py ORM events) ----

def test_enquiry_history_endpoint(admin_client, app):
    eid = _make_enquiry(app)
    admin_client.post(f'/enquiries/edit/{eid}', data={
        'student_name': 'Lead', 'email': 'lead@guha.test', 'phone': '9000000001',
        'status': 'Contacted', 'notes': 'spoke to parent'})
    resp = admin_client.get(f'/enquiries/{eid}/history',
                            headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['entries']
    assert any('spoke to parent' in e['detail'] for e in data['entries'])
    assert any('status' in e['detail'] for e in data['entries'])


def test_enquiry_history_unknown_lead_404(admin_client, app):
    assert admin_client.get('/enquiries/999999/history').status_code == 404


# ---- UI/UX reforms 1-3, 6-7: table page ----

def test_table_cells_have_mobile_data_labels(admin_client, app):
    _make_enquiry(app)
    page = admin_client.get('/enquiries')
    html = page.data.decode()
    for label in ['Lead Info', 'Interested In', 'Source', 'Status',
                  'Follow Up', 'Actions']:
        assert f'data-label="{label}"' in html


def test_metrics_consolidated_into_single_tile_row(admin_client, app):
    _make_enquiry(app)
    page = admin_client.get('/enquiries')
    html = page.data.decode()
    assert 'Total Leads:' not in html  # old duplicate badge strip is gone
    assert html.count('summary-card') >= 4
    assert 'stat-number' in html and 'stat-label' in html


def test_actions_column_is_not_sortable(admin_client, app):
    _make_enquiry(app)
    page = admin_client.get('/enquiries')
    html = page.data.decode()
    assert 'no-sort' in html
    assert '<th scope="col"' in html


def test_table_page_naming_and_modal_theming(admin_client, app):
    _make_enquiry(app)
    page = admin_client.get('/enquiries')
    html = page.data.decode()
    assert 'Enquiry Pipeline' in html
    assert 'Prospect pipeline' not in html
    assert 'bi-funnel me-2 text-white' in html


def test_table_page_accessibility_hooks(admin_client, app):
    _make_enquiry(app)
    page = admin_client.get('/enquiries')
    html = page.data.decode()
    assert 'for="ai-followup-textarea"' in html
    assert 'aria-live="polite"' in html


# ---- UI/UX reforms 4-5: kanban card parity + touch fallback ----

def test_kanban_card_has_kebab_email_and_overdue(admin_client, app):
    from datetime import date
    yesterday = date.today() - timedelta(days=1)
    _make_enquiry(app, student_name='Card Lead', email='card@guha.test',
                  phone='9000000401', follow_up_date=yesterday)
    page = admin_client.get('/enquiries/kanban')
    html = page.data.decode()
    assert 'card@guha.test' in html
    assert 'Overdue' in html
    assert 'Actions for Card Lead' in html
    assert 'AI follow-up draft' in html
    assert 'data-move-select' in html
    assert 'Move to' in html


def test_audit_log_records_enquiry_lifecycle(admin_client, app):
    eid = _make_enquiry(app)
    admin_client.post(f'/enquiries/edit/{eid}', data={
        'student_name': 'Lead', 'email': 'lead@guha.test', 'phone': '9000000001',
        'status': 'Contacted', 'notes': 'first call'})
    admin_client.post(f'/enquiries/delete/{eid}')
    with app.app_context():
        rows = AuditLog.query.filter_by(entity_type='Enquiry', entity_id=eid).all()
        actions = {r.action for r in rows}
        assert 'UPDATE' in actions
        assert 'DELETE' in actions
        notes_change = [r for r in rows if r.changes and 'first call' in r.changes]
        assert notes_change, 'note edit should be captured in audit changes'
