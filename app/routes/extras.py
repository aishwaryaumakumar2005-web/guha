import os
import csv
import json
import uuid
import shutil
import time
from io import StringIO
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app, send_from_directory, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models import (
    User, Student, Tutor, Course, Enquiry, FeeRecord, Attendance,
    Expense, ExpenseCategory, Exam, Task, AuditLog, student_courses, tutor_courses
)
from app.helpers import admin_required, get_backup_dir

IST = timezone(timedelta(hours=5, minutes=30))

extras_bp = Blueprint('extras', __name__)


def ist_now():
    return datetime.now(IST)


def _db_is_sqlite():
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI') or ''
    return uri.startswith('sqlite')


def _get_db_type_and_label():
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI') or ''
    if uri.startswith('sqlite'):
        return 'SQLite', 'SQLite Local DB (instance/institute.db)'
    if 'neon.tech' in uri or 'postgresql' in uri or 'postgres' in uri:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(uri)
            host = parsed.hostname or 'PostgreSQL'
            return 'PostgreSQL', f'PostgreSQL ({host})'
        except Exception:
            return 'PostgreSQL', 'PostgreSQL Cloud Database'
    return 'SQLAlchemy', 'Relational Database'


def _json_safe(value):
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


def _restore_from_json(backup_path):
    """Restore a JSON dump. Deletes existing rows and re-inserts the snapshot."""
    try:
        from sqlalchemy import inspect, text
        with open(backup_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        with db.engine.begin() as conn:
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


def _get_backup_list():
    backup_dir = get_backup_dir(current_app._get_current_object())
    os.makedirs(backup_dir, exist_ok=True)
    backups = sorted(os.listdir(backup_dir), reverse=True)
    backup_files = []
    total_bytes = 0
    for b in backups:
        fp = os.path.join(backup_dir, b)
        if not os.path.isfile(fp):
            continue
        size = os.path.getsize(fp)
        total_bytes += size
        modified_dt = datetime.fromtimestamp(os.path.getmtime(fp), IST)
        modified_str = modified_dt.strftime('%d %b %Y %I:%M %p')
        ext = os.path.splitext(b)[1].lower().replace('.', '') or 'file'
        backup_files.append({
            "name": b,
            "size": f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.2f} MB",
            "size_bytes": size,
            "modified": modified_str,
            "format": ext.upper(),
            "timestamp": int(os.path.getmtime(fp)),
        })
    return backup_files, total_bytes


def _measure_db_latency():
    try:
        t0 = time.time()
        db.session.execute(db.text("SELECT 1")).fetchone()
        latency_ms = round((time.time() - t0) * 1000, 1)
        return latency_ms, "Healthy"
    except Exception as e:
        return None, f"Error: {e}"


def _get_table_counts():
    try:
        counts = {
            'students': Student.query.count(),
            'tutors': Tutor.query.count(),
            'courses': Course.query.count(),
            'enquiries': Enquiry.query.count(),
            'fees': FeeRecord.query.count(),
            'attendance': Attendance.query.count(),
            'expenses': Expense.query.count(),
            'exams': Exam.query.count(),
            'tasks': Task.query.count(),
            'audit_logs': AuditLog.query.count(),
        }
        total_records = sum(counts.values())
        return counts, total_records
    except Exception:
        return {}, 0


