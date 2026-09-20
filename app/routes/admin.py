import os
import json
import uuid
import sqlite3
import re
import secrets
from datetime import datetime, date, timezone, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app, session, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Course, Student, Tutor, Enquiry, FeeRecord, Attendance, SystemSetting, ExpenseCategory, Expense, Exam, ExamScore, ExamAssignment, AuditLog
from app.helpers import admin_required, get_backup_dir

IST = timezone(timedelta(hours=5, minutes=30))

def ist_now():
    return datetime.now(IST)

def _audit_admin_action(action, entity_type='System', entity_id=None, changes=None):
    """Best-effort audit record for privileged console actions."""
    try:
        db.session.add(AuditLog(user_id=current_user.id, username=current_user.username,
                                action=action[:10], entity_type=entity_type,
                                entity_id=entity_id,
                                changes=json.dumps(changes or {}, default=str)))
        db.session.commit()
    except Exception:
        db.session.rollback()

def _backup_path_is_safe(backup_dir, filename):
    backup_root = os.path.realpath(backup_dir)
    candidate = os.path.realpath(os.path.join(backup_root, filename))
    return candidate.startswith(backup_root + os.sep) and os.path.isfile(candidate)

def _valid_phone(value):
    normalized = re.sub(r'[\s()-]', '', value or '')
    return bool(re.fullmatch(r'\+?[1-9]\d{9,14}', normalized))

admin_bp = Blueprint('admin', __name__)

@admin_bp.before_request
def protect_admin_posts():
    if 'admin_csrf_token' not in session:
        session['admin_csrf_token'] = secrets.token_urlsafe(32)
    if request.method == 'POST' and not current_app.testing:
        submitted = request.form.get('admin_csrf_token') or request.headers.get('X-CSRFToken')
        if not submitted or not secrets.compare_digest(submitted, session['admin_csrf_token']):
            abort(400, description='Invalid admin security token.')

