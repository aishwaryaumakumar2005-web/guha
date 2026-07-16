from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import FeeRecord, Student, Course, SystemSetting, Tutor, student_courses
from app.helpers import admin_required, is_ajax_request
from app.forms import FeeForm
from sqlalchemy.orm import subqueryload

fees_bp = Blueprint('fees', __name__)

@fees_bp.route('/fees', methods=['GET', 'POST'])
@login_required
def list():
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
        new_record = FeeRecord(
            student_id=student_id, amount_paid=amount, payment_date=payment_date,
            payment_method=payment_method, remarks=remarks
        )
        db.session.add(new_record)
        db.session.commit()
        message = "Payment recorded successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('fees.list'))
    
    # GET request - filter based on user role
    if current_user.role == 'Staff':
        # Staff: show fee records for their students only
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            course_ids = [c.id for c in tutor.courses]
            student_subquery = db.session.query(student_courses.c.student_id).filter(
                student_courses.c.course_id.in_(course_ids)
            ).distinct()
            all_students = Student.query.filter(Student.id.in_(student_subquery), Student.status == 'Active').all()
            student_ids = [s.id for s in all_students]
            all_records = FeeRecord.query.filter(FeeRecord.student_id.in_(student_ids)).order_by(FeeRecord.payment_date.desc()).all()
        else:
            all_students = []
            all_records = []
    else:
        all_records = FeeRecord.query.order_by(FeeRecord.payment_date.desc()).all()
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
    return render_template('fees.html', records=all_records, students=all_students, balances=student_balances, today=date.today(), is_staff=(current_user.role == 'Staff'))

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