def _run_integrity_scan():
    """Run diagnostics to verify data consistency and flag orphaned records."""
    checks = []
    issues_count = 0

    # 1. Orphaned Fee Records (payments pointing to non-existent students)
    try:
        orphan_fees = FeeRecord.query.filter(
            ~FeeRecord.student_id.in_(db.session.query(Student.id))
        ).count()
        if orphan_fees > 0:
            issues_count += orphan_fees
            checks.append({
                'name': 'Fee Records Linkage',
                'status': 'warning',
                'detail': f'Found {orphan_fees} orphaned fee records without a valid student ID.'
            })
        else:
            checks.append({
                'name': 'Fee Records Linkage',
                'status': 'clean',
                'detail': 'All fee records link to valid students.'
            })
    except Exception as e:
        checks.append({'name': 'Fee Records Linkage', 'status': 'error', 'detail': str(e)})

    # 2. Ghost Course Enrollments
    try:
        ghost_student_enrollments = db.session.query(student_courses).filter(
            ~student_courses.c.student_id.in_(db.session.query(Student.id))
        ).count()
        ghost_course_enrollments = db.session.query(student_courses).filter(
            ~student_courses.c.course_id.in_(db.session.query(Course.id))
        ).count()
        ghost_total = ghost_student_enrollments + ghost_course_enrollments
        if ghost_total > 0:
            issues_count += ghost_total
            checks.append({
                'name': 'Course Enrollments',
                'status': 'warning',
                'detail': f'Found {ghost_total} orphaned enrollment mappings.'
            })
        else:
            checks.append({
                'name': 'Course Enrollments',
                'status': 'clean',
                'detail': 'All course enrollment relations are valid.'
            })
    except Exception as e:
        checks.append({'name': 'Course Enrollments', 'status': 'error', 'detail': str(e)})

    # 3. QR Code Consistency
    try:
        students_no_qr = Student.query.filter(
            db.or_(Student.qr_code_uuid.is_(None), Student.qr_code_uuid == '')
        ).count()
        tutors_no_qr = Tutor.query.filter(
            db.or_(Tutor.qr_code_uuid.is_(None), Tutor.qr_code_uuid == '')
        ).count()
        missing_qr_total = students_no_qr + tutors_no_qr
        if missing_qr_total > 0:
            checks.append({
                'name': 'QR Code Identifiers',
                'status': 'warning',
                'detail': f'{missing_qr_total} users ({students_no_qr} students, {tutors_no_qr} staff) missing QR UUIDs.'
            })
        else:
            checks.append({
                'name': 'QR Code Identifiers',
                'status': 'clean',
                'detail': 'All active students and tutors have QR code UUIDs.'
            })
    except Exception as e:
        checks.append({'name': 'QR Code Identifiers', 'status': 'error', 'detail': str(e)})

    # 4. Expense Categorization Integrity
    try:
        valid_cat_ids = db.session.query(ExpenseCategory.id)
        orphan_expenses = Expense.query.filter(
            db.and_(Expense.category_id.isnot(None), ~Expense.category_id.in_(valid_cat_ids))
        ).count()
        if orphan_expenses > 0:
            issues_count += orphan_expenses
            checks.append({
                'name': 'Expense Categorization',
                'status': 'warning',
                'detail': f'Found {orphan_expenses} expenses referencing deleted categories.'
            })
        else:
            checks.append({
                'name': 'Expense Categorization',
                'status': 'clean',
                'detail': 'All expenses map to valid categories.'
            })
    except Exception as e:
        checks.append({'name': 'Expense Categorization', 'status': 'error', 'detail': str(e)})

    # 5. Database Performance Ping
    latency_ms, db_status = _measure_db_latency()
    checks.append({
        'name': 'Query Latency & Connection',
        'status': 'clean' if db_status == 'Healthy' else 'error',
        'detail': f'Database responsive ({latency_ms} ms ping latency).'
    })

    score = max(0, 100 - (issues_count * 5))
    return {
        'timestamp': ist_now().strftime('%d %b %Y %I:%M %p'),
        'issues_count': issues_count,
        'integrity_score': score,
        'checks': checks
    }


@extras_bp.route('/extras', methods=['GET'])
@login_required
@admin_required
def extras():
    db_type, db_label = _get_db_type_and_label()
    backup_files, total_bytes = _get_backup_list()
    total_size_str = f"{total_bytes/1024:.1f} KB" if total_bytes < 1024*1024 else f"{total_bytes/(1024*1024):.2f} MB"
    last_backup = backup_files[0]['modified'] if backup_files else 'Never'
    latency_ms, db_status = _measure_db_latency()
    table_counts, total_records = _get_table_counts()

    stats = {
        'total_backups': len(backup_files),
        'total_size': total_size_str,
        'last_backup': last_backup,
        'db_type': db_type,
        'db_label': db_label,
        'db_latency': latency_ms,
        'db_status': db_status,
        'total_records': total_records,
    }

    return render_template('extras.html',
                           stats=stats,
                           backups=backup_files,
                           table_counts=table_counts,
                           total_records=total_records)


@extras_bp.route('/extras/backups', methods=['GET'])
@login_required
@admin_required
def list_backups_api():
    backup_files, _ = _get_backup_list()
    return jsonify(backup_files)