@admin_bp.route('/admin', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_console():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save_keys':
            ai_keys = [
                'GEMINI_API_KEY', 'OPENAI_API_KEY', 'AI_DEFAULT_PROVIDER',
                'GEMINI_MODEL', 'OPENAI_MODEL', 'AI_TEMPERATURE', 'AI_SYSTEM_PROMPT'
            ]
            for k in ai_keys:
                form_key = k.lower()
                val = request.form.get(form_key, '').strip()
                if k in ('GEMINI_API_KEY', 'OPENAI_API_KEY') and not val:
                    existing = SystemSetting.query.filter_by(key=k).first()
                    if existing and existing.value:
                        continue
                setting = SystemSetting.query.filter_by(key=k).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=k, value=val))

            feature_keys = [
                'AI_FEATURE_DASHBOARD_INSIGHTS', 'AI_FEATURE_ADMISSIONS_DRAFTING',
                'AI_FEATURE_RETENTION_ADVISORY', 'AI_FEATURE_AUTOMATED_TASKS'
            ]
            for fk in feature_keys:
                form_key = fk.lower()
                val = '1' if request.form.get(form_key) in ('1', 'true', 'on') else '0'
                setting = SystemSetting.query.filter_by(key=fk).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=fk, value=val))

            db.session.commit()
            msg = "AI Configuration, Model Settings & Feature Flags saved successfully!"
            if request.headers.get('X-Requested-With') in ('fetch', 'XMLHttpRequest') or request.is_json:
                return jsonify({'success': True, 'message': msg})
            flash(msg, "success")
            return redirect(url_for('admin.admin_console', _anchor='ai'))
        elif action == 'save_smtp':
            keys = ['SMTP_SERVER', 'SMTP_PORT', 'SMTP_USE_TLS', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'FROM_EMAIL', 'FROM_NAME', 'ADMIN_EMAIL']
            for key in keys:
                val = request.form.get(key, '').strip()
                if key == 'SMTP_PASSWORD' and not val:
                    existing = SystemSetting.query.filter_by(key=key).first()
                    if existing and existing.value:
                        continue
                setting = SystemSetting.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=key, value=val))
            db.session.commit()
            flash("SMTP settings saved successfully!", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'save_whatsapp':
            wa_keys = ['WHATSAPP_TOKEN', 'WHATSAPP_PHONE_ID', 'WHATSAPP_BUSINESS_ID']
            for key in wa_keys:
                val = request.form.get(key, '').strip()
                if key == 'WHATSAPP_TOKEN' and not val:
                    existing = SystemSetting.query.filter_by(key=key).first()
                    if existing and existing.value:
                        continue
                setting = SystemSetting.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=key, value=val))
            db.session.commit()
            flash("WhatsApp API settings saved!", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'send_test_whatsapp':
            test_phone = request.form.get('test_wa_phone', '').strip()
            is_ajax = request.headers.get('X-Requested-With') in ('fetch', 'XMLHttpRequest') or request.is_json
            if test_phone and _valid_phone(test_phone):
                ok, msg = current_app.messenger._send_sms_direct(test_phone, "WhatsApp integration is working! - Guha Academy")
                resp_msg = "Test WhatsApp message sent successfully! Check device." if ok else f"WhatsApp dispatch failed: {msg}"
                if is_ajax:
                    return jsonify({'success': ok, 'message': resp_msg})
                flash(resp_msg, "success" if ok else "danger")
            else:
                if is_ajax:
                    return jsonify({'success': False, 'message': "Enter a valid phone number with country code."}), 400
                flash("Enter a valid phone number with country code.", "warning")
            return redirect(url_for('admin.admin_console', _anchor='ai'))
        elif action == 'whatsapp_fee_reminders':
            result = current_app.messenger.batch_fee_reminders()
            flash(f"Fee reminders: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
            return redirect(url_for('admin.admin_console'))
        elif action == 'whatsapp_attendance_alerts':
            result = current_app.messenger.batch_attendance_alerts()
            flash(f"Attendance alerts: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
            return redirect(url_for('admin.admin_console'))
        elif action == 'whatsapp_exam_schedule':
            course_id = request.form.get('exam_course_id', type=int)
            exam_date = request.form.get('exam_date', '').strip()
            exam_time = request.form.get('exam_time', '10:00 AM').strip()
            venue = request.form.get('exam_venue', 'Main Campus').strip()
            result = current_app.messenger.batch_exam_schedule(course_id=course_id, exam_date=exam_date, exam_time=exam_time, venue=venue)
            flash(f"Exam schedules: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
            return redirect(url_for('admin.admin_console'))
        elif action == 'save_sms':
            sms_keys = ['SMS_GATEWAY_URL', 'SMS_API_KEY', 'SMS_SENDER_ID', 'SMS_PHONE_PARAM', 'SMS_MSG_PARAM', 'SMS_KEY_PARAM', 'SMS_SENDER_PARAM', 'SMS_METHOD']
            for key in sms_keys:
                val = request.form.get(key, '').strip()
                if key == 'SMS_API_KEY' and not val:
                    existing = SystemSetting.query.filter_by(key=key).first()
                    if existing and existing.value:
                        continue
                setting = SystemSetting.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=key, value=val))
            db.session.commit()
            flash("SMS Gateway settings saved!", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'send_test_sms':
            test_phone = request.form.get('test_sms_phone', '').strip()
            is_ajax = request.headers.get('X-Requested-With') in ('fetch', 'XMLHttpRequest') or request.is_json
            if test_phone and _valid_phone(test_phone):
                ok = current_app.sms_service.send_test(test_phone)
                resp_msg = "Test SMS sent successfully!" if ok else "Failed to send test SMS. Check gateway settings."
                if is_ajax:
                    return jsonify({'success': ok, 'message': resp_msg})
                flash(resp_msg, "success" if ok else "danger")
            else:
                if is_ajax:
                    return jsonify({'success': False, 'message': "Enter a valid phone number with country code."}), 400
                flash("Enter a valid phone number with country code.", "warning")
            return redirect(url_for('admin.admin_console', _anchor='ai'))
        elif action == 'sms_fee_reminders':
            result = current_app.sms_service.batch_fee_reminders()
            flash(f"SMS fee reminders: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
            return redirect(url_for('admin.admin_console'))
        elif action == 'sms_attendance_alerts':
            result = current_app.sms_service.batch_attendance_alerts()
            flash(f"SMS attendance alerts: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
            return redirect(url_for('admin.admin_console'))
        elif action == 'sms_exam_schedule':
            course_id = request.form.get('sms_exam_course_id', type=int)
            exam_date = request.form.get('sms_exam_date', '').strip()
            exam_time = request.form.get('sms_exam_time', '10:00 AM').strip()
            venue = request.form.get('sms_exam_venue', 'Main Campus').strip()
            result = current_app.sms_service.batch_exam_schedule(course_id=course_id, exam_date=exam_date, exam_time=exam_time, venue=venue)
            flash(f"SMS exam schedules: {result['sent']} sent, {result['failed']} failed.", "success" if result['sent'] else "warning")
            return redirect(url_for('admin.admin_console'))
        elif action == 'send_test_email':
            test_to = request.form.get('test_email', '').strip()
            if test_to:
                ok = current_app.notifier.send_test(test_to)
                flash("Test email sent! Check your inbox." if ok else "Failed to send test email. Check SMTP settings.", "success" if ok else "danger")
            else:
                flash("Enter a recipient email address.", "warning")
            return redirect(url_for('admin.admin_console'))
        elif action == 'run_notifications':
            results = current_app.notifier.run_all_checks()
            parts = []
            if results['attendance_alerts'] > 0:
                parts.append(f"{results['attendance_alerts']} attendance alert(s)")
            if results['fee_reminders'] > 0:
                parts.append(f"{results['fee_reminders']} fee reminder(s)")
            if results['enquiry_followups'] > 0:
                parts.append(f"{results['enquiry_followups']} follow-up(s)")
            msg = "Notifications sent: " + (", ".join(parts) if parts else "All clear - no alerts needed.")
            flash(msg, "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'toggle_role':
            user_id = request.form.get('user_id')
            is_ajax = request.headers.get('X-Requested-With') == 'fetch'
            user_to_change = User.query.get(user_id)
            if user_to_change:
                if user_to_change.id == current_user.id:
                    msg = "You cannot change your own role."
                    cat = 'danger'
                else:
                    requested_role = request.form.get('role')
                    if requested_role and requested_role not in ('Admin', 'Staff'):
                        msg, cat = 'Unsupported role.', 'danger'
                    elif requested_role == 'Staff' and user_to_change.role == 'Admin' and User.query.filter_by(role='Admin').count() <= 1:
                        msg, cat = 'The last administrator cannot be demoted.', 'danger'
                    else:
                        user_to_change.role = requested_role or ('Admin' if user_to_change.role == 'Staff' else 'Staff')
                        if user_to_change.role == 'Staff':
                            tutor = Tutor.query.filter_by(email=user_to_change.email).first()
                            if not tutor:
                                tutor = Tutor(name=user_to_change.name, email=user_to_change.email, phone='', specialization='', status='Active')
                                db.session.add(tutor)
                        db.session.commit()
                        _audit_admin_action('UPDATE', 'User', user_to_change.id, {'role': user_to_change.role})
                        msg = f"Role for user {user_to_change.username} updated to {user_to_change.role}."
                        cat = 'success'
            else:
                msg = "User not found."
                cat = 'danger'
            if is_ajax:
                return jsonify({'success': cat == 'success', 'message': msg, 'role': user_to_change.role if user_to_change else None})
            flash(msg, cat)
            return redirect(url_for('admin.admin_console', _anchor='users'))
        elif action == 'delete_user':
            user_id = request.form.get('user_id')
            user_to_delete = User.query.get(user_id)
            if user_to_delete:
                if user_to_delete.id == current_user.id:
                    flash("You cannot delete your own account.", "danger")
                else:
                    db.session.delete(user_to_delete)
                    db.session.commit()
                    _audit_admin_action('DELETE', 'User', user_to_delete.id, {'username': user_to_delete.username})
                    flash(f"User account {user_to_delete.username} deleted.", "success")
            return redirect(url_for('admin.admin_console', _anchor='users'))
        elif action == 'save_org':
            # GST rates feed float() on every fee/GST page — reject garbage
            # here instead of 500ing those pages (readers still fall back
            # via get_gst_rates for legacy bad rows).
            gst_rates = {}
            for key, label in (('CGST_PCT', 'CGST'), ('SGST_PCT', 'SGST')):
                try:
                    rate = float(request.form.get(key, '').strip())
                    if not 0 <= rate <= 100:
                        raise ValueError
                    gst_rates[key] = str(rate)
                except (TypeError, ValueError):
                    flash(f"{label} must be a number between 0 and 100.", "danger")
                    return redirect(url_for('admin.admin_console', _anchor='org'))
            if float(gst_rates['CGST_PCT']) + float(gst_rates['SGST_PCT']) > 100:
                flash("Combined CGST and SGST cannot exceed 100%.", "danger")
                return redirect(url_for('admin.admin_console', _anchor='org'))
            gstin = request.form.get('ORG_GSTIN', '').strip().upper()
            if gstin and not re.fullmatch(r'\d{2}[A-Z0-9]{13}', gstin):
                flash("GSTIN must be 15 characters and start with a 2-digit state code.", "danger")
                return redirect(url_for('admin.admin_console', _anchor='org'))
            hsn = request.form.get('ORG_HSN', '').strip()
            if hsn and not re.fullmatch(r'\d{4,8}', hsn):
                flash("HSN/SAC must contain 4 to 8 digits.", "danger")
                return redirect(url_for('admin.admin_console', _anchor='org'))
            state_code = request.form.get('ORG_STATE_CODE', '').strip()
            if state_code and not re.fullmatch(r'\d{1,2}', state_code):
                flash("State code must contain 1 or 2 digits.", "danger")
                return redirect(url_for('admin.admin_console', _anchor='org'))
            prefix = request.form.get('INVOICE_PREFIX', '').strip().upper()
            if prefix and not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,11}', prefix):
                flash("Invoice prefix must be 1-12 characters using letters, numbers, _ or -.", "danger")
                return redirect(url_for('admin.admin_console', _anchor='org'))
            org_keys = ['ORG_NAME', 'ORG_ADDRESS', 'ORG_GSTIN', 'ORG_HSN', 'ORG_STATE', 'ORG_STATE_CODE', 'CGST_PCT', 'SGST_PCT', 'INVOICE_PREFIX']
            previous = {key: (SystemSetting.query.filter_by(key=key).first().value if SystemSetting.query.filter_by(key=key).first() else '') for key in org_keys}
            for key in org_keys:
                if key in gst_rates:
                    val = gst_rates[key]
                else:
                    val = request.form.get(key, '').strip()
                    if key == 'ORG_GSTIN':
                        val = gstin
                    elif key == 'INVOICE_PREFIX':
                        val = prefix
                setting = SystemSetting.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=key, value=val))
            db.session.commit()
            _audit_admin_action('UPDATE', 'Organization', None, {'changed': [k for k in org_keys if previous.get(k) != (SystemSetting.query.filter_by(key=k).first().value if SystemSetting.query.filter_by(key=k).first() else '')]})
            flash("Organization & GST settings saved!", "success")
            return redirect(url_for('admin.admin_console', _anchor='org'))
        elif action == 'save_lifecycle':
            errors = []
            try:
                streak = int(float(request.form.get('LC_ABSENT_STREAK', '').strip()))
                if streak < 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append('Absent-streak must be a whole number of 1 or more.')
            try:
                rate = float(request.form.get('LC_ABSENT_RATE', '').strip())
                if not 0 < rate <= 100:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append('Attendance rate must be a number between 0 and 100.')
            try:
                window = int(float(request.form.get('LC_ATT_WINDOW_DAYS', '').strip()))
                if window < 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append('Attendance window must be a whole number of 1 day or more.')
            if errors:
                for e in errors:
                    flash(e, "danger")
                return redirect(url_for('admin.admin_console'))
            for key, val in [('LC_ABSENT_STREAK', str(streak)),
                             ('LC_ABSENT_RATE', str(rate)),
                             ('LC_ATT_WINDOW_DAYS', str(window))]:
                setting = SystemSetting.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=key, value=val))
            db.session.commit()
            flash("Student lifecycle thresholds saved!", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'reset_db':
            if request.form.get('confirm_reset') != 'RESET DATABASE':
                flash("Type RESET DATABASE to confirm this destructive action.", "danger")
                return redirect(url_for('admin.admin_console', _anchor='db'))
            from init_db import seed_database
            try:
                seed_database()
                _audit_admin_action('RESET', 'Database', None, {'seeded': True})
                flash("Database reset and seeded with premium demo logs successfully!", "success")
            except Exception as e:
                flash(f"Database Reset Error: {e}", "danger")
            return redirect(url_for('admin.admin_console'))
    ai_settings = {}
    for key, default in [
        ('GEMINI_API_KEY', ''), ('OPENAI_API_KEY', ''),
        ('AI_DEFAULT_PROVIDER', 'gemini'),
        ('GEMINI_MODEL', 'gemini-2.5-flash'),
        ('OPENAI_MODEL', 'gpt-4o-mini'),
        ('AI_TEMPERATURE', '0.7'),
        ('AI_SYSTEM_PROMPT', ''),
        ('AI_FEATURE_DASHBOARD_INSIGHTS', '1'),
        ('AI_FEATURE_ADMISSIONS_DRAFTING', '1'),
        ('AI_FEATURE_RETENTION_ADVISORY', '1'),
        ('AI_FEATURE_AUTOMATED_TASKS', '1')
    ]:
        s = SystemSetting.query.filter_by(key=key).first()
        ai_settings[key.lower()] = s.value if s and s.value not in (None, '') else default
        if key == 'GEMINI_API_KEY':
            gemini_key = ai_settings[key.lower()]
        elif key == 'OPENAI_API_KEY':
            openai_key = ai_settings[key.lower()]

    smtp_settings = {}
    for key in ['SMTP_SERVER', 'SMTP_PORT', 'SMTP_USE_TLS', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'FROM_EMAIL', 'FROM_NAME', 'ADMIN_EMAIL']:
        s = SystemSetting.query.filter_by(key=key).first()
        smtp_settings[key.lower()] = s.value if s else ''
    wa_settings = {}
    for key in ['WHATSAPP_TOKEN', 'WHATSAPP_PHONE_ID', 'WHATSAPP_BUSINESS_ID']:
        s = SystemSetting.query.filter_by(key=key).first()
        wa_settings[key.lower()] = s.value if s else ''
    sms_settings = {}
    for key in ['SMS_GATEWAY_URL', 'SMS_API_KEY', 'SMS_SENDER_ID', 'SMS_PHONE_PARAM', 'SMS_MSG_PARAM', 'SMS_KEY_PARAM', 'SMS_SENDER_PARAM', 'SMS_METHOD']:
        s = SystemSetting.query.filter_by(key=key).first()
        sms_settings[key.lower()] = s.value if s else ''
    org_settings = {}
    for key in ['ORG_NAME', 'ORG_ADDRESS', 'ORG_GSTIN', 'ORG_HSN', 'ORG_STATE', 'ORG_STATE_CODE', 'CGST_PCT', 'SGST_PCT', 'INVOICE_PREFIX']:
        s = SystemSetting.query.filter_by(key=key).first()
        org_settings[key.lower()] = s.value if s else ''
    lifecycle_settings = {}
    for key, default in [('LC_ABSENT_STREAK', '3'), ('LC_ABSENT_RATE', '75.0'), ('LC_ATT_WINDOW_DAYS', '30')]:
        s = SystemSetting.query.filter_by(key=key).first()
        lifecycle_settings[key.lower()] = s.value if s and s.value not in (None, '') else default
    db_counts = {
        "courses": Course.query.count(), "students": Student.query.count(), "tutors": Tutor.query.count(),
        "enquiries": Enquiry.query.count(), "fees": FeeRecord.query.count(), "attendance": Attendance.query.count()
    }
    g_active = bool(gemini_key or os.environ.get("GEMINI_API_KEY"))
    o_active = bool(openai_key or os.environ.get("OPENAI_API_KEY"))
    users = User.query.order_by(User.created_at.desc()).all()
    ai_logs = AuditLog.query.filter_by(action='AI_INFER').order_by(AuditLog.timestamp.desc()).limit(10).all()
    backup_dir = get_backup_dir(current_app._get_current_object())
    backup_files = [os.path.join(backup_dir, name) for name in os.listdir(backup_dir)] if os.path.isdir(backup_dir) else []
    latest_backup = max((p for p in backup_files if os.path.isfile(p)), key=os.path.getmtime, default=None)
    system_health = {
        'database': 'healthy',
        'ai': 'configured' if (g_active or o_active) else 'not_configured',
        'smtp': 'configured' if smtp_settings.get('smtp_server') else 'not_configured',
        'sms': 'configured' if sms_settings.get('sms_gateway_url') else 'not_configured',
        'whatsapp': 'configured' if wa_settings.get('whatsapp_token') else 'not_configured',
        'latest_backup': datetime.fromtimestamp(os.path.getmtime(latest_backup), IST).strftime('%d %b %Y %I:%M %p') if latest_backup else None,
    }

    return render_template('admin.html', gemini_key=gemini_key, openai_key=openai_key, ai=ai_settings,
        db_counts=db_counts, g_active=g_active, o_active=o_active, users=users, ai_logs=ai_logs,
        smtp=smtp_settings, wa=wa_settings, sms=sms_settings, org=org_settings,
        lifecycle=lifecycle_settings,
        courses=Course.query.order_by(Course.name).all(), system_health=system_health,
        admin_csrf_token=session['admin_csrf_token'])

@admin_bp.route('/admin/health')
@login_required
@admin_required
def admin_health():
    """Small JSON health summary for monitoring and the admin overview."""
    try:
        db.session.execute(db.text('SELECT 1'))
        database = 'healthy'
    except Exception:
        database = 'failed'
    def configured(*keys):
        return any((SystemSetting.query.filter_by(key=k).first() and SystemSetting.query.filter_by(key=k).first().value) or os.environ.get(k) for k in keys)
    return jsonify({'database': database,
                    'ai': 'configured' if configured('GEMINI_API_KEY', 'OPENAI_API_KEY') else 'not_configured',
                    'smtp': 'configured' if configured('SMTP_SERVER') else 'not_configured',
                    'sms': 'configured' if configured('SMS_GATEWAY_URL') else 'not_configured',
                    'whatsapp': 'configured' if configured('WHATSAPP_TOKEN') else 'not_configured'})

@admin_bp.route('/admin/ai/test-connection', methods=['POST'])
@login_required
@admin_required
def test_ai_connection():
    data = request.get_json(silent=True) or request.form or {}
    provider = data.get('provider', 'gemini')
    if provider not in ('gemini', 'openai'):
        return jsonify({'success': False, 'message': 'Unsupported AI provider.'}), 400
    api_key = data.get('api_key', '').strip()
    
    if hasattr(current_app, 'ai_engine'):
        ai_engine = current_app.ai_engine
    else:
        from app.services.ai_engine import AIEngine
        ai_engine = AIEngine()
        
    result = ai_engine.test_provider_connection(provider=provider, custom_key=api_key)
    return jsonify(result)

@admin_bp.route('/admin/ai/clear-cache', methods=['POST'])
@login_required
@admin_required
def clear_ai_cache():
    if hasattr(current_app, 'ai_engine'):
        ai_engine = current_app.ai_engine
    else:
        from app.services.ai_engine import AIEngine
        ai_engine = AIEngine()
    ai_engine.clear_cache()
    
    # Also purge application analytical cache
    import app as main_app
    import app.routes.dashboard as dashboard
    main_app._sidebar_cache = {"data": None, "time": 0}
    dashboard._stats_cache = {}
    
    return jsonify({
        'success': True,
        'message': 'AI forecast caches, advisory memory, and statistical caches purged successfully!'
    })

@admin_bp.route('/admin/ai/playground', methods=['POST'])
@login_required
@admin_required
def ai_playground():
    import time
    data = request.get_json(silent=True) or request.form or {}
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'success': False, 'message': 'Prompt cannot be empty.'}), 400
    if len(prompt) > 4000:
        return jsonify({'success': False, 'message': 'Prompt is limited to 4,000 characters.'}), 413
    
    provider = data.get('provider') or None
    if provider not in (None, 'auto', 'gemini', 'openai'):
        return jsonify({'success': False, 'message': 'Unsupported AI provider.'}), 400
    if hasattr(current_app, 'ai_engine'):
        ai_engine = current_app.ai_engine
    else:
        from app.services.ai_engine import AIEngine
        ai_engine = AIEngine()
        
    t0 = time.time()
    response_text = ai_engine.call_ai(prompt, provider=provider)
    latency_ms = round((time.time() - t0) * 1000, 1)
    
    if response_text:
        return jsonify({
            'success': True,
            'response': response_text,
            'latency_ms': latency_ms,
            'char_count': len(response_text),
            'word_count': len(response_text.split())
        })
    else:
        return jsonify({
            'success': False,
            'message': 'No response received from the configured AI provider. Please verify API credentials and model configuration.'
        })

