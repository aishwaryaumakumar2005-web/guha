from datetime import date

from app.extensions import db
from app.models import (Tutor, Student, TutorPayrollSettings, PayrollRecord,
                        FeeRecord)

TODAY = date.today()


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
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(FeeRecord(student_id=sid, amount_paid=amount,
                                 payment_date=TODAY, payment_method='Cash'))
        db.session.commit()


def _make_draft(app, tid, net=9000.0):
    with app.app_context():
        rec = PayrollRecord(tutor_id=tid, month=TODAY.month, year=TODAY.year,
            base_amount=10000, commission_amount=0, bonus_amount=0,
            tds_amount=1000, other_deductions=0, net_amount=net, status='Draft')
        db.session.add(rec)
        db.session.commit()
        return rec.id


def _get_payroll(app, admin_client):
    return admin_client.get('/payroll').get_data(as_text=True)


def test_table_has_pager_search_export(admin_client, app):
    body = _get_payroll(app, admin_client)
    assert 'table table-custom sortable table-dark' in body
    assert 'data-page-size="10"' in body
    assert 'data-export-url' in body


def test_only_one_settings_modal_and_shared_key(admin_client, app):
    tid = _tid(app)
    _make_draft(app, tid)
    body = _get_payroll(app, admin_client)
    assert body.count('id="settingsModal"') == 1
    assert 'id="settingsForm"' in body
    assert 'data-settings-key="' in body


def test_native_confirm_removed(admin_client, app):
    tid = _tid(app)
    _make_draft(app, tid)
    body = _get_payroll(app, admin_client)
    assert "onsubmit=\"return confirm(" not in body
    assert 'id="actionConfirmModal"' in body
    assert 'data-action-url="/payroll/' in body


def test_status_chips_present(admin_client, app):
    tid = _tid(app)
    _make_draft(app, tid)
    body = _get_payroll(app, admin_client)
    assert 'Draft 1' in body
    assert 'Cancelled 0' in body
    assert 'Paid 0' in body


def test_confirm_all_hint_mentions_all_existing(admin_client, app):
    tid = _tid(app)
    _make_draft(app, tid)
    body = _get_payroll(app, admin_client)
    assert 'id="processAll-existing"' in body
    assert 'id="processAll-month"' in body
    assert 'id="confirmAll-existing"' in body


def test_paid_date_column_and_ytd(admin_client, app):
    tid = _tid(app)
    _fund_cash(app, 20000)
    rid = _make_draft(app, tid)
    admin_client.post(f'/payroll/{rid}/confirm',
                      data={'payment_method': 'Cash',
                            'paid_date': TODAY.isoformat()})
    body = _get_payroll(app, admin_client)
    assert '>Paid Date</th>' in body
    assert TODAY.strftime('%d %b %Y') in body
    assert 'YTD ₹9,000.00' in body


def test_two_decimal_formatting(admin_client, app):
    tid = _tid(app)
    _make_draft(app, tid)
    body = _get_payroll(app, admin_client)
    assert '₹9,000.00' in body
    assert '₹10,000.00' in body


def test_zero_net_visual_warning(admin_client, app):
    tid = _tid(app)
    _make_draft(app, tid, net=0.0)
    body = _get_payroll(app, admin_client)
    assert 'bi-exclamation-triangle-fill' in body
    assert 'Nothing payable for this period' in body


def test_trend_chart_canvas(admin_client, app):
    body = _get_payroll(app, admin_client)
    assert 'id="payrollTrendChart"' in body
    assert 'Monthly Net Payable' in body


def test_settings_form_has_all_feed_inputs(app, admin_client):
    tid = _tid(app)
    _set_settings(app, tid, base_salary=7000, commission_percentage=15,
                  tds_percentage=12, bonus=500, other_deductions=100,
                  bank_name='HDFC', account_number='123456', ifsc_code='HDFC0001')
    _make_draft(app, tid)
    body = _get_payroll(app, admin_client)
    assert 'id="setting-base"' in body
    assert 'id="setting-commission"' in body
    assert 'id="setting-tds"' in body
    assert 'id="setting-bonus"' in body
    assert 'id="setting-deductions"' in body
    assert 'id="setting-bank"' in body
    assert 'id="setting-account"' in body
    assert 'id="setting-ifsc"' in body