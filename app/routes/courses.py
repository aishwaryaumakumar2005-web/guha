from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import (
    Course, Enquiry, Exam, ExamAssignment, ExamScore, McqAnswer,
    McqAttempt, McqQuestion, student_courses, Tutor,
    tutor_courses, Company,
)
from app.helpers import admin_required, get_gst_rates, is_ajax_request
from app.forms import CourseForm
from sqlalchemy.orm import joinedload
from datetime import date

courses_bp = Blueprint('courses', __name__)

def _parse_capacity(raw):
    """Validate the optional seat-capacity input.

    Returns (value, error): blank -> (None, None); a whole number >= 1 ->
    (int, None); anything else ("-5", "30.5", "lots") -> (None, message)
    instead of the old silent NULL.
    """
    raw = (raw or '').strip()
    if not raw:
        return None, None
    if raw.isdigit() and int(raw) >= 1:
        return int(raw), None
    return None, f"Seat capacity must be a whole number of 1 or more (got '{raw}')"


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
        # Registry codes are canonicalized to uppercase: the DB unique index
        # is case-sensitive, but Excel imports map codes case-insensitively,
        # so 'py' and 'PY' coexisting would silently mis-enroll imports.
        code = form.data.get('code', '').strip().upper()
        description = form.data.get('description', '').strip()
        duration = form.cleaned_data.get('duration_weeks', 0)
        duration_unit = request.form.get('duration_unit', 'weeks')
        fees = form.cleaned_data.get('fees', 0.0)
        capacity, capacity_err = _parse_capacity(request.form.get('capacity', ''))
        if capacity_err:
            if is_ajax_request():
                return jsonify({"success": False, "errors": [capacity_err]}), 400
            flash(capacity_err, 'danger')
            return redirect(url_for('courses.list'))
        gst_applicable = request.form.get('gst_applicable') == 'on'
        syllabus = request.form.get('syllabus', '').strip()
        company_id_raw = request.form.get('company_id', '').strip()
        company_id = int(company_id_raw) if company_id_raw.isdigit() else None
        exists = Course.query.filter(
            db.func.lower(Course.code) == code.lower()).first()
        if exists:
            message = f"Course code '{code}' already exists!"
            if is_ajax_request():
                return jsonify({"success": False, "message": message}), 400
            flash(message, 'danger')
        else:
            new_course = Course(
                name=name, code=code, description=description,
                duration_weeks=duration, duration_unit=duration_unit,
                fees=fees, capacity=capacity,
                gst_applicable=gst_applicable, syllabus=syllabus,
                company_id=company_id
            )
            db.session.add(new_course)
            db.session.commit()
            message = "Course added successfully!"
            if is_ajax_request():
                return jsonify({"success": True, "message": message}), 201
            flash(message, "success")
        return redirect(url_for('courses.list'))
    
    # GET request - filter courses based on user role
    companies = Company.query.filter_by(is_active=True).all()
    search = (request.args.get('q') or '').strip()
    status_filter = request.args.get('status', '').strip()
    if current_user.role == 'Staff':
        # Find the tutor record for this staff user
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        course_ids = [c.id for c in tutor.courses] if tutor else []
        # joinedload: each card reads course.company — without it that's one
        # extra query per card.
        all_courses = (Course.query.options(joinedload(Course.company))
                       .filter(Course.id.in_(course_ids)).all()) if course_ids else []
    else:
        all_courses = Course.query.options(joinedload(Course.company)).all()
    if search:
        needle = search.casefold()
        all_courses = [c for c in all_courses if needle in (c.name or '').casefold() or needle in (c.code or '').casefold()]
    if status_filter in ('Active', 'Archived', 'Draft', 'Paused'):
        all_courses = [c for c in all_courses if (c.status or 'Active') == status_filter]
    
    total_courses = len(all_courses)
    # Active enrollments only: Dropped/Completed rows must not inflate
    # demand badges or capacity. NULL status predates the column default
    # and means Enrolled (same convention as the lifecycle buckets).
    enroll_counts = db.session.query(
        student_courses.c.course_id, db.func.count(student_courses.c.student_id).label('cnt')
    ).filter(db.or_(
        student_courses.c.status == 'Enrolled',
        student_courses.c.status.is_(None),
    )).group_by(student_courses.c.course_id).all()
    enroll_map = {r.course_id: r.cnt for r in enroll_counts}
    courses_with_enrollment = sum(1 for c in all_courses if enroll_map.get(c.id, 0) > 0)
    courses_without_enrollment = total_courses - courses_with_enrollment
    total_enrollments = sum(enroll_map.values())
    cgst_pct, sgst_pct = get_gst_rates()
    return render_template(
        'courses.html', courses=all_courses, total_courses=total_courses,
        courses_with_enrollment=courses_with_enrollment,
        courses_without_enrollment=courses_without_enrollment,
        total_enrollments=total_enrollments, enroll_map=enroll_map,
        gst_rates={'cgst': cgst_pct, 'sgst': sgst_pct},
        is_staff=(current_user.role == 'Staff'),
        companies=companies, q=search, status_filter=status_filter,
        course_statuses=('Active', 'Archived', 'Draft', 'Paused')
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
    # Registry codes are immutable: imports/exports key off them, so the form
    # field is readonly and the code is never rewritten here (a changed code
    # would silently orphan future import mappings).
    course.name = form.data.get('name', '').strip()
    course.description = form.data.get('description', '').strip()
    course.duration_weeks = form.cleaned_data.get('duration_weeks', 0)
    course.duration_unit = request.form.get('duration_unit', 'weeks')
    old_fees = course.fees or 0.0
    new_fees = form.cleaned_data.get('fees', 0.0)
    course.fees = new_fees
    capacity, capacity_err = _parse_capacity(request.form.get('capacity', ''))
    if capacity_err:
        if is_ajax_request():
            return jsonify({"success": False, "errors": [capacity_err]}), 400
        flash(capacity_err, 'danger')
        return redirect(url_for('courses.list'))
    course.capacity = capacity
    course.gst_applicable = request.form.get('gst_applicable') == 'on'
    course.syllabus = request.form.get('syllabus', '').strip()
    company_id_raw = request.form.get('company_id', '').strip()
    course.company_id = int(company_id_raw) if company_id_raw.isdigit() else None
    fee_changed = (new_fees or 0.0) != (old_fees or 0.0)
    db.session.commit()
    message = "Course details updated!"
    if fee_changed:
        # W2: dues are snapshotted at enrollment. Editing the catalog price
        # affects NEW enrollments only — existing students keep their agreed
        # price, so no balances move on this save.
        message += (f" Fee changed ₹{old_fees:,.2f} → ₹{new_fees:,.2f}. "
                    f"Applies to new enrollments; existing students keep their agreed price.")
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('courses.list'))

