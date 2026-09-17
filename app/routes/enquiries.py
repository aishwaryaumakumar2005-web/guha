import re

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required
from datetime import datetime, date as date_cls
from app.extensions import db
from app.models import Enquiry, Course, Student, AuditLog, ensure_enrolled_on
from app.helpers import admin_required, is_ajax_request
from app.forms import (EnquiryForm, ENQUIRY_SOURCES, ENQUIRY_STATUSES,
                       ENQUIRY_CREATE_STATUSES, ENQUIRY_MANUAL_STATUSES)

enquiries_bp = Blueprint('enquiries', __name__)

_CONVERT_HINT = "Use the Convert action to enroll this lead (it creates the student record)."


def _parse_follow_up(raw):
    if not raw:
        return None
    try:
        return date_cls.fromisoformat(str(raw).strip())
    except (ValueError, TypeError):
        return None


def _reject(message, endpoint, status=400):
    """Return a JSON error for AJAX callers, otherwise flash + redirect."""
    if is_ajax_request():
        return jsonify({"success": False, "message": message}), status
    flash(message, "danger")
    return redirect(url_for(endpoint))


def _norm_phone(value):
    return re.sub(r'\D', '', value or '')


def _phones_match(a, b):
    """Treat numbers as equal when identical or sharing the last 10 digits."""
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a) >= 10 and len(b) >= 10 and a[-10:] == b[-10:]


def _find_duplicate_enquiry(phone, email, exclude_id=None):
    """Return an existing lead matching this email or phone, else None.

    Email is matched case-insensitively; phone is normalized to digits and
    compared on the last 10 digits so '+91 98765 43210' matches '9876543210'.
    """
    email = (email or '').strip().lower()
    norm = _norm_phone(phone)
    if not email and not norm:
        return None
    query = Enquiry.query
    if exclude_id:
        query = query.filter(Enquiry.id != exclude_id)
    if email:
        same = query.filter(db.func.lower(Enquiry.email) == email).first()
        if same:
            return same
    if norm:
        tail = norm[-7:]
        for other in query.filter(Enquiry.phone.like('%' + tail)).all():
            if _phones_match(norm, _norm_phone(other.phone)):
                return other
    return None


def _duplicate_message(dup):
    return (f"This lead already exists: {dup.student_name} "
            f"(#{dup.id}, {dup.phone}). Open it instead of creating a duplicate.")


# Stages that count as advisor contact for staleness purposes.
_CONTACT_STAGES = {'Contacted', 'Visited', 'Converted', 'Lost'}

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
        if enquiry_status not in ENQUIRY_CREATE_STATUSES:
            return _reject("New leads can only start as New or Contacted.",
                           'enquiries.list', 400)
        duplicate = _find_duplicate_enquiry(phone, email)
        if duplicate:
            return _reject(_duplicate_message(duplicate), 'enquiries.list', 409)
        new_enq = Enquiry(
            student_name=student_name, email=email, phone=phone,
            course_id=course_id, source=source, status=enquiry_status, notes=notes,
            follow_up_date=_parse_follow_up(request.form.get('follow_up_date'))
        )
        db.session.add(new_enq)
        db.session.commit()
        message = "Enquiry submitted successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('enquiries.list'))
    all_enquiries = Enquiry.query.order_by(Enquiry.created_at.desc(), Enquiry.id.desc()).all()
    all_courses = Course.query.order_by(Course.code).all()
    return render_template('enquiries.html', enquiries=all_enquiries, courses=all_courses,
                           sources=ENQUIRY_SOURCES, today=date_cls.today())

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
    student_name = form.data.get('student_name', '').strip()
    email = form.data.get('email', '').strip()
    phone = form.data.get('phone', '').strip()
    submitted_status = request.form.get('status', 'New')
    if enquiry.status == 'Converted':
        # A converted lead is permanently attached to its student.
        submitted_status = 'Converted'
    elif submitted_status == 'Converted':
        return _reject(_CONVERT_HINT, 'enquiries.list', 400)
    duplicate = _find_duplicate_enquiry(phone, email, exclude_id=enquiry.id)
    if duplicate:
        return _reject(_duplicate_message(duplicate), 'enquiries.list', 409)

    enquiry.student_name = student_name
    enquiry.email = email
    enquiry.phone = phone
    enquiry.course_id = form.cleaned_data.get('course_id')
    enquiry.source = request.form.get('source', 'Walk-in')
    enquiry.status = submitted_status
    enquiry.notes = request.form.get('notes', '').strip()
    enquiry.follow_up_date = _parse_follow_up(request.form.get('follow_up_date'))
    # An advisor editing the lead counts as contact, so it stops being "stale".
    enquiry.last_contacted_at = datetime.utcnow()
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
    email = (enquiry.email or '').strip()
    phone = (enquiry.phone or '').strip()
    if enquiry.status == 'Converted':
        message = "This lead has already been converted to a student."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "warning")
        return redirect(url_for('students.list'))
    if not email:
        # Student.email is NOT NULL UNIQUE — converting without one would
        # either 500 on IntegrityError or poison the table with ''.
        message = "Add an email address to this enquiry before converting — it is required for the student record."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('enquiries.list'))
    student_exists = Student.query.filter(db.func.lower(Student.email) == email.lower()).first()
    if student_exists:
        # Don't create a duplicate and don't mutate the lead — just warn so the
        # advisor can reconcile it manually.
        message = f"Student with email '{email}' is already enrolled!"
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "warning")
        return redirect(url_for('students.list'))
    new_student = Student(name=enquiry.student_name, email=email, phone=phone, status='Active')
    course = Course.query.get(enquiry.course_id) if enquiry.course_id else None
    if course:
        new_student.courses.append(course)
    db.session.add(new_student)
    db.session.flush()
    ensure_enrolled_on(new_student.id)
    enquiry.status = 'Converted'
    enquiry.converted_student_id = new_student.id
    enquiry.last_contacted_at = datetime.utcnow()
    db.session.commit()
    message = f"Enquiry successfully converted! {new_student.name} is now enrolled."
    phone_owner = Student.query.filter(
        Student.phone == phone, Student.id != new_student.id).first() if phone else None
    if phone_owner:
        # Phone is not unique in the schema (shared family numbers are
        # legitimate), so this stays a non-blocking heads-up.
        note = f" Note: phone number is also used by {phone_owner.name}."
        message += note
        if is_ajax_request():
            return jsonify({"success": True, "message": message, "warning": note.strip()}), 201
        flash(message, "success")
        flash(note.strip(), "warning")
        return redirect(url_for('students.list'))
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 201
    flash(message, "success")
    return redirect(url_for('students.list'))

