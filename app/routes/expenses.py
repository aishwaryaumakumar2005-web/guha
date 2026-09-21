from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Expense, ExpenseCategory, Tutor, Student, Course, FeeRecord, TutorPayrollSettings, Account, Company, tutor_courses, student_courses
from app.helpers import admin_required, is_ajax_request, FINANCE_LIST_LIMIT, save_photo_data
from app.forms import ExpenseForm
from app.services.account_service import (
    compute_account_summary, student_outstanding_bulk, agreed_enrollment_items,
    ensure_default_companies, snapshot_company_id,
)
from app.services.payment_methods import classify_method
from sqlalchemy import distinct
from sqlalchemy.orm import joinedload, subqueryload

expenses_bp = Blueprint('expenses', __name__)

DEFAULT_CATEGORIES = ['Rent', 'Salary', 'Electricity', 'Internet', 'Marketing', 'Maintenance', 'Refund', 'GST Auditor', 'GST expenses', 'Others']
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _parse_student_id(raw):
    """Validate the optional refund student link; ''/0 -> None, bogus -> None."""
    if raw is None:
        return None
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return None
    if sid <= 0:
        return None
    if Student.query.get(sid) is None:
        return None
    return sid


def _parse_student_reference(raw):
    """Return (student_id, error), rejecting malformed refund references."""
    if raw in (None, ''):
        return None, None
    sid = _parse_student_id(raw)
    return (sid, None) if sid else (None, 'The selected student does not exist.')


def _refund_category_id():
    """The canonical 'Refund' category, creating it if the baseline seed lacks it."""
    cat = ExpenseCategory.query.filter_by(name='Refund').first()
    if cat is None:
        cat = ExpenseCategory(name='Refund')
        db.session.add(cat)
        db.session.flush()
    return cat.id


def _canonicalize_refund(category_id, student_id):
    """Enforce a single refund rule: an expense reimbursing a student is a
    refund, period. 'Refund' without a student is a booking error, and a
    student-linked expense is always normalized onto the 'Refund' category.

    Returns (final_category_id, error_message); error is None on success.
    """
    cat = ExpenseCategory.query.get(category_id)
    is_refund_cat = bool(cat and cat.name == 'Refund')
    if is_refund_cat and student_id is None:
        return category_id, \
            "Category 'Refund' requires selecting the student being refunded."
    if student_id is not None and not is_refund_cat:
        return _refund_category_id(), None
    return category_id, None


def ensure_expense_categories():
    existing = {c.name for c in ExpenseCategory.query.with_entities(ExpenseCategory.name).all()}
    new_cats = [ExpenseCategory(name=n) for n in DEFAULT_CATEGORIES if n not in existing]
    if new_cats:
        db.session.add_all(new_cats)
        db.session.commit()


def _default_company_id(payment_method, student_id):
    """Attribution default: refunds follow the student's billing company,
    ordinary expenses follow the payment account's company. Falls back to the
    GST entity when nothing resolves; None only if no companies exist."""
    if student_id:
        items = agreed_enrollment_items(student_id)
        if items:
            gst, nongst = ensure_default_companies()
            cid = items[0].get('company_id')
            if not cid:
                cid = snapshot_company_id(items[0], gst.id, nongst.id)
            if cid:
                return cid
    acc = Account.query.filter_by(name=classify_method(payment_method), is_active=True).first()
    if acc and acc.company_id:
        return acc.company_id
    gst, nongst = ensure_default_companies()
    return (gst or nongst).id if (gst or nongst) else None


def _parse_company_id(raw):
    """Optional explicit company; validates the row exists. '' -> None."""
    if raw is None:
        return None
    try:
        cid = int(raw)
    except (TypeError, ValueError):
        return None
    if cid <= 0:
        return None
    if Company.query.get(cid) is None:
        return None
    return cid


def _payment_ref(raw):
    ref = (raw or '').strip()
    return ref[:100]


def _save_attachment(form):
    """Read an uploaded receipt. Returns (data, mime, name) or (None, None, None)."""
    file = form.files.get('attachment') if form.files else None
    if not file or not getattr(file, 'filename', None):
        return None, None, None
    try:
        data, mime = save_photo_data(file, max_mb=4)
    except ValueError as e:
        return e, None, None
    if data is None:
        return None, None, None
    name = file.filename.rsplit('\\', 1)[-1] or 'receipt'
    return data, mime, name[:255]


