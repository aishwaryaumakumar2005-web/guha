"""Regression tests for course-module low/robustness fixes.

Covers: capacity validation feedback, duration_weeks >= 1, required
description/syllabus, and eager company loading (no per-card N+1).
"""
from sqlalchemy import event

from app.extensions import db
from app.models import Company, Course

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _cid(app, code='PY'):
    with app.app_context():
        return Course.query.filter_by(code=code).first().id


def _create_payload(**over):
    data = {'name': 'New Course', 'code': 'NC1', 'duration_weeks': '4',
            'duration_unit': 'weeks', 'fees': '1000', 'description': 'd',
            'syllabus': 's', 'capacity': ''}
    data.update(over)
    return data


# ---- Capacity: explicit error, never silent NULL ----

def test_create_rejects_bad_capacity(admin_client, app):
    for bad in ('-5', '30.5', 'lots'):
        resp = admin_client.post('/courses', data=_create_payload(capacity=bad))
        assert resp.status_code == 302
    with app.app_context():
        assert Course.query.filter_by(code='NC1').count() == 0


def test_create_bad_capacity_ajax(admin_client):
    resp = admin_client.post('/courses', data=_create_payload(capacity='-5'),
                             headers=AJAX)
    assert resp.status_code == 400
    assert any('capacity' in e.lower() for e in resp.get_json()['errors'])


def test_create_stores_valid_capacity(admin_client, app):
    admin_client.post('/courses', data=_create_payload(capacity='45'))
    with app.app_context():
        assert Course.query.filter_by(code='NC1').first().capacity == 45


def test_edit_rejects_bad_capacity(admin_client, app):
    cid = _cid(app)
    resp = admin_client.post(f'/courses/edit/{cid}', data={
        'name': 'Python Programming', 'code': 'PY', 'description': 'd',
        'duration_weeks': '8', 'duration_unit': 'weeks', 'fees': '5000',
        'capacity': '-2', 'syllabus': 's'})
    assert resp.status_code == 302
    with app.app_context():
        assert Course.query.get(cid).capacity is None


# ---- duration_weeks >= 1 ----

def test_create_rejects_zero_duration(admin_client, app):
    resp = admin_client.post('/courses', data=_create_payload(duration_weeks='0'),
                             headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Course.query.filter_by(code='NC1').count() == 0


# ---- description/syllabus required (matches template) ----

def test_create_requires_description_and_syllabus(admin_client, app):
    payload = _create_payload()
    del payload['description']
    del payload['syllabus']
    resp = admin_client.post('/courses', data=payload, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Course.query.filter_by(code='NC1').count() == 0


# ---- company eager load: exactly one unaliased company query ----

def test_company_no_per_card_query(admin_client, app):
    with app.app_context():
        for i in range(4):
            co = Company(name=f'Co {i}', code=f'C{i}', is_active=True,
                         is_gst_registered=True)
            db.session.add(co)
            db.session.flush()
            db.session.add(Course(
                name=f'Course {i}', code=f'CC{i}', description='d',
                duration_weeks=4, duration_unit='weeks', fees=1000.0,
                company_id=co.id, syllabus='s'))
        db.session.commit()
        engine = db.session.get_bind()
    seen = []

    @event.listens_for(engine, 'before_cursor_execute')
    def _count(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    try:
        assert admin_client.get('/courses').status_code == 200
    finally:
        event.remove(engine, 'before_cursor_execute', _count)
    company_queries = [s for s in seen if 'FROM company' in s]
    # 1 = the active-companies list; per-card lazy loads would add N more
    # (joinedload renders as LEFT OUTER JOIN company AS company_1 instead).
    assert len(company_queries) == 1
