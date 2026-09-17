"""Regression tests for course-module medium fixes.

Covers: fee-change impact warning, AI Optimize arg drop, uppercase code
normalization, dynamic GST label, blank capacity, immutable code.
"""
from app.extensions import db
from app.models import Course, SystemSetting

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _cid(app, code='PY'):
    with app.app_context():
        return Course.query.filter_by(code=code).first().id


def _edit_payload(**over):
    data = {'name': 'Python Programming', 'code': 'PY', 'description': 'd',
            'duration_weeks': '8', 'duration_unit': 'weeks', 'fees': '5000',
            'capacity': '', 'syllabus': 's'}
    data.update(over)
    return data


# ---- Fee-change impact warning ----

def test_fee_change_warns_with_count(admin_client, app):
    cid = _cid(app)
    resp = admin_client.post(f'/courses/edit/{cid}',
                             data=_edit_payload(fees='6000'), headers=AJAX)
    assert resp.status_code == 200
    msg = resp.get_json()['message']
    assert 'dues recalculated' in msg
    assert '1 active enrollment' in msg
    with app.app_context():
        assert Course.query.get(cid).fees == 6000.0


def test_fee_unchanged_no_warning(admin_client, app):
    cid = _cid(app)
    resp = admin_client.post(f'/courses/edit/{cid}',
                             data=_edit_payload(), headers=AJAX)
    assert resp.status_code == 200
    assert 'dues recalculated' not in resp.get_json()['message']


# ---- Uppercase normalization + case-insensitive duplicates ----

def test_create_code_uppercased(admin_client, app):
    admin_client.post('/courses', data={
        'name': 'Lower', 'code': 'py-101', 'duration_weeks': '4',
        'duration_unit': 'weeks', 'fees': '1000', 'syllabus': 's'})
    with app.app_context():
        assert Course.query.filter_by(code='PY-101').first() is not None
        assert Course.query.filter_by(code='py-101').first() is None


def test_create_case_variant_code_blocked(admin_client, app):
    with app.app_context():
        before = Course.query.count()
    resp = admin_client.post('/courses', data={
        'name': 'Dup', 'code': 'py', 'duration_weeks': '4',
        'duration_unit': 'weeks', 'fees': '1000', 'syllabus': 's'})
    assert resp.status_code == 302
    with app.app_context():
        assert Course.query.count() == before
        assert Course.query.filter_by(code='PY').count() == 1


# ---- Code immutable ----

def test_edit_code_change_ignored(admin_client, app):
    cid = _cid(app)
    resp = admin_client.post(f'/courses/edit/{cid}',
                             data=_edit_payload(code='CHANGED'))
    assert resp.status_code == 302
    with app.app_context():
        assert Course.query.get(cid).code == 'PY'


# ---- Blank capacity stays NULL ----

def test_edit_blank_capacity_stays_null(admin_client, app):
    cid = _cid(app)
    admin_client.post(f'/courses/edit/{cid}', data=_edit_payload(capacity=''))
    with app.app_context():
        assert Course.query.get(cid).capacity is None


# ---- Template: icon typo, dynamic GST label, safe optimize call ----

def test_course_template_fixes(admin_client, app):
    with app.app_context():
        db.session.add(SystemSetting(key='CGST_PCT', value='6'))
        db.session.add(SystemSetting(key='SGST_PCT', value='6'))
        db.session.commit()
    body = admin_client.get('/courses').get_data(as_text=True)
    assert 'class="bi bi-building me-2 text-primary"' in body
    assert '12% GST Applicable' in body
    assert '18% GST Applicable' not in body
    assert "optimizeSyllabus(" in body
    assert ", '" not in body.split('optimizeSyllabus(')[1].split(')')[0]
