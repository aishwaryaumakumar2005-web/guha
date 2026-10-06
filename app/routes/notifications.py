import os
from datetime import datetime
from flask import Blueprint, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.helpers import admin_required
from app.extensions import db
from app.models import Notification

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/api/notify/attendance')
@login_required
@admin_required
def notify_attendance():
    count = current_app.notifier.check_low_attendance()
    flash(f'Low attendance check complete. {count} alert(s) sent.', 'success')
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/notify/fees')
@login_required
@admin_required
def notify_fees():
    count = current_app.notifier.check_fee_due()
    flash(f'Fee due check complete. {count} reminder(s) sent.', 'success')
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/notify/enquiries')
@login_required
@admin_required
def notify_enquiries():
    count = current_app.notifier.check_enquiry_followups()
    flash(f'Enquiry follow-up check complete. {count} follow-up(s) sent.', 'success')
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/notify/all')
@login_required
@admin_required
def notify_all():
    results = current_app.notifier.run_all_checks()
    flash(f"All checks complete. {sum(results.values())} notification(s) sent.", 'success')
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/cron/notify')
def cron_notify():
    if request.args.get('key', '') != (os.environ.get('CRON_SECRET', '') or 'change-me-in-production'):
        return jsonify({'error': 'Invalid or missing secret key'}), 403
    return jsonify({'status': 'ok', 'results': current_app.notifier.run_all_checks()})

@notifications_bp.route('/api/cron/whatsapp')
def cron_whatsapp():
    if request.args.get('key', '') != (os.environ.get('CRON_SECRET', '') or 'change-me-in-production'):
        return jsonify({'error': 'Invalid or missing secret key'}), 403
    return jsonify({'status': 'ok', 'results': current_app.messenger.run_all_batches()})

@notifications_bp.route('/notifications/<int:id>/read', methods=['POST'])
@login_required
def mark_read(id):
    notification = Notification.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    notification.read_at = notification.read_at or datetime.utcnow()
    db.session.commit()
    return redirect(url_for('tasks.list_tasks'))
