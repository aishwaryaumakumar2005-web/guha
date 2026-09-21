import hashlib
from datetime import datetime, timedelta

from app.extensions import db
from app.models import User, PasswordResetToken
from werkzeug.security import check_password_hash


def test_external_next_is_not_followed(client):
    response = client.post('/login?next=https://evil.example', data={
        'username': 'admin', 'password': 'admin123'
    })
    assert response.status_code == 302
    assert 'evil.example' not in response.headers['Location']


def test_invalid_csrf_is_rejected(app, client):
    app.config['TESTING'] = False
    response = client.post('/login', data={
        'username': 'admin', 'password': 'admin123', 'auth_csrf_token': 'invalid'
    })
    assert response.status_code == 400
    app.config['TESTING'] = True


def test_inactive_user_cannot_login(app, client):
    with app.app_context():
        user = User.query.filter_by(username='staff').first()
        user.is_active = False
        db.session.commit()
    response = client.post('/login', data={'username': 'staff', 'password': 'staff123'})
    assert response.status_code == 200


def test_five_failures_trigger_throttle(client):
    for _ in range(5):
        client.post('/login', data={'username': 'admin', 'password': 'wrong'})
    response = client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert response.status_code == 200
    assert b'too many failed attempts' in response.data.lower()


def test_reset_token_is_single_use(app, client):
    with app.app_context():
        user = User.query.filter_by(username='admin').first()
        raw = 'single-use-token'
        db.session.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        ))
        db.session.commit()
    payload = {'reset_token': 'single-use-token', 'new_password': 'Resetpass123', 'confirm_password': 'Resetpass123'}
    assert client.post('/forgot-password', data=payload).status_code == 302
    assert client.post('/forgot-password', data=payload).status_code == 200
    with app.app_context():
        assert check_password_hash(User.query.filter_by(username='admin').first().password_hash, 'Resetpass123')
