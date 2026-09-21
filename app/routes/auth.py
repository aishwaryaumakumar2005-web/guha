from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, make_response, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import db
from app.models import User, Tutor, PasswordResetToken
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse
from app.forms import LoginForm, RegistrationForm, ForgotPasswordForm
from flask import current_app

auth_bp = Blueprint('auth', __name__)

@auth_bp.app_context_processor
def inject_auth_csrf():
    return {'auth_csrf_token': _csrf_token()}

def _csrf_token():
    if 'auth_csrf_token' not in session:
        session['auth_csrf_token'] = secrets.token_urlsafe(32)
    return session['auth_csrf_token']

def _check_csrf():
    if current_app.testing:
        return
    submitted = request.form.get('auth_csrf_token')
    expected = session.get('auth_csrf_token')
    if not submitted or not expected or not secrets.compare_digest(submitted, expected):
        abort(400, description='Invalid security token.')

def _safe_next(value):
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith('/') or value.startswith('//'):
        return None
    return value

def _token_digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def _ensure_tutor(user):
    # Ensure we don't attempt to query or create Tutor rows when the Tutor table
    # doesn't exist yet (migrations not applied). This prevents a 500 error on
    # staff login for fresh/partial DBs — admin users don't hit this path.
    if user.role == 'Staff':
        try:
            from sqlalchemy import inspect
            if not inspect(db.engine).has_table('tutor'):
                return
        except Exception:
            # If inspection fails for any reason, skip creating tutor to avoid
            # surfacing internal errors during login.
            return

        tutor = Tutor.query.filter(
            db.func.lower(Tutor.email) == (user.email or '').lower()).first()
        if not tutor:
            tutor = Tutor(name=user.name, email=user.email, phone='', specialization='', status='Active')
            db.session.add(tutor)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        try:
            _check_csrf()
            form = LoginForm(request.form)
            if not form.validate():
                for msg in form.error_messages:
                    flash(msg, 'danger')
                return render_template('login.html')
            username = form.data.get('username', '').strip()
            password = form.data.get('password', '')
            current_app.logger.debug(f'Login attempt for username={username}')
            # Usernames are identifiers, not display text. Matching
            # case-insensitively avoids surprising failures after imports or
            # manual database restores (e.g. Staff vs staff).
            user = User.query.filter(db.func.lower(User.username) == username.lower()).first()
            if user and check_password_hash(user.password_hash, password):
                try:
                    _ensure_tutor(user)
                    db.session.commit()
                except Exception as e:
                    current_app.logger.exception('Failed to ensure tutor record during login')
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                if user.role == 'Staff':
                    # "Inactive" used to be display-only: deactivated staff
                    # kept full access. Gate login on the tutor record.
                    from sqlalchemy import inspect
                    tutor = None
                    if inspect(db.engine).has_table('tutor'):
                        tutor = Tutor.query.filter(
                            db.func.lower(Tutor.email) == (user.email or '').lower()
                        ).first()
                    if tutor is not None and (tutor.status or 'Active') != 'Active':
                        flash("Your staff account has been deactivated. Please contact the administrator.", 'danger')
                        return render_template('login.html')
                login_user(user)
                flash(f"Welcome back, {user.name}!", "success")
                next_page = _safe_next(request.args.get('next'))
                return redirect(next_page or url_for('dashboard.dashboard'))
            else:
                flash("Invalid username or password.", "danger")
        except Exception as e:
            # Ensure we print full traceback to console for debugging local 500s
            import traceback
            traceback.print_exc()
            current_app.logger.exception('Unhandled exception during login POST')
            raise
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        _check_csrf()
        form = RegistrationForm(request.form)
        if not form.validate():
            for msg in form.error_messages:
                flash(msg, 'danger')
            return render_template('register.html')
        name = form.data.get('name', '').strip()
        email = form.data.get('email', '').strip().lower()
        username = form.data.get('username', '').strip()
        password = form.data.get('password')
        existing_user = User.query.filter(
            db.or_(db.func.lower(User.username) == username.lower(), db.func.lower(User.email) == email)
        ).first()
        if existing_user:
            flash("Username or Email already registered.", "danger")
            return render_template('register.html')
        new_user = User(
            name=name, email=email, username=username,
            password_hash=generate_password_hash(password), role='Staff'
        )
        db.session.add(new_user)
        db.session.flush()
        _ensure_tutor(new_user)
        db.session.commit()
        flash("Registration successful! You can now log in.", "success")
        return redirect(url_for('auth.login'))
    return render_template('register.html')

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        _check_csrf()
        form = ForgotPasswordForm(request.form)
        if not form.validate():
            for msg in form.error_messages:
                flash(msg, 'danger')
            return render_template('forgot_password.html')
        username = form.data.get('username', '').strip()
        email = form.data.get('email', '').strip()
        token_value = request.form.get('reset_token')
        if token_value:
            token = PasswordResetToken.query.filter_by(token_hash=_token_digest(token_value)).first()
            if not token or not token.is_valid:
                flash("This reset link is invalid or has expired.", "danger")
                return render_template('forgot_password.html')
            new_password = form.data.get('new_password')
            if not new_password:
                flash("Enter a new password.", "danger")
                return render_template('forgot_password.html', show_reset=True, reset_token=token_value)
            token.user.password_hash = generate_password_hash(new_password)
            token.used_at = datetime.utcnow()
            PasswordResetToken.query.filter_by(user_id=token.user_id, used_at=None).update({'used_at': datetime.utcnow()})
            db.session.commit()
            flash("Password successfully reset! You can now log in.", "success")
            return redirect(url_for('auth.login'))
        user = User.query.filter(db.func.lower(User.username) == username.lower(), db.func.lower(User.email) == email).first()
        if user and user.email:
            raw_token = secrets.token_urlsafe(32)
            PasswordResetToken.query.filter_by(user_id=user.id, used_at=None).update({'used_at': datetime.utcnow()})
            db.session.add(PasswordResetToken(user_id=user.id, token_hash=_token_digest(raw_token), expires_at=datetime.utcnow() + timedelta(minutes=30)))
            db.session.commit()
            reset_url = url_for('auth.forgot_password', token=raw_token, _external=True)
            notifier = getattr(current_app, 'notifier', None)
            if notifier:
                notifier._send_email(user.email, 'Reset your Guha Academy password', f'<p>Use this link within 30 minutes:</p><p><a href="{reset_url}">Reset password</a></p>')
        flash("If the account details match, a password-reset link has been sent.", "info")
        return redirect(url_for('auth.forgot_password'))
    reset_token = request.args.get('token')
    if reset_token:
        token = PasswordResetToken.query.filter_by(token_hash=_token_digest(reset_token)).first()
        if token and token.is_valid:
            return render_template('forgot_password.html', show_reset=True, reset_token=reset_token)
    return render_template('forgot_password.html')

