import os
import sys

os.environ['FLASK_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['GEMINI_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''
os.environ['CRON_SECRET'] = 'test'

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User, Tutor, Course, Student, ExpenseCategory


def _reset_caches():
    import app
    import app.routes.dashboard as dashboard
    app._sidebar_cache = {"data": None, "time": 0}
    dashboard._stats_cache = {"data": None, "time": 0}


def _seed_base():
    admin = User(
        username='admin',
        password_hash=generate_password_hash('admin123'),
        role='Admin',
        name='Admin User',
        email='admin@guha.test',
    )
    staff_user = User(
        username='staff',
        password_hash=generate_password_hash('staff123'),
        role='Staff',
        name='Staff User',
        email='staff@guha.test',
    )
    db.session.add_all([admin, staff_user])
    db.session.flush()

    tutor = Tutor(name='Staff User', email='staff@guha.test', phone='9876543210', status='Active')
    db.session.add(tutor)
    db.session.flush()

    course = Course(
        name='Python Programming', code='PY',
        description='Beginner Python', duration_weeks=8,
        duration_unit='weeks', fees=5000.0, gst_applicable=True,
    )
    db.session.add(course)
    db.session.flush()

    tutor.courses.append(course)

    student = Student(
        name='Test Student', email='student@guha.test',
        phone='9876543210', status='Active',
    )
    db.session.add(student)
    db.session.flush()
    student.courses.append(course)

    db.session.add(ExpenseCategory(name='Rent', description='Monthly rent'))
    db.session.commit()


@pytest.fixture()
def app(monkeypatch):
    import init_db
    monkeypatch.setattr(init_db, 'seed_if_empty', lambda: None)
    _reset_caches()
    flask_app = create_app()
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    with flask_app.app_context():
        db.create_all()
        _seed_base()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture()
def admin_client(app):
    with app.test_client() as c:
        resp = c.post('/login', data={'username': 'admin', 'password': 'admin123'})
        assert resp.status_code == 302, 'admin login failed'
        yield c


@pytest.fixture()
def staff_client(app):
    with app.test_client() as c:
        resp = c.post('/login', data={'username': 'staff', 'password': 'staff123'})
        assert resp.status_code == 302, 'staff login failed'
        yield c


def login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password})
