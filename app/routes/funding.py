import csv
import io
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from app.extensions import db
from app.models import OwnerFunding
from app.helpers import admin_required, is_ajax_request, FINANCE_LIST_LIMIT
from app.forms import OwnerFundingForm
from app.services.payment_methods import PAYMENT_METHODS
from app.services.account_service import compute_account_summary

funding_bp = Blueprint('funding', __name__)

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
INVESTMENT_TYPES = ['Capital', 'Director Loan']


def _reject_funding(message, status=400):
    if is_ajax_request():
        return jsonify({'success': False, 'errors': [message]}), status
    flash(message, 'danger')
    return redirect(url_for('funding.list'))


def _trend_months(end_year, end_month, count=24):
    """Last `count` (year, month) pairs ending at end_year/end_month, oldest first."""
    out = []
    y, m = end_year, end_month
    for _ in range(count):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    out.reverse()
    return out


def _monthly_total(year, month):
    return db.session.query(db.func.sum(OwnerFunding.amount)).filter(
        OwnerFunding.status != 'Voided',
        db.extract('year', OwnerFunding.funding_date) == year,
        db.extract('month', OwnerFunding.funding_date) == month
    ).scalar() or 0.0


def _type_total(investment_type):
    return db.session.query(db.func.sum(OwnerFunding.amount)).filter(
        OwnerFunding.status != 'Voided',
        OwnerFunding.investment_type == investment_type
    ).scalar() or 0.0


