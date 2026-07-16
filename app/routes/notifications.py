import os
from flask import Blueprint, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required
from app.helpers import admin_required

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/api/notify/attendance')
@login_required
@admin_required
def notify_attendance():
    count = current_app.notifier.check_low_attendance()
    flash(f"Low attendance check complete. {count} alert(s) sent.", "success")
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/notify/fees')
@login_required
@admin_required
def notify_fees():
    count = current_app.notifier.check_fee_due()
    flash(f"Fee due check complete. {count} reminder(s) sent.", "success")
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/notify/enquiries')
@login_required
@admin_required
def notify_enquiries():
    count = current_app.notifier.check_enquiry_followups()
    flash(f"Enquiry follow-up check complete. {count} reminder(s) sent.", "success")
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/notify/all')
@login_required
@admin_required
def notify_all():
    results = current_app.notifier.run_all_checks()
    total = sum(results.values())
    flash(f"All checks complete. {total} notification(s) sent.", "success")
    return redirect(url_for('admin.admin_console'))

@notifications_bp.route('/api/cron/notify')
def cron_notify():
    key = request.args.get('key', '')
    expected = os.environ.get('CRON_SECRET', '') or 'change-me-in-production'
    if key != expected:
        return jsonify({'error': 'Invalid or missing secret key'}), 403
    results = current_app.notifier.run_all_checks()
    return jsonify({'status': 'ok', 'results': results})

@notifications_bp.route('/api/cron/whatsapp')
def cron_whatsapp():
    key = request.args.get('key', '')
    expected = os.environ.get('CRON_SECRET', '') or 'change-me-in-production'
    if key != expected:
        return jsonify({'error': 'Invalid or missing secret key'}), 403
    results = current_app.messenger.run_all_batches()
    return jsonify({'status': 'ok', 'results': results})