@extras_bp.route('/extras/backup/create', methods=['POST', 'GET'])
@login_required
@admin_required
def create_backup():
    backup_dir = get_backup_dir(current_app._get_current_object())
    os.makedirs(backup_dir, exist_ok=True)
    is_ajax = request.headers.get('X-Requested-With') in ('fetch', 'XMLHttpRequest') or request.is_json
    timestamp = ist_now().strftime('%Y%m%d_%H%M%S')

    def finish(success, msg, backup_name=None):
        if is_ajax:
            return jsonify({'success': success, 'message': msg, 'filename': backup_name})
        flash(msg, 'success' if success else 'danger')
        return redirect(url_for('extras.extras'))

    if _db_is_sqlite():
        db_path = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance', 'institute.db')
        if not os.path.exists(db_path):
            return finish(False, 'Database file not found for backup.')
        backup_name = f'institute_backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_name)
        try:
            shutil.copy2(db_path, backup_path)
            return finish(True, f'Database backup created: {backup_name}', backup_name)
        except Exception as e:
            return finish(False, f'Backup failed: {e}')

    # PostgreSQL (Render)
    backup_name = f'institute_backup_{timestamp}.json'
    backup_path = os.path.join(backup_dir, backup_name)
    ok, msg = _dump_postgres(backup_path)
    if not ok:
        return finish(False, f'Backup failed: {msg}')
    return finish(True, f'Database backup created: {backup_name}', backup_name)


@extras_bp.route('/extras/backup/download/<path:filename>', methods=['GET'])
@login_required
@admin_required
def download_backup(filename):
    clean_name = secure_filename(filename)
    backup_dir = get_backup_dir(current_app._get_current_object())
    file_path = os.path.join(backup_dir, clean_name)

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        flash("Backup file not found.", "danger")
        return redirect(url_for('extras.extras'))

    return send_from_directory(backup_dir, clean_name, as_attachment=True)


@extras_bp.route('/extras/backup/delete/<path:filename>', methods=['POST'])
@login_required
@admin_required
def delete_backup(filename):
    clean_name = secure_filename(filename)
    backup_dir = get_backup_dir(current_app._get_current_object())
    file_path = os.path.join(backup_dir, clean_name)
    is_ajax = request.headers.get('X-Requested-With') in ('fetch', 'XMLHttpRequest') or request.is_json

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        if is_ajax:
            return jsonify({'success': False, 'message': 'Backup file not found.'}), 404
        flash("Backup file not found.", "danger")
        return redirect(url_for('extras.extras'))

    try:
        os.remove(file_path)
        msg = f"Backup '{clean_name}' deleted successfully."
        if is_ajax:
            return jsonify({'success': True, 'message': msg})
        flash(msg, "success")
    except Exception as e:
        msg = f"Failed to delete backup: {e}"
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 500
        flash(msg, "danger")

    return redirect(url_for('extras.extras'))


@extras_bp.route('/extras/backup/restore/<path:filename>', methods=['POST', 'GET'])
@login_required
@admin_required
def restore_backup(filename):
    clean_name = secure_filename(filename)
    backup_dir = get_backup_dir(current_app._get_current_object())
    backup_path = os.path.join(backup_dir, clean_name)
    is_ajax = request.headers.get('X-Requested-With') in ('fetch', 'XMLHttpRequest') or request.is_json

    if not os.path.exists(backup_path):
        msg = "Backup file not found."
        if is_ajax:
            return jsonify({'success': False, 'message': msg}), 404
        flash(msg, "danger")
        return redirect(url_for('extras.extras'))

    if clean_name.endswith('.json'):
        ok, msg = _restore_from_json(backup_path)
        if ok:
            succ_msg = f"Database restored successfully from: {clean_name}"
            if is_ajax:
                return jsonify({'success': True, 'message': succ_msg})
            flash(succ_msg, "success")
        else:
            err_msg = f"Restore failed: {msg}"
            if is_ajax:
                return jsonify({'success': False, 'message': err_msg}), 500
            flash(err_msg, "danger")
        return redirect(url_for('extras.extras'))

    if clean_name.endswith('.db') or clean_name.endswith('.sqlite'):
        if not _db_is_sqlite():
            err_msg = "Cannot restore a SQLite .db file directly into a PostgreSQL database. Please use a .json backup or migration tool."
            if is_ajax:
                return jsonify({'success': False, 'message': err_msg}), 400
            flash(err_msg, "danger")
            return redirect(url_for('extras.extras'))

        db_path = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance', 'institute.db')
        try:
            shutil.copy2(backup_path, db_path)
            succ_msg = f"Database restored from: {clean_name}."
            if is_ajax:
                return jsonify({'success': True, 'message': succ_msg})
            flash(succ_msg, "success")
        except Exception as e:
            err_msg = f"Restore failed: {e}"
            if is_ajax:
                return jsonify({'success': False, 'message': err_msg}), 500
            flash(err_msg, "danger")
        return redirect(url_for('extras.extras'))

    err_msg = f"Unsupported backup format for file: {clean_name}"
    if is_ajax:
        return jsonify({'success': False, 'message': err_msg}), 400
    flash(err_msg, "danger")
    return redirect(url_for('extras.extras'))


