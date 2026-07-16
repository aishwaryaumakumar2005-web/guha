from datetime import datetime, date, timedelta
from io import BytesIO
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import FeeRecord, Expense, ExpenseCategory, Course, Student, student_courses, Attendance, Tutor
from app.helpers import admin_required

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports')
@login_required
def reports():
    # Staff: show simplified reports for their courses
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor:
            return render_template('reports.html', tab='staff', today=date.today(), is_staff=True,
                staff_data={'students': [], 'courses': [], 'attendance_rate': 0, 'total_collected': 0, 'recent_fees': []})
        
        course_ids = [c.id for c in tutor.courses]
        student_subquery = db.session.query(student_courses.c.student_id).filter(
            student_courses.c.course_id.in_(course_ids)
        ).distinct()
        students = Student.query.filter(Student.id.in_(student_subquery)).all()
        
        # Get attendance data for staff's students
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)
        attendance_records = Attendance.query.filter(
            Attendance.person_type == 'student',
            Attendance.person_id.in_([s.id for s in students]),
            Attendance.date >= thirty_days_ago
        ).all()
        
        # Calculate attendance rates
        total_records = len(attendance_records)
        present_records = sum(1 for r in attendance_records if r.status == 'Present')
        attendance_rate = (present_records / total_records * 100) if total_records > 0 else 0
        
        # Get fee data for staff's students
        fee_records = FeeRecord.query.filter(
            FeeRecord.student_id.in_([s.id for s in students])
        ).order_by(FeeRecord.payment_date.desc()).limit(50).all()
        
        total_collected = sum(r.amount_paid for r in fee_records)
        
        return render_template('reports.html', 
            tab='staff', 
            today=today,
            is_staff=True,
            staff_data={
                'students': students,
                'courses': tutor.courses,
                'attendance_rate': round(attendance_rate, 1),
                'total_collected': total_collected,
                'recent_fees': fee_records[:20]
            })

    today = date.today()
    tab = request.args.get('tab', 'income')
    filter_mode = request.args.get('filter_mode', 'monthly')
    filter_month = request.args.get('month', type=int) or today.month
    filter_year = request.args.get('year', type=int) or today.year
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    if filter_mode == 'custom' and start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        if filter_mode == 'quarterly':
            q = (filter_month - 1) // 3 + 1
            q_start = (q - 1) * 3 + 1
            start_date = date(filter_year, q_start, 1)
            if q == 4:
                end_date = date(filter_year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(filter_year, q_start + 3, 1) - timedelta(days=1)
        else:
            start_date = date(filter_year, filter_month, 1)
            if filter_month == 12:
                end_date = date(filter_year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(filter_year, filter_month + 1, 1) - timedelta(days=1)
    months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    total_income = db.session.query(db.func.sum(FeeRecord.amount_paid)).scalar() or 0.0
    fee_monthly_map = {}
    fee_monthly_rows = db.session.query(
        db.extract('month', FeeRecord.payment_date).label('m'),
        db.func.sum(FeeRecord.amount_paid).label('total')
    ).filter(db.extract('year', FeeRecord.payment_date) == filter_year
    ).group_by(db.extract('month', FeeRecord.payment_date)).all()
    for r in fee_monthly_rows:
        fee_monthly_map[int(r.m)] = float(r.total)
    income_monthly = [fee_monthly_map.get(m, 0.0) for m in range(1, 13)]
    fees_monthly = [{"month": months_names[m-1], "total": fee_monthly_map.get(m, 0.0)} for m in range(1, 13)]
    course_wise_income = []
    course_fee_rows = db.session.query(
        student_courses.c.course_id, db.func.sum(FeeRecord.amount_paid).label('total')
    ).select_from(FeeRecord).join(Student).join(student_courses).filter(
        FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
    ).group_by(student_courses.c.course_id).all()
    course_fee_map = {r.course_id: float(r.total) for r in course_fee_rows}
    for course in Course.query.all():
        total = course_fee_map.get(course.id, 0.0)
        if total > 0:
            course_wise_income.append({"name": course.name, "code": course.code, "total": total})
    daily_collections = FeeRecord.query.filter(
        FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
    ).order_by(FeeRecord.payment_date.desc()).all()
    expense_categories = ExpenseCategory.query.all()
    exp_monthly_rows = db.session.query(
        db.extract('month', Expense.expense_date).label('m'),
        db.func.sum(Expense.amount).label('total')
    ).filter(db.extract('year', Expense.expense_date) == filter_year
    ).group_by(db.extract('month', Expense.expense_date)).all()
    exp_monthly_map = {int(r.m): float(r.total) for r in exp_monthly_rows}
    monthly_expense = [{"month": months_names[m-1], "total": exp_monthly_map.get(m, 0.0)} for m in range(1, 13)]
    cat_exp_rows = db.session.query(
        Expense.category_id, db.func.sum(Expense.amount).label('total')
    ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date
    ).group_by(Expense.category_id).all()
    cat_exp_map = {r.category_id: float(r.total) for r in cat_exp_rows}
    category_wise_expense = []
    expense_cat_map = {cat.id: cat for cat in expense_categories}
    for cat_id, total in cat_exp_map.items():
        cat = expense_cat_map.get(cat_id)
        if cat:
            category_wise_expense.append({"name": cat.name, "total": total})
    summary_rows = db.session.query(
        Expense.category_id, db.func.count(Expense.id).label('cnt'), db.func.sum(Expense.amount).label('total')
    ).filter(
        db.extract('month', Expense.expense_date) == filter_month,
        db.extract('year', Expense.expense_date) == filter_year
    ).group_by(Expense.category_id).all()
    summary_map = {r.category_id: {'total': float(r.total), 'count': r.cnt} for r in summary_rows}
    expense_summary = []
    for cat in expense_categories:
        s = summary_map.get(cat.id, {'total': 0.0, 'count': 0})
        expense_summary.append({"name": cat.name, "total": s['total'], "count": s['count']})
    recent_expenses_q = Expense.query.filter(
        Expense.expense_date >= start_date, Expense.expense_date <= end_date
    ).order_by(Expense.expense_date.desc()).limit(20).all()
    recent_expenses = []
    exp_chart_labels = []
    exp_chart_amounts = []
    for e in reversed(recent_expenses_q):
        recent_expenses.append(e)
        exp_chart_labels.append(e.expense_date.strftime('%d %b'))
        exp_chart_amounts.append(e.amount)
    total_income_filtered = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
        FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
    ).scalar() or 0.0
    total_expense_filtered = db.session.query(db.func.sum(Expense.amount)).filter(
        Expense.expense_date >= start_date, Expense.expense_date <= end_date
    ).scalar() or 0.0
    net_balance = float(total_income_filtered) - float(total_expense_filtered)
    pl_monthly = []
    for m in range(1, 13):
        inc = fee_monthly_map.get(m, 0.0)
        exp = exp_monthly_map.get(m, 0.0)
        pl_monthly.append({"month": months_names[m-1], "income": inc, "expense": exp, "net": inc - exp})
    cumulative_income = []
    running = 0.0
    for v in income_monthly:
        running += v
        cumulative_income.append(round(running, 2))
    payment_methods = db.session.query(FeeRecord.payment_method, db.func.sum(FeeRecord.amount_paid)).group_by(FeeRecord.payment_method).all()
    payment_labels = [p[0] for p in payment_methods]
    payment_data = [float(p[1]) for p in payment_methods]
    thirty_days_ago = today - timedelta(days=30)
    daily_totals = db.session.query(
        FeeRecord.payment_date, db.func.sum(FeeRecord.amount_paid)
    ).filter(FeeRecord.payment_date >= thirty_days_ago).group_by(FeeRecord.payment_date).order_by(FeeRecord.payment_date).all()
    daily_labels = [d[0].strftime('%d %b') for d in daily_totals]
    daily_amounts = [float(d[1]) for d in daily_totals]
    net_trend = [p['net'] for p in pl_monthly]
    def get_payment_method_data(method_pattern):
        records = FeeRecord.query.filter(
            FeeRecord.payment_method.ilike(f'%{method_pattern}%'),
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        ).order_by(FeeRecord.payment_date.desc()).all()
        total = sum(r.amount_paid for r in records)
        return {'total': total, 'records': records}
    payment_methods_report = {
        'Cash': get_payment_method_data('Cash'),
        'UPI - Guha India': get_payment_method_data('Guha India'),
        'UPI - Ejaj Sir': get_payment_method_data('Ejaj Sir'),
    }
    other_records = FeeRecord.query.filter(
        ~FeeRecord.payment_method.ilike('%Cash%'),
        ~FeeRecord.payment_method.ilike('%Guha India%'),
        ~FeeRecord.payment_method.ilike('%Ejaj Sir%'),
        FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
    ).order_by(FeeRecord.payment_date.desc()).all()
    other_total = sum(r.amount_paid for r in other_records)
    if other_records:
        payment_methods_report['Others'] = {'total': other_total, 'records': other_records}
    total_collected_period = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
        FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
    ).scalar() or 0.0
    return render_template('reports.html', tab=tab, today=today, filter_mode=filter_mode,
        filter_month=filter_month, filter_year=filter_year,
        start_date_str=start_date_str or start_date.strftime('%Y-%m-%d'),
        end_date_str=end_date_str or end_date.strftime('%Y-%m-%d'),
        total_income=float(total_income), income_monthly=income_monthly, cumulative_income=cumulative_income,
        fees_monthly=fees_monthly, course_wise_income=course_wise_income, daily_collections=daily_collections,
        payment_labels=payment_labels, payment_data=payment_data, daily_labels=daily_labels, daily_amounts=daily_amounts,
        monthly_expense=monthly_expense, category_wise_expense=category_wise_expense, expense_summary=expense_summary,
        recent_expenses=recent_expenses, exp_chart_labels=exp_chart_labels, exp_chart_amounts=exp_chart_amounts,
        total_income_filtered=float(total_income_filtered), total_expense_filtered=float(total_expense_filtered),
        net_balance=net_balance, pl_monthly=pl_monthly, net_trend=net_trend,
        payment_methods_report=payment_methods_report, total_collected_period=float(total_collected_period))