def _funding_context(form_data=None, error_fields=None, autopen=False,
                     f_method='', f_month=0, f_year=0, f_q=''):
    """Template vars shared by the GET page and a failed-POST re-render."""
    fundings_total = OwnerFunding.query.filter(OwnerFunding.status != 'Voided').order_by(None).count()
    query = OwnerFunding.query.filter(OwnerFunding.status != 'Voided')
    if f_method:
        query = query.filter(db.func.lower(OwnerFunding.method) == f_method.lower())
    if f_year:
        query = query.filter(db.extract('year', OwnerFunding.funding_date) == f_year)
    if f_month:
        query = query.filter(db.extract('month', OwnerFunding.funding_date) == f_month)
    f_q_clean = (f_q or '').strip()
    if f_q_clean:
        like = f"%{f_q_clean}%"
        query = query.filter(db.or_(
            OwnerFunding.purpose.ilike(like),
            OwnerFunding.reference.ilike(like)))
    filtered = bool(f_method or f_year or f_month or f_q_clean)
    # F1: the 200-row cap only applies to the unfiltered "latest" view. Any
    # active filter searches the ENTIRE history, so filters never hide rows.
    order = (OwnerFunding.funding_date.desc(), OwnerFunding.id.desc())
    filtered_total = query.order_by(None).count()
    page = max(request.args.get('page', 1, type=int) or 1, 1)
    all_fundings = query.order_by(*order).offset((page - 1) * FINANCE_LIST_LIMIT).limit(FINANCE_LIST_LIMIT).all()

    today = date.today()
    total_invested = db.session.query(db.func.sum(OwnerFunding.amount)).filter(OwnerFunding.status != 'Voided').scalar() or 0.0
    month_total = _monthly_total(today.year, today.month)
    prev_month_first = date(today.year, today.month, 1) - timedelta(days=1)
    prev_month_total = _monthly_total(prev_month_first.year, prev_month_first.month)
    this_year_total = db.session.query(db.func.sum(OwnerFunding.amount)).filter(
        db.extract('year', OwnerFunding.funding_date) == today.year).scalar() or 0.0
    capital_total = _type_total('Capital')
    loan_total = _type_total('Director Loan')

    # F6: 24-month trend plus a per-method split for the doughnut.
    months = _trend_months(today.year, today.month, 24)
    start_y, start_m = months[0]
    rows = db.session.query(
        db.extract('year', OwnerFunding.funding_date).label('y'),
        db.extract('month', OwnerFunding.funding_date).label('m'),
        db.func.sum(OwnerFunding.amount).label('total')
    ).filter(OwnerFunding.status != 'Voided',
        db.or_(
            db.extract('year', OwnerFunding.funding_date) > start_y,
            db.and_(db.extract('year', OwnerFunding.funding_date) == start_y,
                    db.extract('month', OwnerFunding.funding_date) >= start_m)
        )
    ).group_by(
        db.extract('year', OwnerFunding.funding_date),
        db.extract('month', OwnerFunding.funding_date)
    ).all()
    sum_map = {(int(r.y), int(r.m)): float(r.total) for r in rows}
    trend = [{'label': f"{MONTH_NAMES[m - 1]} {y}", 'value': sum_map.get((y, m), 0.0)}
             for (y, m) in months]
    split_rows = db.session.query(
        OwnerFunding.method, db.func.sum(OwnerFunding.amount)
    ).filter(OwnerFunding.status != 'Voided').group_by(OwnerFunding.method).all()
    method_split = [{'method': m or 'Cash', 'total': float(t or 0)} for m, t in split_rows]

    years = [int(y) for (y,) in db.session.query(
        db.extract('year', OwnerFunding.funding_date)
    ).distinct().order_by(db.extract('year', OwnerFunding.funding_date).desc()).all()]

    return {
        'fundings': all_fundings, 'total_invested': total_invested,
        'month_total': month_total, 'prev_month_total': prev_month_total,
        'this_year_total': this_year_total, 'today': today,
        'capital_total': capital_total, 'loan_total': loan_total,
        'account_balances': compute_account_summary(),
        'fundings_total': fundings_total, 'filtered_total': filtered_total,
        'page': page, 'pages': max((filtered_total + FINANCE_LIST_LIMIT - 1) // FINANCE_LIST_LIMIT, 1),
        'list_limit': FINANCE_LIST_LIMIT, 'filtered': filtered,
        'filter_method': f_method, 'filter_month': f_month,
        'filter_year': f_year, 'filter_q': f_q_clean,
        'months': range(1, 13), 'month_names': MONTH_NAMES, 'years': years,
        'payment_methods': PAYMENT_METHODS, 'investment_types': INVESTMENT_TYPES,
        'trend': trend, 'method_split': method_split,
        'form_data': form_data, 'error_fields': error_fields or set(),
        'autopen': autopen,
    }


def _form_data(request):
    return {
        'amount': request.form.get('amount', ''),
        'funding_date': request.form.get('funding_date', ''),
        'method': request.form.get('method', 'Cash'),
        'purpose': request.form.get('purpose', ''),
        'reference': request.form.get('reference', ''),
        'investment_type': request.form.get('investment_type', 'Capital'),
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
                form_data=_form_data(request))
            return render_template('funding.html', **ctx), 400
        amount = form.cleaned_data.get('amount', 0)
        method = request.form.get('method', 'Cash').strip()
        purpose = request.form.get('purpose', '').strip()
        funding_date = form.cleaned_data.get('funding_date', date.today())
        reference = request.form.get('reference', '').strip()[:100] or None
        investment_type = request.form.get('investment_type', 'Capital').strip() or 'Capital'
        if method != 'Cash' and not reference:
            return _reject_funding('A payment reference is required for non-cash funding.')
        duplicate = OwnerFunding.query.filter(
            OwnerFunding.status != 'Voided', OwnerFunding.amount == amount,
            OwnerFunding.funding_date == funding_date, OwnerFunding.method == method,
            OwnerFunding.reference == reference).first()
        if duplicate and request.form.get('confirm_duplicate') != '1':
            return _reject_funding('A matching active funding record already exists. Confirm it is not a duplicate.', 409)
        new_funding = OwnerFunding(
            amount=amount, method=method, purpose=purpose,
            funding_date=funding_date, created_by=current_user.id,
            reference=reference, investment_type=investment_type)
        db.session.add(new_funding)
        db.session.commit()
        message = "Capital contribution recorded successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('funding.list'))
    ctx = _funding_context(
        f_method=request.args.get('method', ''),
        f_month=request.args.get('month', 0, type=int),
        f_year=request.args.get('year', 0, type=int),
        f_q=request.args.get('q', ''))
    return render_template('funding.html', **ctx)


@funding_bp.route('/funding/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    # F2: fixing a mis-entered contribution. INSERT/DELETE rows were already
    # audited; UPDATEs are captured by the global audit hook the same way.
    funding = OwnerFunding.query.get_or_404(id)
    if funding.status == 'Voided':
        return _reject_funding('Voided funding records cannot be edited.', 400)
    form = OwnerFundingForm(request.form)
    if not form.validate():
        if is_ajax_request():
            return jsonify({"success": False, "errors": form.error_messages}), 400
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('funding.list'))
    funding.amount = form.cleaned_data.get('amount', funding.amount)
    funding.funding_date = form.cleaned_data.get('funding_date', funding.funding_date)
    funding.method = request.form.get('method', 'Cash').strip()
    funding.purpose = request.form.get('purpose', '').strip()
    funding.reference = request.form.get('reference', '').strip()[:100] or None
    if funding.method != 'Cash' and not funding.reference:
        return _reject_funding('A payment reference is required for non-cash funding.')
    funding.investment_type = request.form.get('investment_type', 'Capital').strip() or 'Capital'
    db.session.commit()
    message = "Capital contribution updated successfully!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('funding.list'))


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
    if funding.status == 'Voided':
        return _reject_funding('This funding record is already voided.', 400)
    funding.status = 'Voided'
    funding.voided_at = datetime.utcnow()
    funding.voided_by = current_user.id
    funding.void_reason = (request.form.get('reason') or 'Voided by administrator').strip()[:300]
    db.session.commit()
    message = "Funding record voided. The original remains available for audit."
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('funding.list'))


@funding_bp.route('/funding/export')
@login_required
@admin_required
def export():
    # F3: full-history CSV (never capped), with a UTF-8 BOM so Excel opens
    # the ₹/method columns without mojibake.
    rows = OwnerFunding.query.order_by(
        OwnerFunding.funding_date.desc(), OwnerFunding.id.desc()
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Date', 'Type', 'Mode', 'Amount', 'Reference', 'Purpose', 'Recorded By'])
    for f in rows:
        writer.writerow([
            f.funding_date.strftime('%Y-%m-%d') if f.funding_date else '',
            f.investment_type or 'Capital',
            f.method or 'Cash',
            f"{f.amount:.2f}" if f.amount is not None else '',
            f.reference or '',
            f.purpose or '',
            f.creator.name if f.creator else 'System',
        ])
    payload = ('\ufeff' + buf.getvalue()).encode('utf-8')
    return Response(
        payload,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition':
                 f'attachment; filename=capital_funding_{date.today().strftime("%Y_%m_%d")}.csv'})
