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
    assert 'ai_default_provider' in html
    assert 'gemini_model' in html
    assert 'openai_model' in html
    assert 'ai_temperature' in html
    assert 'ai_system_prompt' in html
    assert 'AI Live Playground' in html
    assert 'testAiConnection' in html
    assert 'runAiSimulation' in html


def test_admin_save_ai_advanced_settings(admin_client, app):
    resp = admin_client.post('/admin', data={
        'action': 'save_keys',
        'gemini_api_key': 'test-gemini-key-12345',
        'openai_api_key': 'test-openai-key-67890',
        'ai_default_provider': 'openai',
        'gemini_model': 'gemini-2.5-pro',
        'openai_model': 'gpt-4o',
        'ai_temperature': '0.85',
        'ai_system_prompt': 'You are a friendly counselor.'
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '#ai' in resp.headers.get('Location', '')

    with app.app_context():
        g_setting = SystemSetting.query.filter_by(key='GEMINI_API_KEY').first()
        o_setting = SystemSetting.query.filter_by(key='OPENAI_API_KEY').first()
        provider_setting = SystemSetting.query.filter_by(key='AI_DEFAULT_PROVIDER').first()
        g_model = SystemSetting.query.filter_by(key='GEMINI_MODEL').first()
        o_model = SystemSetting.query.filter_by(key='OPENAI_MODEL').first()
        temp_setting = SystemSetting.query.filter_by(key='AI_TEMPERATURE').first()
        prompt_setting = SystemSetting.query.filter_by(key='AI_SYSTEM_PROMPT').first()

        assert g_setting.value == 'test-gemini-key-12345'
        assert o_setting.value == 'test-openai-key-67890'
        assert provider_setting.value == 'openai'
        assert g_model.value == 'gemini-2.5-pro'
        assert o_model.value == 'gpt-4o'
        assert temp_setting.value == '0.85'
        assert prompt_setting.value == 'You are a friendly counselor.'


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


def test_clear_ai_cache_endpoint_staff(staff_client):
    staff_resp = staff_client.post('/admin/ai/clear-cache')
    assert staff_resp.status_code in (302, 403)


def test_clear_ai_cache_endpoint_admin(admin_client):
    admin_resp = admin_client.post('/admin/ai/clear-cache')
    assert admin_resp.status_code == 200
    data = admin_resp.get_json()
    assert data['success'] is True
    assert 'purged successfully' in data['message']


def test_ai_playground_endpoint(admin_client):
    # Empty prompt validation
    resp_empty = admin_client.post('/admin/ai/playground', json={'prompt': ''})
    assert resp_empty.status_code == 400

    # Successful playground inference simulation
    with patch.object(AIEngine, 'call_ai', return_value='Simulation generated response for testing.'):
        resp = admin_client.post('/admin/ai/playground', json={
            'prompt': 'Analyze attendance metrics',
            'provider': 'gemini'
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['response'] == 'Simulation generated response for testing.'
        assert data['word_count'] == 5
        assert data['latency_ms'] >= 0


def test_ai_engine_call_ai_system_prompt_and_routing(app):
    engine = AIEngine()

    with app.app_context():
        db.session.add(SystemSetting(key='GEMINI_API_KEY', value='test-key'))
        db.session.add(SystemSetting(key='AI_SYSTEM_PROMPT', value='Custom persona instructions.'))
        db.session.add(SystemSetting(key='AI_DEFAULT_PROVIDER', value='gemini'))
        db.session.commit()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': 'AI Reply Text'}]}}]
        }

        with patch('requests.post', return_value=mock_resp) as mock_post:
            result = engine.call_ai("User prompt test")
            assert result == 'AI Reply Text'
            # Check that prompt sent to Gemini includes the custom system prompt
            sent_payload = mock_post.call_args[1]['json']
            sent_text = sent_payload['contents'][0]['parts'][0]['text']
            assert 'Custom persona instructions.' in sent_text
            assert 'User prompt test' in sent_text


def test_ai_engine_clear_cache():
    engine = AIEngine()
    res = engine.clear_cache()
    assert res is True


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
