import io
import json
import zipfile
from datetime import date

from app.extensions import db
from app.models import (Tutor, Student, TutorPayrollSettings, PayrollRecord,
                        Expense, FeeRecord)


def _tid(app):
    with app.app_context():
        return Tutor.query.filter_by(email='staff@guha.test').first().id


def _set_settings(app, tid, **kw):
    with app.app_context():
        s = TutorPayrollSettings.query.filter_by(tutor_id=tid).first()
        if s is None:
            s = TutorPayrollSettings(tutor_id=tid)
            db.session.add(s)
        for k, v in kw.items():
            setattr(s, k, v)
        db.session.commit()


def _fund_cash(app, amount, method='Cash', on=date.today()):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(FeeRecord(student_id=sid, amount_paid=amount,
                                 payment_date=on, payment_method=method))
        db.session.commit()


def _add_fee(app, amount, on):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(FeeRecord(student_id=sid, amount_paid=amount,
                                 payment_date=on))
        db.session.commit()


def _make_draft(app, tid, month, year, net=9000, method='Cash'):
    with app.app_context():
        rec = PayrollRecord(tutor_id=tid, month=month, year=year,
            base_amount=10000, commission_amount=0, bonus_amount=0,
            tds_amount=1000, other_deductions=0, net_amount=net,
            status='Draft', payment_method=method)
        db.session.add(rec)
        db.session.commit()
        return rec.id


# ---- E1: student-level commission breakdown ------------------------------

def test_process_stores_commission_breakdown(app, admin_client):
    tid = _tid(app)
    _set_settings(app, tid, base_salary=5000, commission_percentage=10,
                  tds_percentage=10, bonus=0, other_deductions=0)
    _add_fee(app, 10000, date(2026, 1, 10))
    admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '1', 'year': '2026'})
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid, month=1, year=2026).first()
        rows = json.loads(rec.commission_breakdown)
        assert len(rows) == 1
        row = rows[0]
        assert row['student'] == 'Test Student'
        assert row['fees'] == 10000.0
        assert row['tutor_count'] == 1
        assert row['commission'] == 1000.0


def test_breakdown_visible_on_page(admin_client, app):
    tid = _tid(app)
    _set_settings(app, tid, base_salary=5000, commission_percentage=10,
                  tds_percentage=10, bonus=0, other_deductions=0)
    _add_fee(app, 10000, date(2026, 1, 10))
    admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '1', 'year': '2026'})
    resp = admin_client.get('/payroll?month=1&year=2026')
    body = resp.get_data(as_text=True)
    assert 'data-breakdown-id' in body
    assert 'Student-level Commission Breakdown' in body


# ---- E2: per-record recalculate ------------------------------------------

def test_recalc_refreshes_draft_from_new_fees(app, admin_client):
    tid = _tid(app)
    _set_settings(app, tid, base_salary=5000, commission_percentage=10,
                  tds_percentage=10, bonus=0, other_deductions=0)
    admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '2', 'year': '2026'})
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid, month=2, year=2026).first()
        assert rec.commission_amount == 0.0
    _add_fee(app, 8000, date(2026, 2, 5))
    admin_client.post(f"/payroll/{rec.id}/recalc")
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid, month=2, year=2026).first()
        assert abs(rec.commission_amount - 800.0) < 0.01
        assert rec.commission_pct_used == 10.0


def test_recalc_refused_for_paid(app, admin_client):
    tid = _tid(app)
    _fund_cash(app, 20000)
    rid = _make_draft(app, tid, 2, 2026)
    admin_client.post(f'/payroll/{rid}/confirm')
    resp = admin_client.post(f'/payroll/{rid}/recalc', follow_redirects=True)
    assert 'only draft records' in resp.get_data(as_text=True).lower()


# ---- E3: CSV export + batch payslip ZIP ----------------------------------

def test_export_csv(admin_client, app):
    tid = _tid(app)
    admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '3', 'year': '2026'})
    resp = admin_client.get('/payroll/export?month=3&year=2026')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers.get('Content-Type', '')
    body = resp.data.decode('utf-8-sig')
    assert 'Tutor' in body and 'Net' in body
    assert 'Staff User' in body


def test_payslips_zip(admin_client, app):
    tid = _tid(app)
    admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '3', 'year': '2026'})
    resp = admin_client.get('/payroll/payslips?month=3&year=2026')
    assert resp.status_code == 200
    assert 'application/zip' in resp.headers.get('Content-Type', '')
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = zf.namelist()
    assert len(names) == 1 and names[0].endswith('.pdf')


# ---- E4: notes ------------------------------------------------------------

def test_notes_save_and_show(admin_client, app):
    tid = _tid(app)
    rid = _make_draft(app, tid, 4, 2026)
    admin_client.post(f'/payroll/{rid}/notes', data={'notes': 'Follow up on arrears next month'})
    with app.app_context():
        assert db.session.get(PayrollRecord, rid).notes == 'Follow up on arrears next month'
    resp = admin_client.get('/payroll?month=4&year=2026')
    assert 'Follow up on arrears next month' in resp.get_data(as_text=True)


