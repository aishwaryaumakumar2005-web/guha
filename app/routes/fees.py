from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import FeeRecord, Student, Course, SystemSetting, Tutor, student_courses, Company
from app.helpers import admin_required, get_gst_rates, is_ajax_request, FINANCE_LIST_LIMIT
from app.forms import FeeForm
from app.services.account_service import compute_account_summary, ensure_default_companies, company_bill_name
from sqlalchemy.orm import subqueryload

fees_bp = Blueprint('fees', __name__)

def _split_gst(amount, company):
    """Split an inclusive-of-tax amount into (taxable, gst) for `company`.

    Single source for the create + edit paths so both book identical splits.
    """
    if company and company.is_gst_registered:
        cgst_pct, sgst_pct = get_gst_rates()
        total_gst_pct = cgst_pct + sgst_pct
        taxable_amount = round(amount / (1 + (total_gst_pct / 100)), 2)
        gst_amount = round(amount - taxable_amount, 2)
    else:
        taxable_amount = amount
        gst_amount = 0.0
    return taxable_amount, gst_amount


def _course_company_id(course, gst_company_id, nongst_company_id):
    """Attribute a course to a billing company (mirrors the booking fallback)."""
    if course.company_id:
        return course.company_id
    return gst_company_id if course.gst_applicable else nongst_company_id


def _student_fee_summary(student):
    """Enrollment dues position for receipts: (due, cash_paid, concessions, balance).

    Informational context so a part-payment receipt states where the student
    stands; computed from current enrollment like the balances matrix.
    """
    if not student:
        return 0.0, 0.0, 0.0, 0.0
    cgst_pct, sgst_pct = get_gst_rates()
    total_pct = cgst_pct + sgst_pct
    taxable = sum(c.fees for c in student.courses)
    gst = sum(round(c.fees * total_pct / 100, 2) for c in student.courses if c.gst_applicable)
    due = taxable + gst
    paid = sum(r.amount_paid for r in student.fee_records)
    concessions = sum(r.concession or 0 for r in student.fee_records)
    return due, paid, concessions, due - paid - concessions


def _fee_record_in_company(record, company_id, company_is_gst):
    """Check a fee record against an active company filter.

    Legacy pre-company rows (company_id NULL) are attributed by GST profile,
    matching the booking rule that GST-applicable collections go through the
    GST-registered entity.
    """
    if company_id is None:
        return True
    if record.company_id:
        return record.company_id == company_id
    return bool(company_is_gst) == bool((record.gst_amount or 0) > 0)


def _stored_gst_split(record):
    """Reprint-safe (cgst, sgst) from the record's stored split.

    Splits the booked gst_amount evenly (CGST == SGST for intra-state
    supply) so cgst + sgst always equals the stored value, no matter what
    the current GST settings say. Reprints must never recompute history.
    """
    gst = float(record.gst_amount or 0)
    cgst = round(gst / 2, 2)
    return cgst, round(gst - cgst, 2)

