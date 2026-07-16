from functools import wraps
from flask import request, redirect, url_for, flash
from flask_login import current_user


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
