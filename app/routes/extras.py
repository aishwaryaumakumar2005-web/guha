import os
import json
import uuid
import shutil
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
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
        # Extract host safely without credentials
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


@extras_bp.route('/extras', methods=['GET'])
@login_required
@admin_required
def extras():
    db_type, db_label = _get_db_type_and_label()
    backup_files, total_bytes = _get_backup_list()
    total_size_str = f"{total_bytes/1024:.1f} KB" if total_bytes < 1024*1024 else f"{total_bytes/(1024*1024):.2f} MB"
    last_backup = backup_files[0]['modified'] if backup_files else 'Never'

    stats = {
        'total_backups': len(backup_files),
        'total_size': total_size_str,
        'last_backup': last_backup,
        'db_type': db_type,
        'db_label': db_label,
    }

    return render_template('extras.html', stats=stats, backups=backup_files)


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
