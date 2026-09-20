import json
import pytest
from unittest.mock import patch, MagicMock
from app.models import SystemSetting
from app.extensions import db
from app.services.ai_engine import AIEngine


def test_admin_console_ai_tab_rendered(admin_client):
    resp = admin_client.get('/admin')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'AI Engine Integration' in html
    assert 'gemini_api_key' in html
    assert 'openai_api_key' in html
    assert 'testAiConnection' in html


def test_admin_save_ai_keys_form(admin_client, app):
    resp = admin_client.post('/admin', data={
        'action': 'save_keys',
        'gemini_api_key': 'test-gemini-key-12345',
        'openai_api_key': 'test-openai-key-67890'
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '#ai' in resp.headers.get('Location', '')

    with app.app_context():
        g_setting = SystemSetting.query.filter_by(key='GEMINI_API_KEY').first()
        o_setting = SystemSetting.query.filter_by(key='OPENAI_API_KEY').first()
        assert g_setting is not None and g_setting.value == 'test-gemini-key-12345'
        assert o_setting is not None and o_setting.value == 'test-openai-key-67890'


def test_admin_save_ai_keys_ajax(admin_client, app):
    resp = admin_client.post('/admin', data={
        'action': 'save_keys',
        'gemini_api_key': 'ajax-gemini-key',
        'openai_api_key': 'ajax-openai-key'
    }, headers={'X-Requested-With': 'fetch'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True


def test_ai_test_connection_unauthenticated(client):
    resp = client.post('/admin/ai/test-connection', json={'provider': 'gemini'})
    assert resp.status_code in (302, 401)


def test_ai_test_connection_staff_forbidden(staff_client):
    resp = staff_client.post('/admin/ai/test-connection', json={'provider': 'gemini'})
    assert resp.status_code in (302, 403)


def test_ai_test_connection_no_key(admin_client, app):
    with app.app_context():
        SystemSetting.query.filter(SystemSetting.key.in_(['GEMINI_API_KEY', 'OPENAI_API_KEY'])).delete()
        db.session.commit()

    resp = admin_client.post('/admin/ai/test-connection', json={
        'provider': 'gemini',
        'api_key': ''
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is False
    assert 'No API key configured' in data['message']


def test_ai_test_connection_gemini_success(admin_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'candidates': [{'content': {'parts': [{'text': 'Guha Academy AI Online'}]}}]
    }

    with patch('requests.post', return_value=mock_resp):
        resp = admin_client.post('/admin/ai/test-connection', json={
            'provider': 'gemini',
            'api_key': 'AIzaSyFakeTestKey'
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'Connected to' in data['message']
        assert data['provider'] == 'Google Gemini'
        assert data['reply'] == 'Guha Academy AI Online'


def test_ai_test_connection_openai_success(admin_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'choices': [{'message': {'content': 'Guha Academy AI Online'}}]
    }

    with patch('requests.post', return_value=mock_resp):
        resp = admin_client.post('/admin/ai/test-connection', json={
            'provider': 'openai',
            'api_key': 'sk-proj-faketestkey'
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'gpt-4o-mini' in data['model']
        assert data['provider'] == 'OpenAI'


def test_ai_engine_error_handling():
    engine = AIEngine()

    # 1. Invalid key 403
    mock_403 = MagicMock()
    mock_403.status_code = 403
    with patch('requests.post', return_value=mock_403):
        res = engine.test_provider_connection(provider='gemini', custom_key='invalid_key')
        assert res['success'] is False
        assert 'Invalid API key' in res['message']

    # 2. Rate limit 429
    mock_429 = MagicMock()
    mock_429.status_code = 429
    with patch('requests.post', return_value=mock_429):
        res = engine.test_provider_connection(provider='gemini', custom_key='ratelimited_key')
        assert res['success'] is False
        assert 'Rate limit' in res['message']
