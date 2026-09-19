from datetime import date


def _prev_month(today):
    y, m = today.year, today.month
    return date(y - 1 if m == 1 else y, 12 if m == 1 else m - 1, 1)

from app.models import OwnerFunding, AuditLog


def _create(admin_client, amount, method='Cash', purpose='test', funding_date=None,
            reference='', investment_type='Capital'):
    return admin_client.post('/funding', data={
        'amount': str(amount), 'method': method, 'purpose': purpose,
        'funding_date': funding_date or date.today().isoformat(),
        'reference': reference, 'investment_type': investment_type})


def _one(app, fid):
    with app.app_context():
        return OwnerFunding.query.get(fid)


# ---------------------------------------------------------------- F1 filters

def test_filter_by_method_shows_only_matches_and_filtered_note(admin_client, app):
    _create(admin_client, 1000, 'Cash', 'cash purpose')
    _create(admin_client, 2000, 'Cash', 'cash purpose 2')
    _create(admin_client, 9000, 'Bank Transfer', 'wire purpose')
    resp = admin_client.get('/funding?method=Bank+Transfer')
    body = resp.get_data(as_text=True)
    assert '1 matching record' in body
    assert 'wire purpose' in body
    assert 'cash purpose' not in body
    # filter results are not capped: the resolver reports matches out of total
    assert 'filtered from 3 total' in body


def test_filter_by_year_and_month(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'old row', '2024-03-15')
    _create(admin_client, 7000, 'Cash', 'new row')
    resp = admin_client.get('/funding?year=2024&month=3')
    body = resp.get_data(as_text=True)
    assert 'old row' in body
    assert 'new row' not in body
    assert '1 matching record' in body


def test_search_matches_purpose_or_reference(admin_client, app):
    _create(admin_client, 1000, 'Cash', 'Rent arrears', reference='')
    _create(admin_client, 2000, 'Bank Transfer', 'lump sum', reference='UTR 419284')
    resp = admin_client.get('/funding?q=Rent')
    body = resp.get_data(as_text=True)
    assert 'Rent arrears' in body
    assert 'lump sum' not in body
    resp = admin_client.get('/funding?q=419284')
    body = resp.get_data(as_text=True)
    assert 'lump sum' in body
    assert 'Rent arrears' not in body


# ---------------------------------------------------------------- F2 edit

def test_edit_updates_fields_and_audits(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'draft purpose', reference='CHQ 001')
    with app.app_context():
        fid = OwnerFunding.query.first().id
    resp = admin_client.post(f'/funding/edit/{fid}', data={
        'amount': '7500', 'method': 'Bank Transfer', 'purpose': 'corrected',
        'funding_date': date.today().isoformat(),
        'reference': 'UTR 77', 'investment_type': 'Director Loan'})
    assert resp.status_code == 302
    row = _one(app, fid)
    assert row.amount == 7500.0
    assert row.method == 'Bank Transfer'
    assert row.purpose == 'corrected'
    assert row.reference == 'UTR 77'
    assert row.investment_type == 'Director Loan'
    with app.app_context():
        log = AuditLog.query.filter_by(
            entity_type='OwnerFunding', entity_id=fid, action='UPDATE').first()
        assert log is not None


def test_edit_invalid_rejected(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'original')
    with app.app_context():
        fid = OwnerFunding.query.first().id
    resp = admin_client.post(f'/funding/edit/{fid}', data={
        'amount': '0.50', 'method': 'Cash', 'purpose': 'tiny',
        'funding_date': date.today().isoformat()})
    assert resp.status_code == 302
    row = _one(app, fid)
    assert row.amount == 5000.0