def _reject(message, status=400):
    if is_ajax_request():
        return jsonify({"success": False, "errors": [message]}), status
    flash(message, 'danger')
    return redirect(url_for('expenses.list'))


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
        if ExpenseCategory.query.get(category_id) is None:
            return _reject("Selected category does not exist")
        amount = form.cleaned_data.get('amount', 0)
        description = request.form.get('description', '').strip()
        payment_method = request.form.get('payment_method', 'Cash').strip()
        expense_date = form.cleaned_data.get('expense_date', date.today())
        # W3: optional student link = this Expense is a refund that reduces
        # that student's dues.
        student_id, student_error = _parse_student_reference(request.form.get('student_id'))
        if student_error:
            return _reject(student_error)
        category_id, refund_error = _canonicalize_refund(category_id, student_id)
        if refund_error:
            return _reject(refund_error)
        final_cat = ExpenseCategory.query.get(category_id)
        if final_cat is not None and not final_cat.is_active and not refund_error:
            return _reject("This expense category is archived — reactive it or pick another.")
        # Enhancements: explicit company attribution, payment reference, receipt.
        company_id = _default_company_id(payment_method, student_id)
        explicit_company = _parse_company_id(request.form.get('company_id'))
        if explicit_company:
            company_id = explicit_company
        payment_ref = _payment_ref(request.form.get('payment_ref'))
        if payment_method != 'Cash' and not payment_ref:
            return _reject('A payment reference is required for non-cash expenses.')
        duplicate = Expense.query.filter(
            Expense.status != 'Voided', Expense.amount == amount,
            Expense.expense_date == expense_date,
            Expense.payment_method == payment_method,
            Expense.description == description,
        ).first()
        if duplicate and request.form.get('confirm_duplicate') != '1':
            return _reject('A matching active expense already exists. Confirm it is not a duplicate before saving.', 409)
        att = _save_attachment(request)
        if isinstance(att[0], Exception):
            return _reject(str(att[0]))
        att_data, att_mime, att_name = att
        new_expense = Expense(category_id=category_id, amount=amount, description=description,
                              payment_method=payment_method, expense_date=expense_date,
                              created_by=current_user.id, student_id=student_id,
                              company_id=company_id, payment_ref=payment_ref,
                              attachment_data=att_data, attachment_mime=att_mime,
                              attachment_name=att_name)
        db.session.add(new_expense)
        db.session.commit()
        message = "Expense recorded successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('expenses.list'))
    filter_category = request.args.get('category_id', type=int)
    filter_month = request.args.get('month', type=int)
    filter_year = request.args.get('year', type=int)
    query = Expense.query.filter(Expense.status != 'Voided').options(
        joinedload(Expense.category), joinedload(Expense.creator),
        joinedload(Expense.student), joinedload(Expense.company))
    if filter_category:
        query = query.filter_by(category_id=filter_category)
    today = date.today()
    year = filter_year or today.year
    month = filter_month if filter_month not in (None, 0) else None
    query = query.filter(db.extract('year', Expense.expense_date) == year)
    if month:
        query = query.filter(db.extract('month', Expense.expense_date) == month)
    all_expenses = query.order_by(Expense.expense_date.desc()).limit(FINANCE_LIST_LIMIT).all()
    expenses_total = query.order_by(None).count()
    categories = ExpenseCategory.query.order_by(ExpenseCategory.name).all()
    active_categories = [c for c in categories if c.is_active]
    totals_query = db.session.query(
        Expense.category_id, db.func.sum(Expense.amount).label('total')
    ).filter(Expense.status != 'Voided', db.extract('year', Expense.expense_date) == year)
    if month:
        totals_query = totals_query.filter(db.extract('month', Expense.expense_date) == month)
    totals_map = {cat_id: float(total) for cat_id, total in totals_query.group_by(Expense.category_id).all()}
    category_totals = [{
        "name": cat.name, "total": totals_map.get(cat.id, 0.0),
        "budget": cat.budget_limit,
        "over": bool(cat.budget_limit and totals_map.get(cat.id, 0.0) > cat.budget_limit),
    } for cat in categories]
    grand_total = sum(ct["total"] for ct in category_totals)
    period_label = f"{MONTH_NAMES[month-1]} {year}" if month else f"All months, {year}"
    students = Student.query.order_by(Student.name).all()
    student_outstanding = student_outstanding_bulk([s.id for s in students])
    return render_template('expenses.html', expenses=all_expenses,
        categories=active_categories, all_categories=categories,
        category_totals=category_totals, grand_total=grand_total, today=today,
        filter_category=filter_category, filter_month=filter_month,
        filter_year=year, period_label=period_label,
        account_balances=compute_account_summary(),
        expenses_total=expenses_total, list_limit=FINANCE_LIST_LIMIT,
        students=students, student_outstanding=student_outstanding,
        companies=Company.query.order_by(Company.name).all())