ENQUIRY_STAGES = ENQUIRY_STATUSES

_HISTORY_FIELD_LABELS = {
    'student_name': 'name',
    'email': 'email',
    'phone': 'phone',
    'course_id': 'course',
    'source': 'source',
    'status': 'status',
    'notes': 'notes',
    'follow_up_date': 'follow-up',
    'converted_student_id': 'enrolled student',
}


def _summarize_audit(log):
    """Turn one AuditLog row into a short human-readable activity line."""
    changes = log.changes_dict()
    if log.action == 'INSERT':
        detail = 'Lead created'
    elif log.action == 'DELETE':
        detail = 'Lead deleted'
    else:
        parts = []
        for field, delta in (changes or {}).items():
            label = _HISTORY_FIELD_LABELS.get(field, field.replace('_', ' '))
            if isinstance(delta, dict):
                frm = delta.get('from')
                to = delta.get('to')
                frm = '(empty)' if frm in (None, '') else frm
                to = '(empty)' if to in (None, '') else to
                parts.append(f"{label}: {frm} -> {to}")
            else:
                parts.append(f"{label}: {delta}")
        detail = '; '.join(parts) if parts else 'Updated'
    return {
        'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M') if log.timestamp else '',
        'username': log.username or 'system',
        'action': log.action,
        'detail': detail,
    }


@enquiries_bp.route('/enquiries/<int:id>/history')
@login_required
@admin_required
def history(id):
    Enquiry.query.get_or_404(id)
    logs = (AuditLog.query
            .filter_by(entity_type='Enquiry', entity_id=id)
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .limit(25).all())
    return jsonify({"success": True, "entries": [_summarize_audit(l) for l in logs]})


@enquiries_bp.route('/enquiries/kanban')
@login_required
@admin_required
def kanban():
    columns = {s: Enquiry.query.filter_by(status=s).order_by(Enquiry.created_at.desc()).all() for s in ENQUIRY_STAGES}
    all_courses = Course.query.order_by(Course.code).all()
    return render_template('enquiries_kanban.html', columns=columns, stages=ENQUIRY_STAGES,
                           courses=all_courses, sources=ENQUIRY_SOURCES)

@enquiries_bp.route('/enquiries/status/<int:id>', methods=['POST'])
@login_required
@admin_required
def update_status(id):
    enquiry = Enquiry.query.get_or_404(id)
    new_status = request.form.get('status', '')
    if new_status not in ENQUIRY_MANUAL_STATUSES:
        message = ("Unknown pipeline stage. Converted is reached through the "
                   "Convert action.") if new_status == 'Converted' else "Unknown pipeline stage."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('enquiries.kanban'))
    enquiry.status = new_status
    if new_status in _CONTACT_STAGES:
        enquiry.last_contacted_at = datetime.utcnow()
    db.session.commit()
    if is_ajax_request():
        return jsonify({"success": True, "status": new_status}), 200
    return redirect(url_for('enquiries.kanban'))

@enquiries_bp.route('/enquiries/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete(id):
    enquiry = Enquiry.query.get_or_404(id)
    db.session.delete(enquiry)
    db.session.commit()
    message = "Enquiry record deleted!"
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('enquiries.list'))
