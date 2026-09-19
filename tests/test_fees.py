"""B1 finance hardening: POST-only deletes, fee edit, stored-GST reprints,
created_by audit, payment-method validation, quickCollect XSS.
"""
from datetime import date

from app.extensions import db
from app.models import (
    AuditLog, Course, Expense, ExpenseCategory, FeeRecord, OwnerFunding,
    PayrollRecord, Student, SystemSetting, Tutor, User, student_courses,
)

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _admin_id(app):
    with app.app_context():
        return User.query.filter_by(username='admin').first().id


def _student_id(app):
    with app.app_context():
        return Student.query.filter_by(name='Test Student').first().id


def _post_fee(client, sid, amount=1180.0, method='Cash', remarks='test'):
    return client.post('/fees', data={
        'student_id': str(sid),
        'amount_paid': str(amount),
        'payment_date': date.today().isoformat(),
        'payment_method': method,
        'remarks': remarks,
    })


def _fee_record(app, rid):
    with app.app_context():
        return FeeRecord.query.get(rid)


def test_fee_create_sets_created_by_and_gst_split(admin_client, app):
    sid = _student_id(app)
    resp = _post_fee(admin_client, sid)
    assert resp.status_code == 302
    with app.app_context():
        row = FeeRecord.query.filter_by(student_id=sid).first()
        assert row is not None
        assert row.created_by == _admin_id(app)
        # 1180 @ 18% -> taxable 1000.00 + GST 180.00
        assert row.taxable_amount == 1000.0
        assert row.gst_amount == 180.0
        assert row.receipt_number
        log = AuditLog.query.filter_by(entity_type='FeeRecord', action='INSERT').first()
        assert log is not None
        assert log.username == 'admin'


