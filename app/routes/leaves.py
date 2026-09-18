from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import LeaveRequest
from app.helpers import admin_required, is_ajax_request
from app.forms import LeaveForm

leaves_bp = Blueprint('leaves', __name__)

# Server-side cap so the page never loads unbounded history/pending rows.
LEAVE_LIST_LIMIT = 50


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
        new_leave = LeaveRequest(
            user_id=current_user.id, start_date=start_date, end_date=end_date,
            reason=reason, status='Pending'
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
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('leaves.leaves'))