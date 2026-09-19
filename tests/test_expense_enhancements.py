"""Expense enhancements: company attribution, payment reference, attachment
receipts, budget/archive category management, all-months filter, period-aware
AI optimizer period params, refund impact preview data.
"""
import io
from datetime import date

from app.extensions import db
from app.models import Company, Expense, ExpenseCategory, Student
from app.routes.expenses import ensure_expense_categories
from app.services.account_service import ensure_default_accounts

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _cat_id(app, name):
    with app.app_context():
        ensure_expense_categories()
        return ExpenseCategory.query.filter_by(name=name).first().id


def _sid(app):
    with app.app_context():
        return Student.query.filter_by(name='Test Student').first().id


def _post_expense(client, app, ajax=False, **overrides):
    data = {
        'category_id': str(overrides.get('category_id', _cat_id(app, 'Rent'))),
        'amount': overrides.get('amount', '500'),
        'expense_date': overrides.get('expense_date', date.today().isoformat()),
        'payment_method': overrides.get('payment_method', 'Cash'),
        'description': overrides.get('description', 'test expense'),
    }
    for field in ('student_id', 'company_id', 'payment_ref'):
        if field in overrides:
            data[field] = overrides[field]
    if 'attachment' in overrides:
        data['attachment'] = (io.BytesIO(overrides['attachment'][0]),
                              overrides['attachment'][1])
    headers = dict(AJAX) if ajax else {}
    return client.post('/expenses', data=data, headers=headers)


def test_expense_company_auto_attribution(admin_client, app):
    with app.app_context():
        ensure_default_accounts()
    # Ordinary cash expense tracks the Cash account's company (non-GST entity).
    resp = _post_expense(admin_client, app, description='ordinary-outflow')
    assert resp.status_code == 302
    with app.app_context():
        gst = Company.query.filter_by(code='COMP-GST').first()
        ngst = Company.query.filter_by(code='COMP-NGST').first()
        row = Expense.query.filter_by(description='ordinary-outflow').first()
        assert row.company_id == ngst.id
    # Refund follows the student's billing company (GST entity for a GST course).
    sid = _sid(app)
    resp = _post_expense(admin_client, app, student_id=str(sid),
                         description='refund-outflow')
    assert resp.status_code == 302
    with app.app_context():
        gst = Company.query.filter_by(code='COMP-GST').first()
        row = Expense.query.filter_by(description='refund-outflow').first()
        assert row.student_id == sid
        assert row.category.name == 'Refund'
        assert row.company_id == gst.id


def test_expense_explicit_company_honored(admin_client, app):
    with app.app_context():
        ensure_default_accounts()
        extra = Company(name='Extra Billing Co', code='EXTRA-TEST')
        db.session.add(extra)
        db.session.commit()
        cid = extra.id
    resp = _post_expense(admin_client, app, company_id=str(cid))
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.first().company_id == cid


def test_expense_payment_ref_saved_and_truncated(admin_client, app):
    long_ref = 'UTRABC123' * 30  # 270 chars > 100 column cap
    resp = _post_expense(admin_client, app, payment_ref=long_ref)
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.first().payment_ref == long_ref[:100]


def test_expense_attachment_upload_download_replace_remove(admin_client, app):
    png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
    resp = _post_expense(admin_client, app, attachment=(png, 'receipt.png'))
    assert resp.status_code == 302
    with app.app_context():
        row = Expense.query.first()
        eid = row.id
        assert row.attachment_name == 'receipt.png'
        assert row.attachment_mime == 'image/png'
        assert row.attachment_data == png
    dl = admin_client.get(f'/expenses/attachment/{eid}')
    assert dl.status_code == 200
    assert dl.data == png
    assert dl.headers['Content-Type'].startswith('image/png')
    # Replace on edit.
    png2 = b'\x89PNG\r\n\x1a\n' + b'\x01' * 32
    resp = admin_client.post(f'/expenses/edit/{eid}', data={
        'category_id': str(_cat_id(app, 'Rent')),
        'amount': '600', 'payment_method': 'Cash',
        'expense_date': date.today().isoformat(), 'description': 'edited',
        'attachment': (io.BytesIO(png2), 'new-receipt.png'),
    })
    assert resp.status_code == 302
    with app.app_context():
        row = Expense.query.get(eid)
        assert row.attachment_name == 'new-receipt.png'
        assert row.attachment_data == png2
    # Remove on edit.
    resp = admin_client.post(f'/expenses/edit/{eid}', data={
        'category_id': str(_cat_id(app, 'Rent')),
        'amount': '600', 'payment_method': 'Cash',
        'expense_date': date.today().isoformat(), 'description': 'edited',
        'remove_attachment': '1',
    })
    assert resp.status_code == 302
    with app.app_context():
        row = Expense.query.get(eid)
        assert row.attachment_data is None
        assert row.attachment_mime is None


def test_expense_attachment_rejects_bad_extension(admin_client, app):
    resp = _post_expense(admin_client, app, ajax=True,
                         attachment=(b'not an image', 'note.txt'))
    assert resp.status_code == 400


