from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/api/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json()
    message = (data.get('message', '') if data else '').strip()
    if not message:
        return jsonify({'reply': 'Please ask a question.'})
    reply = current_app.ai_engine.chat_query(message)
    return jsonify({'reply': reply})
