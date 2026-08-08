import os
import uuid
from functools import wraps
from flask import request, redirect, url_for, flash, current_app
from flask_login import current_user
from app.extensions import db

ALLOWED_PHOTO_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def save_photo_data(file_storage, max_mb=4):
    """Validate an uploaded photo and return (raw_bytes, mime) for DB storage, or None."""
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None
    name = file_storage.filename
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in ALLOWED_PHOTO_EXT:
        raise ValueError(f"Unsupported photo format: .{ext or 'unknown'}")
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > max_mb * 1024 * 1024:
        raise ValueError(f"Photo exceeds {max_mb}MB limit")
    data = file_storage.read()
    mime = getattr(file_storage, 'mimetype', None) or f'image/{ext if ext != "jpg" else "jpeg"}'
    if mime.startswith('application/octet-stream') or '/' not in mime:
        mime = f'image/{ext if ext != "jpg" else "jpeg"}'
    return data, mime


def save_photo(file_storage, max_mb=4):
    """Legacy: persist an uploaded photo into static/uploads and return its filename, or None."""
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None
    name = file_storage.filename
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in ALLOWED_PHOTO_EXT:
        raise ValueError(f"Unsupported photo format: .{ext or 'unknown'}")
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > max_mb * 1024 * 1024:
        raise ValueError(f"Photo exceeds {max_mb}MB limit")
    filename = 'u' + uuid.uuid4().hex[:12] + '.' + ext
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, filename))
    return filename


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role != 'Admin':
            flash("Access denied: Admin permissions required.", "danger")
            return redirect(url_for('dashboard.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def is_ajax_request():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


BACKUP_DIR = None


def get_backup_dir(app):
    global BACKUP_DIR
    if BACKUP_DIR is None:
        import os
        BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(app.root_path)), 'backups')
    return BACKUP_DIR


def next_code(prefix, model, column):
    """Return the next sequential public code (e.g. STU0004) for model.column."""
    max_num = 0
    for row in db.session.query(model).all():
        val = getattr(row, column, None)
        if val and val.startswith(prefix):
            try:
                max_num = max(max_num, int(val[len(prefix):]))
            except (ValueError, TypeError):
                continue
    return f'{prefix}{max_num + 1:04d}'