def test_edit_ajax_rejected_json(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'original')
    with app.app_context():
        fid = OwnerFunding.query.first().id
    resp = admin_client.post(f'/funding/edit/{fid}', data={
        'amount': '0.50', 'method': 'Cash', 'purpose': 'tiny',
        'funding_date': date.today().isoformat()}, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


# ---------------------------------------------------------------- F3 export

def test_export_csv_bom_headers_and_full_rows(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'first', reference='CHQ 001', investment_type='Capital')
    _create(admin_client, 2500, 'Bank Transfer', 'second', reference='UTR 42', investment_type='Director Loan')
    resp = admin_client.get('/funding/export')
    assert resp.status_code == 200
    assert 'text/csv' in resp.content_type
    text = resp.get_data(as_text=True)
    assert text.startswith('\ufeff')
    assert 'Date,Type,Mode,Amount,Reference,Purpose,Recorded By' in text
    assert 'Director Loan,Bank Transfer,2500.00,UTR 42,second' in text
    assert 'Capital,Cash,5000.00,CHQ 001,first' in text


# ---------------------------------------------------------------- F4 reference

def test_reference_saved(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'with ref', reference='CHQ 001254')
    with app.app_context():
        row = OwnerFunding.query.first()
        assert row.reference == 'CHQ 001254'


def test_reference_over_100_rejected(admin_client, app):
    resp = _create(admin_client, 5000, 'Cash', 'long ref', reference='R' * 180)
    assert 'at most 100 characters' in resp.get_data(as_text=True).lower()
    with app.app_context():
        assert OwnerFunding.query.count() == 0


def test_reference_blank_stored_none(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'no ref', reference='   ')
    with app.app_context():
        row = OwnerFunding.query.first()
        assert row.reference is None


# ---------------------------------------------------------------- F5 type

def test_investment_type_defaults_to_capital(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'default type')
    with app.app_context():
        row = OwnerFunding.query.first()
        assert row.investment_type == 'Capital'


def test_investment_type_loan_saved(admin_client, app):
    _create(admin_client, 5000, 'Cash', 'loan', investment_type='Director Loan')
    with app.app_context():
        row = OwnerFunding.query.first()
        assert row.investment_type == 'Director Loan'


def test_investment_type_bad_rejected(admin_client, app):
    resp = _create(admin_client, 5000, 'Cash', 'bad type', investment_type='Equity')
    assert resp.status_code in (400, 302)
    with app.app_context():
        assert OwnerFunding.query.count() == 0


def test_type_split_chips_rendered(admin_client, app):
    _create(admin_client, 500000, 'Cash', 'capital bit')
    _create(admin_client, 200000, 'Bank Transfer', 'loan bit', investment_type='Director Loan')
    body = admin_client.get('/funding').get_data(as_text=True)
    assert 'Capital ₹500,000.00' in body
    assert 'Director Loan ₹200,000.00' in body


# ---------------------------------------------------------------- F6 trend/cards

def test_summary_cards_year_month_and_delta(admin_client, app):
    today = date.today()
    prev = _prev_month(today)
    _create(admin_client, 5000, 'Cash', 'this month', today.isoformat())
    _create(admin_client, 7000, 'Cash', 'prev month', prev.isoformat())
    body = admin_client.get('/funding').get_data(as_text=True)
    assert 'Total Invested' in body and '₹12,000.00' in body
    assert 'This Year' in body
    assert 'vs last month' in body
    # delta = 5000 - 7000 = -2000 → down arrow + -2,000.00
    assert 'arrow-down-right' in body
    assert '-2,000.00' in body


def test_trend_and_split_charts_present(admin_client, app):
    _create(admin_client, 1000, 'Cash')
    body = admin_client.get('/funding').get_data(as_text=True)
    assert 'fundingTrendChart' in body
    assert 'fundingSplitChart' in body
    assert 'last 24 months' in body
    assert 'fundingTrendChart' in body


def test_edit_button_in_table_row(admin_client, app):
    _create(admin_client, 1000, 'Cash', 'editable row', reference='x')
    body = admin_client.get('/funding').get_data(as_text=True)
    assert 'openEditFunding(this)' in body
    assert 'data-type=' in body