@expenses_bp.route('/expenses/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    expense = Expense.query.get_or_404(id)
    if expense.status == 'Voided':
        return _reject('Voided expenses cannot be edited.', 400)
    form = ExpenseForm(request.form)
    if not form.validate():
        if is_ajax_request():
            return jsonify({"success": False, "errors": form.error_messages}), 400
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('expenses.list'))
    category_id = form.cleaned_data.get('category_id')
    if ExpenseCategory.query.get(category_id) is None:
        return _reject("Selected category does not exist")
    expense.student_id, student_error = _parse_student_reference(request.form.get('student_id'))
    if student_error:
        return _reject(student_error)
    category_id, refund_error = _canonicalize_refund(category_id, expense.student_id)
    if refund_error:
        return _reject(refund_error)
    expense.category_id = category_id
    final_cat = ExpenseCategory.query.get(category_id)
    if final_cat and not final_cat.is_active:
        return _reject('Archived categories cannot be used for new expense postings.')
    expense.amount = form.cleaned_data.get('amount', 0)
    expense.description = request.form.get('description', '').strip()
    expense.payment_method = request.form.get('payment_method', 'Cash').strip()
    expense.expense_date = form.cleaned_data.get('expense_date', expense.expense_date)
    expense.payment_ref = _payment_ref(request.form.get('payment_ref'))
    # Company: empty = re-infer default; explicit id = honor it.
    explicit_company = _parse_company_id(request.form.get('company_id'))
    if explicit_company:
        expense.company_id = explicit_company
    elif request.form.get('company_id') == '':
        expense.company_id = _default_company_id(expense.payment_method, expense.student_id)
    att = _save_attachment(request)
    if isinstance(att[0], Exception):
        return _reject(str(att[0]))
    att_data, att_mime, att_name = att
    if att_data is not None:
        expense.attachment_data, expense.attachment_mime, expense.attachment_name = att_data, att_mime, att_name
    if request.form.get('remove_attachment'):
        expense.attachment_data = expense.attachment_mime = expense.attachment_name = None
    db.session.commit()
    message = "Expense updated successfully!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('expenses.list'))

@expenses_bp.route('/expenses/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete(id):
    expense = Expense.query.get_or_404(id)
    if expense.status == 'Voided':
        return _reject('This expense is already voided.', 400)
    if expense.payroll_records:
        message = ("This expense is linked to a paid payroll record. "
                   "Reverse the payroll record instead of deleting the expense.")
        if is_ajax_request():
            return jsonify({"success": False, "errors": [message]}), 409
        flash(message, "danger")
        return redirect(url_for('expenses.list'))
    expense.status = 'Voided'
    expense.voided_at = datetime.utcnow()
    expense.voided_by = current_user.id
    expense.void_reason = (request.form.get('reason') or 'Voided by administrator').strip()[:300]
    db.session.commit()
    message = "Expense voided. The original record remains available for audit."
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('expenses.list'))

@expenses_bp.route('/expenses/attachment/<int:id>')
@login_required
@admin_required
def attachment(id):
    expense = Expense.query.get_or_404(id)
    if not expense.attachment_data or not expense.attachment_mime:
        abort(404)
    name = (expense.attachment_name or 'receipt').replace('"', '')
    return Response(expense.attachment_data, mimetype=expense.attachment_mime,
                    headers={'Content-Disposition': f'inline; filename="{name}"'})

# ---------------------------------------------------------------------------
# Category management (add / rename / budget / archive)
# ---------------------------------------------------------------------------

