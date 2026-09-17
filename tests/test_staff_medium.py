"""Regression tests for staff-module medium fixes.

Covers: ID-card data attributes, case-insensitive emails (+ edit AJAX
contract), guarded course ids, tutor duplicate-check, LIKE-escaped
salary lookup.
"""
from datetime import date

from app.extensions import db
from app.models import Expense, ExpenseCategory, Tutor

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _tid(app, email='staff@guha.test'):
    with app.app_context():
        return Tutor.query.filter_by(email=email).first().id


# ---- ID card: no raw interpolation ----

def test_tutor_names_not_interpolated_into_js(admin_client, app):
    with app.app_context():
        db.session.add(Tutor(
            name="O'Brien <img src=x onerror=alert(1)>",
            email='txss@guha.test', phone='9000000100', status='Active'))
        db.session.commit()
    body = admin_client.get('/tutors').get_data(as_text=True)
    assert "showIDCard('" not in body
    assert '<img src=x onerror=alert(1)>' not in body
    assert 'data-idcard-name="O&#39;Brien' in body
    assert 'showTutorIDCard' in body


# ---- Case-insensitive emails + edit AJAX contract ----

def test_create_tutor_blocks_case_variant_email(admin_client, app):
    with app.app_context():
        before = Tutor.query.count()
    resp = admin_client.post('/tutors', data={
        'name': 'Dup', 'email': 'STAFF@guha.test', 'phone': '9000000101',
        'status': 'Active',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Tutor.query.count() == before


def test_edit_tutor_dup_email_ajax(admin_client, app):
    with app.app_context():
        db.session.add(Tutor(name='Other', email='other@guha.test',
                             phone='9000000102', status='Active'))
        db.session.commit()
        tid = Tutor.query.filter_by(email='staff@guha.test').first().id
    resp = admin_client.post(f'/tutors/edit/{tid}', data={
        'name': 'Staff User', 'email': 'OTHER@guha.test',
        'phone': '9876543210', 'status': 'Active',
    }, headers=AJAX)
    assert resp.status_code == 400
    assert 'errors' in resp.get_json()
    with app.app_context():
        assert Tutor.query.get(tid).email == 'staff@guha.test'


# ---- Guarded course ids ----

def test_create_tutor_bad_course_id_no_500(admin_client, app):
    resp = admin_client.post('/tutors', data={
        'name': 'NoCourse', 'email': 'nocourse@guha.test', 'phone': '9000000103',
        'status': 'Active', 'courses': ['abc'],
    })
    assert resp.status_code == 302
    with app.app_context():
        t = Tutor.query.filter_by(email='nocourse@guha.test').first()
        assert t is not None and t.courses == []


# ---- Duplicate-check endpoint ----

def test_tutor_check_duplicate(admin_client):
    resp = admin_client.get('/api/tutors/check-duplicate?email=staff@guha.test')
    assert resp.status_code == 200
    assert len(resp.get_json()['duplicates']) == 1


def test_tutor_check_duplicate_requires_admin(staff_client):
    assert staff_client.get('/api/tutors/check-duplicate?email=x@y.zz').status_code == 302


# ---- Salary lookup escapes LIKE wildcards ----

def test_salary_lookup_ignores_wildcard_name(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory(name='Salary', description='pay')
        db.session.add(cat)
        db.session.flush()
        db.session.add(Tutor(name='100% Sure', email='wild@guha.test',
                             phone='9000000104', status='Active'))
        db.session.flush()
        tid = Tutor.query.filter_by(email='wild@guha.test').first().id
        db.session.add(Expense(category_id=cat.id, amount=5000.0,
                               description='Monthly salary payout',
                               expense_date=date.today()))
        db.session.commit()
    data = admin_client.get(f'/api/tutors/{tid}/details').get_json()
    # Unescaped, name '100% Sure' would LIKE-match every salary row.
    assert data['salary']['total_paid'] == 0
    assert data['salary']['recent_payments'] == []
