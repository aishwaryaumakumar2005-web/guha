from datetime import datetime, date, timedelta
from io import BytesIO
import math
import os
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from fpdf import FPDF
from app.extensions import db
from app.models import Tutor, PayrollRecord, TutorPayrollSettings, Expense, ExpenseCategory, tutor_courses, student_courses
from app.helpers import admin_required
from app.services.account_service import compute_account_summary
from app.services.accounting import LOGO_PATH

payroll_bp = Blueprint('payroll', __name__)

def compute_tutor_payroll(tutor, month, year, percentage=None):
    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor.id).first()
    if not settings:
        settings = TutorPayrollSettings(tutor_id=tutor.id)
        db.session.add(settings)
    base = settings.base_salary or 0.0
    comm_pct = percentage if percentage is not None else (settings.commission_percentage or 0.0)
    bonus = settings.bonus or 0.0
    other_ded = settings.other_deductions or 0.0
    tds_pct = settings.tds_percentage or 0.0
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    from app.models import Student, Course, FeeRecord
    students = Student.query.join(Student.courses).join(Course.tutors).filter(Tutor.id == tutor.id).all()
    commission = 0.0
    if students and comm_pct > 0:
        from sqlalchemy import distinct
        for student in students:
            tutor_count = db.session.query(db.func.count(distinct(Tutor.id))).select_from(Tutor).join(
                tutor_courses, Tutor.id == tutor_courses.c.tutor_id
            ).join(Course, Course.id == tutor_courses.c.course_id).join(
                student_courses, student_courses.c.course_id == Course.id
            ).filter(student_courses.c.student_id == student.id).scalar() or 0
            if tutor_count == 0:
                continue
            student_fees = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
                FeeRecord.student_id == student.id,
                FeeRecord.payment_date >= start_date,
                FeeRecord.payment_date <= end_date
            ).scalar() or 0.0
            commission += (student_fees / tutor_count) * (comm_pct / 100.0)
    gross = base + commission + bonus
    tds = gross * (tds_pct / 100.0) if tds_pct > 0 else 0.0
    net = gross - tds - other_ded
    return {'base': base, 'commission': commission, 'commission_pct': comm_pct,
        'bonus': bonus, 'tds': tds, 'tds_pct': tds_pct, 'other_ded': other_ded, 'net': net, 'gross': gross}

@payroll_bp.route('/payroll')
@login_required
@admin_required
def payroll_list():
    filter_month = request.args.get('month', type=int) or date.today().month
    filter_year = request.args.get('year', type=int) or date.today().year
    filter_status = request.args.get('status', '')
    records = PayrollRecord.query.filter_by(month=filter_month, year=filter_year)
    if filter_status:
        records = records.filter_by(status=filter_status)
    records = records.order_by(PayrollRecord.created_at.desc()).all()
    tutors = Tutor.query.order_by(Tutor.name).all()
    active_records = [r for r in records if r.status != 'Cancelled']
    totals = {
        'base': sum(r.base_amount for r in active_records),
        'commission': sum(r.commission_amount for r in active_records),
        'bonus': sum(r.bonus_amount for r in active_records),
        'tds': sum(r.tds_amount for r in active_records),
        'other': sum(r.other_deductions for r in active_records),
        'net': sum(r.net_amount for r in active_records),
    }
    return render_template('payroll.html', records=records, tutors=tutors,
        filter_month=filter_month, filter_year=filter_year, filter_status=filter_status,
        totals=totals, today=date.today(), account_balances=compute_account_summary())

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
        commission_pct_used=result['commission_pct'])
    db.session.add(record)
    db.session.commit()
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
            commission_pct_used=result['commission_pct'])
        db.session.add(record)
        count += 1
    db.session.commit()
    flash(f"Payroll processed for {count} active tutor(s).", "success")
    return redirect(url_for('payroll.payroll_list', month=month, year=year))

@payroll_bp.route('/payroll/<int:id>/confirm', methods=['POST'])
@login_required
@admin_required
def confirm_payroll(id):
    record = PayrollRecord.query.get_or_404(id)
    if record.status != 'Draft':
        flash("Payroll record is already finalized.", "warning")
        return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))
    salary_cat = ExpenseCategory.query.filter_by(name="Salary").first()
    if not salary_cat:
        salary_cat = ExpenseCategory(name="Salary", description="Staff salary payments")
        db.session.add(salary_cat)
        db.session.commit()
    desc = f"Salary: {record.tutor.name} - {record.month}/{record.year} (Base: Rs.{record.base_amount:,.2f}, Commission: Rs.{record.commission_amount:,.2f}, TDS: Rs.{record.tds_amount:,.2f})"
    expense = Expense(category_id=salary_cat.id, amount=record.net_amount, description=desc,
        expense_date=date.today(), created_by=current_user.id,
        payment_method=record.payment_method or 'Cash')
    db.session.add(expense)
    db.session.flush()
    record.status = 'Paid'
    record.expense_id = expense.id
    record.paid_date = date.today()
    db.session.commit()
    flash(f"Payroll confirmed for {record.tutor.name}. Expense recorded (Rs.{record.net_amount:,.2f}).", "success")
    return redirect(url_for('payroll.payroll_list', month=record.month, year=record.year))

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
    expense = Expense.query.get(record.expense_id) if record.expense_id else None
    db.session.delete(record)
    if expense:
        db.session.delete(expense)
    db.session.commit()
    if was_paid and expense:
        flash(f"Salary deleted for {tutor_name}. The recorded salary expense (Rs.{expense.amount:,.2f}) was also removed.", "success")
    else:
        flash(f"Salary deleted for {tutor_name}.", "success")
    return redirect(url_for('payroll.payroll_list', month=month, year=year))

@payroll_bp.route('/payroll/<int:id>/payslip')
@login_required
@admin_required
def payslip_pdf(id):
    record = PayrollRecord.query.get_or_404(id)
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
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
        download_name=f'payslip_{tutor.name.replace(" ", "_")}_{record.month}_{record.year}.pdf')

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
    # Recalculate existing Draft payroll records for this tutor
    draft_records = PayrollRecord.query.filter_by(tutor_id=tutor_id, status='Draft').all()
    for rec in draft_records:
        rec.base_amount = settings.base_salary or 0.0
        rec.bonus_amount = settings.bonus or 0.0
        rec.other_deductions = settings.other_deductions or 0.0
        # Recalc commission from actual fees for this period
        result = compute_tutor_payroll(tutor, rec.month, rec.year, rec.commission_pct_used)
        rec.commission_amount = result['commission']
        gross = rec.base_amount + rec.commission_amount + rec.bonus_amount
        tds_pct = settings.tds_percentage or 0.0
        rec.tds_amount = gross * (tds_pct / 100.0) if tds_pct > 0 else 0.0
        rec.net_amount = gross - rec.tds_amount - rec.other_deductions
    db.session.commit()
    msg = f"Payroll settings updated for {tutor.name}."
    if draft_records:
        msg += f" {len(draft_records)} draft record(s) recalculated."
    flash(msg, "success")
    return redirect(url_for('payroll.payroll_list'))
