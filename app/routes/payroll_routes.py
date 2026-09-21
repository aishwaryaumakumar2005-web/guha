from datetime import datetime, date, timedelta
import csv
import io
import json
import math
import os
import zipfile
from io import BytesIO
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, current_app, Response
from flask_login import login_required, current_user
from fpdf import FPDF
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Tutor, PayrollRecord, TutorPayrollSettings, Expense, ExpenseCategory, tutor_courses, student_courses
from app.helpers import admin_required
from app.services.account_service import compute_account_summary
from app.services.accounting import LOGO_PATH
from app.services.payment_methods import classify_method

payroll_bp = Blueprint('payroll', __name__)

def _period_end(month, year):
    """Last calendar day of the given payroll period."""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _validate_commission_override(percentage):
    """Per-process override is optional; when given it must be 0-100."""
    if percentage is None:
        return None
    if percentage < 0 or percentage > 100:
        return 'Commission % must be between 0 and 100.'
    return None


def _parse_breakdown(raw):
    """Safely decode a stored commission breakdown (E1); legacy NULL -> []."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _dump_breakdown(breakdown):
    return json.dumps(breakdown, ensure_ascii=False)


def _parse_paid_date(raw, default):
    """Validate the optional confirm-time paid date; ''/today when blank."""
    if raw is None or not str(raw).strip():
        return default
    try:
        d = datetime.strptime(str(raw).strip(), '%Y-%m-%d').date()
    except ValueError:
        return None
    if d > date.today():
        return None
    return d


def _sufficient_balance(payment_method, amount):
    """(ok, available) for a payout on `payment_method`.

    E7: refuse confirmations that would draw an account below zero. Only
    canonical accounts with a resolvable row are enforced; an unknown method
    or an account with no ledger history is never blocked.
    """
    summary = {a['name']: a['balance'] for a in compute_account_summary()}
    available = summary.get(classify_method(payment_method))
    if available is None:
        return True, None
    return float(available) >= amount, float(available)


def _finalize_payroll(record, payment_method, paid_date, payment_ref=None):
    """Confirm a single draft into Paid + salary expense (P2/P5/E7).

    Returns (ok, message). Refuses negative-nets and insufficient account
    balance; the salary expense is dated to the pay period's last day.
    """
    if record.net_amount < 0:
        return False, (f"Cannot confirm {record.tutor.name}'s payroll for "
                       f"{record.month}/{record.year}: the net amount is negative "
                       f"(Rs.{record.net_amount:,.2f}).")
    ok, available = _sufficient_balance(payment_method, record.net_amount)
    if not ok:
        return False, (f"Cannot confirm {record.tutor.name}'s payroll for "
                       f"{record.month}/{record.year}: the {payment_method} account has "
                       f"only Rs.{available:,.2f} available, below the Rs.{record.net_amount:,.2f} payout.")
    payment_ref = (payment_ref or '').strip()[:100]
    if payment_method != 'Cash' and not payment_ref:
        return False, 'A payment reference is required for non-cash payroll payments.'
    salary_cat = ExpenseCategory.query.filter_by(name="Salary").first()
    if not salary_cat:
        salary_cat = ExpenseCategory(name="Salary", description="Staff salary payments")
        db.session.add(salary_cat)
        db.session.flush()
    desc = f"Salary: {record.tutor.name} - {record.month}/{record.year} (Base: Rs.{record.base_amount:,.2f}, Commission: Rs.{record.commission_amount:,.2f}, TDS: Rs.{record.tds_amount:,.2f})"
    expense_date = min(_period_end(record.month, record.year), date.today())
    expense = Expense(category_id=salary_cat.id, amount=record.net_amount, description=desc,
        expense_date=expense_date, created_by=current_user.id,
        payment_method=payment_method, payment_ref=payment_ref or None)
    db.session.add(expense)
    db.session.flush()
    record.status = 'Paid'
    record.expense_id = expense.id
    record.paid_date = paid_date
    record.payment_method = payment_method
    return True, f"Payroll confirmed for {record.tutor.name}. Expense recorded (Rs.{record.net_amount:,.2f}) for {expense_date.strftime('%b %Y')}."


def compute_tutor_payroll(tutor, month, year, percentage=None):
    start_date = date(year, month, 1)
    end_date = _period_end(month, year)
    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor.id).first()
    if not settings:
        settings = TutorPayrollSettings(tutor_id=tutor.id)
        db.session.add(settings)
    from app.services.salary_calculator import calculate_tutor_salary
    result = calculate_tutor_salary(tutor, start_date, end_date, percentage)
    return {key: result[key] for key in
            ('base', 'commission', 'commission_pct', 'bonus', 'tds', 'tds_pct',
             'other_ded', 'net', 'gross', 'breakdown')}

@payroll_bp.route('/payroll')
@login_required
@admin_required
def payroll_list():
    filter_month = request.args.get('month', type=int) or date.today().month
    filter_year = request.args.get('year', type=int) or date.today().year
    filter_status = request.args.get('status', '')
    today = date.today()
    records = PayrollRecord.query.filter_by(month=filter_month, year=filter_year)
    if filter_status:
        records = records.filter_by(status=filter_status)
    records = records.order_by(PayrollRecord.created_at.desc()).all()
    tutors = Tutor.query.order_by(Tutor.name).all()
    active_records = [r for r in records if r.status not in ('Cancelled', 'Reversed')]
    breakdowns = {r.id: _parse_breakdown(r.commission_breakdown) for r in records}
    # Lightweight per-record meta for the shared confirm/notes/breakdown modals.
    record_meta = {
        r.id: {
            'name': r.tutor.name,
            'net': r.net_amount,
            'method': r.payment_method or 'Cash',
            'notes': r.notes or '',
            'period': f"{r.month}/{r.year}",
        } for r in records
    }
    # E6: active tutors with no payroll record for the selected period.
    missing_tutors = [t for t in tutors
                      if t.status == 'Active' and t.id not in {r.tutor_id for r in records}]
    totals = {
        'base': sum(r.base_amount for r in active_records),
        'commission': sum(r.commission_amount for r in active_records),
        'bonus': sum(r.bonus_amount for r in active_records),
        'tds': sum(r.tds_amount for r in active_records),
        'other': sum(r.other_deductions for r in active_records),
        'net': sum(r.net_amount for r in active_records),
    }
    # UI/UX: post-'All' status counts (period-wide, pre-filter), per-tutor YTD
    # net for the filtered year, per-period existing-record counts, and the
    # 24-month net-payable trend for the summary chart.
    status_counts = {s: 0 for s in ('Draft', 'Paid', 'Cancelled', 'Reversed')}
    for r in PayrollRecord.query.filter_by(month=filter_month, year=filter_year).all():
        if r.status in status_counts:
            status_counts[r.status] += 1
    ytd_records = PayrollRecord.query.filter(PayrollRecord.year == filter_year,
        PayrollRecord.status.notin_(['Cancelled', 'Reversed'])).all()
    ytd_nets = {}
    for r in ytd_records:
        ytd_nets[r.tutor_id] = ytd_nets.get(r.tutor_id, 0.0) + r.net_amount
    period_counts = {
        f"{y}-{m}": c for y, m, c in
        db.session.query(PayrollRecord.year, PayrollRecord.month,
                         db.func.count(db.func.distinct(PayrollRecord.tutor_id)))
        .group_by(PayrollRecord.year, PayrollRecord.month).all()}
    active_tutor_count = Tutor.query.filter_by(status='Active').count()
    trend = []
    for offset in range(23, -1, -1):
        total = today.year * 12 + (today.month - 1) - offset
        trend_year, trend_month = divmod(total, 12)
        trend_month += 1
        aggregated = db.session.query(db.func.coalesce(db.func.sum(PayrollRecord.net_amount), 0.0)) \
            .filter(PayrollRecord.month == trend_month, PayrollRecord.year == trend_year,
                    PayrollRecord.status.notin_(['Cancelled', 'Reversed'])).scalar()
        trend.append({'label': f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][trend_month-1]} {str(trend_year)[2:]}",
                      'value': round(aggregated or 0.0, 2)})
    settings_js = {
        t.id: {
            'name': t.name,
            'base_salary': (t.payroll_settings.base_salary if t.payroll_settings else 0) or 0,
            'commission_percentage': (t.payroll_settings.commission_percentage if t.payroll_settings else 0) or 0,
            'tds_percentage': (t.payroll_settings.tds_percentage if t.payroll_settings else 10) or 10,
            'bonus': (t.payroll_settings.bonus if t.payroll_settings else 0) or 0,
            'other_deductions': (t.payroll_settings.other_deductions if t.payroll_settings else 0) or 0,
            'bank_name': (t.payroll_settings.bank_name if t.payroll_settings else '') or '',
            'account_number': (t.payroll_settings.account_number if t.payroll_settings else '') or '',
            'ifsc_code': (t.payroll_settings.ifsc_code if t.payroll_settings else '') or '',
        } for t in tutors
    }
    return render_template('payroll.html', records=records, tutors=tutors,
        filter_month=filter_month, filter_year=filter_year, filter_status=filter_status,
        totals=totals, today=date.today(), account_balances=compute_account_summary(),
        breakdowns=breakdowns, missing_tutors=missing_tutors, record_meta=record_meta,
        status_counts=status_counts, ytd_nets=ytd_nets, period_counts=period_counts,
        active_tutor_count=active_tutor_count, trend=trend, settings_js=settings_js)

@payroll_bp.route('/payroll/process', methods=['POST'])
@login_required
@admin_required
def process_payroll():
    tutor_id = request.form.get('tutor_id', type=int)
    try:
        month = int(request.form.get('month', 0))
        year = int(request.form.get('year', 0))
    except (ValueError, TypeError):
        flash('Invalid month or year value.', 'danger')
        return redirect(url_for('payroll.payroll_list'))
    if month < 1 or month > 12 or year < 2000:
        flash('Month must be 1-12 and year must be 2000+.', 'danger')
        return redirect(url_for('payroll.payroll_list'))
    percentage = request.form.get('percentage', type=float)
    override_err = _validate_commission_override(percentage)
    if override_err:
        flash(override_err, 'danger')
        return redirect(url_for('payroll.payroll_list', month=month, year=year))
    tutor = Tutor.query.get_or_404(tutor_id)
    result = compute_tutor_payroll(tutor, month, year, percentage)
    existing = PayrollRecord.query.filter_by(tutor_id=tutor_id, month=month, year=year).first()
    if existing:
        flash(f"Payroll already exists for {tutor.name} ({month}/{year}).", "warning")
        return redirect(url_for('payroll.payroll_list', month=month, year=year))
    record = PayrollRecord(tutor_id=tutor_id, month=month, year=year,
        base_amount=result['base'], commission_amount=result['commission'],
        bonus_amount=result['bonus'], tds_amount=result['tds'],
        other_deductions=result['other_ded'], net_amount=result['net'], status='Draft',
        payment_method=request.form.get('payment_method', 'Cash'),
        commission_pct_used=result['commission_pct'],
        commission_breakdown=_dump_breakdown(result['breakdown']))
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError:
        # Race with a concurrent request that created the same period record.
        db.session.rollback()
        flash(f"Payroll already exists for {tutor.name} ({month}/{year}).", "warning")
        return redirect(url_for('payroll.payroll_list', month=month, year=year))
    flash(f"Payroll processed for {tutor.name}: Rs.{result['net']:,.2f} net.", "success")
    return redirect(url_for('payroll.payroll_list', month=month, year=year))

@payroll_bp.route('/payroll/process-all', methods=['POST'])
@login_required
@admin_required
def process_all_payroll():
    try:
        month = int(request.form.get('month', 0))
        year = int(request.form.get('year', 0))
    except (ValueError, TypeError):
        flash('Invalid month or year value.', 'danger')
        return redirect(url_for('payroll.payroll_list'))
    if month < 1 or month > 12 or year < 2000:
        flash('Month must be 1-12 and year must be 2000+.', 'danger')
        return redirect(url_for('payroll.payroll_list'))
    percentage = request.form.get('percentage', type=float)
    override_err = _validate_commission_override(percentage)
    if override_err:
        flash(override_err, 'danger')
        return redirect(url_for('payroll.payroll_list', month=month, year=year))
    tutors = Tutor.query.filter_by(status='Active').order_by(Tutor.name).all()
    count = 0
    for tutor in tutors:
        existing = PayrollRecord.query.filter_by(tutor_id=tutor.id, month=month, year=year).first()
        if existing:
            continue
        result = compute_tutor_payroll(tutor, month, year, percentage)
        record = PayrollRecord(tutor_id=tutor.id, month=month, year=year,
            base_amount=result['base'], commission_amount=result['commission'],
            bonus_amount=result['bonus'], tds_amount=result['tds'],
            other_deductions=result['other_ded'], net_amount=result['net'], status='Draft',
            payment_method=request.form.get('payment_method', 'Cash'),
            commission_pct_used=result['commission_pct'],
            commission_breakdown=_dump_breakdown(result['breakdown']))
        db.session.add(record)
        count += 1
    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent process-all (or individual process) created a record
        # for one of these tutors+periods mid-loop; roll the batch back.
        db.session.rollback()
        flash("Could not process payroll: one or more records already exist for the selected period. No changes were saved.", "warning")
        return redirect(url_for('payroll.payroll_list', month=month, year=year))
    flash(f"Payroll processed for {count} active tutor(s).", "success")
    return redirect(url_for('payroll.payroll_list', month=month, year=year))

@payroll_bp.route('/payroll/<int:id>/confirm', methods=['POST'])
@login_required
@admin_required
def confirm_payroll(id):
    record = PayrollRecord.query.with_for_update().filter_by(id=id).first_or_404()
    if record.status != 'Draft':
        flash("Payroll record is already finalized.", "warning")
        return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))
    payment_method = (request.form.get('payment_method') or record.payment_method or 'Cash').strip()
    paid_date = _parse_paid_date(request.form.get('paid_date'), date.today())
    if paid_date is None:
        flash("Paid date cannot be empty or in the future.", "danger")
        return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))
    ok, message = _finalize_payroll(record, payment_method, paid_date, request.form.get('payment_ref'))
    if not ok:
        flash(message, "danger")
    else:
        db.session.commit()
        flash(message, "success")
    return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))

@payroll_bp.route('/payroll/confirm-all', methods=['POST'])
@login_required
@admin_required
def confirm_all_payroll():
    try:
        month = int(request.form.get('month', 0))
        year = int(request.form.get('year', 0))
    except (ValueError, TypeError):
        flash('Invalid month or year value.', 'danger')
        return redirect(url_for('payroll.payroll_list'))
    if month < 1 or month > 12 or year < 2000:
        flash('Month must be 1-12 and year must be 2000+.', 'danger')
        return redirect(url_for('payroll.payroll_list'))
    payment_method = (request.form.get('payment_method') or 'Cash').strip()
    payment_ref = (request.form.get('payment_ref') or '').strip()
    paid_date = _parse_paid_date(request.form.get('paid_date'), date.today())
    if paid_date is None:
        flash("Paid date cannot be empty or in the future.", "danger")
        return redirect(url_for('payroll.payroll_list', month=month, year=year))
    records = PayrollRecord.query.filter_by(month=month, year=year, status='Draft').all()
    confirmed = 0
    problems = {'negative': 0, 'balance': 0}
    for rec in records:
        ok, message = _finalize_payroll(rec, payment_method, paid_date, payment_ref)
        if not ok:
            if 'negative' in message:
                problems['negative'] += 1
            else:
                problems['balance'] += 1
            continue
        confirmed += 1
    if confirmed:
        db.session.commit()
        flash(f"Confirmed {confirmed} record(s) for {month}/{year} (method: {payment_method}, paid {paid_date.strftime('%d %b %Y')}).", "success")
    else:
        db.session.rollback()
        flash("Nothing was confirmed - check for negative nets or insufficient account balances.", "danger")
    if problems['negative']:
        flash(f"{problems['negative']} record(s) skipped: negative net amount.", "warning")
    if problems['balance']:
        flash(f"{problems['balance']} record(s) skipped: insufficient account balance.", "warning")
    return redirect(url_for('payroll.payroll_list', month=month, year=year))

@payroll_bp.route('/payroll/<int:id>/recalc', methods=['POST'])
@login_required
@admin_required
def recalc_payroll(id):
    record = PayrollRecord.query.get_or_404(id)
    if record.status != 'Draft':
        flash("Only draft records can be recalculated.", "warning")
        return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))
    tutor = record.tutor
    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor.id).first()
    comm_pct = settings.commission_percentage if settings else None
    result = compute_tutor_payroll(tutor, record.month, record.year, comm_pct)
    record.base_amount = result['base']
    record.commission_amount = result['commission']
    record.bonus_amount = result['bonus']
    record.tds_amount = result['tds']
    record.other_deductions = result['other_ded']
    record.net_amount = result['net']
    record.commission_pct_used = result['commission_pct']
    record.commission_breakdown = _dump_breakdown(result['breakdown'])
    db.session.commit()
    flash(f"Payroll recalculated for {tutor.name} ({record.month}/{record.year}): Rs.{result['net']:,.2f} net.", "success")
    return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))

@payroll_bp.route('/payroll/<int:id>/notes', methods=['POST'])
@login_required
@admin_required
def update_notes(id):
    record = PayrollRecord.query.get_or_404(id)
    notes = (request.form.get('notes') or '').strip()
    record.notes = notes or None
    db.session.commit()
    flash(f"Notes saved for {record.tutor.name}'s payroll ({record.month}/{record.year}).", "success")
    return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))

@payroll_bp.route('/payroll/export')
@login_required
@admin_required
def export_payroll():
    filter_month = request.args.get('month', type=int) or date.today().month
    filter_year = request.args.get('year', type=int) or date.today().year
    filter_status = request.args.get('status', '')
    records = PayrollRecord.query.filter_by(month=filter_month, year=filter_year)
    if filter_status:
        records = records.filter_by(status=filter_status)
    records = records.order_by(PayrollRecord.tutor_id).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Tutor', 'Month', 'Year', 'Base', 'Commission', 'Bonus', 'Gross',
                     'TDS', 'Other Deductions', 'Net', 'Payment Mode', 'Status',
                     'Paid Date', 'Notes'])
    for r in records:
        writer.writerow([
            r.tutor.name, r.month, r.year, r.base_amount, r.commission_amount,
            r.bonus_amount, r.base_amount + r.commission_amount + r.bonus_amount,
            r.tds_amount, r.other_deductions, r.net_amount, r.payment_method or 'Cash',
            r.status, r.paid_date.strftime('%Y-%m-%d') if r.paid_date else '', r.notes or '',
        ])
    data = buf.getvalue().encode('utf-8-sig')
    return Response(data, mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=payroll_{filter_year}_{filter_month:02d}.csv'})

@payroll_bp.route('/payroll/payslips')
@login_required
@admin_required
def payslips_zip():
    filter_month = request.args.get('month', type=int) or date.today().month
    filter_year = request.args.get('year', type=int) or date.today().year
    filter_status = request.args.get('status', '')
    records = PayrollRecord.query.filter_by(month=filter_month, year=filter_year)
    if filter_status:
        records = records.filter_by(status=filter_status)
    records = records.order_by(PayrollRecord.tutor_id).all()
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for r in records:
            zf.writestr(
                f'payslip_{r.tutor.name.replace(" ", "_")}_{r.month}_{r.year}.pdf',
                _build_payslip_pdf(r))
    buf.seek(0)
    if not records:
        flash("No payslips to download for the selected period.", "warning")
        return redirect(url_for('payroll.payroll_list', month=filter_month, year=filter_year))
    return send_file(buf, mimetype='application/zip', as_attachment=True,
        download_name=f'payslips_{filter_year}_{filter_month:02d}.zip')

@payroll_bp.route('/payroll/<int:id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_payroll(id):
    record = PayrollRecord.query.get_or_404(id)
    if record.status == 'Paid':
        flash("Cannot cancel a paid payroll record.", "danger")
        return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))
    record.status = 'Cancelled'
    db.session.commit()
    flash(f"Payroll cancelled for {record.tutor.name}.", "info")
    return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))

@payroll_bp.route('/payroll/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_payroll(id):
    record = PayrollRecord.query.get_or_404(id)
    tutor_name = record.tutor.name
    month, year = record.month, record.year
    was_paid = record.status == 'Paid'
    if was_paid and request.form.get('confirm') != '1':
        # Deleting a paid record rewrites past P&L (linked salary expense is
        # removed too), so it must be explicitly acknowledged, not just a
        # default button press.
        flash(f"Salary deletion not confirmed for {tutor_name}. Paid records affect past accounting; please retry with explicit confirmation.", "danger")
        return redirect(url_for('payroll.payroll_list', month=month, year=year))
    expense = Expense.query.get(record.expense_id) if record.expense_id else None
    if was_paid:
        record.status = 'Reversed'
        if expense:
            expense.status = 'Voided'
            expense.voided_at = datetime.utcnow()
            expense.voided_by = current_user.id
            expense.void_reason = f'Payroll reversal for {tutor_name}'
    else:
        record.status = 'Cancelled'
    db.session.commit()
    if was_paid and expense:
        flash(f"Salary reversed for {tutor_name}; the linked expense was voided for audit.", "success")
    else:
        flash(f"Salary deleted for {tutor_name}.", "success")
    return redirect(url_for('payroll.payroll_list', month=month, year=year))

def _build_payslip_pdf(record):
    tutor = record.tutor
    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor.id).first()
    month_names = ['', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December']
    period = f"{month_names[record.month]} {record.year}"
    cfg = current_app.accounting._get_settings()

    pdf = FPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    NAVY = (25, 55, 110)
    BLUE = (42, 82, 152)
    INK = (25, 25, 25)
    LABEL = (70, 70, 70)
    MUTED = (95, 95, 95)
    HEAD_FILL = (10, 30, 46)

    def text_color(c):
        pdf.set_text_color(*c)

    def set_font(style='', size=10):
        pdf.set_font('Helvetica', style, size)

    # ---- Header band ----
    pdf.set_fill_color(241, 243, 246)
    pdf.rect(0, 0, 210, 58, 'F')
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(1.2)
    pdf.line(8, 58, 202, 58)
    pdf.set_line_width(0.2)

    # Logo top-left
    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, 14, 12, 34, 34)

    set_font('B', 18)
    text_color(NAVY)
    pdf.set_xy(54, 11)
    pdf.cell(0, 9, cfg['org_name'], align='L')
    set_font('B', 12)
    text_color(BLUE)
    pdf.set_xy(54, 21)
    pdf.cell(0, 6, '(Powered By Guha India)', align='L')
    set_font('', 10)
    text_color((45, 45, 45))
    pdf.set_xy(54, 29)
    pdf.multi_cell(78, 5, cfg['org_address'], new_x="LMARGIN", new_y="NEXT")
    contact_y = pdf.get_y() + 1
    contact = f"GSTIN: {cfg['org_gstin']}  Mobile: {cfg['org_mobile']}  Email: {cfg['org_email']}"
    pdf.set_xy(54, contact_y)
    pdf.multi_cell(78, 5, contact, new_x="LMARGIN", new_y="NEXT")

    # Right side: title + meta
    set_font('B', 18)
    text_color(NAVY)
    pdf.set_xy(120, 12)
    pdf.cell(78, 10, 'PAY SLIP', align='R')
    set_font('B', 9.5)
    text_color((40, 40, 40))
    pdf.set_xy(120, 27)
    pdf.cell(78, 6, f"Employee No: {tutor.emp_code or f'TUT{tutor.id:04d}'}", align='R')
    pdf.set_xy(120, 34)
    pdf.cell(78, 6, f"Pay Period: {period}", align='R')
    pdf.set_xy(120, 41)
    pdf.cell(78, 6, f"Status: {record.status}", align='R')

    pdf.set_y(66)

    # Employee Details (two columns)
    set_font('B', 12)
    text_color(NAVY)
    pdf.set_xy(15, 66)
    pdf.cell(0, 8, 'Employee Details:', new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(140, 150, 165)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)

    left_col = [
        ('Employee Name', tutor.name),
        ('Designation', tutor.specialization or '-'),
        ('Phone', tutor.phone),
        ('Email', tutor.email),
        ('Employment Status', tutor.status),
    ]
    right_col = [
        ('Employee No', tutor.emp_code or f"TUT{tutor.id:04d}"),
        ('Bank Name', settings.bank_name if settings and settings.bank_name else '-'),
        ('Account No', settings.account_number if settings and settings.account_number else '-'),
        ('IFSC Code', settings.ifsc_code if settings and settings.ifsc_code else '-'),
        ('Payment Method', record.payment_method or '-'),
    ]
    row_h = 8
    y_start = pdf.get_y()
    for i, (label, val) in enumerate(left_col):
        pdf.set_xy(15, y_start + i * row_h)
        set_font('B', 9)
        text_color(LABEL)
        pdf.cell(44, row_h, label + ':')
        set_font('', 10.5)
        text_color(INK)
        pdf.cell(62, row_h, str(val))
    for i, (label, val) in enumerate(right_col):
        pdf.set_xy(120, y_start + i * row_h)
        set_font('B', 9)
        text_color(LABEL)
        pdf.cell(40, row_h, label + ':')
        set_font('', 10.5)
        text_color(INK)
        pdf.cell(40, row_h, str(val))
    pdf.set_y(y_start + len(left_col) * row_h + 8)

    # Earnings & Deductions table
    set_font('B', 12)
    text_color(NAVY)
    pdf.set_x(15)
    pdf.cell(0, 8, 'Earnings & Deductions', new_y="NEXT")
    pdf.set_draw_color(140, 150, 165)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)

    col_w = [100, 40, 40]
    headers = ['Description', 'Earnings (Rs.)', 'Deductions (Rs.)']

    def table_header():
        set_font('B', 9.5)
        pdf.set_fill_color(*HEAD_FILL)
        text_color((255, 255, 255))
        pdf.set_x(15)
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], row_h, h, border=1, fill=True, align='C' if i > 0 else 'L')
        pdf.ln()

    def table_row(cols, bold=False, fill=False):
        pdf.set_fill_color(238, 243, 250) if fill else pdf.set_fill_color(255, 255, 255)
        text_color(INK)
        set_font('B' if bold else '', 9.5)
        pdf.set_x(15)
        for i, c in enumerate(cols):
            pdf.cell(col_w[i], row_h, str(c), border=1, fill=True, align='C' if i > 0 else 'L')
        pdf.ln()

    table_header()
    table_row(['Base Salary', f'Rs. {record.base_amount:,.2f}', ''], fill=True)
    table_row([f'Commission ({record.commission_pct_used or 0}%)', f'Rs. {record.commission_amount:,.2f}', ''], fill=True)
    if record.bonus_amount > 0:
        table_row(['Bonus', f'Rs. {record.bonus_amount:,.2f}', ''], fill=True)
    if record.tds_amount > 0:
        table_row(['TDS Deduction', '', f'Rs. {record.tds_amount:,.2f}'], fill=True)
    if record.other_deductions > 0:
        table_row(['Other Deductions', '', f'Rs. {record.other_deductions:,.2f}'], fill=True)
    gross = record.base_amount + record.commission_amount + record.bonus_amount
    total_ded = record.tds_amount + record.other_deductions
    table_row(['Gross Pay', f'Rs. {gross:,.2f}', ''], bold=True)
    table_row(['Total Deductions', '', f'Rs. {total_ded:,.2f}'], bold=True)
    pdf.ln(5)

    # Net payable highlight band
    band_h = 22 if record.status == 'Paid' else 14
    band_y = pdf.get_y()
    pdf.set_fill_color(*HEAD_FILL)
    pdf.rect(15, band_y, 180, band_h, 'F')
    pdf.set_xy(20, band_y + 3)
    set_font('B', 13)
    text_color((255, 255, 255))
    pdf.cell(95, 10, 'NET PAYABLE')
    pdf.cell(80, 10, f'Rs. {record.net_amount:,.2f}', align='R')
    if record.status == 'Paid':
        pdf.set_xy(20, band_y + 13)
        set_font('', 9)
        text_color((255, 255, 255))
        pdf.cell(175, 6, f'Paid on: {record.paid_date.strftime("%d %b %Y") if record.paid_date else "-"}', align='R')
    pdf.ln(band_h + 4)

    # Amount in words
    set_font('', 9.5)
    text_color(INK)
    words = current_app.accounting._number_to_words(int(math.floor(record.net_amount)))
    pdf.set_x(15)
    pdf.cell(180, 6, f"Amount in words: Rupees {words} only.", new_y="NEXT")

    pdf.ln(3)
    set_font('', 9)
    text_color(MUTED)
    pdf.set_x(15)
    pdf.multi_cell(180, 5, "Note: This payslip is computer generated and does not require a physical signature to be valid for record purposes.", new_y="NEXT")

    # Signatures (space above reserved for company seal)
    if pdf.get_y() < 240:
        pdf.set_y(240)
    sig_y = pdf.get_y()
    pdf.set_draw_color(90, 90, 90)
    pdf.line(15, sig_y, 90, sig_y)
    pdf.set_xy(15, sig_y + 2)
    set_font('B', 9)
    text_color(INK)
    pdf.cell(75, 6, "Employee Signature", align='L')
    pdf.line(130, sig_y, 195, sig_y)
    pdf.set_xy(130, sig_y - 12)
    set_font('', 8.5)
    text_color(LABEL)
    pdf.cell(65, 5, "(Seal & Signature)", align='R')
    pdf.set_xy(130, sig_y + 2)
    set_font('B', 9)
    text_color(INK)
    pdf.cell(65, 6, "For Guha India", align='R')

    # Footer band with company details
    pdf.set_fill_color(241, 243, 246)
    pdf.rect(0, 266, 210, 31, 'F')
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(1.0)
    pdf.line(8, 266, 202, 266)
    pdf.set_line_width(0.2)
    set_font('B', 10)
    text_color(NAVY)
    pdf.set_xy(10, 270)
    pdf.cell(190, 6, cfg['org_name'], align='C')
    set_font('', 8.5)
    text_color((45, 45, 45))
    pdf.set_xy(10, 277)
    pdf.cell(190, 5, cfg['org_address'], align='C')
    pdf.set_xy(10, 283)
    pdf.cell(190, 5, f"GSTIN: {cfg['org_gstin']}  Mobile: {cfg['org_mobile']}  Email: {cfg['org_email']}   |   Generated: {datetime.now().strftime('%d %b %Y %I:%M %p')}", align='C')

    # Page border (drawn last so it frames header/footer bands)
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.7)
    pdf.rect(8, 8, 194, 281, 'D')
    pdf.set_draw_color(170, 180, 195)
    pdf.set_line_width(0.3)
    pdf.rect(10, 10, 190, 277, 'D')


    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf.getvalue()


@payroll_bp.route('/payroll/<int:id>/payslip')
@login_required
@admin_required
def payslip_pdf(id):
    record = PayrollRecord.query.get_or_404(id)
    data = _build_payslip_pdf(record)
    return send_file(BytesIO(data), mimetype='application/pdf', as_attachment=True,
        download_name=f'payslip_{record.tutor.name.replace(" ", "_")}_{record.month}_{record.year}.pdf')

@payroll_bp.route('/payroll/settings/<int:tutor_id>', methods=['POST'])
@login_required
@admin_required
def update_settings(tutor_id):
    from app.forms import PayrollSettingsForm
    tutor = Tutor.query.get_or_404(tutor_id)
    form = PayrollSettingsForm(request.form)
    if not form.validate():
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('payroll.payroll_list'))
    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor_id).first()
    if not settings:
        settings = TutorPayrollSettings(tutor_id=tutor_id)
        db.session.add(settings)
    settings.base_salary = form.cleaned_data.get('base_salary', 0)
    settings.commission_percentage = form.cleaned_data.get('commission_percentage', 0)
    settings.tds_percentage = form.cleaned_data.get('tds_percentage', 10)
    settings.bonus = form.cleaned_data.get('bonus', 0)
    settings.other_deductions = form.cleaned_data.get('other_deductions', 0)
    settings.bank_name = form.data.get('bank_name', '').strip()
    settings.account_number = form.data.get('account_number', '').strip()
    settings.ifsc_code = form.data.get('ifsc_code', '').strip()
    db.session.flush()
    # Recalculate existing Draft payroll records for this tutor from the
    # freshly saved settings - including the commission % (P2). Drafts are
    # fully recomputed through the same path a fresh process run uses, so a
    # base/TDS/bonus/commission change is always reflected.
    draft_records = PayrollRecord.query.filter_by(tutor_id=tutor_id, status='Draft').all()
    comm_pct = settings.commission_percentage or 0.0
    for rec in draft_records:
        result = compute_tutor_payroll(tutor, rec.month, rec.year, comm_pct)
        rec.base_amount = result['base']
        rec.commission_amount = result['commission']
        rec.bonus_amount = result['bonus']
        rec.tds_amount = result['tds']
        rec.other_deductions = result['other_ded']
        rec.net_amount = result['net']
        rec.commission_pct_used = comm_pct
        rec.commission_breakdown = _dump_breakdown(result['breakdown'])
    db.session.commit()
    msg = f"Payroll settings updated for {tutor.name}."
    if draft_records:
        msg += f" {len(draft_records)} draft record(s) recalculated."
    flash(msg, "success")
    return redirect(url_for('payroll.payroll_list'))
