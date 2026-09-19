from datetime import date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import OwnerFunding
from app.helpers import admin_required, is_ajax_request, FINANCE_LIST_LIMIT
from app.forms import OwnerFundingForm
from app.services.account_service import compute_account_summary

funding_bp = Blueprint('funding', __name__)


def _funding_context(form_data=None, error_fields=None, autopen=False):
    """Template vars shared by the GET page and a failed-POST re-render."""
    fundings_total = OwnerFunding.query.order_by(None).count()
    all_fundings = OwnerFunding.query.order_by(
        OwnerFunding.funding_date.desc(), OwnerFunding.id.desc()
    ).limit(FINANCE_LIST_LIMIT).all()
    # Totals stay global (SQL aggregates) even when the list below is capped.
    total_invested = db.session.query(db.func.sum(OwnerFunding.amount)).scalar() or 0.0
    today = date.today()
    month_total = db.session.query(db.func.sum(OwnerFunding.amount)).filter(
        db.extract('year', OwnerFunding.funding_date) == today.year,
        db.extract('month', OwnerFunding.funding_date) == today.month
    ).scalar() or 0.0
    return {
        'fundings': all_fundings, 'total_invested': total_invested,
        'month_total': month_total, 'today': today,
        'account_balances': compute_account_summary(),
        'fundings_total': fundings_total, 'list_limit': FINANCE_LIST_LIMIT,
        'form_data': form_data, 'error_fields': error_fields or set(),
        'autopen': autopen,
    }


@funding_bp.route('/funding', methods=['GET', 'POST'])
@login_required
@admin_required
def list():
    if request.method == 'POST':
        form = OwnerFundingForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            # B3: failed submits re-render with the typed values preserved so
            # the add-modal reopens filled in instead of wiping user input.
            for msg in form.error_messages:
                flash(msg, "danger")
            ctx = _funding_context(
                autopen=True,
                error_fields=form.error_dict,
                form_data={
                    'amount': request.form.get('amount', ''),
                    'funding_date': request.form.get('funding_date', ''),
                    'method': request.form.get('method', 'Cash'),
                    'purpose': request.form.get('purpose', ''),
                })
            return render_template('funding.html', **ctx), 400
        amount = form.cleaned_data.get('amount', 0)
        method = request.form.get('method', 'Cash').strip()
        purpose = request.form.get('purpose', '').strip()
        funding_date = form.cleaned_data.get('funding_date', date.today())
        new_funding = OwnerFunding(
            amount=amount, method=method, purpose=purpose,
            funding_date=funding_date, created_by=current_user.id
        )
        db.session.add(new_funding)
        db.session.commit()
        message = "Capital contribution recorded successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('funding.list'))
    return render_template('funding.html', **_funding_context())


@funding_bp.route('/funding/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete(id):
    # B4: deleting a ledger entry permanently reverses it, so the client
    # must explicitly confirm (hidden confirm=1 field) — a stray POST or
    # scripted request can no longer silently remove a contribution.
    if request.form.get('confirm') != '1':
        flash("Deletion not confirmed - the contribution was kept.", "danger")
        return redirect(url_for('funding.list'))
    funding = OwnerFunding.query.get_or_404(id)
    db.session.delete(funding)
    db.session.commit()
    message = "Capital contribution record deleted!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('funding.list'))