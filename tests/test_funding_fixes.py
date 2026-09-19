from datetime import date

from app.models import OwnerFunding

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _count(app):
    with app.app_context():
        return OwnerFunding.query.count()


def test_amount_below_min_rejected_with_clear_message(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '0.50', 'method': 'Cash', 'purpose': 'tiny',
        'funding_date': date.today().isoformat()})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True).lower()
    assert 'amount must be at least 1' in body
    assert _count(app) == 0


def test_amount_above_max_rejected(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '10000000', 'method': 'Cash', 'purpose': 'too big',
        'funding_date': date.today().isoformat()})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True).lower()
    assert 'amount must be at most 9999999' in body
    assert _count(app) == 0


def test_amount_min_accepted(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '1', 'method': 'Cash', 'purpose': 'exact min',
        'funding_date': date.today().isoformat()})
    assert resp.status_code == 302
    assert _count(app) == 1


def test_future_date_message(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '5000', 'method': 'Cash', 'purpose': 'future',
        'funding_date': '2099-01-01'})
    assert resp.status_code == 400
    assert 'cannot be in the future' in resp.get_data(as_text=True).lower()
    assert _count(app) == 0


def test_malformed_date_message(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '5000', 'method': 'Cash', 'purpose': 'junk date',
        'funding_date': 'not-a-date'})
    assert resp.status_code == 400
    assert 'invalid date format' in resp.get_data(as_text=True).lower()
    assert _count(app) == 0


def test_failed_create_preserves_input_and_reopens_modal(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '25000', 'method': 'Bank Transfer', 'purpose': 'Rent arrears',
        'funding_date': '2099-05-01'})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    # typed values survive
    assert 'value="25000"' in body
    assert 'Rent arrears' in body
    assert 'value="2099-05-01"' in body
    # modal-auto-open flag rendered and selects the submitted method
    assert 'new bootstrap.Modal(_fModal).show()' in body
    assert 'value="Bank Transfer" selected' in body


def test_ajax_failure_keeps_json_shape(admin_client, app):
    resp = admin_client.post('/funding', data={
        'amount': '0.50', 'method': 'Cash', 'purpose': 'x',
        'funding_date': date.today().isoformat()}, headers=AJAX)
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload['success'] is False
    assert any('amount' in e.lower() for e in payload['errors'])


def test_delete_requires_confirm(admin_client, app):
    admin_client.post('/funding', data={
        'amount': '5000', 'method': 'Cash', 'purpose': 'seed',
        'funding_date': date.today().isoformat()})
    with app.app_context():
        fid = OwnerFunding.query.first().id
    resp = admin_client.post(f'/funding/delete/{fid}')  # no confirm field
    assert resp.status_code == 302
    assert _count(app) == 1  # kept
    resp = admin_client.post(f'/funding/delete/{fid}', data={'confirm': '1'})
    assert resp.status_code == 302
    assert _count(app) == 0


def test_delete_ajax_without_confirm_blocked(admin_client, app):
    admin_client.post('/funding', data={
        'amount': '5000', 'method': 'Cash', 'purpose': 'seed',
        'funding_date': date.today().isoformat()})
    with app.app_context():
        fid = OwnerFunding.query.first().id
    resp = admin_client.post(f'/funding/delete/{fid}', headers=AJAX)
    assert resp.status_code == 302
    assert _count(app) == 1


def test_funding_page_renders_modal_unopened_by_default(admin_client, app):
    resp = admin_client.get('/funding')
    assert resp.status_code == 200
    assert 'new bootstrap.Modal(_fModal).show()' not in resp.get_data(as_text=True)