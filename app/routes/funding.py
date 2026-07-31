from datetime import date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import OwnerFunding
from app.helpers import admin_required, is_ajax_request
from app.forms import OwnerFundingForm

funding_bp = Blueprint('funding', __name__)


@funding_bp.route('/funding', methods=['GET', 'POST'])
@login_required
@admin_required
def list():
    if request.method == 'POST':
        form = OwnerFundingForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('funding.list'))
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
    all_fundings = OwnerFunding.query.order_by(
        OwnerFunding.funding_date.desc(), OwnerFunding.id.desc()
    ).all()
    total_invested = sum(f.amount for f in all_fundings)
    today = date.today()
    month_total = sum(
        f.amount for f in all_fundings
        if f.funding_date.year == today.year and f.funding_date.month == today.month
    )
    return render_template('funding.html', fundings=all_fundings,
        total_invested=total_invested, month_total=month_total, today=today)


@funding_bp.route('/funding/delete/<int:id>')
@login_required
@admin_required
def delete(id):
    funding = OwnerFunding.query.get_or_404(id)
    db.session.delete(funding)
    db.session.commit()
    message = "Capital contribution record deleted!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('funding.list'))
