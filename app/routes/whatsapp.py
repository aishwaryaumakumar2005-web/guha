from flask import Blueprint, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required
from app.helpers import admin_required

whatsapp_bp = Blueprint('whatsapp', __name__)

@whatsapp_bp.route('/api/whatsapp/fee-reminders')
@login_required
@admin_required
def wa_fee_reminders():
    result = current_app.messenger.batch_fee_reminders()
    flash(f"Fee reminders: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
    return redirect(url_for('admin.admin_console'))

@whatsapp_bp.route('/api/whatsapp/attendance-alerts')
@login_required
@admin_required
def wa_attendance_alerts():
    result = current_app.messenger.batch_attendance_alerts()
    flash(f"Attendance alerts: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
    return redirect(url_for('admin.admin_console'))

@whatsapp_bp.route('/api/whatsapp/exam-schedule', methods=['POST'])
@login_required
@admin_required
def wa_exam_schedule():
    course_id = request.form.get('exam_course_id', type=int)
    exam_date = request.form.get('exam_date', '').strip()
    exam_time = request.form.get('exam_time', '10:00 AM').strip()
    venue = request.form.get('exam_venue', 'Main Campus').strip()
    result = current_app.messenger.batch_exam_schedule(course_id=course_id, exam_date=exam_date, exam_time=exam_time, venue=venue)
    flash(f"Exam schedules: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
    return redirect(url_for('admin.admin_console'))
