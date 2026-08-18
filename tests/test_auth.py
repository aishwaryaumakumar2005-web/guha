from app.extensions import db
from app.models import User


def test_login_page_renders(client):
    resp = client.get('/login')
    assert resp.status_code in (200, 302)


def test_login_redirects_authenticated_to_dashboard(admin_client):
    resp = admin_client.get('/login')
    assert resp.status_code == 302
    assert '/login' not in resp.headers.get('Location', '')


def test_valid_login_redirects_to_dashboard(client):
    resp = client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert resp.status_code == 302
    assert resp.headers.get('Location', '') in ('/', '/dashboard')


def test_invalid_login_stays_on_login(client):
    resp = client.post('/login', data={'username': 'admin', 'password': 'wrong'})
    assert resp.status_code == 200


def test_protected_page_redirects_anonymous(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/login' in resp.headers.get('Location', '')


def test_dashboard_accessible_when_logged_in(admin_client):
    resp = admin_client.get('/')
    assert resp.status_code == 200


def test_staff_cannot_reach_admin_console(staff_client):
    resp = staff_client.get('/admin')
    assert resp.status_code == 302
    assert '/login' not in resp.headers.get('Location', '')


def test_admin_can_reach_admin_console(admin_client):
    resp = admin_client.get('/admin')
    assert resp.status_code in (200, 302)


def test_logout_redirects(app, client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    resp = client.post('/logout')
    assert resp.status_code == 302


def test_register_creates_user(app, client):
    resp = client.post('/register', data={
        'name': 'New Person',
        'email': 'new@guha.test',
        'username': 'newuser',
        'password': 'secret1',
        'confirm_password': 'secret1',
    })
    assert resp.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username='newuser').first()
        assert user is not None
        assert user.role == 'Staff'


def test_forgot_password_resets(app, client):
    client.post('/forgot-password', data={
        'username': 'admin', 'email': 'admin@guha.test',
        'new_password': 'newpass1', 'confirm_password': 'newpass1',
    })
    with app.app_context():
        user = User.query.filter_by(username='admin').first()
        from werkzeug.security import check_password_hash
        assert check_password_hash(user.password_hash, 'newpass1')