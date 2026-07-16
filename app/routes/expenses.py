from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Expense, ExpenseCategory, Tutor, Student, Course, FeeRecord
from app.helpers import admin_required, is_ajax_request
from app.forms import ExpenseForm
from sqlalchemy.orm import joinedload

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
        expense_date = form.cleaned_data.get('expense_date', date.today())
        new_expense = Expense(category_id=category_id, amount=amount, description=description, expense_date=expense_date, created_by=current_user.id)
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
        filter_year=filter_year or today.year)

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
    salary_cat = ExpenseCategory.query.filter_by(name="Salary").first()
    if not salary_cat:
        salary_cat = ExpenseCategory(name="Salary", description="Staff salary payments")
        db.session.add(salary_cat)
        db.session.commit()
    tutors = Tutor.query.all()
    selected_tutor_id = request.values.get('tutor_id', type=int)
    percentage = request.values.get('percentage', default=10.0, type=float)
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
    calculated_salary = 0.0
    if selected_tutor_id:
        selected_tutor = Tutor.query.get(selected_tutor_id)
        if selected_tutor:
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
    if request.method == 'POST' and request.form.get('action') == 'record_salary':
        if not selected_tutor or calculated_salary <= 0:
            flash("Cannot record zero or invalid salary calculation.", "danger")
        else:
            date_label = f"{start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}" if filter_type == 'range' else f"{start_date.strftime('%B %Y')}"
            desc = f"Salary for Tutor: {selected_tutor.name} - calculated from collection: Rs.{total_collected:,.2f} ({percentage}%) for period {date_label}"
            salary_expense = Expense(category_id=salary_cat.id, amount=calculated_salary, description=desc, expense_date=today, created_by=current_user.id)
            db.session.add(salary_expense)
            db.session.commit()
            flash(f"Recorded salary of Rs.{calculated_salary:,.2f} for {selected_tutor.name} in Expenses!", "success")
            return redirect(url_for('expenses.list'))
    return render_template('salary_calculator.html', tutors=tutors, selected_tutor=selected_tutor,
        selected_tutor_id=selected_tutor_id, percentage=percentage, filter_type=filter_type,
        filter_month=filter_month, filter_year=filter_year, start_date=start_date, end_date=end_date,
        students=students, fee_records=fee_records, total_collected=total_collected,
        calculated_salary=calculated_salary, today=today)

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
