import csv
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import LeaveRequest, Tutor, Attendance
from app.helpers import admin_required, is_ajax_request
from app.forms import LeaveForm, LEAVE_TYPES

leaves_bp = Blueprint('leaves', __name__)

# Server-side cap so the page never loads unbounded history/pending rows.
LEAVE_LIST_LIMIT = 50

DEFAULT_LEAVE_TYPE = 'Casual'


def _overlap_errors(form, start_date, end_date):
    """Reject a new request that overlaps an existing Pending/Approved one."""
    conflict = LeaveRequest.query.filter(
        LeaveRequest.user_id == current_user.id,
        LeaveRequest.status.in_(['Pending', 'Approved']),
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date,
    ).first()
    if conflict:
        form._error('start_date', 'You already have a pending or approved leave overlapping these dates.')


def _leave_balance(user):
    """Per leave type: entitlement, days used this year, days remaining."""
    entitlements = current_app.config.get('LEAVE_ENTITLEMENTS', {}).get(user.role, {})
    if not entitlements:
        return {}
    year = date.today().year
    approved = LeaveRequest.query.filter(
        LeaveRequest.user_id == user.id,
        LeaveRequest.status == 'Approved',
        LeaveRequest.start_date >= date(year, 1, 1),
        LeaveRequest.start_date <= date(year, 12, 31),
    ).all()
    used = {}
    for req in approved:
        leave_type = req.leave_type or DEFAULT_LEAVE_TYPE
        used[leave_type] = used.get(leave_type, 0) + (req.end_date - req.start_date).days + 1
    return {
        leave_type: {
            'entitlement': ent,
            'used': used.get(leave_type, 0),
            'remaining': max(ent - used.get(leave_type, 0), 0),
        }
        for leave_type, ent in entitlements.items()
    }


def _days_on_leave_this_month(user_id):
    """Approved leave days that overlap the current calendar month (≤ today)."""
    today = date.today()
    month_start = today.replace(day=1)
    rows = LeaveRequest.query.filter(
        LeaveRequest.user_id == user_id,
        LeaveRequest.status == 'Approved',
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= month_start,
    ).all()
    days = 0
    for req in rows:
        lo = max(req.start_date, month_start)
        hi = min(req.end_date, today)
        if hi >= lo:
            days += (hi - lo).days + 1
    return days


def _sync_leave_attendance(leave):
    """Mark the approved dates as Leave for the staff member's tutor record.

    Only fills days that have no attendance record yet, so manual marks are
    never clobbered. Returns the number of rows written.
    """
    if not leave.staff or not leave.staff.email:
        return 0
    tutor = Tutor.query.filter_by(email=leave.staff.email).first()
    if not tutor:
        return 0
    written = 0
    day_count = (leave.end_date - leave.start_date).days + 1
    for offset in range(day_count):
        d = leave.start_date + timedelta(days=offset)
        existing = Attendance.query.filter_by(
            person_type='tutor', person_id=tutor.id, date=d
        ).first()
        if existing:
            continue
        db.session.add(Attendance(
            person_type='tutor', person_id=tutor.id, date=d,
            status='Leave', marked_by='auto_leave'))
        written += 1
    return written


def _send_status_notification(leave):
    """Best-effort email + WhatsApp/SMS on a status change. Never raises."""
    try:
        staff = leave.staff
        if not staff:
            return
        dates_text = f"{leave.start_date.strftime('%d %b %Y')} to {leave.end_date.strftime('%d %b %Y')}"
        if staff.email:
            current_app.notifier.notify_leave_status(
                staff.email, staff.name, dates_text, leave.status, leave.remarks)
        tutor = Tutor.query.filter_by(email=staff.email).first()
        if tutor and tutor.phone:
            current_app.messenger.send_leave_status(
                tutor.phone, staff.name, dates_text, leave.status, leave.remarks)
    except Exception as e:
        current_app.logger.warning('Leave status notification failed: %s', e)


