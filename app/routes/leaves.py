from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import LeaveRequest
from app.helpers import admin_required, is_ajax_request
from app.forms import LeaveForm

leaves_bp = Blueprint('leaves', __name__)

@leaves_bp.route('/leaves', methods=['GET', 'POST'])
@login_required
def leaves():
    if request.method == 'POST':
        form = LeaveForm(request.form)
        if not form.validate():
            if is_ajax_request():
                return jsonify({"success": False, "errors": form.error_messages}), 400
            for msg in form.error_messages:
                flash(msg, 'danger')
            return redirect(url_for('leaves.leaves'))
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
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
        pending_leaves = LeaveRequest.query.filter_by(status='Pending').order_by(LeaveRequest.created_at.desc()).all()
        history_leaves = LeaveRequest.query.filter(LeaveRequest.status != 'Pending').order_by(LeaveRequest.created_at.desc()).all()
    else:
        pending_leaves = LeaveRequest.query.filter_by(user_id=current_user.id, status='Pending').order_by(LeaveRequest.created_at.desc()).all()
        history_leaves = LeaveRequest.query.filter_by(user_id=current_user.id).filter(LeaveRequest.status != 'Pending').order_by(LeaveRequest.created_at.desc()).all()
    return render_template('leaves.html', pending_leaves=pending_leaves, history_leaves=history_leaves)

@leaves_bp.route('/leaves/action/<int:leave_id>/<string:action>')
@login_required
@admin_required
def leave_action(leave_id, action):
    leave = LeaveRequest.query.get_or_404(leave_id)
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
    db.session.commit()
    if is_ajax_request():
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for('leaves.leaves'))
