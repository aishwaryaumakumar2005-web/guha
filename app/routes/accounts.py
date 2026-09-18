from flask import Blueprint, jsonify, redirect, render_template, request, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models import Account, Company
from app.helpers import admin_required, is_ajax_request
from app.services.account_service import (
    compute_account_summary, account_breakdown, ensure_default_accounts, matching_methods,
)


accounts_bp = Blueprint('accounts', __name__)

ACCOUNT_TYPES = ('Cash', 'Bank', 'UPI', 'Card', 'Other')


@accounts_bp.route('/accounts')
@login_required
@admin_required
def index():
    ensure_default_accounts()
    summary = compute_account_summary()
    default_name = summary[0]['name'] if summary else 'Cash'
    breakdown = account_breakdown(default_name)
    active_methods = matching_methods(default_name)
    companies = Company.query.filter_by(is_active=True).order_by(Company.name).all()
    return render_template(
        'accounts.html', accounts=summary, active_name=default_name,
        breakdown=breakdown, active_methods=active_methods,
        companies=companies, account_types=ACCOUNT_TYPES,
    )


@accounts_bp.route('/accounts/<account_name>')
@login_required
@admin_required
def detail(account_name):
    ensure_default_accounts()
    summary = compute_account_summary()
    breakdown = account_breakdown(account_name)
    active_methods = matching_methods(account_name)
    companies = Company.query.filter_by(is_active=True).order_by(Company.name).all()
    return render_template(
        'accounts.html', accounts=summary, active_name=account_name,
        breakdown=breakdown, active_methods=active_methods,
        companies=companies, account_types=ACCOUNT_TYPES,
    )


@accounts_bp.route('/accounts/edit/<int:account_id>', methods=['POST'])
@login_required
@admin_required
def edit(account_id):
    acc = Account.query.get_or_404(account_id)

    def _fail(msg):
        if is_ajax_request():
            return jsonify({"success": False, "errors": [msg]}), 400
        flash(msg, 'danger')
        return redirect(url_for('accounts.detail', account_name=acc.name))

    name = (request.form.get('name') or '').strip()
    if not name:
        return _fail("Account name is required.")
    if len(name) > 100:
        return _fail("Account name must be at most 100 characters.")
    clash = Account.query.filter(Account.name == name, Account.id != acc.id).first()
    if clash:
        return _fail(f"Another account is already named '{name}'.")
    account_type = (request.form.get('account_type') or '').strip()
    if account_type not in ACCOUNT_TYPES:
        return _fail(f"Account type must be one of: {', '.join(ACCOUNT_TYPES)}.")
    raw_company = (request.form.get('company_id') or '').strip()
    company_id = None
    if raw_company:
        if not raw_company.isdigit() or Company.query.get(int(raw_company)) is None:
            return _fail("Selected company does not exist.")
        company_id = int(raw_company)
    try:
        opening = float(request.form.get('opening_balance', 0) or 0)
    except (TypeError, ValueError):
        return _fail("Opening balance must be a number.")
    acc.name = name
    acc.account_type = account_type
    acc.company_id = company_id
    acc.opening_balance = opening
    acc.is_active = bool(request.form.get('is_active'))
    # Cache invalidation rides on the ORM update event; the UPDATE itself is
    # auto-audited. Redirect to the (possibly renamed) ledger view.
    db.session.commit()
    message = f"Account '{name}' updated."
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('accounts.detail', account_name=name))
