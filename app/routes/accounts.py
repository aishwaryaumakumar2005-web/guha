from flask import Blueprint, render_template
from flask_login import login_required
from app.helpers import admin_required
from app.services.account_service import (
    compute_account_summary, account_breakdown, ensure_default_accounts,
)


accounts_bp = Blueprint('accounts', __name__)


@accounts_bp.route('/accounts')
@login_required
@admin_required
def index():
    ensure_default_accounts()
    summary = compute_account_summary()
    default_name = summary[0]['name'] if summary else 'Cash'
    breakdown = account_breakdown(default_name)
    return render_template(
        'accounts.html', accounts=summary, active_name=default_name, breakdown=breakdown,
    )


@accounts_bp.route('/accounts/<account_name>')
@login_required
@admin_required
def detail(account_name):
    ensure_default_accounts()
    summary = compute_account_summary()
    breakdown = account_breakdown(account_name)
    return render_template(
        'accounts.html', accounts=summary, active_name=account_name, breakdown=breakdown,
    )
