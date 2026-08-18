from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import db
from app.models import User, Tutor
from app.forms import LoginForm, RegistrationForm, ForgotPasswordForm

auth_bp = Blueprint('auth', __name__)

def _ensure_tutor(user):
    if user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=user.email).first()
        if not tutor:
            tutor = Tutor(name=user.name, email=user.email, phone='', specialization='', status='Active')
            db.session.add(tutor)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        form = LoginForm(request.form)
        if not form.validate():
            for msg in form.error_messages:
                flash(msg, 'danger')
            return render_template('login.html')
        username = form.data.get('username', '').strip()
        password = form.data.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            _ensure_tutor(user)
            db.session.commit()
            login_user(user)
            flash(f"Welcome back, {user.name}!", "success")
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.dashboard'))
        else:
            flash("Invalid username or password.", "danger")
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
    if request.method == 'POST':
        form = RegistrationForm(request.form)
        if not form.validate():
            for msg in form.error_messages:
                flash(msg, 'danger')
            return render_template('register.html')
        name = form.data.get('name', '').strip()
        email = form.data.get('email', '').strip()
        username = form.data.get('username', '').strip()
        password = form.data.get('password')
        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
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
        form = ForgotPasswordForm(request.form)
        if not form.validate():
            for msg in form.error_messages:
                flash(msg, 'danger')
            return render_template('forgot_password.html')
        username = form.data.get('username', '').strip()
        email = form.data.get('email', '').strip()
        new_password = form.data.get('new_password')
        confirm_password = form.data.get('confirm_password')
        user = User.query.filter_by(username=username, email=email).first()
        if not user:
            flash("No matching user found with that username and email.", "danger")
            return render_template('forgot_password.html')
        if new_password and confirm_password:
            if new_password != confirm_password:
                flash("Passwords do not match.", "danger")
                return render_template('forgot_password.html', show_reset=True, username=username, email=email)
            user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash("Password successfully reset! You can now log in.", "success")
            return redirect(url_for('auth.login'))
        return render_template('forgot_password.html', show_reset=True, username=username, email=email)
    return render_template('forgot_password.html')

@auth_bp.route('/logout', methods=['POST'])
def logout():
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
<title>Logged Out - Guha Academy</title>
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
<img src="/static/images/logo.png" alt="GUHA ACADEMY" class="brand-logo">
<div class="brand-text-col">
<div class="brand-text">GUHA ACADEMY</div>
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