@fees_bp.route('/fees', methods=['GET', 'POST'])
@login_required
def list():
    ensure_default_companies()
    companies = Company.query.filter_by(is_active=True).all()
    comp_map = {c.id: c for c in companies}
    
    # Handle POST (add fee) - only for admin
    if request.method == 'POST':
        if current_user.role != 'Admin':
            if is_ajax_request():
                return jsonify({"success": False, "errors": ["Only admins can add fee records"]}), 403
            flash("Only admins can add fee records", 'danger')
            return redirect(url_for('fees.list'))
        
        form = FeeForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('fees.list'))
        student_id = form.cleaned_data.get('student_id')
        if Student.query.get(student_id) is None:
            if is_ajax_request():
                return jsonify({"success": False, "errors": ["Selected student does not exist"]}), 400
            flash("Selected student does not exist", 'danger')
            return redirect(url_for('fees.list'))
        amount = form.cleaned_data.get('amount_paid', 0)
        # Waiver granted on this receipt: settles dues without cash movement.
        concession = form.cleaned_data.get('concession', 0) or 0
        remarks = request.form.get('remarks', '').strip()
        # FeeForm.choices already rejected anything outside PAYMENT_METHODS, so
        # the raw value is safe for ledger bucketing from here on.
        payment_method = request.form.get('payment_method') or 'UPI'
        payment_date = form.cleaned_data.get('payment_date', date.today())
        req_company_id = request.form.get('company_id')
        
        selected_company = None
        if req_company_id and req_company_id.isdigit():
            selected_company = Company.query.get(int(req_company_id))
        
        if not selected_company:
            student = Student.query.get(student_id)
            if student:
                # Prefer company directly assigned to one of the student's courses
                for c in student.courses:
                    if c.company_id:
                        selected_company = Company.query.get(c.company_id)
                        break
            # Final fallback: pick by GST flag on any enrolled course
            if not selected_company and student:
                if any(c.gst_applicable for c in student.courses):
                    selected_company = Company.query.filter_by(is_gst_registered=True).first()
                else:
                    selected_company = Company.query.filter_by(is_gst_registered=False).first() or Company.query.first()
        
        cgst_pct, sgst_pct = get_gst_rates()
        taxable_amount, gst_amount = _split_gst(amount, selected_company)

        new_record = FeeRecord(
            student_id=student_id,
            company_id=selected_company.id if selected_company else None,
            amount_paid=amount,
            taxable_amount=taxable_amount,
            gst_amount=gst_amount,
            payment_date=payment_date,
            payment_method=payment_method,
            remarks=remarks,
            concession=concession,
            created_by=current_user.id
        )
        db.session.add(new_record)
        db.session.flush()

        prefix = selected_company.invoice_prefix if selected_company else 'INV/'
        new_record.receipt_number = f"{prefix}{new_record.payment_date.strftime('%Y%m')}-{new_record.id:04d}"
        db.session.commit()

        message = "Payment recorded successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message, "receipt_id": new_record.id}), 201
        flash(message, "success")
        return redirect(url_for('fees.list'))
    
    # GET request - filter based on user role
    company_filter = request.args.get('company_id')
    company_id = int(company_filter) if company_filter and company_filter.isdigit() else None

    query = FeeRecord.query

    if company_id:
        query = query.filter(FeeRecord.company_id == company_id)

    selected_company = comp_map.get(company_id) if company_id else None
    gst_company_id = next((c.id for c in companies if c.is_gst_registered), None)
    nongst_company_id = next((c.id for c in companies if not c.is_gst_registered), None)

    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            course_ids = [c.id for c in tutor.courses]
            student_subquery = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids)
            ).distinct()
            all_students = Student.query.options(subqueryload(Student.courses)).filter(Student.id.in_(student_subquery), Student.status == 'Active').all()
            student_ids = [s.id for s in all_students]
            scoped = query.filter(FeeRecord.student_id.in_(student_ids))
            history_total = scoped.order_by(None).count()
            all_records = scoped.order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).limit(FINANCE_LIST_LIMIT).all()
        else:
            all_students = []
            all_records = []
            history_total = 0
    else:
        history_total = query.order_by(None).count()
        all_records = query.options(subqueryload(FeeRecord.student).subqueryload(Student.courses), subqueryload(FeeRecord.company)).order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).limit(FINANCE_LIST_LIMIT).all()
        all_students = Student.query.options(subqueryload(Student.courses)).filter_by(status='Active').all()

    cgst_pct, sgst_pct = get_gst_rates()
    total_gst_pct = cgst_pct + sgst_pct
    selected_is_gst = bool(selected_company.is_gst_registered) if selected_company else False
    student_balances = []
    for student in Student.query.options(subqueryload(Student.courses), subqueryload(Student.fee_records)).filter(Student.id.in_([s.id for s in all_students])).all():
        courses = student.courses
        if company_id:
            # The matrix must agree with the filtered history above: only
            # dues billed through the selected entity count here.
            courses = [c for c in courses
                       if _course_company_id(c, gst_company_id, nongst_company_id) == company_id]
        total_taxable = sum(c.fees for c in courses)
        gst_amount = sum(
            round(c.fees * total_gst_pct / 100, 2)
            for c in courses if c.gst_applicable
        )
        total_fee = total_taxable + gst_amount
        in_scope = [r for r in student.fee_records
                    if _fee_record_in_company(r, company_id, selected_is_gst)]
        total_paid = sum(r.amount_paid for r in in_scope)
        total_concession = sum(r.concession or 0 for r in in_scope)
        balance = total_fee - total_paid - total_concession
        overpaid = total_paid > total_fee
        # Aging: days since enrollment while anything is still owed. No extra
        # schema — enrollment_date is the dues clock.
        days_due = 0
        if balance > 0 and student.enrollment_date:
            days_due = max(0, (date.today() - student.enrollment_date).days)
        student_balances.append({
            "student": student, "total_fee": total_fee, "total_taxable": total_taxable,
            "total_paid": total_paid, "total_concession": total_concession,
            "balance": balance, "overpaid": overpaid,
            "credit": round(total_paid - total_fee, 2) if overpaid else 0.0,
            "days_due": days_due,
            "gst_amount": gst_amount, "gst_applicable": any(c.gst_applicable for c in courses)
        })
    # U2: per-student billing-entity default for the record-payment modal, so
    # the company select follows the student instead of always opening on GST.
    default_company = {}
    for s in all_students:
        cid = None
        for c in s.courses:
            if c.company_id:
                cid = c.company_id
                break
        if not cid:
            cid = gst_company_id if any(c.gst_applicable for c in s.courses) else nongst_company_id
        if cid:
            default_company[s.id] = cid
    return render_template(
        'fees.html', records=all_records, students=all_students, balances=student_balances,
        companies=companies, selected_company_id=company_id,
        selected_company=selected_company, default_company=default_company,
        history_total=history_total, list_limit=FINANCE_LIST_LIMIT,
        today=date.today(), is_staff=(current_user.role == 'Staff'),
        account_balances=(compute_account_summary() if current_user.role == 'Admin' else [])
    )

