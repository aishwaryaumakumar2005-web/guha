from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Expense, ExpenseCategory, Tutor, Student, Course, FeeRecord, TutorPayrollSettings, tutor_courses, student_courses
from app.helpers import admin_required, is_ajax_request
from app.forms import ExpenseForm
from app.services.account_service import compute_account_summary
from sqlalchemy import distinct
from sqlalchemy.orm import joinedload, subqueryload

expenses_bp = Blueprint('expenses', __name__)

DEFAULT_CATEGORIES = ['Rent', 'Salary', 'Electricity', 'Internet', 'Marketing', 'Maintenance', 'Refund', 'GST Auditor', 'GST expenses', 'Others']

def ensure_expense_categories():
    existing = {c.name for c in ExpenseCategory.query.with_entities(ExpenseCategory.name).all()}
    new_cats = [ExpenseCategory(name=n) for n in DEFAULT_CATEGORIES if n not in existing]
    if new_cats:
        db.session.add_all(new_cats)
        db.session.commit()

@expenses_bp.route('/expenses', methods=['GET', 'POST'])
@login_required
@admin_required
def list():
    ensure_expense_categories()
    if request.method == 'POST':
        form = ExpenseForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('expenses.list'))
        category_id = form.cleaned_data.get('category_id')
        amount = form.cleaned_data.get('amount', 0)
        description = request.form.get('description', '').strip()
        payment_method = request.form.get('payment_method', 'Cash').strip()
        expense_date = form.cleaned_data.get('expense_date', date.today())
        new_expense = Expense(category_id=category_id, amount=amount, description=description, payment_method=payment_method, expense_date=expense_date, created_by=current_user.id)
        db.session.add(new_expense)
        db.session.commit()
        message = "Expense recorded successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('expenses.list'))
    filter_category = request.args.get('category_id', type=int)
    filter_month = request.args.get('month')
    filter_year = request.args.get('year', type=int)
    query = Expense.query.options(joinedload(Expense.category), joinedload(Expense.creator))
    if filter_category:
        query = query.filter_by(category_id=filter_category)
    if filter_month and filter_year:
        query = query.filter(
            db.extract('month', Expense.expense_date) == int(filter_month),
            db.extract('year', Expense.expense_date) == filter_year
        )
    elif filter_year:
        query = query.filter(db.extract('year', Expense.expense_date) == filter_year)
    all_expenses = query.order_by(Expense.expense_date.desc()).all()
    categories = ExpenseCategory.query.all()
    today = date.today()
    month = filter_month or today.month
    year = filter_year or today.year
    totals_query = db.session.query(
        Expense.category_id, db.func.sum(Expense.amount).label('total')
    ).filter(
        db.extract('month', Expense.expense_date) == int(month),
        db.extract('year', Expense.expense_date) == year
    ).group_by(Expense.category_id).all()
    totals_map = {cat_id: float(total) for cat_id, total in totals_query}
    category_totals = [{"name": cat.name, "total": totals_map.get(cat.id, 0.0)} for cat in categories]
    grand_total = sum(ct["total"] for ct in category_totals)
    return render_template('expenses.html', expenses=all_expenses, categories=categories,
        category_totals=category_totals, grand_total=grand_total, today=today,
        filter_category=filter_category, filter_month=filter_month or today.month,
        filter_year=filter_year or today.year, account_balances=compute_account_summary())

@expenses_bp.route('/expenses/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    expense = Expense.query.get_or_404(id)
    form = ExpenseForm(request.form)
    if not form.validate():
        if is_ajax_request():
            return jsonify({"success": False, "errors": form.error_messages}), 400
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('expenses.list'))
    expense.category_id = form.cleaned_data.get('category_id')
    expense.amount = form.cleaned_data.get('amount', 0)
    expense.description = request.form.get('description', '').strip()
    expense.payment_method = request.form.get('payment_method', 'Cash').strip()
    expense.expense_date = form.cleaned_data.get('expense_date', expense.expense_date)
    db.session.commit()
    message = "Expense updated successfully!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('expenses.list'))

