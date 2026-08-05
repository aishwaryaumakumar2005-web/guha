from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import FeeRecord, Student, Course, SystemSetting, Tutor, student_courses, Company
from app.helpers import admin_required, is_ajax_request
from app.forms import FeeForm
from app.services.account_service import compute_account_summary, ensure_default_companies
from sqlalchemy.orm import subqueryload

fees_bp = Blueprint('fees', __name__)

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
        amount = form.cleaned_data.get('amount_paid', 0)
        remarks = request.form.get('remarks', '').strip()
        payment_method = request.form.get('payment_method', 'UPI')
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
        
        cgst_pct = float((SystemSetting.query.filter_by(key='CGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='CGST_PCT').first() else 9.0
        sgst_pct = float((SystemSetting.query.filter_by(key='SGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='SGST_PCT').first() else 9.0
        total_gst_pct = cgst_pct + sgst_pct

        if selected_company and selected_company.is_gst_registered:
            taxable_amount = round(amount / (1 + (total_gst_pct / 100)), 2)
            gst_amount = round(amount - taxable_amount, 2)
        else:
            taxable_amount = amount
            gst_amount = 0.0

        new_record = FeeRecord(
            student_id=student_id,
            company_id=selected_company.id if selected_company else None,
            amount_paid=amount,
            taxable_amount=taxable_amount,
            gst_amount=gst_amount,
            payment_date=payment_date,
            payment_method=payment_method,
            remarks=remarks
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
    query = FeeRecord.query

    if company_filter and company_filter.isdigit():
        query = query.filter(FeeRecord.company_id == int(company_filter))

    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            course_ids = [c.id for c in tutor.courses]
            student_subquery = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids)
            ).distinct()
            all_students = Student.query.filter(Student.id.in_(student_subquery), Student.status == 'Active').all()
            student_ids = [s.id for s in all_students]
            all_records = query.filter(FeeRecord.student_id.in_(student_ids)).order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).all()
        else:
            all_students = []
            all_records = []
    else:
        all_records = query.order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).all()
        all_students = Student.query.filter_by(status='Active').all()
    
    cgst_pct = float((SystemSetting.query.filter_by(key='CGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='CGST_PCT').first() else 9.0
    sgst_pct = float((SystemSetting.query.filter_by(key='SGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='SGST_PCT').first() else 9.0
    total_gst_pct = cgst_pct + sgst_pct
    student_balances = []
    for student in Student.query.options(subqueryload(Student.courses), subqueryload(Student.fee_records)).filter(Student.id.in_([s.id for s in all_students])).all():
        total_taxable = sum(c.fees for c in student.courses)
        gst_amount = sum(
            round(c.fees * total_gst_pct / 100, 2)
            for c in student.courses if c.gst_applicable
        )
        total_fee = total_taxable + gst_amount
        total_paid = sum(r.amount_paid for r in student.fee_records)
        balance = total_fee - total_paid
        student_balances.append({
            "student": student, "total_fee": total_fee, "total_taxable": total_taxable,
            "total_paid": total_paid, "balance": balance,
            "gst_amount": gst_amount, "gst_applicable": any(c.gst_applicable for c in student.courses)
        })
    return render_template(
        'fees.html', records=all_records, students=all_students, balances=student_balances,
        companies=companies, selected_company_id=int(company_filter) if company_filter and company_filter.isdigit() else None,
        today=date.today(), is_staff=(current_user.role == 'Staff'),
        account_balances=(compute_account_summary() if current_user.role == 'Admin' else [])
    )

@fees_bp.route('/fees/receipt/<int:id>')
@login_required
def receipt(id):
    record = FeeRecord.query.get_or_404(id)
    cgst_pct = float((SystemSetting.query.filter_by(key='CGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='CGST_PCT').first() else 9.0
    sgst_pct = float((SystemSetting.query.filter_by(key='SGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='SGST_PCT').first() else 9.0
    
    company = record.company
    if not company and record.student:
        if any(c.gst_applicable for c in record.student.courses):
            company = Company.query.filter_by(is_gst_registered=True).first()
        else:
            company = Company.query.filter_by(is_gst_registered=False).first()
    
    cgst_val = round((record.taxable_amount or (record.amount_paid / 1.18)) * (cgst_pct / 100), 2) if company and company.is_gst_registered else 0.0
    sgst_val = round((record.taxable_amount or (record.amount_paid / 1.18)) * (sgst_pct / 100), 2) if company and company.is_gst_registered else 0.0

    return render_template(
        'partials/_receipt_modal.html',
        record=record,
        company=company,
        cgst_pct=cgst_pct,
        sgst_pct=sgst_pct,
        cgst_val=cgst_val,
        sgst_val=sgst_val
    )

@fees_bp.route('/fees/delete/<int:id>')
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