@reports_bp.route('/reports/pdf')
@login_required
@admin_required
def report_pdf():
    from fpdf import FPDF
    today = date.today()
    tab = request.args.get('tab', 'income')
    filter_mode = request.args.get('filter_mode', 'monthly')
    filter_month = request.args.get('month', type=int) or today.month
    filter_year = request.args.get('year', type=int) or today.year
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    if filter_mode == 'custom' and start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        if filter_mode == 'quarterly':
            q = (filter_month - 1) // 3 + 1
            q_start = (q - 1) * 3 + 1
            start_date = date(filter_year, q_start, 1)
            end_date = date(filter_year + 1, 1, 1) - timedelta(days=1) if q == 4 else date(filter_year, q_start + 3, 1) - timedelta(days=1)
        else:
            start_date = date(filter_year, filter_month, 1)
            end_date = date(filter_year + 1, 1, 1) - timedelta(days=1) if filter_month == 12 else date(filter_year, filter_month + 1, 1) - timedelta(days=1)
    period_label = f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}"
    class ReportPDF(FPDF):
        def header(self):
            self.set_font('Helvetica', 'B', 16)
            self.set_text_color(47, 72, 88)
            self.cell(0, 10, 'Guha Academy - Computer Institute', align='C', new_x="LMARGIN", new_y="NEXT")
            self.set_font('Helvetica', '', 9)
            self.set_text_color(100, 100, 100)
            titles = {'income': 'Income Report', 'fees': 'Student Fees Report', 'expense': 'Expense Report', 'overall': 'Overall Report'}
            self.cell(0, 6, f'{titles.get(tab, "Report")}  |  Period: {period_label}', align='C', new_x="LMARGIN", new_y="NEXT")
            self.ln(4)
            self.set_draw_color(217, 93, 57)
            self.set_line_width(0.5)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(6)
        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 7)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, f'Generated: {today.strftime("%d %b %Y %I:%M %p")}  |  Page {self.page_no()}/{{nb}}', align='C')
        def section_title(self, title):
            self.set_font('Helvetica', 'B', 12)
            self.set_text_color(47, 72, 88)
            self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
            self.ln(2)
        def kpi_box(self, label, value, color=(107, 142, 35)):
            self.set_font('Helvetica', 'B', 12)
            self.set_text_color(*color)
            self.cell(60, 7, value, align='C')
            self.set_font('Helvetica', '', 7)
            self.set_text_color(100, 100, 100)
            self.cell(0, 7, label, align='C', new_x="LMARGIN", new_y="NEXT")
            self.ln(1)
        def table_header(self, cols, widths):
            self.set_font('Helvetica', 'B', 8)
            self.set_fill_color(47, 72, 88)
            self.set_text_color(255, 255, 255)
            for i, col in enumerate(cols):
                self.cell(widths[i], 6, col, border=1, align='C', fill=True)
            self.ln()
        def table_row(self, cols, widths, aligns=None):
            self.set_font('Helvetica', '', 8)
            self.set_text_color(50, 50, 50)
            for i, col in enumerate(cols):
                a = aligns[i] if aligns else 'C'
                self.cell(widths[i], 5, str(col), border=1, align=a)
            self.ln()
    pdf = ReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    if tab == 'income':
        total_income = db.session.query(db.func.sum(FeeRecord.amount_paid)).scalar() or 0.0
        income_rows = db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')
        ).filter(db.extract('year', FeeRecord.payment_date) == filter_year).group_by(db.extract('month', FeeRecord.payment_date)).all()
        income_map = {int(r.m): float(r.total) for r in income_rows}
        income_monthly = [income_map.get(m, 0.0) for m in range(1, 13)]
        pdf.section_title('Income Summary')
        pdf.kpi_box('Total Income (All Time)', f'Rs. {total_income:,.2f}', (107, 142, 35))
        pdf.kpi_box(f'Year {filter_year}', f'Rs. {sum(income_monthly):,.2f}', (47, 72, 88))
        pdf.kpi_box(f'Monthly Avg ({filter_year})', f'Rs. {sum(income_monthly)/12:,.2f}', (70, 130, 180))
        pdf.ln(4)
        pdf.section_title(f'Monthly Income - {filter_year}')
        pdf.table_header(['Month', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], [20] + [14]*12)
        pdf.table_row(['Income (Rs.)'] + [f'{v:,.0f}' for v in income_monthly], [20] + [14]*12, ['L'] + ['R']*12)
    elif tab == 'fees':
        fees_rows = db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')
        ).filter(db.extract('year', FeeRecord.payment_date) == filter_year).group_by(db.extract('month', FeeRecord.payment_date)).all()
        fees_map = {int(r.m): float(r.total) for r in fees_rows}
        fees_monthly = [fees_map.get(m, 0.0) for m in range(1, 13)]
        months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        pdf.section_title('Monthly Fees Collection')
        pdf.table_header(['Month'] + months_names, [20] + [14]*12)
        pdf.table_row(['Amount (Rs.)'] + [f'{v:,.0f}' for v in fees_monthly], [20] + [14]*12, ['L'] + ['R']*12)
        pdf.ln(3)
        course_fee_rows = db.session.query(
            student_courses.c.course_id, db.func.sum(FeeRecord.amount_paid).label('total')
        ).select_from(FeeRecord).join(Student).join(student_courses).filter(
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        ).group_by(student_courses.c.course_id).all()
        course_fee_map = {r.course_id: float(r.total) for r in course_fee_rows}
        course_wise = [(course.name, course_fee_map.get(course.id, 0.0)) for course in Course.query.all() if course_fee_map.get(course.id, 0.0) > 0]
        if course_wise:
            pdf.section_title('Course-wise Income')
            pdf.table_header(['Course', 'Amount (Rs.)'], [140, 50])
            for name, total in course_wise:
                pdf.table_row([name, f'{total:,.2f}'], [140, 50], ['L', 'R'])
        pdf.ln(3)
        daily = FeeRecord.query.filter(
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        ).order_by(FeeRecord.payment_date.desc()).all()
        if daily:
            pdf.section_title('Daily Collections')
            pdf.table_header(['Date', 'Student', 'Amount', 'Method', 'Remarks'], [30, 45, 35, 35, 45])
            for r in daily[:30]:
                pdf.table_row([r.payment_date.strftime('%d %b %Y'), r.student.name[:20], f'{r.amount_paid:,.0f}', r.payment_method, (r.remarks or '')[:25]], [30, 45, 35, 35, 45], ['L', 'L', 'R', 'C', 'L'])
    elif tab == 'expense':
        expense_cats = ExpenseCategory.query.all()
        months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        exp_rows = db.session.query(
            db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')
        ).filter(db.extract('year', Expense.expense_date) == filter_year).group_by(db.extract('month', Expense.expense_date)).all()
        exp_map = {int(r.m): float(r.total) for r in exp_rows}
        monthly_exp = [exp_map.get(m, 0.0) for m in range(1, 13)]
        pdf.section_title('Monthly Expense')
        pdf.table_header(['Month'] + months_names, [20] + [14]*12)
        pdf.table_row(['Amount (Rs.)'] + [f'{v:,.0f}' for v in monthly_exp], [20] + [14]*12, ['L'] + ['R']*12)
        pdf.ln(3)
        cat_exp_rows = db.session.query(
            Expense.category_id, db.func.sum(Expense.amount).label('total')
        ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date).group_by(Expense.category_id).all()
        cat_exp_map = {r.category_id: float(r.total) for r in cat_exp_rows}
        cat_wise = [(cat.name, cat_exp_map.get(cat.id, 0.0)) for cat in expense_cats if cat_exp_map.get(cat.id, 0.0) > 0]
        if cat_wise:
            pdf.section_title('Category-wise Expense')
            pdf.table_header(['Category', 'Amount (Rs.)'], [140, 50])
            for name, total in cat_wise:
                pdf.table_row([name, f'{total:,.2f}'], [140, 50], ['L', 'R'])
        pdf.ln(3)
        pdf.section_title(f'Expense Summary - {months_names[filter_month-1]} {filter_year}')
        pdf.table_header(['Category', 'Count', 'Total (Rs.)'], [100, 30, 60])
        summary_rows = db.session.query(
            Expense.category_id, db.func.count(Expense.id).label('cnt'), db.func.sum(Expense.amount).label('total')
        ).filter(db.extract('month', Expense.expense_date) == filter_month, db.extract('year', Expense.expense_date) == filter_year).group_by(Expense.category_id).all()
        summary_map = {r.category_id: {'total': float(r.total), 'count': r.cnt} for r in summary_rows}
        for cat in expense_cats:
            s = summary_map.get(cat.id, {'total': 0.0, 'count': 0})
            pdf.table_row([cat.name, str(s['count']), f'{s["total"]:,.2f}'], [100, 30, 60], ['L', 'C', 'R'])
    elif tab == 'overall':
        total_income = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date).scalar() or 0.0
        total_expense = db.session.query(db.func.sum(Expense.amount)).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date).scalar() or 0.0
        net = float(total_income) - float(total_expense)
        pdf.section_title('Profit & Loss Summary')
        pdf.kpi_box('Total Income', f'Rs. {float(total_income):,.2f}', (107, 142, 35))
        pdf.kpi_box('Total Expense', f'Rs. {float(total_expense):,.2f}', (192, 57, 43))
        pdf.kpi_box('Net Balance', f"{'+' if net >= 0 else ''}Rs. {net:,.2f}", (47, 72, 88) if net >= 0 else (192, 57, 43))
        pdf.ln(4)
        months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        pdf.section_title(f'Monthly P&L - {filter_year}')
        pdf.table_header(['Month', 'Income', 'Expense', 'Net', 'Status'], [30, 45, 45, 45, 35])
        inc_rows = db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year).group_by(db.extract('month', FeeRecord.payment_date)).all()
        inc_map = {int(r.m): float(r.total) for r in inc_rows}
        exp_rows_ov = db.session.query(db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')).filter(db.extract('year', Expense.expense_date) == filter_year).group_by(db.extract('month', Expense.expense_date)).all()
        exp_map_ov = {int(r.m): float(r.total) for r in exp_rows_ov}
        for m in range(1, 13):
            inc = inc_map.get(m, 0.0)
            exp = exp_map_ov.get(m, 0.0)
            n = inc - exp
            status = 'Profit' if n > 0 else ('Loss' if n < 0 else 'Breakeven')
            pdf.table_row([months_names[m-1], f'{inc:,.2f}', f'{exp:,.2f}', f"{'+' if n >= 0 else ''}{n:,.2f}", status], [30, 45, 45, 45, 35], ['C', 'R', 'R', 'R', 'C'])
    elif tab == 'payment_methods':
        all_records = FeeRecord.query.filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date).order_by(FeeRecord.payment_date.desc()).all()
        total_period = sum(r.amount_paid for r in all_records)
        def filter_pm(records, pattern):
            matched = [r for r in records if pattern.lower() in (r.payment_method or '').lower()]
            return sum(r.amount_paid for r in matched), matched
        pm_methods = [('Cash', 'Cash'), ('UPI - Guha India', 'Guha India'), ('UPI - Ejaj Sir', 'Ejaj Sir')]
        pdf.section_title('Payment Methods Report')
        pdf.kpi_box('Total Collected', f'Rs. {total_period:,.2f}', (47, 72, 88))
        pdf.ln(4)
        for label, pattern in pm_methods:
            total, records = filter_pm(all_records, pattern)
            pdf.section_title(f'{label} - Rs. {total:,.2f}')
            if records:
                pdf.table_header(['Date', 'Student', 'Amount', 'Remarks'], [30, 55, 35, 70])
                for r in records[:30]:
                    pdf.table_row([r.payment_date.strftime('%d %b %Y'), r.student.name[:20], f'{r.amount_paid:,.0f}', (r.remarks or '')[:30]], [30, 55, 35, 70], ['L', 'L', 'R', 'L'])
            pdf.ln(2)
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    filenames = {'income': 'Income_Report', 'fees': 'Student_Fees_Report', 'expense': 'Expense_Report', 'overall': 'Overall_Report', 'payment_methods': 'Payment_Methods_Report'}
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'{filenames.get(tab, "Report")}_{filter_year}_{filter_month}.pdf')