@leaves_bp.route('/leaves', methods=['GET', 'POST'])
@login_required
def leaves():
    if request.method == 'POST':
        form = LeaveForm(request.form)
        valid = form.validate()
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        if valid and start_date and end_date:
            _overlap_errors(form, start_date, end_date)
            valid = len(form.errors) == 0
        if not valid:
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('leaves.leaves'))
        reason = request.form.get('reason', '').strip()
        leave_type = (request.form.get('leave_type') or DEFAULT_LEAVE_TYPE).strip() or DEFAULT_LEAVE_TYPE
        if leave_type not in LEAVE_TYPES:
            leave_type = DEFAULT_LEAVE_TYPE
        new_leave = LeaveRequest(
            user_id=current_user.id, start_date=start_date, end_date=end_date,
            reason=reason, leave_type=leave_type, status='Pending'
        )
        db.session.add(new_leave)
        db.session.commit()
        message = "Leave request submitted successfully!"
        if is_ajax_request():
            return jsonify({"success": True, "message": message}), 201
        flash(message, "success")
        return redirect(url_for('leaves.leaves'))

    if current_user.role == 'Admin':
        pending_q = LeaveRequest.query.filter_by(status='Pending').order_by(LeaveRequest.created_at.asc())
        history_q = LeaveRequest.query.filter(LeaveRequest.status != 'Pending').order_by(LeaveRequest.created_at.desc())
    else:
        pending_q = LeaveRequest.query.filter_by(
            user_id=current_user.id, status='Pending'
        ).order_by(LeaveRequest.created_at.asc())
        history_q = LeaveRequest.query.filter_by(user_id=current_user.id).filter(
            LeaveRequest.status != 'Pending'
        ).order_by(LeaveRequest.created_at.desc())
    pending_total = pending_q.count()
    history_total = history_q.count()
    pending_leaves = pending_q.limit(LEAVE_LIST_LIMIT).all()
    history_leaves = history_q.limit(LEAVE_LIST_LIMIT).all()
    return render_template(
        'leaves.html',
        pending_leaves=pending_leaves,
        history_leaves=history_leaves,
        pending_total=pending_total,
        history_total=history_total,
        list_limit=LEAVE_LIST_LIMIT,
        leave_balance=_leave_balance(current_user) if current_user.role != 'Admin' else None,
        leave_types=LEAVE_TYPES,
        aging_days=current_app.config.get('LEAVE_AGING_DAYS', 7),
        today=date.today(),
    )


@leaves_bp.route('/leaves/action/<int:leave_id>/<string:action>', methods=['POST'])
@login_required
@admin_required
def leave_action(leave_id, action):
    leave = LeaveRequest.query.get_or_404(leave_id)
    if action in ('approve', 'reject') and leave.status != 'Pending':
        message = (f"Leave request for {leave.staff.name} was already actioned "
                   f"(current status: {leave.status}).")
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    if action == 'approve':
        leave.status = 'Approved'
        message = f"Leave request for {leave.staff.name} approved."
        _sync_leave_attendance(leave)
    elif action == 'reject':
        leave.status = 'Rejected'
        message = f"Leave request for {leave.staff.name} rejected."
    else:
        message = "Invalid action."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    leave.approved_by = current_user.id
    leave.actioned_at = datetime.utcnow()
    leave.remarks = (request.form.get('remarks') or '').strip() or None
    db.session.commit()
    _send_status_notification(leave)
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('leaves.leaves'))


@leaves_bp.route('/leaves/withdraw/<int:leave_id>', methods=['POST'])
@login_required
def withdraw_leave(leave_id):
    leave = LeaveRequest.query.get_or_404(leave_id)
    if leave.user_id != current_user.id:
        message = "You can only cancel your own leave requests."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 403
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    if leave.status != 'Pending':
        message = f"Only pending requests can be cancelled (current status: {leave.status})."
        if is_ajax_request():
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('leaves.leaves'))
    db.session.delete(leave)
    db.session.commit()
    message = "Leave request cancelled. The audit log records the removal."
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('leaves.leaves'))


@leaves_bp.route('/leaves/export')
@login_required
def export_leaves():
    query = LeaveRequest.query
    if current_user.role != 'Admin':
        query = query.filter_by(user_id=current_user.id)
    status = request.args.get('status')
    leave_type = request.args.get('leave_type')
    if status:
        query = query.filter_by(status=status)
    if leave_type:
        query = query.filter_by(leave_type=leave_type)
    rows = query.order_by(LeaveRequest.created_at.desc()).all()
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(['ID', 'Staff Name', 'Username', 'Leave Type', 'Start Date', 'End Date',
                     'Duration Days', 'Reason', 'Status', 'Approved By', 'Actioned At',
                     'Remarks', 'Created At'])
    for req in rows:
        writer.writerow([
            req.id,
            req.staff.name if req.staff else '',
            req.staff.username if req.staff else '',
            req.leave_type or DEFAULT_LEAVE_TYPE,
            req.start_date.isoformat(),
            req.end_date.isoformat(),
            (req.end_date - req.start_date).days + 1,
            req.reason or '',
            req.status,
            req.approver.name if req.approver else '',
            req.actioned_at.isoformat() if req.actioned_at else '',
            req.remarks or '',
            req.created_at.isoformat() if req.created_at else '',
        ])
    output = buf.getvalue().encode('utf-8-sig')
    return send_file(BytesIO(output), mimetype='text/csv', as_attachment=True,
                     download_name=f'leave_history_{date.today().strftime("%Y%m%d")}.csv')