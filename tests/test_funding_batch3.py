from datetime import date


def _create(admin_client, amount=5000, method='Cash', purpose='test', reference=''):
    return admin_client.post('/funding', data={
        'amount': str(amount), 'method': method, 'purpose': purpose,
        'funding_date': date.today().isoformat(),
        'reference': reference, 'investment_type': 'Capital'})


def _body(admin_client, *args, **kwargs):
    return admin_client.get('/funding', *args, **kwargs).get_data(as_text=True)


# ---------------------------------------------------------------- U1 delete echo

def test_delete_button_echoes_record_details(admin_client, app):
    _create(admin_client, 12345, 'Bank Transfer', 'Rent arrears', 'UTR 991')
    body = _body(admin_client)
    assert 'openDeleteFunding(this)' in body
    assert 'data-amount="12345.0"' in body
    assert 'data-method="Bank Transfer"' in body
    assert 'data-purpose="Rent arrears"' in body
    assert 'data-type="Capital"' in body
    # the confirm modal now gets a specific title + the echoed amount in the message
    assert 'Reverse Capital Contribution' in body
    assert 'This action cannot be undone.' in body
    # the JS builds the message from the record's real values
    assert 'toLocaleString' in body
    assert 'Purpose: "' in body


# ---------------------------------------------------------------- U2 double submit

def test_modal_forms_are_guarded_against_double_submit(admin_client, app):
    body = _body(admin_client)
    assert body.count('onsubmit="return guardForm(this);"') >= 2
    assert 'if (form.dataset.submitting === \'1\')' in body
    assert 'form.dataset.submitting = \'1\'' in body


# ---------------------------------------------------------------- U3 purpose truncation

def test_purpose_truncated_with_tooltip(admin_client, app):
    long = 'O' * 120
    _create(admin_client, purpose=long)
    body = _body(admin_client)
    assert 'text-truncate' in body
    assert 'title="' in body
    # text still present once (in the title attribute) — not duplicated/escaped
    assert body.count(long) >= 1


# ---------------------------------------------------------------- U4 drill-down links

def test_summary_cards_deep_link_to_filters(admin_client, app):
    today = date.today()
    body = _body(admin_client)
    assert f'/funding?year={today.year}' in body
    assert f'/funding?month={today.month}&amp;year={today.year}' in body


def test_method_badge_is_drill_down_link(admin_client, app):
    _create(admin_client, method='Cash')
    _create(admin_client, method='UPI')
    body = _body(admin_client)
    assert 'method=Cash' in body
    assert 'method=UPI' in body


# ---------------------------------------------------------------- U5 balance hint label

def test_balance_hint_labels_its_account(admin_client, app):
    body = _body(admin_client)
    assert 'account — available balance:' in body
    assert 'funding-balance-hint' in body
    assert 'edit-funding-balance-hint' in body


# ---------------------------------------------------------------- U6 live amount preview

def test_amount_preview_wired_in_both_modals(admin_client, app):
    body = _body(admin_client)
    assert 'funding-amount-preview' in body
    assert 'edit-funding-amount-preview' in body
    assert 'will be recorded' in body
    assert 'wireAmountPreview(' in body


# ---------------------------------------------------------------- shared confirmAction title

def test_confirm_action_accepts_optional_title_param(admin_client, app):
    # base.html's confirmAction(message, callback, title) renders with the
    # funding page's script — prove the shared API exposes the 3rd param.
    body = _body(admin_client)
    assert 'confirmAction = function(message, callback, title)' in body
    assert "title || 'Confirm Action'" in body