@expenses_bp.route('/expenses/delete/<int:id>')
@login_required
@admin_required
def delete(id):
    expense = Expense.query.get_or_404(id)
    db.session.delete(expense)
    db.session.commit()
    message = "Expense record deleted!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('expenses.list'))

@expenses_bp.route('/salary-calculator', methods=['GET', 'POST'])
@login_required
@admin_required
def salary_calculator():
    tutors = Tutor.query.all()
    selected_tutor_id = request.values.get('tutor_id', type=int)
    today = date.today()
    filter_type = request.values.get('filter_type', 'month')
    filter_month = request.values.get('month', default=today.month, type=int)
    filter_year = request.values.get('year', default=today.year, type=int)
    start_date_str = request.values.get('start_date')
    end_date_str = request.values.get('end_date')
    start_date = None
    end_date = None
    if filter_type == 'range' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if not start_date or not end_date:
        start_date = date(filter_year, filter_month, 1)
        if filter_month == 12:
            end_date = date(filter_year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(filter_year, filter_month + 1, 1) - timedelta(days=1)
    selected_tutor = None
    students = []
    fee_records = []
    total_collected = 0.0
    split_collected = 0.0
    calculated_salary = 0.0
    split_salary = 0.0
    shared_students = []
    percentage = request.values.get('percentage', type=float)
    if selected_tutor_id:
        selected_tutor = Tutor.query.get(selected_tutor_id)
        if selected_tutor:
            if percentage is None:
                settings = TutorPayrollSettings.query.filter_by(tutor_id=selected_tutor.id).first()
                percentage = (settings.commission_percentage or 10.0) if settings and settings.commission_percentage else 10.0
            students = Student.query.join(Student.courses).join(Course.tutors).filter(Tutor.id == selected_tutor.id).all()
            student_ids = [s.id for s in students]
            if student_ids:
                fee_records = FeeRecord.query.filter(
                    FeeRecord.student_id.in_(student_ids),
                    FeeRecord.payment_date >= start_date,
                    FeeRecord.payment_date <= end_date
                ).all()
                total_collected = sum(record.amount_paid for record in fee_records)
                calculated_salary = total_collected * (percentage / 100.0)
                fees_by_student = {}
                for record in fee_records:
                    fees_by_student[record.student_id] = fees_by_student.get(record.student_id, 0.0) + record.amount_paid
                for student in students:
                    tutor_count = db.session.query(db.func.count(distinct(Tutor.id))).select_from(Tutor).join(
                        tutor_courses, Tutor.id == tutor_courses.c.tutor_id
                    ).join(Course, Course.id == tutor_courses.c.course_id).join(
                        student_courses, student_courses.c.course_id == Course.id
                    ).filter(student_courses.c.student_id == student.id).scalar() or 0
                    if tutor_count == 0:
                        continue
                    if tutor_count > 1:
                        shared_students.append({'student': student, 'tutor_count': tutor_count})
                    split_collected += fees_by_student.get(student.id, 0.0) / tutor_count
                split_salary = split_collected * (percentage / 100.0)
    if percentage is None:
        percentage = 10.0
    return render_template('salary_calculator.html', tutors=tutors, selected_tutor=selected_tutor,
        selected_tutor_id=selected_tutor_id, percentage=percentage, filter_type=filter_type,
        filter_month=filter_month, filter_year=filter_year, start_date=start_date, end_date=end_date,
        students=students, fee_records=fee_records, total_collected=total_collected,
        split_collected=split_collected, calculated_salary=calculated_salary,
        split_salary=split_salary, shared_students=shared_students, today=today)

@expenses_bp.route('/api/expenses/chart-data')
@login_required
def api_expenses_chart():
    year = request.args.get('year', type=int) or date.today().year
    monthly = db.session.query(
        db.extract('month', Expense.expense_date).label('m'),
        db.func.sum(Expense.amount).label('total')
    ).filter(db.extract('year', Expense.expense_date) == year).group_by(db.extract('month', Expense.expense_date)).all()
    month_map = {int(r.m): float(r.total) for r in monthly}
    months_data = [month_map.get(m, 0.0) for m in range(1, 13)]
    return jsonify({"months": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], "totals": months_data, "year": year})