@courses_bp.route('/courses/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete(id):
    course = Course.query.get_or_404(id)
    course.status = 'Archived'
    db.session.commit()
    message = "Course archived successfully. Enrollments, exams and scores were preserved."
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('courses.list'))


@courses_bp.route('/courses/<int:id>')
@login_required
def detail(id):
    course = Course.query.get_or_404(id)
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor or course.id not in {c.id for c in tutor.courses}:
            return '', 403
    active_count = db.session.query(db.func.count(student_courses.c.student_id)).filter(
        student_courses.c.course_id == id,
        db.or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None))).scalar() or 0
    enquiries_count = Enquiry.query.filter_by(course_id=id).count()
    return render_template('course_detail.html', course=course,
                           active_count=active_count,
                           enquiries_count=enquiries_count,
                           capacity_left=(course.capacity - active_count) if course.capacity else None)


@courses_bp.route('/courses/archive/<int:id>', methods=['POST'])
@login_required
@admin_required
def archive(id):
    course = Course.query.get_or_404(id)
    course.status = 'Archived'
    db.session.commit()
    flash('Course archived. Historical records were preserved.', 'success')
    return redirect(url_for('courses.list'))


def _legacy_delete_disabled(id):
    """Retained below only for source compatibility; archive is the public action."""
    course = Course.query.get_or_404(id)
    try:
        # Remove association rows explicitly for compatibility with older Render schemas
        # whose foreign keys may not have been created with ON DELETE CASCADE.
        db.session.execute(student_courses.delete().where(student_courses.c.course_id == course.id))
        db.session.execute(tutor_courses.delete().where(tutor_courses.c.course_id == course.id))
        # Preserve lead history: detach enquiries from the course instead of
        # deleting them (course_id is nullable with ON DELETE SET NULL).
        Enquiry.query.filter_by(course_id=course.id).update(
            {'course_id': None}, synchronize_session=False)
        exam_ids = [exam.id for exam in Exam.query.filter_by(course_id=course.id).all()]
        if exam_ids:
            # Clear exam descendants first for compatibility with older schemas
            # whose exam foreign keys may not have ON DELETE CASCADE.
            McqAnswer.query.filter(
                McqAnswer.mcq_attempt_id.in_(
                    db.session.query(McqAttempt.id).filter(McqAttempt.exam_id.in_(exam_ids))
                )
            ).delete(synchronize_session=False)
            McqAnswer.query.filter(
                McqAnswer.mcq_question_id.in_(
                    db.session.query(McqQuestion.id).filter(McqQuestion.exam_id.in_(exam_ids))
                )
            ).delete(synchronize_session=False)
            ExamAssignment.query.filter(ExamAssignment.exam_id.in_(exam_ids)).delete(synchronize_session=False)
            ExamScore.query.filter(ExamScore.exam_id.in_(exam_ids)).delete(synchronize_session=False)
            McqQuestion.query.filter(McqQuestion.exam_id.in_(exam_ids)).delete(synchronize_session=False)
            McqAttempt.query.filter(McqAttempt.exam_id.in_(exam_ids)).delete(synchronize_session=False)
            Exam.query.filter(Exam.id.in_(exam_ids)).delete(synchronize_session=False)
        db.session.delete(course)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to delete course id=%s', course.id)
        message = 'Course could not be deleted. Please try again or contact an administrator.'
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 500
        flash(message, 'danger')
        return redirect(url_for('courses.list'))
    message = "Course deleted successfully!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('courses.list'))