# ---- E5: confirm-time payment method + paid date -------------------------

def test_confirm_uses_selected_method_and_paid_date(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 20000)
    rid = _make_draft(app, tid, 5, 2026)
    admin_client.post(f'/payroll/{rid}/confirm',
                      data={'payment_method': 'Cash', 'paid_date': '2026-06-10'})
    with app.app_context():
        rec = db.session.get(PayrollRecord, rid)
        assert rec.status == 'Paid'
        assert rec.payment_method == 'Cash'
        assert rec.paid_date == date(2026, 6, 10)
        assert rec.expense.payment_method == 'Cash'


def test_confirm_rejects_future_paid_date(admin_client, app):
    tid = _tid(app)
    rid = _make_draft(app, tid, 5, 2026)
    resp = admin_client.post(
        f'/payroll/{rid}/confirm',
        data={'payment_method': 'Cash', 'paid_date': '2099-01-01'},
        follow_redirects=True)
    assert 'in the future' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert db.session.get(PayrollRecord, rid).status == 'Draft'


def test_confirm_updates_bank_method_not_cash(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 20000, method='Bank Transfer')
    rid = _make_draft(app, tid, 5, 2026, method='Cash')
    admin_client.post(f'/payroll/{rid}/confirm',
                      data={'payment_method': 'Bank Transfer', 'paid_date': '2026-06-10'})
    with app.app_context():
        rec = db.session.get(PayrollRecord, rid)
        assert rec.payment_method == 'Bank Transfer'
        assert rec.expense.payment_method == 'Bank Transfer'


# ---- E6: confirm-all + missing tutors -------------------------------------

def test_confirm_all_confirms_drafts(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 30000)
    rid1 = _make_draft(app, tid, 6, 2026)
    rid2 = _make_draft(app, tid, 7, 2026)
    admin_client.post('/payroll/confirm-all', data={
        'month': '6', 'year': '2026', 'payment_method': 'Cash'})
    with app.app_context():
        assert db.session.get(PayrollRecord, rid1).status == 'Paid'
        assert db.session.get(PayrollRecord, rid2).status == 'Draft'
        assert rec_expense_count(rid1) == 1


def rec_expense_count(rid):
    rec = db.session.get(PayrollRecord, rid)
    return Expense.query.filter(Expense.id == rec.expense_id).count()


def test_confirm_all_skips_negative_net(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 30000)
    with app.app_context():
        rec = PayrollRecord(tutor_id=tid, month=8, year=2026, base_amount=100,
            commission_amount=0, bonus_amount=0, tds_amount=100,
            other_deductions=500, net_amount=-500, status='Draft')
        db.session.add(rec)
        db.session.commit()
        rid = rec.id
    resp = admin_client.post('/payroll/confirm-all', data={
        'month': '8', 'year': '2026', 'payment_method': 'Cash'},
        follow_redirects=True)
    assert 'negative net' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert db.session.get(PayrollRecord, rid).status == 'Draft'


def test_missing_tutors_hint(admin_client, app):
    tid = _tid(app)
    with app.app_context():
        other = Tutor(name='No Payroll Tutor', email='nopay@guha.test',
                      phone='9000000000', status='Active')
        db.session.add(other)
        db.session.commit()
    admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '1', 'year': '2026'})
    resp = admin_client.get('/payroll?month=1&year=2026')
    body = resp.get_data(as_text=True)
    assert 'No Payroll Tutor' in body
    assert 'no payroll record for' in body


# ---- E7: account balance enforced at confirm ------------------------------

def test_confirm_blocked_when_insufficient_balance(admin_client, app):
    tid = _tid(app)
    rid = _make_draft(app, tid, 9, 2026, net=9000)
    resp = admin_client.post(f'/payroll/{rid}/confirm', follow_redirects=True)
    body = resp.get_data(as_text=True).lower()
    assert 'available' in body
    with app.app_context():
        rec = db.session.get(PayrollRecord, rid)
        assert rec.status == 'Draft'
        assert rec.expense_id is None


def test_confirm_ok_with_sufficient_balance(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 20000)
    rid = _make_draft(app, tid, 9, 2026, net=9000)
    admin_client.post(f'/payroll/{rid}/confirm')
    with app.app_context():
        rec = db.session.get(PayrollRecord, rid)
        assert rec.status == 'Paid'


# ---- E8: commission documentation present ---------------------------------

def test_commission_info_modal_present(admin_client, app):
    resp = admin_client.get('/payroll')
    body = resp.get_data(as_text=True)
    assert 'How Commission is Calculated' in body
    assert 'no pro-rating' in body.replace('pro-rating', 'pro-rating').lower()