@fees_bp.route('/fees/receipt/<int:id>')
@login_required
def receipt(id):
    record = FeeRecord.query.get_or_404(id)
    if current_user.role == 'Staff':
        # Same course-scope as the list page: staff may only reprint
        # receipts for students in their own courses. 404 (not 403) to
        # avoid confirming whether an out-of-scope receipt id exists.
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        allowed = set()
        if tutor:
            course_ids = [c.id for c in tutor.courses]
            if course_ids:
                allowed = {r[0] for r in db.session.query(
                    student_courses.c.student_id).filter(
                        student_courses.c.course_id.in_(course_ids)).distinct().all()}
        if record.student_id not in allowed:
            abort(404)
    cgst_pct, sgst_pct = get_gst_rates()
    
    company = record.company
    if not company and record.student:
        if any(c.gst_applicable for c in record.student.courses):
            company = Company.query.filter_by(is_gst_registered=True).first()
        else:
            company = Company.query.filter_by(is_gst_registered=False).first()
    
    
    cgst_val = round((record.taxable_amount or (record.amount_paid / 1.18)) * (cgst_pct / 100), 2) if company and company.is_gst_registered else 0.0
    sgst_val = round((record.taxable_amount or (record.amount_paid / 1.18)) * (sgst_pct / 100), 2) if company and company.is_gst_registered else 0.0
    # Reprints use the stored split — never recompute history from current rates.
    stored_taxable = float(record.taxable_amount or 0)
    if company and company.is_gst_registered and stored_taxable:
        taxable_val = stored_taxable
        cgst_val, sgst_val = _stored_gst_split(record)
    else:
        taxable_val = record.taxable_amount or (record.amount_paid / 1.18)

    due_total, paid_total, concessions_total, balance_due = _student_fee_summary(record.student)
    course_names = ', '.join(f"{c.name} ({c.code})" for c in record.student.courses) if record.student and record.student.courses else ''

    return render_template(
        'partials/_receipt_modal.html',
        record=record,
        company=company,
        bill_name=company_bill_name(company) if company else None,
        cgst_pct=cgst_pct,
        sgst_pct=sgst_pct,
        cgst_val=cgst_val,
        sgst_val=sgst_val,
        taxable_val=taxable_val,
        due_total=due_total,
        paid_total=paid_total,
        concessions_total=concessions_total,
        balance_due=balance_due,
        course_names=course_names
    )

@fees_bp.route('/fees/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    record = FeeRecord.query.get_or_404(id)
    form = FeeForm(request.form)
    if not form.validate():
        if is_ajax_request():
            return jsonify({"success": False, "errors": form.error_messages}), 400
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('fees.list'))
    student_id = form.cleaned_data.get('student_id')
    if Student.query.get(student_id) is None:
        if is_ajax_request():
            return jsonify({"success": False, "errors": ["Selected student does not exist"]}), 400
        flash("Selected student does not exist", 'danger')
        return redirect(url_for('fees.list'))
    amount = form.cleaned_data.get('amount_paid', 0)
    payment_date = form.cleaned_data.get('payment_date', record.payment_date)
    concession = form.cleaned_data.get('concession', 0) or 0
    # FeeForm.choices already validated this value (see create path).
    payment_method = request.form.get('payment_method') or record.payment_method
    remarks = request.form.get('remarks', '').strip()
    company = record.company
    req_company_id = request.form.get('company_id')
    if req_company_id and req_company_id.isdigit():
        found = Company.query.get(int(req_company_id))
        if found:
            company = found
    taxable_amount, gst_amount = _split_gst(amount, company)
    record.student_id = student_id
    record.company_id = company.id if company else None
    record.amount_paid = amount
    record.taxable_amount = taxable_amount
    record.gst_amount = gst_amount
    record.payment_date = payment_date
    record.payment_method = payment_method
    record.remarks = remarks
    record.concession = concession
    # receipt_number is intentionally preserved: an edit corrects the booking,
    # it must not burn a new invoice number. The UPDATE is auto-audited.
    db.session.commit()
    message = "Fee record updated successfully!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('fees.list'))

@fees_bp.route('/fees/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete(id):
    fee = FeeRecord.query.get_or_404(id)
    db.session.delete(fee)
    db.session.commit()
    message = "Fee transaction record removed!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('fees.list'))

