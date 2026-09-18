"""B1 finance hardening: POST-only deletes, fee edit, stored-GST reprints,
created_by audit, payment-method validation, quickCollect XSS.
"""
from datetime import date

from app.extensions import db
from app.models import (
    AuditLog, Expense, ExpenseCategory, FeeRecord, OwnerFunding,
    Student, SystemSetting, User,
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