@admin_bp.route('/admin/backup')
@login_required
@admin_required
def create_backup():
    backup_dir = get_backup_dir(current_app._get_current_object())
    os.makedirs(backup_dir, exist_ok=True)
    is_ajax = request.headers.get('X-Requested-With') == 'fetch'
    timestamp = ist_now().strftime('%Y%m%d_%H%M%S')

    def finish(success, msg):
        if is_ajax:
            return jsonify({'success': success, 'message': msg})
        flash(msg, 'success' if success else 'danger')
        return redirect(url_for('admin.admin_console'))

    if _db_is_sqlite():
        import shutil
        db_path = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance', 'institute.db')
        if not os.path.exists(db_path):
            return finish(False, 'Database file not found for backup.')
        backup_name = f'institute_backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_name)
        shutil.copy2(db_path, backup_path)
        return finish(True, f'Database backup created: {backup_name}')

    # Postgres (Render) - pg_dump preferred, JSON dump as fallback
    backup_name = f'institute_backup_{timestamp}.json'
    backup_path = os.path.join(backup_dir, backup_name)
    ok, msg = _dump_postgres(backup_path)
    if not ok:
        return finish(False, f'Backup failed: {msg}')
    return finish(True, f'Database backup created: {backup_name}')


def _db_is_sqlite():
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI') or ''
    return uri.startswith('sqlite')


def _json_safe(value):
    from decimal import Decimal
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def _dump_postgres(backup_path):
    """Create a Postgres backup. Tries pg_dump first, falls back to a JSON dump."""
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI') or ''
    try:
        import subprocess
        env = dict(os.environ)
        result = subprocess.run(
            ['pg_dump', db_uri, '-f', backup_path],
            capture_output=True, text=True, timeout=180, env=env
        )
        if result.returncode == 0 and os.path.exists(backup_path) and os.path.getsize(backup_path) > 0:
            return True, None
        fallback_err = (result.stderr or 'pg_dump failed').strip()[-500:]
    except Exception as e:
        fallback_err = f'pg_dump unavailable: {e}'
    try:
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        data = {}
        for t in tables:
            cols = [c['name'] for c in insp.get_columns(t)]
            rows = db.session.execute(db.text(f'SELECT * FROM "{t}"')).fetchall()
            data[t] = [dict(zip(cols, [_json_safe(v) for v in row])) for row in rows]
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1)
        return True, None
    except Exception as e:
        return False, f'{fallback_err}; JSON dump also failed: {e}'

@admin_bp.route('/admin/backups')
@login_required
@admin_required
def list_backups():
    backup_dir = get_backup_dir(current_app._get_current_object())
    os.makedirs(backup_dir, exist_ok=True)
    backups = sorted((b for b in os.listdir(backup_dir) if os.path.isfile(os.path.join(backup_dir, b))), reverse=True)
    backup_files = []
    for b in backups:
        fp = os.path.join(backup_dir, b)
        size = os.path.getsize(fp)
        modified = datetime.fromtimestamp(os.path.getmtime(fp), IST).strftime('%d %b %Y %I:%M %p')
        backup_files.append({"name": b, "size": f"{size/1024:.1f} KB", "modified": modified})
    return jsonify(backup_files)

@admin_bp.route('/admin/backup/restore/<filename>', methods=['POST'])
@login_required
@admin_required
def restore_backup(filename):
    backup_dir = get_backup_dir(current_app._get_current_object())
    if not _backup_path_is_safe(backup_dir, filename):
        flash("Backup file not found.", "danger")
        return redirect(url_for('admin.admin_console'))
    backup_path = os.path.realpath(os.path.join(backup_dir, filename))
    if request.form.get('confirm_restore') != 'RESTORE DATABASE':
        flash("Type RESTORE DATABASE to confirm this destructive action.", "danger")
        return redirect(url_for('admin.admin_console'))
    if filename.endswith('.json'):
        ok, msg = _restore_from_json(backup_path)
        if ok:
            _audit_admin_action('RESTORE', 'Database', None, {'filename': filename})
            flash(f"Database restored from: {filename}.", "success")
        else:
            flash(f"Restore failed: {msg}", "danger")
        return redirect(url_for('admin.admin_console'))
    import shutil
    db_path = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance', 'institute.db')
    shutil.copy2(backup_path, db_path)
    _audit_admin_action('RESTORE', 'Database', None, {'filename': filename})
    flash(f"Database restored from: {filename}. Restarting app...", "success")
    return redirect(url_for('admin.admin_console'))


