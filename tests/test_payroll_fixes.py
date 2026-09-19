from datetime import date

from app.extensions import db
from app.models import (Tutor, Student, TutorPayrollSettings, PayrollRecord,
                        Expense, ExpenseCategory, FeeRecord)


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


def _fund_cash(app, amount):
    """Record cash income so the Cash account can cover salary confirmations
    (E7 enforces sufficient balance server-side)."""
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(FeeRecord(student_id=sid, amount_paid=amount,
                                 payment_date=date.today(), payment_method='Cash'))
        db.session.commit()


# ---- P1: net must never go negative -------------------------------------

def test_settings_reject_deductions_over_net(admin_client, app):
    tid = _tid(app)
    resp = admin_client.post(f'/payroll/settings/{tid}', data={
        'base_salary': '10000', 'commission_percentage': '0',
        'tds_percentage': '10', 'bonus': '0', 'other_deductions': '20000',
    }, follow_redirects=True)
    assert 'cannot exceed' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert TutorPayrollSettings.query.filter_by(tutor_id=tid).first() is None


def test_settings_accepts_deductions_within_net(admin_client, app):
    tid = _tid(app)
    resp = admin_client.post(f'/payroll/settings/{tid}', data={
        'base_salary': '10000', 'commission_percentage': '0',
        'tds_percentage': '10', 'bonus': '0', 'other_deductions': '9000',
    }, follow_redirects=True)
    body = resp.get_data(as_text=True).lower()
    assert 'cannot exceed' not in body
    with app.app_context():
        s = TutorPayrollSettings.query.filter_by(tutor_id=tid).first()
        assert s is not None and s.other_deductions == 9000.0


def test_compute_clamps_net_to_zero(app):
    tid = _tid(app)
    _set_settings(app, tid, base_salary=1000, commission_percentage=0,
                  tds_percentage=10, bonus=0, other_deductions=5000)
    with app.app_context():
        from app.routes.payroll_routes import compute_tutor_payroll
        tutor = db.session.get(Tutor, tid)
        res = compute_tutor_payroll(tutor, 6, 2026)
        assert res['net'] == 0.0
        assert res['other_ded'] == 900.0  # clamped to gross - tds


def test_confirm_refuses_negative_net(admin_client, app):
    tid = _tid(app)
    with app.app_context():
        rec = PayrollRecord(tutor_id=tid, month=1, year=2026,
            base_amount=1000, commission_amount=0, bonus_amount=0,
            tds_amount=0, other_deductions=5000, net_amount=-4000,
            status='Draft')
        db.session.add(rec)
        db.session.commit()
        rid = rec.id
        expense_count = Expense.query.count()
    resp = admin_client.post(f'/payroll/{rid}/confirm', follow_redirects=True)
    assert 'negative' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert Expense.query.count() == expense_count
        assert db.session.get(PayrollRecord, rid).status == 'Draft'


# ---- P2: salary expense belongs to its pay period -----------------------

def test_confirm_dates_expense_to_period_end(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 20000)
    with app.app_context():
        rec = PayrollRecord(tutor_id=tid, month=2, year=2026,
            base_amount=10000, commission_amount=0, bonus_amount=0,
            tds_amount=1000, other_deductions=0, net_amount=9000,
            status='Draft')
        db.session.add(rec)
        db.session.commit()
        rid = rec.id
    admin_client.post(f'/payroll/{rid}/confirm')
    with app.app_context():
        rec = db.session.get(PayrollRecord, rid)
        assert rec.status == 'Paid'
        assert rec.expense.expense_date == date(2026, 2, 28)
        assert rec.paid_date == date.today()


def test_confirm_future_period_clamps_to_today(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 20000)
    future_year = date.today().year + 1
    with app.app_context():
        rec = PayrollRecord(tutor_id=tid, month=1, year=future_year,
            base_amount=10000, commission_amount=0, bonus_amount=0,
            tds_amount=1000, other_deductions=0, net_amount=9000,
            status='Draft')
        db.session.add(rec)
        db.session.commit()
        rid = rec.id
    admin_client.post(f'/payroll/{rid}/confirm')
    with app.app_context():
        rec = db.session.get(PayrollRecord, rid)
        assert rec.expense.expense_date == date.today()


# ---- P2: settings change recomputes drafts with the new commission % ----