@reports_bp.route('/reports/excel')
@login_required
@admin_required
def report_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    today = date.today()
    tab = request.args.get('tab', 'income')
    filter_mode = request.args.get('filter_mode', 'monthly')
    filter_month = request.args.get('month', type=int) or today.month
    filter_year = request.args.get('year', type=int) or today.year
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    if filter_mode == 'custom' and start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        if filter_mode == 'quarterly':
            q = (filter_month - 1) // 3 + 1
            q_start = (q - 1) * 3 + 1
            start_date = date(filter_year, q_start, 1)
            end_date = date(filter_year + 1, 1, 1) - timedelta(days=1) if q == 4 else date(filter_year, q_start + 3, 1) - timedelta(days=1)
        else:
            start_date = date(filter_year, filter_month, 1)
            end_date = date(filter_year + 1, 1, 1) - timedelta(days=1) if filter_month == 12 else date(filter_year, filter_month + 1, 1) - timedelta(days=1)
    wb = Workbook()
    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='2F4858', end_color='2F4858', fill_type='solid')
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    def write_sheet(ws, title, headers, rows):
        ws.title = title
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center')
            c.border = thin_border
        for r, row in enumerate(rows, 2):
            for col, val in enumerate(row, 1):
                c = ws.cell(row=r, column=col, value=val)
                c.border = thin_border
                c.alignment = Alignment(horizontal='right' if isinstance(val, (int, float)) else 'left')
        for col in ws.columns:
            max_len = max((len(str(c.value or '')) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 40)
    if tab == 'income':
        inc_rows = db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year).group_by(db.extract('month', FeeRecord.payment_date)).all()
        inc_map = {int(r.m): float(r.total) for r in inc_rows}
        income_monthly = [inc_map.get(m, 0.0) for m in range(1, 13)]
        total_all_time = db.session.query(db.func.sum(FeeRecord.amount_paid)).scalar() or 0
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        ws = wb.active
        write_sheet(ws, 'Monthly Income', ['Month'] + months, [['Income (Rs.)'] + income_monthly])
        ws2 = wb.create_sheet('Summary')
        write_sheet(ws2, 'Summary', ['Metric', 'Value'], [['Total Income (All Time)', total_all_time], [f'Total ({filter_year})', sum(income_monthly)], [f'Monthly Avg ({filter_year})', sum(income_monthly) / 12]])
    elif tab == 'fees':
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        fees_rows = db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year).group_by(db.extract('month', FeeRecord.payment_date)).all()
        fees_map = {int(r.m): float(r.total) for r in fees_rows}
        fees_monthly = [fees_map.get(m, 0.0) for m in range(1, 13)]
        ws = wb.active
        write_sheet(ws, 'Monthly Fees', ['Month'] + months, [['Collection (Rs.)'] + fees_monthly])
        rows = []
        course_fee_rows = db.session.query(student_courses.c.course_id, db.func.sum(FeeRecord.amount_paid).label('total')).select_from(FeeRecord).join(Student).join(student_courses).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date).group_by(student_courses.c.course_id).all()
        course_fee_map = {r.course_id: float(r.total) for r in course_fee_rows}
        for course in Course.query.all():
            total = course_fee_map.get(course.id, 0.0)
            if total > 0:
                rows.append([course.name, course.code, total])
        if rows:
            ws2 = wb.create_sheet('Course-wise')
            write_sheet(ws2, 'Course-wise', ['Course', 'Code', 'Collected (Rs.)'], rows)
        daily = FeeRecord.query.filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date).order_by(FeeRecord.payment_date.desc()).all()
        if daily:
            ws3 = wb.create_sheet('Daily Collections')
            write_sheet(ws3, 'Daily Collections', ['Date', 'Student', 'Amount', 'Method', 'Remarks'], [[r.payment_date.strftime('%d-%b-%Y'), r.student.name, r.amount_paid, r.payment_method, r.remarks or ''] for r in daily])
    elif tab == 'expense':
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        exp_rows = db.session.query(db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')).filter(db.extract('year', Expense.expense_date) == filter_year).group_by(db.extract('month', Expense.expense_date)).all()
        exp_map = {int(r.m): float(r.total) for r in exp_rows}
        monthly_exp = [exp_map.get(m, 0.0) for m in range(1, 13)]
        ws = wb.active
        write_sheet(ws, 'Monthly Expense', ['Month'] + months, [['Expense (Rs.)'] + monthly_exp])
        rows = []
        cat_exp_rows = db.session.query(Expense.category_id, db.func.sum(Expense.amount).label('total')).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date).group_by(Expense.category_id).all()
        cat_exp_map = {r.category_id: float(r.total) for r in cat_exp_rows}
        for cat in ExpenseCategory.query.all():
            total = cat_exp_map.get(cat.id, 0.0)
            rows.append([cat.name, total])
        ws2 = wb.create_sheet('Category-wise')
        write_sheet(ws2, 'Category-wise', ['Category', 'Total (Rs.)'], rows)
        recent = Expense.query.filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date).order_by(Expense.expense_date.desc()).limit(50).all()
        if recent:
            ws3 = wb.create_sheet('Recent Expenses')
            write_sheet(ws3, 'Recent Expenses', ['Date', 'Category', 'Description', 'Amount'], [[r.expense_date.strftime('%d-%b-%Y'), r.category.name, r.description[:60], r.amount] for r in recent])
    elif tab == 'overall':
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        ws = wb.active
        total_inc = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date).scalar() or 0.0
        total_exp = db.session.query(db.func.sum(Expense.amount)).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date).scalar() or 0.0
        write_sheet(ws, 'P&L Summary', ['Metric', 'Value'], [['Total Income', float(total_inc)], ['Total Expense', float(total_exp)], ['Net Balance', float(total_inc) - float(total_exp)]])
        rows = []
        inc_rows_ov = db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year).group_by(db.extract('month', FeeRecord.payment_date)).all()
        inc_map_ov = {int(r.m): float(r.total) for r in inc_rows_ov}
        exp_rows_ov = db.session.query(db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')).filter(db.extract('year', Expense.expense_date) == filter_year).group_by(db.extract('month', Expense.expense_date)).all()
        exp_map_ov = {int(r.m): float(r.total) for r in exp_rows_ov}
        for m in range(1, 13):
            inc = inc_map_ov.get(m, 0.0)
            exp = exp_map_ov.get(m, 0.0)
            rows.append([months[m-1], inc, exp, inc - exp])
        ws2 = wb.create_sheet('Monthly P&L')
        write_sheet(ws2, 'Monthly P&L', ['Month', 'Income', 'Expense', 'Net'], rows)
    elif tab == 'payment_methods':
        ws = wb.active
        ws.title = 'Summary'
        all_records = FeeRecord.query.filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date).order_by(FeeRecord.payment_date.desc()).all()
        total_period = sum(r.amount_paid for r in all_records)
        write_sheet(ws, 'Payment Summary', ['Method', 'Total (Rs.)'], [])
        def filter_pm(records, pattern):
            matched = [r for r in records if pattern.lower() in (r.payment_method or '').lower()]
            return sum(r.amount_paid for r in matched), matched
        pm_methods = [('Cash', 'Cash'), ('UPI - Guha India', 'Guha India'), ('UPI - Ejaj Sir', 'Ejaj Sir')]
        for label, pattern in pm_methods:
            total, records = filter_pm(all_records, pattern)
            ws2 = wb.create_sheet(label[:20])
            write_sheet(ws2, label, ['Date', 'Student', 'Amount', 'Remarks'], [[r.payment_date.strftime('%d-%b-%Y'), r.student.name, r.amount_paid, (r.remarks or '')] for r in records])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filenames = {'income': 'Income_Report', 'fees': 'Student_Fees_Report', 'expense': 'Expense_Report', 'overall': 'Overall_Report'}
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'{filenames.get(tab, "Report")}_{filter_year}_{filter_month}.xlsx')
