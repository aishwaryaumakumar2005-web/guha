from flask import Blueprint, render_template, jsonify
from flask_login import login_required
from app.extensions import db
from app.helpers import admin_required

extras_bp = Blueprint('extras', __name__)

@extras_bp.route('/extras', methods=['GET'])
@login_required
@admin_required
def extras():
    return render_template('extras.html')
