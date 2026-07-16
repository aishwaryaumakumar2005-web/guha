import os
import json
import uuid
import sqlite3
from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, Course, Student, Tutor, Enquiry, FeeRecord, Attendance, SystemSetting, ExpenseCategory, Expense, Exam, ExamScore, ExamAssignment, AuditLog
from app.helpers import admin_required, get_backup_dir

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_console():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save_keys':
            gemini_val = request.form.get('gemini_api_key', '').strip()
            openai_val = request.form.get('openai_api_key', '').strip()
            g_setting = SystemSetting.query.filter_by(key='GEMINI_API_KEY').first()
            if g_setting:
                g_setting.value = gemini_val
            else:
                db.session.add(SystemSetting(key='GEMINI_API_KEY', value=gemini_val))
            o_setting = SystemSetting.query.filter_by(key='OPENAI_API_KEY').first()
            if o_setting:
                o_setting.value = openai_val
            else:
                db.session.add(SystemSetting(key='OPENAI_API_KEY', value=openai_val))
            db.session.commit()
            flash("AI Credentials saved and applied instantly!", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'save_smtp':
            keys = ['SMTP_SERVER', 'SMTP_PORT', 'SMTP_USE_TLS', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'FROM_EMAIL', 'FROM_NAME', 'ADMIN_EMAIL']
            for key in keys:
                val = request.form.get(key, '').strip()
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
            if test_phone:
                ok, msg = current_app.messenger._send_sms_direct(test_phone, "WhatsApp integration is working! - Guha Academy")
                flash("Test message sent! Check your WhatsApp." if ok else f"Failed: {msg}", "success" if ok else "danger")
            else:
                flash("Enter a recipient phone number.", "warning")
            return redirect(url_for('admin.admin_console'))
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
            if test_phone:
                ok = current_app.sms_service.send_test(test_phone)
                flash("Test SMS sent!" if ok else "Failed to send test SMS. Check gateway settings.", "success" if ok else "danger")
            else:
                flash("Enter a recipient phone number.", "warning")
            return redirect(url_for('admin.admin_console'))
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
            user_to_change = User.query.get(user_id)
            if user_to_change:
                if user_to_change.id == current_user.id:
                    flash("You cannot change your own role.", "danger")
                else:
                    user_to_change.role = 'Admin' if user_to_change.role == 'Staff' else 'Staff'
                    if user_to_change.role == 'Staff':
                        tutor = Tutor.query.filter_by(email=user_to_change.email).first()
                        if not tutor:
                            tutor = Tutor(name=user_to_change.name, email=user_to_change.email, phone='', specialization='', status='Active')
                            db.session.add(tutor)
                    db.session.commit()
                    flash(f"Role for user {user_to_change.username} updated to {user_to_change.role}.", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'delete_user':
            user_id = request.form.get('user_id')
            user_to_delete = User.query.get(user_id)
            if user_to_delete:
                if user_to_delete.id == current_user.id:
                    flash("You cannot delete your own account.", "danger")
                else:
                    db.session.delete(user_to_delete)
                    db.session.commit()
                    flash(f"User account {user_to_delete.username} deleted.", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'save_org':
            org_keys = ['ORG_NAME', 'ORG_ADDRESS', 'ORG_GSTIN', 'ORG_HSN', 'ORG_STATE', 'ORG_STATE_CODE', 'CGST_PCT', 'SGST_PCT', 'INVOICE_PREFIX']
            for key in org_keys:
                val = request.form.get(key, '').strip()
                setting = SystemSetting.query.filter_by(key=key).first()
                if setting:
                    setting.value = val
                else:
                    db.session.add(SystemSetting(key=key, value=val))
            db.session.commit()
            flash("Organization & GST settings saved!", "success")
            return redirect(url_for('admin.admin_console'))
        elif action == 'reset_db':
            from init_db import seed_database
            try:
                seed_database()
                flash("Database reset and seeded with premium demo logs successfully!", "success")
            except Exception as e:
                flash(f"Database Reset Error: {e}", "danger")
            return redirect(url_for('admin.admin_console'))
    gemini_key = ""
    g_setting = SystemSetting.query.filter_by(key='GEMINI_API_KEY').first()
    if g_setting:
        gemini_key = g_setting.value
    openai_key = ""
    o_setting = SystemSetting.query.filter_by(key='OPENAI_API_KEY').first()
    if o_setting:
        openai_key = o_setting.value
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
    db_counts = {
        "courses": Course.query.count(), "students": Student.query.count(), "tutors": Tutor.query.count(),
        "enquiries": Enquiry.query.count(), "fees": FeeRecord.query.count(), "attendance": Attendance.query.count()
    }
    g_active = bool(gemini_key or os.environ.get("GEMINI_API_KEY"))
    o_active = bool(openai_key or os.environ.get("OPENAI_API_KEY"))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin.html', gemini_key=gemini_key, openai_key=openai_key,
        db_counts=db_counts, g_active=g_active, o_active=o_active, users=users,
        smtp=smtp_settings, wa=wa_settings, sms=sms_settings, org=org_settings,
        courses=Course.query.order_by(Course.name).all())

@admin_bp.route('/admin/backup')
@login_required
@admin_required
def create_backup():
    import shutil
    backup_dir = get_backup_dir(current_app._get_current_object())
    os.makedirs(backup_dir, exist_ok=True)
    db_path = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance', 'institute.db')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'institute_backup_{timestamp}.db'
    backup_path = os.path.join(backup_dir, backup_name)
    shutil.copy2(db_path, backup_path)
    flash(f"Database backup created: {backup_name}", "success")
    return redirect(url_for('admin.admin_console'))

@admin_bp.route('/admin/backups')
@login_required
@admin_required
def list_backups():
    backup_dir = get_backup_dir(current_app._get_current_object())
    os.makedirs(backup_dir, exist_ok=True)
    backups = sorted(os.listdir(backup_dir), reverse=True)
    backup_files = []
    for b in backups:
        fp = os.path.join(backup_dir, b)
        size = os.path.getsize(fp)
        modified = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%d %b %Y %I:%M %p')
        backup_files.append({"name": b, "size": f"{size/1024:.1f} KB", "modified": modified})
    return jsonify(backup_files)

@admin_bp.route('/admin/backup/restore/<filename>')
@login_required
@admin_required
def restore_backup(filename):
    import shutil
    backup_dir = get_backup_dir(current_app._get_current_object())
    backup_path = os.path.join(backup_dir, filename)
    if not os.path.exists(backup_path):
        flash("Backup file not found.", "danger")
        return redirect(url_for('admin.admin_console'))
    db_path = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance', 'institute.db')
    shutil.copy2(backup_path, db_path)
    flash(f"Database restored from: {filename}. Restarting app...", "success")
    return redirect(url_for('admin.admin_console'))

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
                            db.text("INSERT INTO student_courses (student_id, course_id) VALUES (:s, :c)"),
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