def test_settings_recalc_applies_new_commission_pct(app, admin_client):
    tid = _tid(app)
    _set_settings(app, tid, base_salary=5000, commission_percentage=10,
                  tds_percentage=10, bonus=0, other_deductions=0)
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(FeeRecord(student_id=sid, amount_paid=10000,
                                 payment_date=date(2026, 1, 10)))
        db.session.commit()
    admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '1', 'year': '2026'})
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid, month=1, year=2026).first()
        assert rec.commission_pct_used == 10.0
        assert abs(rec.commission_amount - 1000.0) < 0.01
    admin_client.post(f'/payroll/settings/{tid}', data={
        'base_salary': '6000', 'commission_percentage': '15',
        'tds_percentage': '10', 'bonus': '0', 'other_deductions': '0'})
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid, month=1, year=2026).first()
        assert rec.commission_pct_used == 15.0
        assert rec.base_amount == 6000.0
        assert abs(rec.commission_amount - 1500.0) < 0.01
        assert abs(rec.net_amount - 6750.0) < 0.01  # (6000 + 1500) * 0.9


# ---- P3: no 500 on duplicate submits ------------------------------------

def test_duplicate_process_warns_not_crash(admin_client, app):
    tid = _tid(app)
    data = {'tutor_id': str(tid), 'month': '3', 'year': '2026'}
    first = admin_client.post('/payroll/process', data=data, follow_redirects=True)
    assert first.status_code == 200
    second = admin_client.post('/payroll/process', data=data, follow_redirects=True)
    assert 'already exists' in second.get_data(as_text=True).lower()
    with app.app_context():
        recs = PayrollRecord.query.filter_by(tutor_id=tid, month=3, year=2026).all()
        assert len(recs) == 1


# ---- P3: percentage override is validated -------------------------------

def test_process_rejects_percentage_override_out_of_range(admin_client, app):
    tid = _tid(app)
    resp = admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '4', 'year': '2026', 'percentage': '150'},
        follow_redirects=True)
    assert 'between 0 and 100' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert PayrollRecord.query.filter_by(tutor_id=tid, month=4, year=2026).first() is None


def test_process_accepts_percentage_override_boundary(admin_client, app):
    tid = _tid(app)
    resp = admin_client.post('/payroll/process', data={
        'tutor_id': str(tid), 'month': '4', 'year': '2026', 'percentage': '100'},
        follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        rec = PayrollRecord.query.filter_by(tutor_id=tid, month=4, year=2026).first()
        assert rec is not None and rec.commission_pct_used == 100.0


def test_process_all_rejects_percentage_out_of_range(admin_client, app):
    resp = admin_client.post('/payroll/process-all', data={
        'month': '4', 'year': '2026', 'percentage': '-5'},
        follow_redirects=True)
    assert 'between 0 and 100' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert PayrollRecord.query.filter_by(month=4, year=2026).first() is None


# ---- P3: deleting a Paid record needs explicit confirmation -------------

def test_paid_delete_requires_confirm(admin_client, app):
    tid = _tid(app)
    with app.app_context():
        cat = ExpenseCategory(name='Salary', description='Staff salary')
        db.session.add(cat)
        db.session.flush()
        expense = Expense(category_id=cat.id, amount=9000, description='Salary x',
                          expense_date=date(2026, 5, 31))
        db.session.add(expense)
        db.session.flush()
        rec = PayrollRecord(tutor_id=tid, month=5, year=2026,
            base_amount=10000, commission_amount=0, bonus_amount=0,
            tds_amount=1000, other_deductions=0, net_amount=9000,
            status='Paid', expense_id=expense.id, paid_date=date(2026, 6, 1))
        db.session.add(rec)
        db.session.commit()
        rid, eid = rec.id, expense.id
    without = admin_client.post(f'/payroll/{rid}/delete', follow_redirects=True)
    assert 'not confirmed' in without.get_data(as_text=True).lower()
    with app.app_context():
        assert db.session.get(PayrollRecord, rid) is not None
        assert db.session.get(Expense, eid) is not None
    with_confirm = admin_client.post(f'/payroll/{rid}/delete',
                                     data={'confirm': '1'}, follow_redirects=True)
    assert with_confirm.status_code == 200
    with app.app_context():
        assert db.session.get(PayrollRecord, rid) is None
        assert db.session.get(Expense, eid) is None


def test_draft_delete_works_without_confirm(admin_client, app):
    tid = _tid(app)
    with app.app_context():
        rec = PayrollRecord(tutor_id=tid, month=6, year=2026,
            base_amount=1000, commission_amount=0, bonus_amount=0,
            tds_amount=100, other_deductions=0, net_amount=900, status='Draft')
        db.session.add(rec)
        db.session.commit()
        rid = rec.id
    admin_client.post(f'/payroll/{rid}/delete')
    with app.app_context():
        assert db.session.get(PayrollRecord, rid) is None