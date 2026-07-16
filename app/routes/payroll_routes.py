from datetime import datetime, date, timedelta
from io import BytesIO
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from fpdf import FPDF
from app.extensions import db
from app.models import Tutor, PayrollRecord, TutorPayrollSettings, Expense, ExpenseCategory
from app.helpers import admin_required

payroll_bp = Blueprint('payroll', __name__)

def compute_tutor_payroll(tutor, month, year, percentage=None):
    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor.id).first()
    if not settings:
        settings = TutorPayrollSettings(tutor_id=tutor.id)
        db.session.add(settings)
        db.session.commit()
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
    student_ids = [s.id for s in students]
    commission = 0.0
    if student_ids and comm_pct > 0:
        total_collected = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
            FeeRecord.student_id.in_(student_ids),
            FeeRecord.payment_date >= start_date,
            FeeRecord.payment_date <= end_date
        ).scalar() or 0.0
        commission = total_collected * (comm_pct / 100.0)
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
    totals = {
        'base': sum(r.base_amount for r in records),
        'commission': sum(r.commission_amount for r in records),
        'bonus': sum(r.bonus_amount for r in records),
        'tds': sum(r.tds_amount for r in records),
        'other': sum(r.other_deductions for r in records),
        'net': sum(r.net_amount for r in records),
    }
    return render_template('payroll.html', records=records, tutors=tutors,
        filter_month=filter_month, filter_year=filter_year, filter_status=filter_status,
        totals=totals, today=date.today())

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
        other_deductions=result['other_ded'], net_amount=result['net'], status='Draft')
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
            other_deductions=result['other_ded'], net_amount=result['net'], status='Draft')
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
        expense_date=date.today(), created_by=current_user.id)
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
    pdf = FPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    line_h = 7
    def text_color(r, g, b):
        pdf.set_text_color(r, g, b)
    def set_font(style='', size=10):
        pdf.set_font('Helvetica', style, size)
    pdf.set_fill_color(10, 30, 46)
    pdf.rect(0, 0, 210, 35, 'F')
    set_font('B', 18)
    text_color(0, 212, 255)
    pdf.set_xy(15, 8)
    pdf.cell(0, 10, 'Guha Academy', align='L')
    set_font('', 8)
    text_color(200, 200, 200)
    pdf.set_xy(15, 20)
    pdf.cell(0, 6, 'Computer Institute  |  Salary Payslip', align='L')
    set_font('B', 12)
    text_color(255, 255, 255)
    pdf.set_xy(15, 28)
    pdf.cell(0, 6, f'Period: {period}', align='R')
    pdf.set_xy(15, 45)
    set_font('B', 11)
    text_color(30, 60, 80)
    pdf.cell(0, 8, 'Employee Details', new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(4)
    set_font('', 9)
    text_color(60, 60, 60)
    left_col = [('Employee Name', tutor.name), ('Email', tutor.email), ('Phone', tutor.phone), ('Specialization', tutor.specialization or '-')]
    right_col = [('Bank Name', settings.bank_name if settings and settings.bank_name else '-'),
        ('Account No', settings.account_number if settings and settings.account_number else '-'),
        ('IFSC Code', settings.ifsc_code if settings and settings.ifsc_code else '-'), ('Status', tutor.status)]
    y_start = pdf.get_y()
    for i, (label, val) in enumerate(left_col):
        pdf.set_xy(15, y_start + i * line_h)
        set_font('B', 8)
        text_color(100, 100, 100)
        pdf.cell(40, line_h, label)
        set_font('', 9)
        text_color(30, 30, 30)
        pdf.cell(65, line_h, str(val))
    for i, (label, val) in enumerate(right_col):
        pdf.set_xy(120, y_start + i * line_h)
        set_font('B', 8)
        text_color(100, 100, 100)
        pdf.cell(35, line_h, label)
        set_font('', 9)
        text_color(30, 30, 30)
        pdf.cell(40, line_h, str(val))
    pdf.set_y(y_start + len(left_col) * line_h + 6)
    set_font('B', 11)
    text_color(30, 60, 80)
    pdf.cell(0, 8, 'Earnings & Deductions', new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(4)
    col_w = [90, 30, 30, 30]
    headers = ['Description', 'Earnings', 'Deductions', '']
    def table_header():
        set_font('B', 8)
        pdf.set_fill_color(10, 30, 46)
        text_color(255, 255, 255)
        for i, h in enumerate(headers):
            w = col_w[i] if i < len(col_w) - 1 else 0
            if w > 0:
                pdf.cell(w, line_h, h, border=1, fill=True, align='C')
        pdf.ln()
    def table_row(cols, is_total=False):
        pdf.set_fill_color(240, 245, 250) if is_total else pdf.set_fill_color(255, 255, 255)
        text_color(30, 30, 30)
        set_font('B' if is_total else '', 8)
        for i, c in enumerate(cols):
            w = col_w[i] if i < len(col_w) - 1 else 0
            if w > 0:
                pdf.cell(w, line_h, str(c), border=1, fill=True, align='C' if i > 0 else 'L')
        pdf.ln()
    table_header()
    table_row(['Base Salary', f'Rs. {record.base_amount:,.2f}', '', ''])
    table_row([f'Commission ({record.tutor.payroll_settings.commission_percentage if record.tutor.payroll_settings else 0}%)', f'Rs. {record.commission_amount:,.2f}', '', ''])
    if record.bonus_amount > 0:
        table_row(['Bonus', f'Rs. {record.bonus_amount:,.2f}', '', ''])
    if record.tds_amount > 0:
        table_row(['TDS Deduction', '', f'Rs. {record.tds_amount:,.2f}', ''])
    if record.other_deductions > 0:
        table_row(['Other Deductions', '', f'Rs. {record.other_deductions:,.2f}', ''])
    gross = record.base_amount + record.commission_amount + record.bonus_amount
    total_ded = record.tds_amount + record.other_deductions
    table_row(['', f'Gross: Rs. {gross:,.2f}', f'Total: Rs. {total_ded:,.2f}', ''], is_total=True)
    pdf.ln(6)
    pdf.set_fill_color(10, 30, 46)
    pdf.rect(25, pdf.get_y(), 150, 12, 'F')
    pdf.set_xy(30, pdf.get_y() + 1)
    set_font('B', 12)
    text_color(255, 255, 255)
    pdf.cell(60, 10, 'NET PAYABLE')
    pdf.cell(90, 10, f'Rs. {record.net_amount:,.2f}', align='R')
    pdf.ln(20)
    text_color(150, 150, 150)
    set_font('', 7)
    pdf.cell(0, 5, f'Generated on: {datetime.now().strftime("%d %b %Y %I:%M %p")}  |  This is a computer-generated document.', align='C')
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
    db.session.commit()
    flash(f"Payroll settings updated for {tutor.name}.", "success")
    return redirect(url_for('payroll.payroll_list'))
