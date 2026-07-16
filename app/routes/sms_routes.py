from flask import Blueprint, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required
from app.helpers import admin_required

sms_bp = Blueprint('sms', __name__)

@sms_bp.route('/api/sms/fee-reminders')
@login_required
@admin_required
def sms_fee_reminders():
    result = current_app.sms_service.batch_fee_reminders()
    flash(f"SMS fee reminders: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
    return redirect(url_for('admin.admin_console'))

@sms_bp.route('/api/sms/attendance-alerts')
@login_required
@admin_required
def sms_attendance_alerts():
    result = current_app.sms_service.batch_attendance_alerts()
    flash(f"SMS attendance alerts: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
    return redirect(url_for('admin.admin_console'))

@sms_bp.route('/api/sms/exam-schedule', methods=['POST'])
@login_required
@admin_required
def sms_exam_schedule():
    course_id = request.form.get('exam_course_id', type=int)
    exam_date = request.form.get('exam_date', '').strip()
    exam_time = request.form.get('exam_time', '10:00 AM').strip()
    venue = request.form.get('exam_venue', 'Main Campus').strip()
    result = current_app.sms_service.batch_exam_schedule(course_id=course_id, exam_date=exam_date, exam_time=exam_time, venue=venue)
    flash(f"SMS exam schedules: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
    return redirect(url_for('admin.admin_console'))