def _restore_from_json(backup_path):
    """Restore a JSON dump. Deletes existing rows and re-inserts the snapshot."""
    try:
        from sqlalchemy import inspect, text
        with open(backup_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        with db.engine.begin() as conn:
            # Disable FK checks for a clean replace
            if _db_is_sqlite():
                conn.execute(text('PRAGMA foreign_keys = OFF'))
            else:
                conn.execute(text('SET session_replication_role = replica'))
            for t in tables:
                if t in data:
                    conn.execute(text(f'DELETE FROM "{t}"'))
            for t, rows in data.items():
                if t not in tables or not rows:
                    continue
                cols = list(rows[0].keys())
                placeholders = ', '.join([':' + c for c in cols])
                stmt = text(f'INSERT INTO "{t}" ({", ".join(cols)}) VALUES ({placeholders})')
                for row in rows:
                    conn.execute(stmt, row)
            if _db_is_sqlite():
                conn.execute(text('PRAGMA foreign_keys = ON'))
            else:
                conn.execute(text('SET session_replication_role = default'))
        return True, None
    except Exception as e:
        return False, str(e)

# ---------------------------------------------------------------------------
# Database Import (merge from another instance)
# ---------------------------------------------------------------------------
def _tables_in(conn):
    return set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

def _parse_date(val):
    if val is None:
        return date.today()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return datetime.strptime(val, '%Y-%m-%d').date()
        except Exception:
            return date.today()
    return date.today()

def _parse_dt(val):
    if val is None:
        return datetime.utcnow()
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
            try:
                return datetime.strptime(val, fmt)
            except Exception:
                pass
        return datetime.utcnow()
    return datetime.utcnow()

def _analyze_import_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = _tables_in(conn)

    existing = {
        'student_emails': {s.email for s in Student.query.with_entities(Student.email).all()},
        'tutor_emails': {t.email for t in Tutor.query.with_entities(Tutor.email).all()},
        'course_codes': {c.code for c in Course.query.with_entities(Course.code).all()},
        'cat_names': {c.name for c in ExpenseCategory.query.with_entities(ExpenseCategory.name).all()},
    }

    def _summarize(table, unique_col=None, existing_set=None):
        info = {'total': 0, 'new': 0, 'conflicts': 0, 'has_table': False}
        if table in tables:
            info['has_table'] = True
            rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
            info['total'] = len(rows)
            if unique_col and existing_set is not None:
                for r in rows:
                    if r[unique_col] in existing_set:
                        info['conflicts'] += 1
                    else:
                        info['new'] += 1
            else:
                info['new'] = info['total']
        return info

    preview = {
        'courses': _summarize('course', 'code', existing['course_codes']),
        'students': _summarize('student', 'email', existing['student_emails']),
        'tutors': _summarize('tutor', 'email', existing['tutor_emails']),
        'expense_categories': _summarize('expense_category', 'name', existing['cat_names']),
        'enquiries': _summarize('enquiry'),
        'fees': _summarize('fee_record'),
        'attendance': _summarize('attendance'),
        'exams': _summarize('exam'),
        'exam_scores': _summarize('exam_score'),
        'exam_assignments': _summarize('exam_assignment'),
        'expenses': _summarize('expense'),
        'student_courses': _summarize('student_courses'),
        'tutor_courses': _summarize('tutor_courses'),
    }
    preview['has_any'] = any(v['total'] > 0 for v in preview.values())
    conn.close()
    return preview

def _val(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default

def _execute_import(db_path, selected):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = _tables_in(conn)

    id_map = {'student': {}, 'tutor': {}, 'course': {}, 'expense_category': {}, 'exam': {}}
    results = {}

    def _rows(table):
        if table not in tables:
            return []
        return conn.execute(f"SELECT * FROM [{table}]").fetchall()

    def _rv(r, key, default=None):
        return _val(r, key, default)

    # 1. Courses
    if 'courses' in selected:
        imported = skipped = 0
        for r in _rows('course'):
            existing = Course.query.filter_by(code=r['code']).first()
            if existing:
                id_map['course'][r['id']] = existing.id; skipped += 1
            else:
                c = Course(name=r['name'], code=r['code'], description=_rv(r, 'description'),
                           duration_weeks=r['duration_weeks'],
                           duration_unit=_rv(r, 'duration_unit') or 'weeks',
                           fees=r['fees'],
                           gst_applicable=bool(_rv(r, 'gst_applicable', False)),
                           syllabus=_rv(r, 'syllabus'))
                db.session.add(c); db.session.flush()
                id_map['course'][r['id']] = c.id; imported += 1
        results['courses'] = {'imported': imported, 'skipped': skipped}

    # 2. Students
    if 'students' in selected:
        imported = skipped = 0
        for r in _rows('student'):
            existing = Student.query.filter_by(email=r['email']).first()
            if existing:
                id_map['student'][r['id']] = existing.id; skipped += 1
            else:
                s = Student(name=r['name'], email=r['email'], phone=r['phone'],
                           enrollment_date=_parse_date(_rv(r, 'enrollment_date')),
                           status=_rv(r, 'status') or 'Active',
                           qr_code_uuid=_rv(r, 'qr_code_uuid') or str(uuid.uuid4()))
                db.session.add(s); db.session.flush()
                id_map['student'][r['id']] = s.id; imported += 1
        results['students'] = {'imported': imported, 'skipped': skipped}

        if 'student_courses' in tables:
            assoc = 0
            for r in conn.execute("SELECT * FROM student_courses").fetchall():
                ns = id_map['student'].get(r['student_id'])
                nc = id_map['course'].get(r['course_id'])
                if ns and nc:
                    hit = db.session.execute(
                        db.text("SELECT 1 FROM student_courses WHERE student_id=:s AND course_id=:c"),
                        {'s': ns, 'c': nc}).fetchone()
                    if not hit:
                        db.session.execute(
                            db.text("INSERT INTO student_courses (student_id, course_id, enrolled_on) VALUES (:s, :c, CURRENT_DATE)"),
                            {'s': ns, 'c': nc})
                        assoc += 1
            results['student_courses'] = assoc

    # 3. Tutors
    if 'tutors' in selected:
        imported = skipped = 0
        for r in _rows('tutor'):
            existing = Tutor.query.filter_by(email=r['email']).first()
            if existing:
                id_map['tutor'][r['id']] = existing.id; skipped += 1
            else:
                t = Tutor(name=r['name'], email=r['email'], phone=r['phone'],
                         specialization=_rv(r, 'specialization'),
                         status=_rv(r, 'status') or 'Active',
                         qr_code_uuid=_rv(r, 'qr_code_uuid') or str(uuid.uuid4()))
                db.session.add(t); db.session.flush()
                id_map['tutor'][r['id']] = t.id; imported += 1
        results['tutors'] = {'imported': imported, 'skipped': skipped}

        if 'tutor_courses' in tables:
            assoc = 0
            for r in conn.execute("SELECT * FROM tutor_courses").fetchall():
                nt = id_map['tutor'].get(r['tutor_id'])
                nc = id_map['course'].get(r['course_id'])
                if nt and nc:
                    hit = db.session.execute(
                        db.text("SELECT 1 FROM tutor_courses WHERE tutor_id=:t AND course_id=:c"),
                        {'t': nt, 'c': nc}).fetchone()
                    if not hit:
                        db.session.execute(
                            db.text("INSERT INTO tutor_courses (tutor_id, course_id) VALUES (:t, :c)"),
                            {'t': nt, 'c': nc})
                        assoc += 1
            results['tutor_courses'] = assoc

    # 4. Expense Categories
    if 'expense_categories' in selected:
        imported = skipped = 0
        for r in _rows('expense_category'):
            existing = ExpenseCategory.query.filter_by(name=r['name']).first()
            if existing:
                id_map['expense_category'][r['id']] = existing.id; skipped += 1
            else:
                ec = ExpenseCategory(name=r['name'], description=_rv(r, 'description'))
                db.session.add(ec); db.session.flush()
                id_map['expense_category'][r['id']] = ec.id; imported += 1
        results['expense_categories'] = {'imported': imported, 'skipped': skipped}

    # 5. Enquiries
    if 'enquiries' in selected:
        imported = 0
        for r in _rows('enquiry'):
            nc = id_map['course'].get(r['course_id'])
            if not nc:
                continue
            e = Enquiry(student_name=r['student_name'], email=_rv(r, 'email'),
                       phone=r['phone'], course_id=nc,
                       source=_rv(r, 'source') or 'Walk-in',
                       status=_rv(r, 'status') or 'New',
                       notes=_rv(r, 'notes'),
                       created_at=_parse_dt(_rv(r, 'created_at')))
            db.session.add(e); imported += 1
        results['enquiries'] = imported

    # 6. Fees
    if 'fees' in selected:
        imported = 0
        for r in _rows('fee_record'):
            ns = id_map['student'].get(r['student_id'])
            if not ns:
                continue
            f = FeeRecord(student_id=ns, amount_paid=r['amount_paid'],
                         payment_date=_parse_date(_rv(r, 'payment_date')),
                         payment_method=_rv(r, 'payment_method') or 'Cash',
                         remarks=_rv(r, 'remarks'))
            db.session.add(f); imported += 1
        results['fees'] = imported

    # 7. Attendance
    if 'attendance' in selected:
        imported = 0
        for r in _rows('attendance'):
            pid = r['person_id']; ptype = r['person_type']
            new_id = id_map['student'].get(pid) if ptype == 'student' else id_map['tutor'].get(pid) if ptype == 'tutor' else None
            if not new_id:
                continue
            a = Attendance(person_type=ptype, person_id=new_id,
                          date=_parse_date(_rv(r, 'date')),
                          status=_rv(r, 'status') or 'Present',
                          marked_by=_rv(r, 'marked_by') or 'manual',
                          timestamp=_parse_dt(_rv(r, 'timestamp')))
            db.session.add(a); imported += 1
        results['attendance'] = imported

    # 8. Exams
    if 'exams' in selected:
        imported = 0
        for r in _rows('exam'):
            nc = id_map['course'].get(r['course_id'])
            if not nc:
                continue
            ex = Exam(course_id=nc, title=r['title'],
                     exam_date=_parse_date(_rv(r, 'exam_date')),
                     max_marks=r['max_marks'], passing_marks=r['passing_marks'],
                     description=_rv(r, 'description'),
                     exam_type=_rv(r, 'exam_type') or 'manual',
                     num_questions=_rv(r, 'num_questions') or 0,
                     duration_minutes=_rv(r, 'duration_minutes') or 0,
                     is_published=bool(_rv(r, 'is_published', False)),
                     created_at=_parse_dt(_rv(r, 'created_at')))
            db.session.add(ex); db.session.flush()
            id_map['exam'][r['id']] = ex.id; imported += 1
        results['exams'] = imported

    # 9. Exam Scores
    if 'exam_scores' in selected:
        imported = 0
        for r in _rows('exam_score'):
            ne = id_map['exam'].get(r['exam_id'])
            ns = id_map['student'].get(r['student_id'])
            if not ne or not ns:
                continue
            try:
                es = ExamScore(exam_id=ne, student_id=ns,
                              marks_obtained=r['marks_obtained'],
                              remarks=_rv(r, 'remarks'))
                db.session.add(es); imported += 1
            except Exception:
                pass
        results['exam_scores'] = imported

    # 10. Exam Assignments
    if 'exam_assignments' in selected:
        imported = 0
        for r in _rows('exam_assignment'):
            ne = id_map['exam'].get(r['exam_id'])
            ns = id_map['student'].get(r['student_id'])
            if not ne or not ns:
                continue
            ea = ExamAssignment(exam_id=ne, student_id=ns,
                               assigned_by=_rv(r, 'assigned_by') or 1,
                               due_date=_parse_date(_rv(r, 'due_date')),
                               status=_rv(r, 'status') or 'assigned')
            db.session.add(ea); imported += 1
        results['exam_assignments'] = imported

    # 11. Expenses
    if 'expenses' in selected:
        imported = 0
        for r in _rows('expense'):
            nc = id_map['expense_category'].get(r['category_id'])
            if not nc:
                continue
            exp = Expense(category_id=nc, amount=r['amount'],
                         description=r['description'],
                         expense_date=_parse_date(_rv(r, 'expense_date')),
                         created_by=_rv(r, 'created_by'),
                         created_at=_parse_dt(_rv(r, 'created_at')))
            db.session.add(exp); imported += 1
        results['expenses'] = imported

    db.session.commit()
    conn.close()
    return results

@admin_bp.route('/admin/import-database', methods=['GET', 'POST'])
@login_required
@admin_required
def import_database():
    temp_dir = os.path.join(current_app.instance_path, 'imports')
    os.makedirs(temp_dir, exist_ok=True)

    if request.method == 'POST':
        # Step 1 — file upload
        if 'db_file' in request.files:
            file = request.files['db_file']
            if not file.filename:
                flash('Please select a .db file to import.', 'warning')
                return redirect(url_for('admin.import_database'))
            safe = f'import_{uuid.uuid4().hex}.db'
            temp_path = os.path.join(temp_dir, safe)
            file.save(temp_path)
            try:
                preview = _analyze_import_db(temp_path)
            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                flash(f'Could not read database: {e}', 'danger')
                return redirect(url_for('admin.import_database'))
            return render_template('admin_import.html', preview=preview, temp_path=temp_path)

        # Step 2 — confirm import
        if 'confirm_import' in request.form:
            temp_path = request.form.get('temp_path', '')
            if not temp_path or not os.path.exists(temp_path):
                flash('Import file expired. Please upload again.', 'danger')
                return redirect(url_for('admin.import_database'))
            selected = request.form.getlist('tables')
            try:
                results = _execute_import(temp_path, selected)
                return render_template('admin_import.html', results=results)
            except Exception as e:
                flash(f'Import failed: {e}', 'danger')
                return redirect(url_for('admin.import_database'))
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    return render_template('admin_import.html')


def _audit_entity_label(et):
    labels = {
        'Student': 'Student', 'Tutor': 'Tutor', 'Course': 'Course',
        'Enquiry': 'Enquiry', 'FeeRecord': 'Fee Record', 'Attendance': 'Attendance',
        'Expense': 'Expense', 'ExpenseCategory': 'Expense Category',
        'Exam': 'Exam', 'ExamScore': 'Exam Score', 'ExamAssignment': 'Exam Assignment',
        'User': 'User', 'LeaveRequest': 'Leave Request', 'PayrollRecord': 'Payroll Record',
    }
    return labels.get(et, et)


@admin_bp.route('/admin/audit-log')
@login_required
@admin_required
def audit_log():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    entity_filter = request.args.get('entity', '')
    action_filter = request.args.get('action', '')

    q = AuditLog.query
    if entity_filter:
        q = q.filter(AuditLog.entity_type == entity_filter)
    if action_filter:
        q = q.filter(AuditLog.action == action_filter)

    total = q.count()
    logs = q.order_by(AuditLog.timestamp.desc()).offset((page - 1) * per_page).limit(per_page).all()

    entity_types = [r[0] for r in db.session.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all()]

    return render_template('admin_audit.html', logs=logs, page=page, per_page=per_page, total=total,
                           entity_filter=entity_filter, action_filter=action_filter,
                           entity_types=entity_types, label=_audit_entity_label)


@admin_bp.route('/admin/_diag-accounts')
@login_required
@admin_required
def diag_accounts():
    if not current_app.config.get('ENABLE_ADMIN_DIAGNOSTICS', False):
        return jsonify({'error': 'Not found'}), 404
    rows = db.session.execute(db.text(
        "SELECT id, name, account_type, is_active FROM account ORDER BY id"
    )).fetchall()
    return jsonify({
        'uri': '[redacted]',
        'accounts': [{'id': r[0], 'name': r[1], 'account_type': r[2], 'is_active': r[3]} for r in rows],
        'payment_methods': [r[0] for r in db.session.execute(db.text(
            "SELECT DISTINCT payment_method FROM fee_record WHERE payment_method IS NOT NULL ORDER BY 1")).fetchall()],
    })