def test_fee_create_bogus_student_rejected(admin_client, app):
    resp = admin_client.post('/fees', data={
        'student_id': '99999', 'amount_paid': '500',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert FeeRecord.query.count() == 0


def test_fee_delete_get_405(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid)
    with app.app_context():
        rid = FeeRecord.query.first().id
    assert admin_client.get(f'/fees/delete/{rid}').status_code == 405
    with app.app_context():
        assert FeeRecord.query.get(rid) is not None


def test_fee_delete_post_audited(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid)
    with app.app_context():
        rid = FeeRecord.query.first().id
    resp = admin_client.post(f'/fees/delete/{rid}')
    assert resp.status_code == 302
    with app.app_context():
        assert FeeRecord.query.get(rid) is None
        log = AuditLog.query.filter_by(
            entity_type='FeeRecord', action='DELETE', entity_id=rid).first()
        assert log is not None


def test_fee_edit_preserves_receipt_and_recomputes_split(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0)
    with app.app_context():
        row = FeeRecord.query.first()
        rid, old_receipt = row.id, row.receipt_number
    resp = admin_client.post(f'/fees/edit/{rid}', data={
        'student_id': str(sid), 'amount_paid': '2360',
        'payment_date': date.today().isoformat(),
        'payment_method': 'UPI', 'remarks': 'corrected',
    })
    assert resp.status_code == 302
    with app.app_context():
        row = FeeRecord.query.get(rid)
        assert row.receipt_number == old_receipt
        assert row.amount_paid == 2360.0
        assert row.taxable_amount == 2000.0
        assert row.gst_amount == 360.0
        assert row.payment_method == 'UPI'
        log = AuditLog.query.filter_by(
            entity_type='FeeRecord', action='UPDATE', entity_id=rid).first()
        assert log is not None


def test_fee_edit_bogus_student_rejected(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid)
    with app.app_context():
        rid = FeeRecord.query.first().id
    resp = admin_client.post(f'/fees/edit/{rid}', data={
        'student_id': '99999', 'amount_paid': '500',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert FeeRecord.query.get(rid).student_id == sid


def test_invalid_payment_method_rejected(admin_client, app):
    sid = _student_id(app)
    resp = admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '500',
        'payment_date': date.today().isoformat(),
        'payment_method': 'BitcoinXYZ',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert FeeRecord.query.count() == 0


def test_expense_invalid_method_rejected(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory.query.first().id
    resp = admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '100',
        'description': 'bad method test',
        'expense_date': date.today().isoformat(),
        'payment_method': 'BarterSystem',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Expense.query.count() == 0


def test_expense_amount_over_ceiling_rejected(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory.query.first().id
    resp = admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '1000000',
        'description': 'over ceiling',
        'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Expense.query.count() == 0


def test_expense_month_filter_keeps_selection(admin_client, app):
    month = date.today().month
    year = date.today().year
    html = admin_client.get(f'/expenses?month={month}&year={year}').data.decode()
    assert f'<option value="{month}" selected>' in html


def test_expense_delete_post_only(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory.query.first().id
    admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '100',
        'description': 'to delete',
        'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    })
    with app.app_context():
        eid = Expense.query.first().id
    assert admin_client.get(f'/expenses/delete/{eid}').status_code == 405
    assert admin_client.post(f'/expenses/delete/{eid}').status_code == 302
    with app.app_context():
        assert Expense.query.get(eid) is None
        assert AuditLog.query.filter_by(
            entity_type='Expense', action='DELETE', entity_id=eid).first() is not None


def test_expense_linked_to_payroll_not_deleted(admin_client, app):
    with app.app_context():
        salary_cat = ExpenseCategory(name='Salary', description='Payroll')
        db.session.add(salary_cat)
        db.session.commit()
        cat_id = salary_cat.id
        tutor_id = Tutor.query.first().id
    admin_client.post('/expenses', data={
        'category_id': str(cat_id), 'amount': '25000',
        'description': 'salary linked to payroll',
        'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    })
    with app.app_context():
        eid = Expense.query.filter_by(description='salary linked to payroll').first().id
        db.session.add(PayrollRecord(
            tutor_id=tutor_id, month=9, year=2026, net_amount=25000.0,
            status='Paid', payment_method='Cash', expense_id=eid,
        ))
        db.session.commit()
    assert admin_client.post(f'/expenses/delete/{eid}').status_code == 302
    with app.app_context():
        assert Expense.query.get(eid) is not None
        assert PayrollRecord.query.filter_by(expense_id=eid).first() is not None
    resp = admin_client.post(f'/expenses/delete/{eid}', headers=AJAX)
    assert resp.status_code == 409
    assert resp.get_json()['success'] is False
    with app.app_context():
        assert Expense.query.get(eid) is not None
        assert PayrollRecord.query.filter_by(expense_id=eid).first() is not None


def test_funding_delete_post_only_and_audited(admin_client, app):
    admin_client.post('/funding', data={
        'amount': '5000', 'method': 'Cash', 'purpose': 'seed',
        'funding_date': date.today().isoformat(),
    })
    with app.app_context():
        fid = OwnerFunding.query.first().id
        assert AuditLog.query.filter_by(
            entity_type='OwnerFunding', action='INSERT', entity_id=fid).first() is not None
    assert admin_client.get(f'/funding/delete/{fid}').status_code == 405
    assert admin_client.post(f'/funding/delete/{fid}').status_code == 302
    with app.app_context():
        assert OwnerFunding.query.get(fid) is None
        assert AuditLog.query.filter_by(
            entity_type='OwnerFunding', action='DELETE', entity_id=fid).first() is not None


def test_receipt_uses_stored_gst_after_rate_change(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0)
    with app.app_context():
        rid = FeeRecord.query.first().id
        # Change the live GST rates to 6% + 6% AFTER booking.
        for key, val in (('CGST_PCT', '6'), ('SGST_PCT', '6')):
            row = SystemSetting.query.filter_by(key=key).first()
            if row is None:
                db.session.add(SystemSetting(key=key, value=val))
            else:
                row.value = val
        db.session.commit()
    html = admin_client.get(f'/fees/receipt/{rid}').data.decode()
    # Stored split: taxable 1000.00, CGST/SGST 90.00 each.
    assert '1000.00' in html
    assert '90.00' in html
    # Recomputed-at-12% values must NOT appear (1053.57 taxable, 63.21 CGST).
    assert '1053.57' not in html
    assert '63.21' not in html


def test_quickcollect_xss_safe(admin_client, app):
    from app.models import Course
    with app.app_context():
        tricky = Student(name='O\'Brien "test" <x>', email='x@guha.test',
                         phone='9999999999', status='Active')
        db.session.add(tricky)
        db.session.flush()
        tricky.courses.append(Course.query.first())
        db.session.commit()
    html = admin_client.get('/fees').data.decode()
    assert 'onclick="quickCollect(this)"' in html
    assert 'data-student-name="O&#39;Brien' in html
    assert "quickCollect(1, '" not in html


# ---------------------------------------------------------------------------
# B2 — P1 fixes: tiles, cache invalidation, zero amounts, receipt scoping
# ---------------------------------------------------------------------------

def test_accounts_tiles_show_income(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0, method='Cash')
    html = admin_client.get('/accounts/Cash').data.decode()
    # The Activity tiles/badges carry the ₹ prefix (top cards do not) — this
    # exact string only renders when the set-before-use fix is in place.
    assert '+₹1,180.00' in html


def test_ledger_cache_invalidated_on_write(admin_client, app):
    from app.services.account_service import compute_account_summary
    sid = _student_id(app)
    admin_client.get('/fees')  # prime the summary cache while DB is empty
    _post_fee(admin_client, sid, amount=1180.0, method='Cash')
    summary = compute_account_summary()
    cash = next(a for a in summary if a['name'] == 'Cash')
    assert cash['income'] == 1180.0


def test_zero_amount_fee_rejected(admin_client, app):
    sid = _student_id(app)
    resp = admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '0',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert FeeRecord.query.count() == 0
    # Boundary 0.01 is still accepted.
    resp = admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '0.01',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert FeeRecord.query.count() == 1


def test_zero_amount_expense_rejected(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory.query.first().id
    resp = admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '0',
        'description': 'zero test',
        'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Expense.query.count() == 0


def test_funding_invalid_method_rejected(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '5000', 'method': 'BarterSystem', 'purpose': 'x',
        'funding_date': date.today().isoformat(),
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert OwnerFunding.query.count() == 0


def _seed_outsider(app):
    """Second student on a course the seeded staff tutor does NOT teach."""
    from app.models import Course
    with app.app_context():
        sid = Student.query.filter_by(name='Test Student').first().id
        other_course = Course(
            name='Other Course', code='OC', description='d',
            duration_weeks=4, duration_unit='weeks', fees=1000.0,
            gst_applicable=False,
        )
        db.session.add(other_course)
        db.session.flush()
        outsider = Student(name='Outsider', email='out@guha.test',
                           phone='8888888888', status='Active')
        db.session.add(outsider)
        db.session.flush()
        outsider.courses.append(other_course)
        db.session.add(FeeRecord(student_id=sid, amount_paid=1180.0,
                                 payment_date=date.today(), payment_method='Cash'))
        db.session.add(FeeRecord(student_id=outsider.id, amount_paid=500.0,
                                 payment_date=date.today(), payment_method='Cash'))
        db.session.commit()
        rows = {r.student_id: r.id for r in FeeRecord.query.all()}
        return rows[sid], rows[outsider.id]


def test_receipt_staff_scoping(staff_client, app):
    own_rid, other_rid = _seed_outsider(app)
    # Staff sees own-course receipts, 404 on anyone else's.
    assert staff_client.get(f'/fees/receipt/{own_rid}').status_code == 200
    assert staff_client.get(f'/fees/receipt/{other_rid}').status_code == 404


def test_receipt_admin_sees_all(admin_client, app):
    own_rid, other_rid = _seed_outsider(app)
    assert admin_client.get(f'/fees/receipt/{own_rid}').status_code == 200
    assert admin_client.get(f'/fees/receipt/{other_rid}').status_code == 200


# ---------------------------------------------------------------------------
# B3 — Func P1: company-scoped balances, account management
# ---------------------------------------------------------------------------

def _company_ids(app):
    from app.models import Company
    with app.app_context():
        gst = Company.query.filter_by(code='COMP-GST').first()
        nongst = Company.query.filter_by(code='COMP-NGST').first()
        # Companies are seeded on first /fees visit.
        return (gst.id if gst else None, nongst.id if nongst else None)


def test_balances_scoped_to_company(admin_client, app):
    sid = _student_id(app)
    admin_client.get('/fees')  # seed companies
    gst_id, nongst_id = _company_ids(app)
    assert gst_id and nongst_id
    _post_fee(admin_client, sid, amount=1180.0)
    gst_html = admin_client.get(f'/fees?company_id={gst_id}').data.decode()
    assert '1,180.00' in gst_html       # paid through the GST entity
    assert '5,900.00' in gst_html       # 5000 + 18% due through GST entity
    assert 'Student Balances Matrix —' in gst_html
    other_html = admin_client.get(f'/fees?company_id={nongst_id}').data.decode()
    assert '1,180.00' not in other_html
    assert '5,900.00' not in other_html


def test_account_rename_orphans_bucket_without_crash(admin_client, app):
    from app.models import Account
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0, method='Cash')
    with app.app_context():
        cash_id = Account.query.filter_by(name='Cash').first().id
    resp = admin_client.post(f'/accounts/edit/{cash_id}', data={
        'name': 'Petty Cash', 'account_type': 'Cash',
        'company_id': '', 'opening_balance': '0', 'is_active': '1',
    })
    assert resp.status_code == 302
    # No finance page may 500 on the orphaned bucket...
    for url in ('/accounts', '/accounts/Cash', '/fees', '/expenses', '/funding'):
        assert admin_client.get(url).status_code == 200, url
    html = admin_client.get('/accounts').data.decode()
    assert 'Petty Cash' in html
    assert '1,180.00' in html  # orphan 'Cash' bucket keeps its money visible
    assert 'without a matching account row' in html


def test_account_edit_duplicate_name_rejected(admin_client, app):
    from app.models import Account
    with app.app_context():
        cash_id = Account.query.filter_by(name='Cash').first().id
    resp = admin_client.post(f'/accounts/edit/{cash_id}', data={
        'name': 'UPI', 'account_type': 'Cash',
        'company_id': '', 'opening_balance': '0', 'is_active': '1',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert Account.query.get(cash_id).name == 'Cash'


def test_account_edit_get_405(admin_client, app):
    from app.models import Account
    with app.app_context():
        cash_id = Account.query.filter_by(name='Cash').first().id
    assert admin_client.get(f'/accounts/edit/{cash_id}').status_code == 405


def test_account_edit_opening_reflects(admin_client, app):
    from app.models import Account
    with app.app_context():
        cash_id = Account.query.filter_by(name='Cash').first().id
    resp = admin_client.post(f'/accounts/edit/{cash_id}', data={
        'name': 'Cash', 'account_type': 'Cash',
        'company_id': '', 'opening_balance': '500', 'is_active': '1',
    })
    assert resp.status_code == 302
    html = admin_client.get('/accounts/Cash').data.decode()
    assert '500.00' in html


# ---------------------------------------------------------------------------
# B3 — UI P1: reconciling receipt, company preselect
# ---------------------------------------------------------------------------

def test_receipt_installment_line_reconciles(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0, remarks='capstone')
    with app.app_context():
        rid = FeeRecord.query.first().id
    html = admin_client.get(f'/fees/receipt/{rid}').data.decode()
    assert 'Course fee installment' in html
    assert 'Balance due' in html
    assert 'Paid to date' in html
    assert '5900.00' in html    # enrollment total (receipt uses %.2f)
    assert '4720.00' in html    # 5900 - 1180 balance
    assert '5000.00' not in html  # no full-fee line masquerading as this payment


def test_company_preselected_per_student(admin_client, app):
    admin_client.get('/fees')  # seed companies
    gst_id, _ = _company_ids(app)
    html = admin_client.get('/fees').data.decode()
    assert f'data-company-id="{gst_id}"' in html


# ---------------------------------------------------------------------------
# B4 — P2: no-op ensure, future dates, salary clamp
# ---------------------------------------------------------------------------

def test_ensure_default_accounts_no_commit_on_noop(app):
    from sqlalchemy import event
    from app.extensions import db
    from app.services.account_service import ensure_default_accounts
    with app.app_context():
        ensure_default_accounts()  # settle state (may commit)
        calls = []

        def _count(s):
            calls.append(1)

        event.listen(db.session, 'after_commit', _count)
        try:
            ensure_default_accounts()
        finally:
            event.remove(db.session, 'after_commit', _count)
        assert calls == []


def test_future_payment_date_rejected(admin_client, app):
    from datetime import timedelta
    sid = _student_id(app)
    future = (date.today() + timedelta(days=5)).isoformat()
    for url, data in (
        ('/fees', {'student_id': str(sid), 'amount_paid': '500',
                   'payment_date': future, 'payment_method': 'Cash'}),
        ('/expenses', {'category_id': '1', 'amount': '100',
                       'description': 'future', 'expense_date': future,
                       'payment_method': 'Cash'}),
        ('/funding', {'amount': '5000', 'method': 'Cash',
                      'purpose': 'future', 'funding_date': future}),
    ):
        resp = admin_client.post(url, data=data, headers=AJAX)
        assert resp.status_code == 400, url
    with app.app_context():
        assert FeeRecord.query.count() == 0
        assert Expense.query.count() == 0
        assert OwnerFunding.query.count() == 0


def test_salary_calculator_percentage_clamped(admin_client, app):
    from app.models import Tutor
    with app.app_context():
        tid = Tutor.query.first().id
    html = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=999').data.decode()
    assert 'value="100.0"' in html
    html = admin_client.get(
        f'/salary-calculator?tutor_id={tid}&percentage=-5').data.decode()
    assert 'value="0.0"' in html


def test_payroll_settings_percentage_capped(admin_client, app):
    from app.models import Tutor, TutorPayrollSettings
    with app.app_context():
        tid = Tutor.query.first().id
    admin_client.post(f'/payroll/settings/{tid}', data={
        'base_salary': '10000', 'commission_percentage': '150',
        'tds_percentage': '10', 'bonus': '0', 'other_deductions': '0',
    })
    with app.app_context():
        settings = TutorPayrollSettings.query.filter_by(tutor_id=tid).first()
        assert settings is None or settings.commission_percentage != 150


# ---------------------------------------------------------------------------
# B4 — Func P2: bounded lists, exports, dues (overpaid/aging/concession)
# ---------------------------------------------------------------------------

def test_fees_history_capped_with_total(admin_client, app):
    sid = _student_id(app)
    with app.app_context():
        for i in range(205):
            db.session.add(FeeRecord(student_id=sid, amount_paid=10.0,
                                     payment_date=date.today(),
                                     payment_method='Cash'))
        db.session.commit()
    html = admin_client.get('/fees').data.decode()
    assert 'latest 200 of 205 records' in html


def test_expenses_funding_lists_show_totals(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory.query.first().id
        for i in range(3):
            db.session.add(Expense(category_id=cat, amount=10.0,
                                   description=f'e{i}',
                                   expense_date=date.today(),
                                   payment_method='Cash'))
        db.session.commit()
    html = admin_client.get('/expenses').data.decode()
    assert 'latest 3 of 3 records' in html
    html = admin_client.get('/funding').data.decode()
    assert 'latest 0 of 0 records' in html


def test_breakdown_shows_type_totals(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0, method='Cash',
              remarks='ledger-row-xyz')
    html = admin_client.get('/accounts/Cash').data.decode()
    assert '1 fees' in html
    # Regression: matching_methods compared canonical vs normalized names, so
    # the per-account ledger silently matched nothing (always empty).
    assert 'ledger-row-xyz' in html


def test_exports_respect_company_filter(admin_client, app):
    sid = _student_id(app)
    admin_client.get('/fees')  # seed companies
    gst_id, nongst_id = _company_ids(app)
    _post_fee(admin_client, sid, amount=1180.0)
    html = admin_client.get('/fees').data.decode()
    assert 'export/tally' in html and 'export/zoho' in html
    tally = admin_client.get(f'/fees/export/tally?company_id={gst_id}')
    assert tally.status_code == 200
    assert 'attachment' in tally.headers.get('Content-Disposition', '')
    empty = admin_client.get(f'/fees/export/tally?company_id={nongst_id}')
    assert empty.status_code == 302  # no rows -> redirected with warning
    zoho = admin_client.get(f'/fees/export/zoho?company_id={gst_id}')
    assert zoho.status_code == 200
    assert 'attachment' in zoho.headers.get('Content-Disposition', '')


def test_overpaid_status_visible(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=7000.0)  # due is 5900
    html = admin_client.get('/fees').data.decode()
    assert 'Overpaid' in html
    assert '1,100.00' in html  # credit
    assert 'Paid In Full' not in html


def test_aging_shown_for_dues(admin_client, app):
    from datetime import timedelta
    sid = _student_id(app)
    with app.app_context():
        student = Student.query.get(sid)
        student.enrollment_date = date.today() - timedelta(days=45)
        db.session.commit()
    html = admin_client.get('/fees').data.decode()
    assert '45d' in html


def test_concession_settles_dues(admin_client, app):
    sid = _student_id(app)
    resp = admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '180', 'concession': '1000',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    html = admin_client.get('/fees').data.decode()
    assert '+₹1,000.00 waiver' in html
    assert '₹4,720.00' in html  # 5900 - 180 - 1000 outstanding
    with app.app_context():
        row = FeeRecord.query.filter_by(student_id=sid).first()
        assert row.concession == 1000.0


def test_negative_concession_rejected(admin_client, app):
    sid = _student_id(app)
    resp = admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '180', 'concession': '-50',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    }, headers=AJAX)
    assert resp.status_code == 400
    with app.app_context():
        assert FeeRecord.query.count() == 0


def test_receipt_shows_concessions(admin_client, app):
    sid = _student_id(app)
    admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '1180', 'concession': '1000',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    })
    with app.app_context():
        rid = FeeRecord.query.first().id
    html = admin_client.get(f'/fees/receipt/{rid}').data.decode()
    assert 'Concessions / waivers' in html
    assert '3720.00' in html  # 5900 - 1180 - 1000


# ---------------------------------------------------------------------------
# B5 — P3: date filter, indexes, KPIs, receipt settings, coverage
# ---------------------------------------------------------------------------

def test_date_range_filter_narrows_history(admin_client, app):
    from datetime import timedelta
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0)
    with app.app_context():
        db.session.add(FeeRecord(student_id=sid, amount_paid=777.0,
                                 payment_date=date.today() - timedelta(days=40),
                                 payment_method='Cash'))
        db.session.commit()
    html = admin_client.get(
        f'/fees?from_date={date.today().isoformat()}').data.decode()
    assert '1,180.00' in html
    assert '777.00' not in html
    # Malformed dates are ignored, not 500s.
    html = admin_client.get('/fees?from_date=not-a-date&to_date=xx').data.decode()
    assert '1,180.00' in html and '777.00' in html
    # Dead placeholder div is gone, replaced by a working form.
    assert 'dateRangeFilterContainer' not in html
    assert 'name="from_date"' in html


def test_finance_indexes_present(app):
    from sqlalchemy import inspect
    from app.extensions import db
    with app.app_context():
        insp = inspect(db.engine)
        assert {'idx_fee_company', 'idx_fee_payment_method'} <= {
            c['name'] for c in insp.get_indexes('fee_record')}
        assert {'idx_expense_payment_method'} <= {
            c['name'] for c in insp.get_indexes('expense')}
        assert {'idx_funding_method'} <= {
            c['name'] for c in insp.get_indexes('owner_funding')}


def test_kpi_strip_values(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0)
    html = admin_client.get('/fees').data.decode()
    assert 'Collected this month' in html
    assert 'Outstanding now' in html
    assert '4,720.00' in html   # 5900 - 1180 outstanding
    assert '20.0%' in html      # 1180 / 5900 collected
    assert 'Receipts' in html


def test_receipt_details_from_settings(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0)
    with app.app_context():
        rid = FeeRecord.query.first().id
        db.session.add(SystemSetting(key='ORG_STATE', value='Karnataka'))
        db.session.add(SystemSetting(key='ORG_STATE_CODE', value='29'))
        db.session.commit()
    html = admin_client.get(f'/fees/receipt/{rid}').data.decode()
    assert 'Karnataka (29)' in html
    assert 'Tamil Nadu (33)' not in html
    assert 'yazh_academy_logo' in html  # file present -> rendered


def test_expense_create_edit_and_filters(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory.query.first().id
    resp = admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '250',
        'description': 'filter me',
        'expense_date': date.today().isoformat(),
        'payment_method': 'UPI',
    })
    assert resp.status_code == 302
    with app.app_context():
        eid = Expense.query.first().id
    # Category + month filters narrow the list.
    html = admin_client.get(f'/expenses?category_id={cat}').data.decode()
    assert 'filter me' in html
    html = admin_client.get('/expenses?category_id=99999').data.decode()
    assert 'filter me' not in html
    # Edit validation rejects bad category.
    resp = admin_client.post(f'/expenses/edit/{eid}', data={
        'category_id': '99999', 'amount': '250',
        'description': 'filter me',
        'expense_date': date.today().isoformat(),
        'payment_method': 'UPI',
    }, headers=AJAX)
    assert resp.status_code == 400
    # Edit happy path works.
    resp = admin_client.post(f'/expenses/edit/{eid}', data={
        'category_id': str(cat), 'amount': '300',
        'description': 'edited desc',
        'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.get(eid).amount == 300.0


def test_funding_create_and_totals(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '5000', 'method': 'Bank Transfer', 'purpose': 'infra',
        'funding_date': date.today().isoformat(),
    })
    assert resp.status_code == 302
    html = admin_client.get('/funding').data.decode()
    assert 'infra' in html
    assert '5,000.00' in html  # month_total + total_invested aggregates
    with app.app_context():
        rec = OwnerFunding.query.first()
        assert rec.method == 'Bank Transfer'
        assert rec.created_by == _admin_id(app)


def test_account_icon_and_mode_labels(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0, method='UPI')
    html = admin_client.get('/accounts').data.decode()
    assert 'bi-phone' in html  # shared ACCOUNT_TYPE_ICONS via summary dict
    upi_html = admin_client.get('/accounts/UPI').data.decode()
    assert '>UPI<' in upi_html  # canonical label, not raw 'upi'


# ---------------------------------------------------------------------------
# W1/W4/W5 follow-ups
# ---------------------------------------------------------------------------

def test_invoice_rows_reconcile():
    from app.services.accounting import build_invoice_item_rows
    import re

    def _num(s):
        return float(s.replace('Rs.', '').replace(',', '').strip())

    rows = build_invoice_item_rows('Course fee installment (X)', True, '999293',
                                   1000.0, 90.0, 90.0, 1180.0)
    assert len(rows) == 1  # one installment row, never per-course full fees
    amount, cgst, sgst, total = (_num(rows[0][2]), _num(rows[0][3]),
                                 _num(rows[0][4]), _num(rows[0][5]))
    assert round(amount + cgst + sgst, 2) == total
    rows = build_invoice_item_rows('Course fee installment', False, '999293',
                                   500.0, 0, 0, 500.0)
    assert len(rows) == 1
    assert _num(rows[0][2]) == _num(rows[0][3])


def test_invoice_item_description_truncates(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=1180.0)
    with app.app_context():
        rec = FeeRecord.query.first()
        desc = app.accounting.invoice_item_description(rec)
    assert desc.startswith('Course fee installment')
    assert len(desc) <= 40  # fixed-width PDF cell cannot wrap


def test_receipt_footer_scoped_to_entity(admin_client, app):
    from app.models import Course
    sid = _student_id(app)
    with app.app_context():
        extra = Course(name='Extra NonGST', code='EX', description='d',
                       duration_weeks=4, duration_unit='weeks', fees=2000.0,
                       gst_applicable=False)
        db.session.add(extra)
        db.session.flush()
        student = Student.query.get(sid)
        student.courses.append(extra)
        db.session.commit()
    _post_fee(admin_client, sid, amount=1180.0)  # books to the GST entity
    with app.app_context():
        rid = FeeRecord.query.first().id
    html = admin_client.get(f'/fees/receipt/{rid}').data.decode()
    assert '5900.00' in html    # GST-scoped dues only
    assert '6900.00' not in html  # not the global enrollment total
    assert '2000.00' not in html  # other entity's course leaks nowhere


def test_kpi_cash_vs_settled(admin_client, app):
    sid = _student_id(app)
    admin_client.post('/fees', data={
        'student_id': str(sid), 'amount_paid': '1180', 'concession': '1000',
        'payment_date': date.today().isoformat(), 'payment_method': 'Cash',
    })
    html = admin_client.get('/fees').data.decode()
    assert '20.0%' in html  # cash-only headline rate
    assert '36.9%' in html  # 2180 / 5900 settled
    assert 'settled incl. waivers' in html


# ---------------------------------------------------------------------------
# W2 — agreed-dues snapshot at enrollment
# ---------------------------------------------------------------------------

def test_w2_snapshot_columns_present(app):
    from sqlalchemy import inspect
    with app.app_context():
        assoc = {c['name'] for c in inspect(db.engine).get_columns('student_courses')}
        assert {'agreed_fee', 'agreed_gst', 'agreed_company_id'} <= assoc
        expense = {c['name'] for c in inspect(db.engine).get_columns('expense')}
        assert 'student_id' in expense


def test_w2_stamp_freezes_catalog_price(admin_client, app):
    sid = _student_id(app)
    from app.models import stamp_agreed_dues
    with app.app_context():
        assert stamp_agreed_dues(sid) == 1
        db.session.commit()
        row = db.session.query(student_courses).filter_by(student_id=sid).first()
        assert row.agreed_fee == 5000.0
        assert row.agreed_gst == 1
    # Mid-cycle catalog revision: price rises 5000 -> 8000.
    with app.app_context():
        Course.query.filter_by(code='PY').first().fees = 8000.0
        db.session.commit()
    html = admin_client.get('/fees').data.decode()
    assert '5,900.00' in html      # agreed 5000 + 18% GST — unchanged
    assert '9,440.00' not in html  # the new 8000 + 18% must not appear


def test_w2_enrollment_route_stamps_agreed_dues(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    resp = admin_client.post('/students', data={
        'name': 'W2 Alice', 'email': 'w2alice@guha.test', 'phone': '9123456789',
        'status': 'Active', 'courses': [str(cid)],
    })
    assert resp.status_code == 302
    with app.app_context():
        s = Student.query.filter_by(email='w2alice@guha.test').first()
        row = db.session.query(student_courses).filter_by(student_id=s.id).first()
        assert row is not None
        assert row.agreed_fee == 5000.0
        assert row.agreed_gst == 1


def test_w2_unsnapshotted_rows_fall_back_to_catalog(admin_client, app):
    # Seeded student has no snapshot (seed bypasses stamping): dues still
    # compute from the live course row until a snapshot is taken.
    html = admin_client.get('/fees').data.decode()
    assert '5,900.00' in html


def test_w2_course_edit_message_no_longer_claims_recalc(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    resp = admin_client.post(f'/courses/edit/{cid}', data={
        'name': 'Python Programming', 'code': 'PY',
        'description': 'Beginner Python', 'duration_weeks': '8',
        'duration_unit': 'weeks', 'fees': '8000', 'syllabus': 's',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'agreed price' in resp.data
    assert b'recalculated' not in resp.data


# ---------------------------------------------------------------------------
# W3 — student-linked refund expenses
# ---------------------------------------------------------------------------

def _refund(app, client, sid, amount, category='Refund'):
    with app.app_context():
        cat = ExpenseCategory.query.filter_by(name=category).first()
        if cat is None:
            cat = ExpenseCategory(name=category)
            db.session.add(cat)
            db.session.commit()
        cat_id = cat.id
    return client.post('/expenses', data={
        'category_id': str(cat_id), 'amount': str(amount),
        'description': 'refund test', 'expense_date': date.today().isoformat(),
        'payment_method': 'Cash', 'student_id': str(sid),
    })


def test_w3_refund_reopens_paid_in_full(admin_client, app):
    sid = _student_id(app)
    _post_fee(admin_client, sid, amount=5900.0)
    assert 'Paid In Full' in admin_client.get('/fees').data.decode()
    assert _refund(app, admin_client, sid, 2000).status_code == 302
    with app.app_context():
        exp = Expense.query.filter_by(student_id=sid).first()
        assert exp is not None
        assert exp.student_id == sid
    html = admin_client.get('/fees').data.decode()
    assert 'refunded' in html
    assert '2,000.00' in html
    assert 'Paid In Full' not in html
    assert 'Partial Dues' in html
    # balance = 5900 - 5900 + 2000 = 2000
    assert '<td class="fw-semibold">₹2,000.00</td>' in html


def test_w3_unlinked_expense_does_not_touch_dues(admin_client, app):
    sid = _student_id(app)
    with app.app_context():
        cat = ExpenseCategory.query.filter_by(name='Rent').first().id
    resp = admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '999',
        'description': 'plain rent', 'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.first().student_id is None
    html = admin_client.get('/fees').data.decode()
    assert '5,900.00' in html
    assert '999.00' not in html


def test_w3_refund_category_without_student_rejected(admin_client, app):
    # 'Refund' without a valid student link is a booking error: posting one
    # must not silently create a normal expense.
    resp = _refund(app, admin_client, 99999, 100)
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.count() == 0
    with app.app_context():
        refund_cat = ExpenseCategory.query.filter_by(name='Refund').first().id
    resp = admin_client.post('/expenses', data={
        'category_id': str(refund_cat), 'amount': '100',
        'description': 'orphan refund', 'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    }, headers=AJAX)
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False
    with app.app_context():
        assert Expense.query.count() == 0


def test_w3_student_link_normalized_to_refund_category(admin_client, app):
    with app.app_context():
        cat = ExpenseCategory.query.filter_by(name='Rent').first().id
    sid = _student_id(app)
    resp = admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '100',
        'description': 'mislabeled refund', 'expense_date': date.today().isoformat(),
        'payment_method': 'Cash', 'student_id': str(sid),
    })
    assert resp.status_code == 302
    with app.app_context():
        exp = Expense.query.filter_by(description='mislabeled refund').first()
        assert exp.student_id == sid
        assert exp.category.name == 'Refund'


def test_w3_expense_edit_toggles_student_link(admin_client, app):
    sid = _student_id(app)
    with app.app_context():
        cat = ExpenseCategory.query.filter_by(name='Rent').first().id
    resp = admin_client.post('/expenses', data={
        'category_id': str(cat), 'amount': '150',
        'description': 'repurpose me', 'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        eid = Expense.query.first().id
    resp = admin_client.post(f'/expenses/edit/{eid}', data={
        'category_id': str(cat), 'amount': '150',
        'description': 'now a refund', 'expense_date': date.today().isoformat(),
        'payment_method': 'Cash', 'student_id': str(sid),
    })
    assert resp.status_code == 302
    with app.app_context():
        assert Expense.query.get(eid).student_id == sid
        assert Expense.query.get(eid).category.name == 'Refund'


def test_w3_refund_edit_requires_student(admin_client, app):
    sid = _student_id(app)
    _refund(app, admin_client, sid, 500)
    with app.app_context():
        eid = Expense.query.filter_by(student_id=sid).first().id
        refund_cat = ExpenseCategory.query.filter_by(name='Refund').first().id
    resp = admin_client.post(f'/expenses/edit/{eid}', data={
        'category_id': str(refund_cat), 'amount': '500',
        'description': 'refund test', 'expense_date': date.today().isoformat(),
        'payment_method': 'Cash',
    })
    assert resp.status_code == 302
    with app.app_context():
        exp = Expense.query.get(eid)
        assert exp.student_id == sid


def test_w3_routes_validate_bad_method_unchanged(admin_client, app):
    sid = _student_id(app)
    resp = _refund(app, admin_client, sid, 500)
    assert resp.status_code == 302
    with app.app_context():
        exp = Expense.query.filter_by(student_id=sid).first()
        assert exp.payment_method == 'Cash'
