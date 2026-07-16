import os, sys
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, redirect, url_for, flash, render_template, g
from markupsafe import Markup

# Ensure project root is on sys.path (critical for Render deployment)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config import DevConfig, ProdConfig
from .extensions import db, login_manager, cors

_basedir = _project_root
_sidebar_cache = {"data": None, "time": 0}


def scheduled_backup():
    """Scheduled daily backup function"""
    try:
        import shutil
        backup_dir = os.path.join(_basedir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        db_path = os.path.join(_basedir, 'instance', 'institute.db')
        
        if os.path.exists(db_path):
            today_str = date.today().isoformat()
            backup_name = f'auto_backup_{today_str}.db'
            backup_path = os.path.join(backup_dir, backup_name)
            
            if not os.path.exists(backup_path):
                shutil.copy2(db_path, backup_path)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduled backup created: {backup_name}")
                
                # Clean up old backups (keep last 30 days)
                cutoff_date = date.today() - timedelta(days=30)
                for filename in os.listdir(backup_dir):
                    if filename.startswith('auto_backup_') and filename.endswith('.db'):
                        file_path = os.path.join(backup_dir, filename)
                        file_date = datetime.fromtimestamp(os.path.getmtime(file_path)).date()
                        if file_date < cutoff_date:
                            os.remove(file_path)
                            print(f"Removed old backup: {filename}")
    except Exception as e:
        print(f"Scheduled backup error: {e}")


def create_app(config_object=None):
    if config_object is None:
        env = os.environ.get('FLASK_ENV', 'development')
        config_object = DevConfig if env == 'development' else ProdConfig

    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    app.config.from_object(config_object)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///institute.db'
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
        app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)

    db.init_app(app)
    login_manager.init_app(app)
    cors.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    from .models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from .services.ai_engine import AIEngine
    from .services.notifier import Notifier
    from .services.messenger import Messenger
    from .services.sms_service import SmsService
    from .services.accounting import AccountingService

    app.ai_engine = AIEngine()
    app.notifier = Notifier(app)
    app.messenger = Messenger(app)
    app.sms_service = SmsService(app)
    app.accounting = AccountingService(app)

    from .routes.auth import auth_bp
    from .routes.dashboard import dashboard_bp
    from .routes.courses import courses_bp
    from .routes.students import students_bp
    from .routes.tutors import tutors_bp
    from .routes.enquiries import enquiries_bp
    from .routes.fees import fees_bp
    from .routes.expenses import expenses_bp
    from .routes.attendance import attendance_bp
    from .routes.leaves import leaves_bp
    from .routes.reports import reports_bp
    from .routes.admin import admin_bp
    from .routes.google_sync import google_sync_bp
    from .routes.api import api_bp
    from .routes.notifications import notifications_bp
    from .routes.whatsapp import whatsapp_bp
    from .routes.sms_routes import sms_bp
    from .routes.accounting import accounting_bp
    from .routes.payroll_routes import payroll_bp
    from .routes.exam_routes import exams_bp
    from .routes.chat import chat_bp
    from .routes.extras import extras_bp

    blueprints = [
        auth_bp, dashboard_bp, courses_bp, students_bp, tutors_bp,
        enquiries_bp, fees_bp, expenses_bp, attendance_bp, leaves_bp,
        reports_bp, admin_bp, google_sync_bp, api_bp,
        notifications_bp, whatsapp_bp, sms_bp, accounting_bp,         payroll_bp, exams_bp,
        chat_bp,
        extras_bp,
    ]
    for bp in blueprints:
        app.register_blueprint(bp)

    @app.context_processor
    def inject_sidebar_counts():
        from time import time
        if time() - _sidebar_cache["time"] < 30 and _sidebar_cache["data"]:
            return _sidebar_cache["data"]
        from .models import User, Student, Tutor, Course, Enquiry
        try:
            data = {
                'student_count': Student.query.count(),
                'staff_count': Tutor.query.count(),
                'course_count': Course.query.count(),
                'enquiry_count': Enquiry.query.count(),
                'admin_count': User.query.filter(User.role == 'Admin').count(),
            }
        except Exception:
            data = {'student_count': 0, 'staff_count': 0, 'admin_count': 0, 'course_count': 0, 'enquiry_count': 0}
        _sidebar_cache["data"] = data
        _sidebar_cache["time"] = time()
        return data

    @app.context_processor
    def inject_globals():
        _empty_svgs = {
            'students': '<svg viewBox="0 0 120 100" fill="none"><circle cx="38" cy="30" r="12" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><path d="M20 68c0-10 8-18 18-18s18 8 18 18" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><circle cx="82" cy="28" r="10" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><path d="M68 62c0-8 6.5-14.5 14-14.5S96 54 96 62" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><circle cx="60" cy="72" r="20" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="4 4" opacity="0.5"/></svg>',
            'courses': '<svg viewBox="0 0 120 100" fill="none"><rect x="20" y="14" width="80" height="72" rx="8" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="34" y1="36" x2="86" y2="36" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="34" y1="50" x2="72" y2="50" stroke="currentColor" stroke-width="2" opacity="0.15"/><line x1="34" y1="64" x2="60" y2="64" stroke="currentColor" stroke-width="2" opacity="0.1"/></svg>',
            'enquiries': '<svg viewBox="0 0 120 100" fill="none"><rect x="28" y="10" width="64" height="80" rx="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="40" y1="32" x2="80" y2="32" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="40" y1="44" x2="72" y2="44" stroke="currentColor" stroke-width="2" opacity="0.15"/><line x1="40" y1="56" x2="68" y2="56" stroke="currentColor" stroke-width="2" opacity="0.1"/><path d="M96 66l10 10-10-10z" stroke="currentColor" stroke-width="2" fill="none" opacity="0.6"/></svg>',
            'expenses': '<svg viewBox="0 0 120 100" fill="none"><rect x="30" y="16" width="60" height="68" rx="4" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="42" y1="36" x2="78" y2="36" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="42" y1="48" x2="66" y2="48" stroke="currentColor" stroke-width="2" opacity="0.15"/><line x1="42" y1="60" x2="54" y2="60" stroke="currentColor" stroke-width="2" opacity="0.1"/></svg>',
            'fees': '<svg viewBox="0 0 120 100" fill="none"><circle cx="60" cy="44" r="22" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><path d="M52 38h16v12H52z" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><line x1="60" y1="28" x2="60" y2="22" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="60" y1="66" x2="60" y2="72" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="42" y1="44" x2="36" y2="44" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="78" y1="44" x2="84" y2="44" stroke="currentColor" stroke-width="2" opacity="0.2"/></svg>',
            'exams': '<svg viewBox="0 0 120 100" fill="none"><rect x="34" y="12" width="52" height="76" rx="4" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="44" y1="32" x2="62" y2="32" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="44" y1="44" x2="58" y2="44" stroke="currentColor" stroke-width="2" opacity="0.15"/><line x1="44" y1="56" x2="68" y2="56" stroke="currentColor" stroke-width="2" opacity="0.1"/><path d="M78 66l14 14-14-14zM92 80l-6-6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
            'attendance': '<svg viewBox="0 0 120 100" fill="none"><rect x="24" y="14" width="72" height="72" rx="8" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="24" y1="34" x2="96" y2="34" stroke="currentColor" stroke-width="2" opacity="0.1"/><line x1="48" y1="14" x2="48" y2="4" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="72" y1="14" x2="72" y2="4" stroke="currentColor" stroke-width="2" opacity="0.2"/><circle cx="60" cy="66" r="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
            'leaves': '<svg viewBox="0 0 120 100" fill="none"><rect x="24" y="12" width="72" height="76" rx="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="24" y1="34" x2="96" y2="34" stroke="currentColor" stroke-width="2" opacity="0.1"/><line x1="48" y1="12" x2="48" y2="4" stroke="currentColor" stroke-width="2" opacity="0.2"/><line x1="72" y1="12" x2="72" y2="4" stroke="currentColor" stroke-width="2" opacity="0.2"/><circle cx="60" cy="66" r="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
            'payroll': '<svg viewBox="0 0 120 100" fill="none"><rect x="26" y="18" width="68" height="64" rx="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><rect x="36" y="28" width="48" height="12" rx="3" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><rect x="36" y="48" width="32" height="10" rx="2" stroke="currentColor" stroke-width="2" fill="none" opacity="0.12"/><path d="M86 60l14 14-14-14z" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
            'backups': '<svg viewBox="0 0 120 100" fill="none"><ellipse cx="60" cy="72" rx="32" ry="10" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><rect x="36" y="24" width="48" height="48" rx="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><rect x="44" y="34" width="32" height="6" rx="2" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><rect x="44" y="46" width="24" height="6" rx="2" stroke="currentColor" stroke-width="2" fill="none" opacity="0.12"/><path d="M74 16l10 10-10-10z" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
            'sync': '<svg viewBox="0 0 120 100" fill="none"><path d="M36 60c0-13 11-24 24-24s24 11 24 24" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><circle cx="84" cy="60" r="12" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><path d="M84 52v8h8" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.2"/><circle cx="36" cy="60" r="12" stroke="currentColor" stroke-width="2" fill="none" opacity="0.2"/><path d="M36 52v8h-8" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.2"/></svg>',
            'salary': '<svg viewBox="0 0 120 100" fill="none"><rect x="26" y="20" width="68" height="60" rx="6" stroke="currentColor" stroke-width="2" fill="none" opacity="0.3"/><line x1="40" y1="38" x2="80" y2="38" stroke="currentColor" stroke-width="2" opacity="0.15"/><circle cx="60" cy="58" r="4" stroke="currentColor" stroke-width="2" fill="none" opacity="0.5"/></svg>',
            'general': '<svg viewBox="0 0 120 100" fill="none"><circle cx="60" cy="42" r="24" stroke="currentColor" stroke-width="2" fill="none" opacity="0.25"/><line x1="78" y1="60" x2="92" y2="74" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.25"/></svg>',
        }
        def empty_state(title, subtitle=None, type='general', cta_url=None, cta_text=None, cta_icon=None, colspan=None, cta_attrs=''):
            svg = _empty_svgs.get(type, _empty_svgs['general'])
            icon = cta_icon or 'bi-' + {'students':'people-fill','courses':'journal-code','enquiries':'question-circle-fill','expenses':'receipt','fees':'wallet2','exams':'pencil-square','attendance':'calendar2-check','leaves':'calendar-range','payroll':'cash-stack','backups':'hdd-stack-fill','sync':'arrow-repeat','salary':'calculator-fill','general':'inbox-fill'}.get(type, 'inbox-fill')
            cta = ''
            if cta_url and cta_text:
                cta = f'<a href="{cta_url}" class="empty-state-cta" {cta_attrs}><i class="bi {icon} me-1"></i> {cta_text}</a>'
            html = f'''<div class="empty-state"><div class="empty-state-illustration">{svg}</div><div class="empty-state-content"><h4 class="empty-state-title">{title}</h4>'''
            if subtitle:
                html += f'<p class="empty-state-subtitle">{subtitle}</p>'
            html += f'{cta}</div></div>'
            if colspan:
                html = f'<td colspan="{colspan}" class="empty-state-td">{html}</td>'
            return Markup(html)
        return dict(empty_state=empty_state)

    from sqlalchemy import event
    with app.app_context():
        @event.listens_for(db.get_engine(), 'connect')
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA cache_size=-8000')
            cursor.execute('PRAGMA busy_timeout=5000')
            cursor.execute('PRAGMA temp_store=MEMORY')
            cursor.close()
        db.create_all()
        try:
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_expense_date ON expense(expense_date)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_expense_category ON expense(category_id)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_fee_date ON fee_record(payment_date)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_fee_student ON fee_record(student_id)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_attendance_person_date ON attendance(person_type, person_id, date)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_enquiry_status ON enquiry(status)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_enquiry_course ON enquiry(course_id)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_leave_user_status ON leave_request(user_id, status)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_leave_status ON leave_request(status)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)'))
            db.session.execute(db.text('CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id)'))
            db.session.commit()
        except Exception:
            db.session.rollback()
        from app.audit import register_audit_events
        register_audit_events()

    @app.before_request
    def _set_audit_user():
        from flask_login import current_user
        g.audit_user = current_user if current_user.is_authenticated else None

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    # Auto-seed all sample data on first deploy (fresh database)
    with app.app_context():
        from init_db import seed_if_empty
        seed_if_empty()

    # Start the scheduler for daily backups (only in development)
    # Render uses cron jobs for scheduled tasks, not in-app scheduler
    if os.environ.get('FLASK_ENV') == 'development':
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(scheduled_backup, 'cron', hour=2, minute=0)
        _scheduler.start()

    return app