@extras_bp.route('/extras/backup/upload', methods=['POST'])
@login_required
@admin_required
def upload_backup():
    if 'backup_file' not in request.files:
        flash('No file selected.', 'warning')
        return redirect(url_for('extras.extras'))

    file = request.files['backup_file']
    if not file.filename:
        flash('Please select a valid backup file (.json or .db).', 'warning')
        return redirect(url_for('extras.extras'))

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.json', '.db', '.sqlite'):
        flash('Invalid file extension. Please upload a .json or .db backup file.', 'danger')
        return redirect(url_for('extras.extras'))

    backup_dir = get_backup_dir(current_app._get_current_object())
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = ist_now().strftime('%Y%m%d_%H%M%S')
    save_name = f'uploaded_{timestamp}_{filename}'
    save_path = os.path.join(backup_dir, save_name)

    try:
        file.save(save_path)
    except Exception as e:
        flash(f'Failed to save uploaded file: {e}', 'danger')
        return redirect(url_for('extras.extras'))

    should_restore = request.form.get('auto_restore') == '1'
    if should_restore:
        if ext == '.json':
            ok, msg = _restore_from_json(save_path)
            if ok:
                flash(f'Backup uploaded and restored successfully: {save_name}', 'success')
            else:
                flash(f'Backup uploaded, but restore failed: {msg}', 'danger')
        elif ext in ('.db', '.sqlite') and _db_is_sqlite():
            db_path = os.path.join(os.path.dirname(os.path.abspath(current_app.root_path)), 'instance', 'institute.db')
            try:
                shutil.copy2(save_path, db_path)
                flash(f'Backup uploaded and restored successfully: {save_name}', 'success')
            except Exception as e:
                flash(f'Backup uploaded, but restore failed: {e}', 'danger')
        else:
            flash(f'Backup uploaded as {save_name}. Direct restore skipped due to engine difference.', 'warning')
    else:
        flash(f'Backup uploaded successfully as: {save_name}', 'success')

    return redirect(url_for('extras.extras'))


# ---------------------------------------------------------------------------
# Diagnostics & Health Scanner
# ---------------------------------------------------------------------------
@extras_bp.route('/extras/diagnostics/scan', methods=['GET', 'POST'])
@login_required
@admin_required
def diagnostics_scan():
    report = _run_integrity_scan()
    return jsonify(report)


# ---------------------------------------------------------------------------
# System Maintenance & Cache Flush
# ---------------------------------------------------------------------------
@extras_bp.route('/extras/maintenance/flush-cache', methods=['POST'])
@login_required
@admin_required
def flush_cache():
    try:
        from app.routes.dashboard import _stats_cache
        _stats_cache.clear()
    except Exception:
        pass
    return jsonify({
        'success': True,
        'message': 'Dashboard stats cache and temporary data purged successfully.'
    })


# ---------------------------------------------------------------------------
# Bulk Data Export Center (Direct CSV Streams)
# ---------------------------------------------------------------------------
def _csv_response(rows, filename):
    """Generate a downloadable CSV response with UTF-8 BOM for Excel compatibility."""
    si = StringIO()
    si.write('\ufeff')  # UTF-8 BOM
    writer = csv.writer(si)
    for row in rows:
        writer.writerow(row)
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@extras_bp.route('/extras/export/students.csv', methods=['GET'])
@login_required
@admin_required
def export_students_csv():
    students = Student.query.order_by(Student.id.asc()).all()
    rows = [['Student ID', 'Roll No', 'Name', 'Email', 'Phone', 'Enrollment Date', 'Status', 'QR UUID']]
    for s in students:
        rows.append([
            s.id,
            s.roll_no or '',
            s.name or '',
            s.email or '',
            s.phone or '',
            s.enrollment_date.strftime('%Y-%m-%d') if s.enrollment_date else '',
            s.status or 'Active',
            s.qr_code_uuid or ''
        ])
    filename = f"students_master_{ist_now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