def test_expense_category_add_edit_budget_archive(admin_client, app):
    resp = admin_client.post('/expenses/categories/add',
                             data={'name': 'Transport', 'budget': '5000',
                                   'description': 'Commute'})
    assert resp.status_code == 302
    with app.app_context():
        cat = ExpenseCategory.query.filter_by(name='Transport').first()
        tid = cat.id
        assert cat.budget_limit == 5000.0
    # Duplicate add is rejected.
    resp = admin_client.post('/expenses/categories/add', data={'name': 'transport'})
    assert resp.status_code == 302
    with app.app_context():
        assert ExpenseCategory.query.filter_by(name='Transport').count() == 1
    # Blank name rejected.
    resp = admin_client.post('/expenses/categories/add', data={'name': '  '})
    assert resp.status_code == 302
    with app.app_context():
        assert ExpenseCategory.query.filter_by(name='Transport').count() == 1
    # Edit budget + archive.
    resp = admin_client.post(f'/expenses/categories/{tid}/edit',
                             data={'name': 'Transport', 'budget': '6000',
                                   'description': 'Bus & auto', 'is_active': '0'})
    assert resp.status_code == 302
    with app.app_context():
        cat = ExpenseCategory.query.get(tid)
        assert cat.budget_limit == 6000.0
        assert not cat.is_active
    # Archived category rejected for new bookings (AJAX -> 400).
    resp = _post_expense(admin_client, app, ajax=True, category_id=str(tid))
    assert resp.status_code == 400
    with app.app_context():
        assert Expense.query.count() == 0
    # Existing booked expense stays editable onto an archived category.
    with app.app_context():
        existing = Expense(category_id=_cat_id(app, 'Rent'), amount=100,
                           payment_method='Cash', description='seeded',
                           expense_date=date.today(), created_by=1)
        db.session.add(existing)
        db.session.commit()
        eid = existing.id
    resp = admin_client.post(f'/expenses/edit/{eid}', data={
        'category_id': str(tid), 'amount': '100', 'payment_method': 'Cash',
        'expense_date': date.today().isoformat(), 'description': 'still editable',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.get(eid).category_id == tid


def test_expense_category_refund_protected(admin_client, app):
    with app.app_context():
        rid = _cat_id(app, 'Refund')
    resp = admin_client.post(f'/expenses/categories/{rid}/edit',
                             data={'name': 'Customer Refunds', 'budget': '',
                                   'is_active': '1'})
    assert resp.status_code == 302
    with app.app_context():
        assert ExpenseCategory.query.get(rid).name == 'Refund'
    resp = admin_client.post(f'/expenses/categories/{rid}/edit',
                             data={'name': 'Refund', 'budget': '',
                                   'is_active': '0'})
    assert resp.status_code == 302
    with app.app_context():
        assert ExpenseCategory.query.get(rid).is_active


def test_expense_all_months_filter(admin_client, app):
    jan, mar = 'jan-expense', 'march-expense'
    for desc, month in [(jan, 1), (mar, 3)]:
        resp = _post_expense(admin_client, app, description=desc,
                             expense_date=f'2026-{month:02d}-15')
        assert resp.status_code == 302
    # month=0 shows all months of the selected year.
    page = admin_client.get('/expenses?month=0&year=2026').get_data(as_text=True)
    assert jan in page and mar in page
    # month=3 narrows to March only.
    page = admin_client.get('/expenses?month=3&year=2026').get_data(as_text=True)
    assert mar in page and jan not in page


def test_expense_list_shows_budget_over_badge(admin_client, app):
    rid = _cat_id(app, 'Rent')
    with app.app_context():
        ExpenseCategory.query.get(rid).budget_limit = 1000.0
        db.session.commit()
    resp = _post_expense(admin_client, app, category_id=str(rid), amount='2500',
                         expense_date=date.today().isoformat())
    assert resp.status_code == 302
    page = admin_client.get('/expenses').get_data(as_text=True)
    assert 'Over by ₹1,500' in page


def test_ai_expense_optimization_period_params(admin_client, app):
    today = date.today()
    prev_year, prev_month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    prev_date = date(prev_year, prev_month, 10)
    resp = _post_expense(admin_client, app, description='last-month-cost',
                         expense_date=prev_date.isoformat())
    assert resp.status_code == 302
    r = admin_client.get(
        f'/api/expenses/ai-optimization?month={prev_month}&year={prev_year}')
    assert r.status_code == 200
    data = r.get_json()
    assert data['total_expenses'] == 500.0
    r = admin_client.get(
        f'/api/expenses/ai-optimization?month={today.month}&year={today.year}')
    assert r.get_json()['total_expenses'] == 0.0


def test_expense_categories_page_renders(admin_client, app):
    resp = admin_client.get('/expenses/categories')
    assert resp.status_code == 200
    assert 'Expense Categories' in resp.get_data(as_text=True)


def test_expenses_page_requires_admin(app):
    with app.test_client() as staff:
        staff.post('/login', data={'username': 'staff', 'password': 'staff123'})
        assert staff.get('/expenses').status_code == 302
        assert staff.get('/expenses/categories').status_code == 302
        assert staff.post('/expenses/categories/add',
                          data={'name': 'X'}).status_code == 302