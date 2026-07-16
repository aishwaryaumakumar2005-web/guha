from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Course, student_courses, SystemSetting, Tutor, tutor_courses
from app.helpers import admin_required, is_ajax_request
from app.forms import CourseForm

courses_bp = Blueprint('courses', __name__)

@courses_bp.route('/courses', methods=['GET', 'POST'])
@login_required
def list():
    # Handle POST (add course) - only for admin
    if request.method == 'POST':
        if current_user.role != 'Admin':
            if is_ajax_request():
                return jsonify({"success": False, "errors": ["Only admins can add courses"]}), 403
            flash("Only admins can add courses", 'danger')
            return redirect(url_for('courses.list'))
        
        form = CourseForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('courses.list'))
        name = form.data.get('name', '').strip()
        code = form.data.get('code', '').strip()
        description = form.data.get('description', '').strip()
        duration = form.cleaned_data.get('duration_weeks', 0)
        duration_unit = request.form.get('duration_unit', 'weeks')
        fees = form.cleaned_data.get('fees', 0.0)
        gst_applicable = request.form.get('gst_applicable') == 'on'
        syllabus = request.form.get('syllabus', '').strip()
        exists = Course.query.filter_by(code=code).first()
        if exists:
            message = f"Course code '{code}' already exists!"
            if is_ajax_request():
                return jsonify({"success": False, "message": message}), 400
            flash(message, 'danger')
        else:
            new_course = Course(
                name=name, code=code, description=description,
                duration_weeks=duration, duration_unit=duration_unit,
                fees=fees, gst_applicable=gst_applicable, syllabus=syllabus
            )
            db.session.add(new_course)
            db.session.commit()
            message = "Course added successfully!"
            if is_ajax_request():
                return jsonify({"success": True, "message": message}), 201
            flash(message, "success")
        return redirect(url_for('courses.list'))
    
    # GET request - filter courses based on user role
    if current_user.role == 'Staff':
        # Find the tutor record for this staff user
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if tutor:
            all_courses = tutor.courses
        else:
            all_courses = []
    else:
        all_courses = Course.query.all()
    
    total_courses = len(all_courses)
    enroll_counts = db.session.query(
        student_courses.c.course_id, db.func.count(student_courses.c.student_id).label('cnt')
    ).group_by(student_courses.c.course_id).all()
    enroll_map = {r.course_id: r.cnt for r in enroll_counts}
    courses_with_enrollment = sum(1 for c in all_courses if enroll_map.get(c.id, 0) > 0)
    courses_without_enrollment = total_courses - courses_with_enrollment
    total_enrollments = sum(enroll_map.values())
    cgst_pct = float((SystemSetting.query.filter_by(key='CGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='CGST_PCT').first() else 9.0
    sgst_pct = float((SystemSetting.query.filter_by(key='SGST_PCT').first()).value or '9') if SystemSetting.query.filter_by(key='SGST_PCT').first() else 9.0
    return render_template(
        'courses.html', courses=all_courses, total_courses=total_courses,
        courses_with_enrollment=courses_with_enrollment,
        courses_without_enrollment=courses_without_enrollment,
        total_enrollments=total_enrollments,
        gst_rates={'cgst': cgst_pct, 'sgst': sgst_pct},
        is_staff=(current_user.role == 'Staff')
    )

@courses_bp.route('/courses/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit(id):
    course = Course.query.get_or_404(id)
    form = CourseForm(request.form)
    if not form.validate():
        if is_ajax_request():
            return jsonify({"success": False, "errors": form.error_messages}), 400
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('courses.list'))
    new_code = form.data.get('code', '').strip()
    if new_code != course.code:
        exists = Course.query.filter_by(code=new_code).first()
        if exists:
            flash(f"Course code '{new_code}' already exists!", 'danger')
            return redirect(url_for('courses.list'))
    course.name = form.data.get('name', '').strip()
    course.code = new_code
    course.description = form.data.get('description', '').strip()
    course.duration_weeks = form.cleaned_data.get('duration_weeks', 0)
    course.duration_unit = request.form.get('duration_unit', 'weeks')
    course.fees = form.cleaned_data.get('fees', 0.0)
    course.gst_applicable = request.form.get('gst_applicable') == 'on'
    course.syllabus = request.form.get('syllabus', '').strip()
    db.session.commit()
    message = "Course details updated!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('courses.list'))

@courses_bp.route('/courses/delete/<int:id>')
@login_required
@admin_required
def delete(id):
    course = Course.query.get_or_404(id)
    db.session.delete(course)
    db.session.commit()
    message = "Course deleted successfully!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('courses.list'))