@extras_bp.route('/extras/export/fees.csv', methods=['GET'])
@login_required
@admin_required
def export_fees_csv():
    fees = FeeRecord.query.order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).all()
    rows = [['Payment ID', 'Student ID', 'Student Name', 'Roll No', 'Amount Paid', 'Payment Date', 'Method', 'Concession', 'Remarks']]
    for f in fees:
        s_name = f.student.name if f.student else 'Unknown'
        s_roll = f.student.roll_no if f.student else ''
        rows.append([
            f.id,
            f.student_id,
            s_name,
            s_roll,
            f"{f.amount_paid:.2f}",
            f.payment_date.strftime('%Y-%m-%d') if f.payment_date else '',
            f.payment_method or 'Cash',
            f"{f.concession:.2f}" if f.concession else "0.00",
            f.remarks or ''
        ])
    filename = f"fees_ledger_{ist_now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


@extras_bp.route('/extras/export/attendance.csv', methods=['GET'])
@login_required
@admin_required
def export_attendance_csv():
    records = Attendance.query.order_by(Attendance.date.desc(), Attendance.id.desc()).limit(2000).all()
    rows = [['Attendance ID', 'Date', 'Person Type', 'Person ID', 'Status', 'Marked By', 'Timestamp']]
    for a in records:
        rows.append([
            a.id,
            a.date.strftime('%Y-%m-%d') if a.date else '',
            a.person_type or 'student',
            a.person_id,
            a.status or 'Present',
            a.marked_by or 'manual',
            a.timestamp.strftime('%Y-%m-%d %H:%M:%S') if a.timestamp else ''
        ])
    filename = f"attendance_register_{ist_now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


@extras_bp.route('/extras/export/enquiries.csv', methods=['GET'])
@login_required
@admin_required
def export_enquiries_csv():
    enquiries = Enquiry.query.order_by(Enquiry.created_at.desc(), Enquiry.id.desc()).all()
    rows = [['Enquiry ID', 'Student Name', 'Email', 'Phone', 'Course ID', 'Source', 'Status', 'Created Date', 'Notes']]
    for e in enquiries:
        rows.append([
            e.id,
            e.student_name or '',
            e.email or '',
            e.phone or '',
            e.course_id or '',
            e.source or 'Walk-in',
            e.status or 'New',
            e.created_at.strftime('%Y-%m-%d') if e.created_at else '',
            (e.notes or '').replace('\n', ' ')
        ])
    filename = f"enquiries_pipeline_{ist_now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


@extras_bp.route('/extras/export/expenses.csv', methods=['GET'])
@login_required
@admin_required
def export_expenses_csv():
    expenses = Expense.query.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    rows = [['Expense ID', 'Date', 'Category ID', 'Description', 'Amount', 'Payment Method']]
    for exp in expenses:
        rows.append([
            exp.id,
            exp.expense_date.strftime('%Y-%m-%d') if exp.expense_date else '',
            exp.category_id or '',
            (exp.description or '').replace('\n', ' '),
            f"{exp.amount:.2f}",
            exp.payment_method or 'Cash'
        ])
    filename = f"expenses_ledger_{ist_now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


@extras_bp.route('/extras/export/tutors.csv', methods=['GET'])
@login_required
@admin_required
def export_tutors_csv():
    tutors = Tutor.query.order_by(Tutor.id.asc()).all()
    rows = [['Tutor ID', 'Name', 'Email', 'Phone', 'Specialization', 'Status', 'QR UUID']]
    for t in tutors:
        rows.append([
            t.id,
            t.name or '',
            t.email or '',
            t.phone or '',
            t.specialization or '',
            t.status or 'Active',
            t.qr_code_uuid or ''
        ])
    filename = f"tutors_directory_{ist_now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)