def _reject_categories(message):
    flash(message, 'danger')
    return redirect(url_for('expenses.categories'))

@expenses_bp.route('/expenses/categories')
@login_required
@admin_required
def categories():
    cats = ExpenseCategory.query.order_by(ExpenseCategory.name).all()
    return render_template('expense_categories.html', cats=cats)

@expenses_bp.route('/expenses/categories/add', methods=['POST'])
@login_required
@admin_required
def categories_add():
    name = request.form.get('name', '').strip()
    if not name:
        return _reject_categories("Category name is required.")
    if len(name) > 100:
        return _reject_categories("Category name must be at most 100 characters.")
    existing = ExpenseCategory.query.filter(db.func.lower(ExpenseCategory.name) == name.lower()).first()
    if existing:
        return _reject_categories(f"Category '{name}' already exists.")
    budget = request.form.get('budget')
    try:
        budget = round(float(budget), 2) if budget else None
    except (TypeError, ValueError):
        budget = None
    cat = ExpenseCategory(name=name, description=(request.form.get('description') or '').strip() or None,
                          budget_limit=budget, is_active=True)
    db.session.add(cat)
    db.session.commit()
    flash(f"Category '{name}' added.", 'success')
    return redirect(url_for('expenses.categories'))

@expenses_bp.route('/expenses/categories/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def categories_edit(id):
    cat = ExpenseCategory.query.get_or_404(id)
    name = request.form.get('name', '').strip()
    if not name:
        return _reject_categories("Category name is required.")
    if len(name) > 100:
        return _reject_categories("Category name must be at most 100 characters.")
    if cat.name == 'Refund' and name.lower() != 'refund':
        return _reject_categories("The 'Refund' category cannot be renamed — refunds must stay canonical.")
    clash = ExpenseCategory.query.filter(
        db.func.lower(ExpenseCategory.name) == name.lower(),
        ExpenseCategory.id != cat.id).first()
    if clash:
        return _reject_categories(f"Category '{name}' already exists.")
    budget = request.form.get('budget')
    try:
        budget = round(float(budget), 2) if budget else None
    except (TypeError, ValueError):
        budget = None
    is_active = request.form.get('is_active') == '1'
    if cat.name == 'Refund' and not is_active:
        return _reject_categories("The 'Refund' category cannot be archived.")
    cat.name = name
    cat.description = (request.form.get('description') or '').strip() or None
    cat.budget_limit = budget
    cat.is_active = is_active
    db.session.commit()
    flash(f"Category '{name}' updated.", 'success')
    return redirect(url_for('expenses.categories'))

@expenses_bp.route('/salary-calculator', methods=['GET', 'POST'])
@login_required
@admin_required
def salary_calculator():
    tutors = Tutor.query.filter_by(status='Active').order_by(Tutor.name.asc()).all()
    selected_tutor_id = request.values.get('tutor_id', type=int)
    today = date.today()
    filter_type = request.values.get('filter_type', 'month')
    filter_month = request.values.get('month', default=today.month, type=int)
    filter_year = request.values.get('year', default=today.year, type=int)
    start_date_str = (request.values.get('start_date') or '').strip()
    end_date_str = (request.values.get('end_date') or '').strip()
    start_date = None
    end_date = None
    filter_error = None
    # B3: a custom range must be complete and ordered. Missing, unparsable or
    # reversed dates are rejected loudly instead of silently falling back to
    # the monthly view (which used to show numbers the admin did not ask for).
    if filter_type == 'range':
        if not start_date_str or not end_date_str:
            filter_error = 'Custom date range requires both a From and a To date.'
        else:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                filter_error = 'Invalid date values in the custom range.'
            else:
                if start_date > end_date:
                    filter_error = 'The From date cannot be after the To date.'
                    start_date = None
                    end_date = None
    if filter_error is None and not (start_date and end_date):
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
    breakdown = []
    projection = None
    if selected_tutor_id and filter_error is None:
        selected_tutor = Tutor.query.get(selected_tutor_id)
        if selected_tutor:
            if percentage is None:
                # B2/F5: single source of truth with compute_tutor_payroll() —
                # stored commission % from settings (0.0 when unset), never a
                # magic default the payroll run would not use.
                from app.helpers import tutor_commission_percentage
                percentage = tutor_commission_percentage(selected_tutor.id)
            # Clamp: a forged percentage must not mint absurd salaries (nor
            # negative ones). Settings form caps at 100 going forward; this
            # also covers legacy out-of-range rows.
            percentage = max(0.0, min(100.0, percentage))
            # B1/B5/F1: only active enrollments under this tutor, split over
            # ACTIVE tutors only, and fees attributed only when the enrollment
            # overlapped the payment date — all shared with payroll.
            from app.helpers import tutor_students, active_tutor_count_for_student, tutor_overlapping_fees
            students = tutor_students(selected_tutor.id)
            if students:
                fee_records = tutor_overlapping_fees(selected_tutor.id, start_date, end_date)
                fees_by_student = {}
                for record in fee_records:
                    fees_by_student[record.student_id] = fees_by_student.get(record.student_id, 0.0) + record.amount_paid
                total_collected = sum(fees_by_student.values())
                calculated_salary = total_collected * (percentage / 100.0)
                for student in students:
                    fees = fees_by_student.get(student.id, 0.0)
                    tutor_count = active_tutor_count_for_student(student.id)
                    if tutor_count == 0:
                        continue
                    if tutor_count > 1:
                        shared_students.append({'student': student, 'tutor_count': tutor_count})
                    split_collected += fees / tutor_count
                    if fees > 0:
                        # F3: per-student contribution breakdown (payroll E1 parity).
                        breakdown.append({
                            'student': student,
                            'roll_no': getattr(student, 'roll_no', None) or '',
                            'fees': fees,
                            'tutor_count': tutor_count,
                            'effective': fees / tutor_count,
                            'commission': fees / tutor_count * (percentage / 100.0),
                        })
                breakdown.sort(key=lambda b: (-b['commission'], b['student'].name.lower()))
                split_salary = split_collected * (percentage / 100.0)
            # F2: projected net pay using the tutor's payroll settings —
            # mirrors compute_tutor_payroll()'s clamping so the draft that the
            # 'Generate' action creates matches what is shown here.
            settings_row = TutorPayrollSettings.query.filter_by(tutor_id=selected_tutor.id).first()
            base = (settings_row.base_salary or 0.0) if settings_row else 0.0
            bonus = (settings_row.bonus or 0.0) if settings_row else 0.0
            tds_pct = (settings_row.tds_percentage or 0.0) if settings_row else 0.0
            other_ded = (settings_row.other_deductions or 0.0) if settings_row else 0.0
            gross = base + split_salary + bonus
            tds = gross * (tds_pct / 100.0) if tds_pct > 0 else 0.0
            other = min(other_ded, max(0.0, gross - tds)) if gross > 0 else 0.0
            projection = {'base': base, 'commission': split_salary, 'bonus': bonus,
                          'tds': tds, 'other': other, 'net': max(0.0, gross - tds - other),
                          'gross': gross, 'tds_pct': tds_pct, 'configured': settings_row is not None}
    if percentage is None:
        percentage = 0.0
    percentage = max(0.0, min(100.0, percentage))
    return render_template('salary_calculator.html', tutors=tutors, selected_tutor=selected_tutor,
        selected_tutor_id=selected_tutor_id, percentage=percentage, filter_type=filter_type,
        filter_month=filter_month, filter_year=filter_year, start_date=start_date, end_date=end_date,
        start_date_str=start_date_str, end_date_str=end_date_str, filter_error=filter_error,
        students=students, fee_records=fee_records, total_collected=total_collected,
        split_collected=split_collected, calculated_salary=calculated_salary,
        split_salary=split_salary, shared_students=shared_students, breakdown=breakdown,
        projection=projection, today=today)

@expenses_bp.route('/api/expenses/chart-data')
@login_required
@admin_required
def api_expenses_chart():
    year = request.args.get('year', type=int) or date.today().year
    monthly = db.session.query(
        db.extract('month', Expense.expense_date).label('m'),
        db.func.sum(Expense.amount).label('total')
    ).filter(db.extract('year', Expense.expense_date) == year).group_by(db.extract('month', Expense.expense_date)).all()
    month_map = {int(r.m): float(r.total) for r in monthly}
    months_data = [month_map.get(m, 0.0) for m in range(1, 13)]
    return jsonify({"months": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], "totals": months_data, "year": year})
