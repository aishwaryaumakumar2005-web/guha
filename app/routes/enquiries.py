from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models import Enquiry, Course, Student
from app.helpers import admin_required, is_ajax_request
from app.forms import EnquiryForm

enquiries_bp = Blueprint('enquiries', __name__)

@enquiries_bp.route('/enquiries', methods=['GET', 'POST'])
@login_required
@admin_required
def list():
    if request.method == 'POST':
        form = EnquiryForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('enquiries.list'))
        student_name = form.data.get('student_name', '').strip()
        email = form.data.get('email', '').strip()
        phone = form.data.get('phone', '').strip()
        course_id = form.cleaned_data.get('course_id')
        source = request.form.get('source', 'Walk-in')
        enquiry_status = request.form.get('status', 'New')
        notes = request.form.get('notes', '').strip()
        new_enq = Enquiry(
            student_name=student_name, email=email, phone=phone,
            course_id=course_id, source=source, status=enquiry_status, notes=notes
        )
        db.session.add(new_enq)
        db.session.commit()
        message = "Enquiry submitted successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('enquiries.list'))
    all_enquiries = Enquiry.query.all()
    all_courses = Course.query.all()
    return render_template('enquiries.html', enquiries=all_enquiries, courses=all_courses)

@enquiries_bp.route('/enquiries/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    enquiry = Enquiry.query.get_or_404(id)
    form = EnquiryForm(request.form)
    if not form.validate():
        if is_ajax_request():
            return jsonify({"success": False, "errors": form.error_messages}), 400
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('enquiries.list'))
    enquiry.student_name = form.data.get('student_name', '').strip()
    enquiry.email = form.data.get('email', '').strip()
    enquiry.phone = form.data.get('phone', '').strip()
    enquiry.course_id = form.cleaned_data.get('course_id')
    enquiry.source = request.form.get('source', 'Walk-in')
    enquiry.status = request.form.get('status', 'New')
    enquiry.notes = request.form.get('notes', '').strip()
    db.session.commit()
    message = "Enquiry details updated!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('enquiries.list'))

@enquiries_bp.route('/enquiries/convert/<int:id>', methods=['POST'])
@login_required
@admin_required
def convert(id):
    enquiry = Enquiry.query.get_or_404(id)
    student_exists = Student.query.filter_by(email=enquiry.email).first()
    if student_exists:
        message = f"Student with email '{enquiry.email}' is already enrolled!"
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "warning")
    else:
        new_student = Student(name=enquiry.student_name, email=enquiry.email, phone=enquiry.phone, status='Active')
        course = Course.query.get(enquiry.course_id)
        if course:
            new_student.courses.append(course)
        db.session.add(new_student)
        enquiry.status = 'Converted'
        db.session.commit()
        message = f"Enquiry successfully converted! {new_student.name} is now enrolled."
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
    return redirect(url_for('students.list'))

ENQUIRY_STAGES = ['New', 'Contacted', 'Visited', 'Converted', 'Lost']

@enquiries_bp.route('/enquiries/kanban')
@login_required
@admin_required
def kanban():
    columns = {s: Enquiry.query.filter_by(status=s).order_by(Enquiry.created_at.desc()).all() for s in ENQUIRY_STAGES}
    all_courses = Course.query.all()
    return render_template('enquiries_kanban.html', columns=columns, stages=ENQUIRY_STAGES, courses=all_courses)

@enquiries_bp.route('/enquiries/status/<int:id>', methods=['POST'])
@login_required
@admin_required
def update_status(id):
    enquiry = Enquiry.query.get_or_404(id)
    new_status = request.form.get('status', '')
    if new_status and new_status in ENQUIRY_STAGES:
        enquiry.status = new_status
        db.session.commit()
    if is_ajax_request() or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return '', 200
    return redirect(url_for('enquiries.kanban'))

@enquiries_bp.route('/enquiries/delete/<int:id>')
@login_required
@admin_required
def delete(id):
    enquiry = Enquiry.query.get_or_404(id)
    db.session.delete(enquiry)
    db.session.commit()
    message = "Enquiry records deleted!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('enquiries.list'))
