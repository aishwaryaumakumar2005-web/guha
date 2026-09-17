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


def staff_can_view_student(student_id):
    """Admins see every student; staff only those sharing their courses.

    Imports are lazy because app.models imports from this module.
    """
    if not current_user.is_authenticated:
        return False
    if current_user.role == 'Admin':
        return True
    if current_user.role != 'Staff':
        return False
    from app.models import Tutor, student_courses
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    if not tutor:
        return False
    course_ids = [c.id for c in tutor.courses]
    if not course_ids:
        return False
    return db.session.query(student_courses).filter(
        student_courses.c.student_id == student_id,
        student_courses.c.course_id.in_(course_ids)
    ).first() is not None


BACKUP_DIR = None


def get_backup_dir(app):
    global BACKUP_DIR
    if BACKUP_DIR is None:
        import os
        BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(app.root_path)), 'backups')
    return BACKUP_DIR


def next_code(prefix, model, column):
    """Return the next sequential public code (e.g. STU0004) for model.column.

    Reads only the code column (never full rows), so bulk imports don't pay
    an N+1 object load per insert. Two concurrent transactions can still
    compute the same value — callers creating records must commit through
    commit_with_retry() below instead of a bare db.session.commit().
    """
    col = getattr(model, column)
    seen = [val for (val,) in
            db.session.query(col).filter(col.startswith(prefix)).all()]
    # Same-flush siblings: when several objects are added before one flush,
    # earlier siblings' codes live only in the session (uncommitted), so the
    # query above can't see them. Read local __dict__ state (never triggers
    # a refresh — expired attributes are simply skipped; committed rows are
    # already covered by the query).
    for obj in list(db.session.new) + list(db.session.identity_map.values()):
        if isinstance(obj, model):
            seen.append(obj.__dict__.get(column))
    max_num = 0
    for val in seen:
        if val and val.startswith(prefix):
            try:
                max_num = max(max_num, int(val[len(prefix):]))
            except (ValueError, TypeError):
                continue
    return f'{prefix}{max_num + 1:04d}'


def cell_text(value):
    """Excel cell -> stripped string. Empty cells become '', never 'None'.

    Shared by the student/tutor importers so blank cells can't become
    literal 'None' records.
    """
    if value is None:
        return ''
    text = str(value).strip()
    return '' if text.lower() == 'none' else text


def get_gst_rates():
    """Return (cgst_pct, sgst_pct) from SystemSetting with safe fallbacks.

    Never raises: missing, blank, non-numeric, or out-of-range values fall
    back to 9.0 each. Every reader must use this instead of float()-ing the
    raw setting (a single bad admin save used to 500 every fee/GST page).
    """
    from app.models import SystemSetting

    def _rate(key):
        try:
            row = SystemSetting.query.filter_by(key=key).first()
            if row is None or row.value in (None, ''):
                return 9.0
            val = float(row.value)
            if 0 <= val <= 100:
                return val
        except (TypeError, ValueError):
            pass
        return 9.0

    return _rate('CGST_PCT'), _rate('SGST_PCT')


def commit_with_retry(build_and_commit, attempts=3):
    """Run build_and_commit() (which ends with commit) with IntegrityError retries.

    The callback must rebuild all of its objects from scratch on every call:
    a failed attempt leaves the session rolled back and pending objects
    detached, so reusing them would re-insert stale state. Re-raises the
    last IntegrityError when attempts run out.
    """
    from sqlalchemy.exc import IntegrityError
    last_exc = None
    for _ in range(attempts):
        try:
            return build_and_commit()
        except IntegrityError as e:
            db.session.rollback()
            last_exc = e
    raise last_exc
