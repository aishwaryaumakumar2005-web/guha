from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, current_app
import os
from flask_login import login_required, current_user
from app.extensions import db
from app.models import FeeRecord, Student, Course, SystemSetting, Tutor, student_courses, Company
from app.helpers import admin_required, get_gst_rates, is_ajax_request, FINANCE_LIST_LIMIT
from app.forms import FeeForm
from app.services.account_service import compute_account_summary, ensure_default_companies, company_bill_name, agreed_enrollment_items, agreed_enrollment_items_bulk, snapshot_company_id, student_refunded_total, student_refunded_totals_bulk
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


def _parse_iso_date(raw):
    """Parse an optional YYYY-MM-DD filter param; malformed values are ignored."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _student_fee_summary(student, company=None):
    """Enrollment dues position for receipts: (due, cash_paid, concessions, balance).

    When `company` is given, dues are scoped to that entity — mirroring the
    B3 matrix rule (assigned courses + GST-profile legacy attribution) — so a
    receipt's footer agrees with the filtered matrix instead of mixing
    entities. Without it, the position is institute-global.
    W2: dues use the agreed-at-enrollment snapshot, not live catalog prices.
    W3: refunds (Expenses linked to the student) reduce what counts as paid,
    so a refunded-overpayment flips back to a real balance instead of
    lingering as a credit.
    """
    if not student:
        return 0.0, 0.0, 0.0, 0.0
    cgst_pct, sgst_pct = get_gst_rates()
    total_pct = cgst_pct + sgst_pct
    items = agreed_enrollment_items(student.id)
    records = [r for r in student.fee_records]
    if company is not None:
        items = [it for it in items
                 if (it['company_id'] or None) == company.id
                 or (not it['company_id'] and bool(it['gst_applicable']) == bool(company.is_gst_registered))]
        records = [r for r in records
                   if _fee_record_in_company(r, company.id, company.is_gst_registered)]
    taxable = round(sum(it['fee'] for it in items), 2)
    gst = round(sum(round(it['fee'] * total_pct / 100, 2) for it in items if it['gst_applicable']), 2)
    due = round(taxable + gst, 2)
    paid = round(sum(r.amount_paid for r in records), 2)
    concessions = round(sum(r.concession or 0 for r in records), 2)
    refunded = student_refunded_total(student.id)
    return due, paid, concessions, round(due - paid - concessions + refunded, 2)


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
                # Prefer company directly assigned to one of the student's
                # enrollments (snapshot-aware).
                for it in agreed_enrollment_items(student.id):
                    if it['company_id']:
                        selected_company = Company.query.get(it['company_id'])
                        break
            # Final fallback: pick by GST flag on any enrolled course
            if not selected_company and student:
                if any(it['gst_applicable'] for it in agreed_enrollment_items(student.id)):
                    selected_company = Company.query.filter_by(is_gst_registered=True).first()
                else:
                    selected_company = Company.query.filter_by(is_gst_registered=False).first() or Company.query.first()
        
        cgst_pct, sgst_pct = get_gst_rates()
        taxable_amount, gst_amount = _split_gst(amount, selected_company)

        duplicate = FeeRecord.query.filter(
            FeeRecord.status != 'Voided', FeeRecord.student_id == student_id,
            FeeRecord.amount_paid == amount, FeeRecord.payment_date == payment_date,
            FeeRecord.payment_method == payment_method,
        ).first()
        if duplicate and request.form.get('confirm_duplicate') != '1':
            message = 'A matching active payment already exists for this student, amount, date and method.'
            if is_ajax_request():
                return jsonify({"success": False, "duplicate": True, "message": message}), 409
            flash(message + ' Confirm it is not a duplicate before recording again.', 'warning')
            return redirect(url_for('fees.list'))

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

    # Single-student view (dashboard outstanding rows deep-link here).
    student_filter = request.args.get('student_id')
    student_filter_id = int(student_filter) if student_filter and student_filter.isdigit() else None

    query = FeeRecord.query.filter(FeeRecord.status != 'Voided')

    if company_id:
        query = query.filter(FeeRecord.company_id == company_id)
    if student_filter_id:
        query = query.filter(FeeRecord.student_id == student_filter_id)

    # B12: real date-range filter on the payment history (replaces the dead
    # dateRangeFilterContainer div). Dues matrix below stays all-time.
    from_date = _parse_iso_date(request.args.get('from_date'))
    to_date = _parse_iso_date(request.args.get('to_date'))
    if from_date:
        query = query.filter(FeeRecord.payment_date >= from_date)
    if to_date:
        query = query.filter(FeeRecord.payment_date <= to_date)

    selected_company = comp_map.get(company_id) if company_id else None
    gst_company_id = next((c.id for c in companies if c.is_gst_registered), None)
    nongst_company_id = next((c.id for c in companies if not c.is_gst_registered), None)

    student_ids = None
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            course_ids = [c.id for c in tutor.courses]
            student_subquery = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids)
            ).distinct()
            all_students = Student.query.options(subqueryload(Student.courses)).filter(Student.id.in_(student_subquery), Student.status == 'Active').all()
            if student_filter_id:
                all_students = [s for s in all_students if s.id == student_filter_id]
            student_ids = [s.id for s in all_students]
            scoped = query.filter(FeeRecord.student_id.in_(student_ids))
            history_total = scoped.order_by(None).count()
            all_records = scoped.order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).all()
        else:
            all_students = []
            all_records = []
            history_total = 0
            student_ids = []
    else:
        history_total = query.order_by(None).count()
        all_records = query.options(subqueryload(FeeRecord.student).subqueryload(Student.courses), subqueryload(FeeRecord.company)).order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).all()
        students_q = Student.query.options(subqueryload(Student.courses)).filter_by(status='Active')
        if student_filter_id:
            students_q = students_q.filter(Student.id == student_filter_id)
        all_students = students_q.all()

    cgst_pct, sgst_pct = get_gst_rates()
    total_gst_pct = cgst_pct + sgst_pct
    selected_is_gst = bool(selected_company.is_gst_registered) if selected_company else False
    student_balances = []
    student_objs = Student.query.options(subqueryload(Student.courses), subqueryload(Student.fee_records)).filter(Student.id.in_([s.id for s in all_students])).all()
    # W2 batched agreed-dues snapshot: one pair of queries for the whole page.
    agreed_map = agreed_enrollment_items_bulk([s.id for s in student_objs])
    # Adding refunded totals
    refunded_map = student_refunded_totals_bulk([s.id for s in student_objs])
    for student in student_objs:
        # W2: dues are agreed at enrollment, not live catalog prices. Catalog
        # edits affect new enrollments only.
        items = agreed_map.get(student.id, [])
        if company_id:
            # The matrix must agree with the filtered history above: only
            # dues billed through the selected entity count here.
            items = [it for it in items
                     if snapshot_company_id(it, gst_company_id, nongst_company_id) == company_id]
        total_taxable = round(sum(it['fee'] for it in items), 2)
        gst_amount = round(sum(
            round(it['fee'] * total_gst_pct / 100, 2)
            for it in items if it['gst_applicable']
        ), 2)
        total_fee = round(total_taxable + gst_amount, 2)
        in_scope = [r for r in student.fee_records
                    if _fee_record_in_company(r, company_id, selected_is_gst)]
        # Round every float aggregate: sums of 2dp floats can drift a cent,
        # which is enough to flip Paid In Full to Partial Dues.
        total_paid = round(sum(r.amount_paid for r in in_scope), 2)
        total_concession = round(sum(r.concession or 0 for r in in_scope), 2)
        # W3: refunds (Expenses linked to the student) reduce what has been
        # collected. Net collected = cash in - cash back; balance accounts for
        # both sides of the ledger.
        total_refunded = refunded_map.get(student.id, 0.0)
        balance = round(total_fee - total_paid - total_concession + total_refunded, 2)
        net_collected = round(total_paid - total_refunded, 2)
        overpaid = net_collected > total_fee
        # Aging: days since enrollment while anything is still owed. No extra
        # schema — enrollment_date is the dues clock.
        days_due = 0
        if balance > 0 and student.enrollment_date:
            days_due = max(0, (date.today() - student.enrollment_date).days)
        student_balances.append({
            "student": student, "total_fee": total_fee, "total_taxable": total_taxable,
            "total_paid": total_paid, "total_concession": total_concession,
            "total_refunded": total_refunded,
            "balance": balance, "overpaid": overpaid,
            "credit": round(net_collected - total_fee, 2) if overpaid else 0.0,
            "days_due": days_due,
            "gst_amount": gst_amount, "gst_applicable": any(it['gst_applicable'] for it in items)
        })
    # U2: per-student billing-entity default for the record-payment modal, so
    # the company select follows the student instead of always opening on GST.
    default_company = {}
    for s in all_students:
        items = agreed_map.get(s.id, [])
        cid = next((it['company_id'] for it in items if it['company_id']), None)
        if not cid:
            cid = gst_company_id if any(it['gst_applicable'] for it in items) else nongst_company_id
        if cid:
            default_company[s.id] = cid
    # U7: collection KPI strip. Month intake respects the company filter (and
    # staff scope); dues aggregates come from the (equally scoped) matrix.
    today = date.today()
    month_start = date(today.year, today.month, 1)
    month_q = FeeRecord.query.filter(FeeRecord.status != 'Voided', FeeRecord.payment_date >= month_start)
    if from_date:
        month_q = month_q.filter(FeeRecord.payment_date >= from_date)
    if to_date:
        month_q = month_q.filter(FeeRecord.payment_date <= to_date)
    if company_id:
        month_q = month_q.filter(FeeRecord.company_id == company_id)
    if student_ids is not None:
        month_q = month_q.filter(FeeRecord.student_id.in_(student_ids))
    kpi_month = round(month_q.with_entities(db.func.sum(FeeRecord.amount_paid)).scalar() or 0.0, 2)
    kpi_due = round(sum(b['total_fee'] for b in student_balances), 2)
    # W3: collection KPIs are NET of refunds — cash handed back can't inflate
    # the collection rate or the "settled" figure.
    kpi_cash = round(sum(b['total_paid'] - b['total_refunded'] for b in student_balances), 2)
    kpi_settled = round(sum(b['total_paid'] + b['total_concession'] - b['total_refunded'] for b in student_balances), 2)
    kpi = {
        'month_collected': kpi_month,
        'outstanding': round(sum(b['balance'] for b in student_balances if b['balance'] > 0), 2),
        # W5: the headline rate is cash actually collected; waivers are shown
        # separately so forgiveness can never masquerade as collection.
        'collection_pct': round(kpi_cash / kpi_due * 100, 1) if kpi_due else 0.0,
        'settled_pct': round(kpi_settled / kpi_due * 100, 1) if kpi_due else 0.0,
        'receipts': history_total,
    }
    return render_template(
        'fees.html', records=all_records, students=all_students, balances=student_balances,
        companies=companies, selected_company_id=company_id,
        selected_company=selected_company, default_company=default_company,
        history_total=history_total, list_limit=history_total,
        from_date=from_date.isoformat() if from_date else '',
        to_date=to_date.isoformat() if to_date else '',
        kpi=kpi,
        today=today, is_staff=(current_user.role == 'Staff'),
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
        if any(it['gst_applicable'] for it in agreed_enrollment_items(record.student.id)):
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

    due_total, paid_total, concessions_total, balance_due = _student_fee_summary(record.student, company)
    course_names = ', '.join(f"{c.name} ({c.code})" for c in record.student.courses) if record.student and record.student.courses else ''
    discount_details = []
    if record.student:
        enrollment_rows = db.session.query(student_courses).filter(
            student_courses.c.student_id == record.student.id
        ).all()
        course_map = {c.id: c for c in record.student.courses}
        for enrollment in enrollment_rows:
            if enrollment.discount_type and (enrollment.discount_amount or 0) > 0:
                course = course_map.get(enrollment.course_id)
                discount_details.append({
                    'course_name': course.name if course else 'Course fee',
                    'discount_type': enrollment.discount_type,
                    'discount_value': enrollment.discount_value or 0,
                    'discount_amount': enrollment.discount_amount or 0,
                    'net_fee': enrollment.net_fee or enrollment.agreed_fee or 0,
                    'gst_amount': enrollment.gst_amount or 0,
                    'final_fee': enrollment.final_fee or 0,
                })

    # U8: receipt furniture comes from settings/company, never literals.
    accounting = getattr(current_app, 'accounting', None)
    org = accounting._get_settings() if accounting else {}
    place_of_supply = f"{org.get('org_state') or 'Tamil Nadu'} ({org.get('org_state_code') or '33'})"
    logo_file = os.path.join(current_app.static_folder or '', 'uploads', 'yazh_academy_logo.png')
    logo_url = url_for('static', filename='uploads/yazh_academy_logo.png') if os.path.exists(logo_file) else None

    return render_template(
        'partials/_receipt_modal.html',
        record=record,
        company=company,
        bill_name=company_bill_name(company) if company else None,
        cgst_pct=cgst_pct,
        sgst_pct=sgst_pct,
        cgst_val=cgst_val,
        sgst_val=sgst_val,
        taxable_val=taxable_val, discount_details=discount_details,
        due_total=due_total,
        paid_total=paid_total,
        concessions_total=concessions_total,
        balance_due=balance_due,
        course_names=course_names,
        org_address=org.get('org_address') or '',
        org_phone=org.get('org_mobile') or '',
        org_email=org.get('org_email') or '',
        org_gstin=org.get('org_gstin') or '',
        place_of_supply=place_of_supply,
        logo_url=logo_url
    )

@fees_bp.route('/fees/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    record = FeeRecord.query.get_or_404(id)
    if record.status == 'Voided':
        message = 'Voided fee transactions cannot be edited.'
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, 'danger')
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
    if fee.status == 'Voided':
        message = 'This fee transaction is already voided.'
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, 'warning')
        return redirect(url_for('fees.list'))
    reason = (request.form.get('reason') or request.form.get('remarks') or '').strip()
    if not reason:
        reason = 'Voided by administrator'
    fee.status = 'Voided'
    fee.voided_at = datetime.utcnow()
    fee.voided_by = current_user.id
    fee.void_reason = reason[:300]
    db.session.commit()
    message = "Fee transaction voided. The original record remains available for audit."
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('fees.list'))
