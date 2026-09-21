from datetime import date
from io import BytesIO
from flask import Blueprint, current_app, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models import FeeRecord, Student, Tutor, student_courses
from app.helpers import admin_required

accounting_bp = Blueprint('accounting', __name__)

@accounting_bp.route('/fees/invoice/<int:fee_id>')
@login_required
def download_invoice(fee_id):
    fee_record = FeeRecord.query.filter(FeeRecord.status != 'Voided').get_or_404(fee_id)
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        allowed = set()
        if tutor:
            course_ids = [course.id for course in tutor.courses]
            if course_ids:
                allowed = {row[0] for row in db.session.query(
                    student_courses.c.student_id
                ).filter(student_courses.c.course_id.in_(course_ids)).distinct().all()}
        if fee_record.student_id not in allowed:
            # Do not disclose whether an out-of-scope receipt exists.
            from flask import abort
            abort(404)
    elif current_user.role != 'Admin':
        from flask import abort
        abort(403)
    buf, inv_no = current_app.accounting.generate_invoice_pdf(fee_record)
    student = fee_record.student
    return send_file(buf, mimetype='application/pdf',
        as_attachment=True,
        download_name=f'invoice_{inv_no}_{(student.name or "student").replace(" ", "_")}.pdf')

@accounting_bp.route('/fees/export/tally')
@login_required
@admin_required
def export_tally():
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    company_id = request.args.get('company_id')
    query = FeeRecord.query.filter(FeeRecord.status != 'Voided')
    if company_id and company_id.isdigit():
        query = query.filter(FeeRecord.company_id == int(company_id))
    if from_date:
        from datetime import datetime
        query = query.filter(FeeRecord.payment_date >= datetime.strptime(from_date, '%Y-%m-%d').date())
    if to_date:
        from datetime import datetime
        query = query.filter(FeeRecord.payment_date <= datetime.strptime(to_date, '%Y-%m-%d').date())
    records = query.order_by(FeeRecord.payment_date).all()
    if not records:
        flash("No fee records found for selected period.", "warning")
        return redirect(url_for('fees.list'))
    xml_data = current_app.accounting.generate_tally_xml(records)
    return send_file(BytesIO(xml_data), mimetype='application/xml',
        as_attachment=True,
        download_name=f'tally_fees_{date.today().strftime("%Y%m%d")}.xml')

@accounting_bp.route('/fees/export/zoho')
@login_required
@admin_required
def export_zoho():
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    company_id = request.args.get('company_id')
    query = FeeRecord.query.filter(FeeRecord.status != 'Voided')
    if company_id and company_id.isdigit():
        query = query.filter(FeeRecord.company_id == int(company_id))
    if from_date:
        from datetime import datetime
        query = query.filter(FeeRecord.payment_date >= datetime.strptime(from_date, '%Y-%m-%d').date())
    if to_date:
        from datetime import datetime
        query = query.filter(FeeRecord.payment_date <= datetime.strptime(to_date, '%Y-%m-%d').date())
    records = query.order_by(FeeRecord.payment_date).all()
    if not records:
        flash("No fee records found for selected period.", "warning")
        return redirect(url_for('fees.list'))
    csv_data = current_app.accounting.generate_zoho_csv(records)
    return send_file(BytesIO(csv_data), mimetype='text/csv',
        as_attachment=True,
        download_name=f'zoho_fees_{date.today().strftime("%Y%m%d")}.csv')