@auth_bp.route('/logout', methods=['POST'])
def logout():
    _check_csrf()
    logout_user()
    session.clear()
    resp = redirect(url_for('auth.logged_out'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@auth_bp.route('/logged-out')
def logged_out():
    logout_user()
    session.clear()
    html = '''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Logged Out - Guha India</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:linear-gradient(135deg,#0a1e2e,#0d2740);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#fff}
.card{max-width:420px;width:100%;background:#0f2d4a;border-radius:24px;border:2px solid #00d4ff;box-shadow:0 20px 40px rgba(0,212,255,.2);padding:40px;text-align:center}
.brand-wrap{display:flex;align-items:center;justify-content:center;gap:12px}
.brand-logo{height:48px;width:auto;filter:brightness(2.0) contrast(1.4) saturate(1.4)}
.brand-text{font-size:1.2rem;font-weight:800;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(90deg,#FFD700,#FFA500);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:0.04em}
.brand-text-col{text-align:left}
.slogan{font-size:0.7rem;color:rgba(255,255,255,0.55);letter-spacing:0.06em;margin-bottom:20px}
p{color:#ccc;margin-bottom:20px;font-size:.95rem}
a{display:inline-block;padding:12px 32px;background:#00d4ff;color:#000;border-radius:10px;text-decoration:none;font-weight:600}
a:hover{box-shadow:0 4px 15px rgba(0,212,255,.5)}
@media(max-width:576px){.card{padding:28px 20px}}
</style>
</head>
<body>
<div class="card">
<div class="brand-wrap">
<img src="/static/images/logo.png" alt="GUHA INDIA" class="brand-logo">
<div class="brand-text-col">
<div class="brand-text">GUHA INDIA</div>
<div class="slogan">Learn Today, Lead Tomorrow</div>
</div>
</div>
<p>You have been logged out successfully.</p>
<a href="/login">Back to Login</a>
</div>
</body>
</html>'''
    resp = make_response(html, 200)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp
