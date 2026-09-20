import json
import uuid
import hashlib
import re
import secrets
from collections import Counter
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash, session, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Enquiry, Course, SystemSetting, GoogleSyncRow, GoogleSyncConnection, AuditLog
from app.helpers import admin_required

google_sync_bp = Blueprint('google_sync', __name__)

@google_sync_bp.before_request
def google_sync_security():
    if 'admin_csrf_token' not in session:
        session['admin_csrf_token'] = secrets.token_urlsafe(32)
    if request.method == 'POST' and not current_app.testing:
        token = request.headers.get('X-CSRFToken') or (request.form.get('admin_csrf_token') if request.form else '')
        if not token or not secrets.compare_digest(token, session['admin_csrf_token']):
            return jsonify({'error': 'Security token expired. Reload the page and try again.'}), 400

def _safe_error(exc):
    current_app.logger.exception('Google Sync error')
    return 'Google Sheets could not be reached. Check sharing, credentials, and API access.'

def _valid_sheet_id(value):
    return bool(re.fullmatch(r'[A-Za-z0-9_-]{20,120}', value or ''))

def _valid_form_url(value):
    return not value or bool(re.match(r'^https://(docs\.google\.com/forms/|forms\.gle/)', value))

def _audit(action, changes):
    db.session.add(AuditLog(user_id=current_user.id, username=current_user.username,
                            action=action, entity_type='GoogleSync', changes=json.dumps(changes, default=str)))

@google_sync_bp.route('/google-sync')
@login_required
@admin_required
def google_sync():
    sa_setting = SystemSetting.query.filter_by(key='sa_key').first()
    sheet_setting = SystemSetting.query.filter_by(key='enquiry_sheet_id').first()
    last_sync_setting = SystemSetting.query.filter_by(key='enquiry_last_sync').first()
    synced_ids_setting = SystemSetting.query.filter_by(key='enquiry_synced_ids').first()
    form_url_setting = SystemSetting.query.filter_by(key='enquiry_form_url').first()
    has_key = bool(sa_setting and sa_setting.value)
    sheet_id = sheet_setting.value if sheet_setting else ''
    last_sync = last_sync_setting.value if last_sync_setting else ''
    form_url = form_url_setting.value if form_url_setting else ''
    synced_ids = synced_ids_setting.value.split(',') if synced_ids_setting and synced_ids_setting.value else []
    synced_enquiries = Enquiry.query.filter(Enquiry.notes.ilike('[Google Form]%')).order_by(Enquiry.id.desc()).limit(50).all()
    return render_template('google_sync.html', has_key=has_key, sheet_id=sheet_id, last_sync=last_sync,
        form_url=form_url, synced_enquiries=synced_enquiries, courses=Course.query.all(),
        admin_csrf_token=session['admin_csrf_token'])

@google_sync_bp.route('/api/google-sync/upload-key', methods=['POST'])
@login_required
@admin_required
def google_sync_upload_key():
    payload = request.get_json(silent=True) or {}
    key_json = payload.get('key_json', '').strip()
    if len(key_json) > 20000:
        return jsonify({'error': 'Credential file is too large.'}), 413
    if not key_json:
        return jsonify({'error': 'No key provided'}), 400
    try:
        key_data = json.loads(key_json)
    except json.decoder.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON'}), 400
    required = ('type', 'client_email', 'private_key', 'token_uri')
    if key_data.get('type') != 'service_account' or any(not key_data.get(k) for k in required[1:]):
        return jsonify({'error': 'This is not a complete Google service-account key.'}), 400
    setting = SystemSetting.query.filter_by(key='sa_key').first()
    if setting:
        setting.value = key_json
    else:
        db.session.add(SystemSetting(key='sa_key', value=key_json))
    db.session.commit()
    _audit('UPDATE', {'credential_uploaded': True, 'service_account_email': key_data.get('client_email')})
    db.session.commit()
    return jsonify({'status': 'ok'}), 200

@google_sync_bp.route('/api/google-sync/save-sheet', methods=['POST'])
@login_required
@admin_required
def google_sync_save_sheet():
    payload = request.get_json(silent=True) or {}
    sheet_id = payload.get('sheet_id', '').strip()
    form_url = payload.get('form_url', '').strip()
    worksheet = (payload.get('worksheet') or '').strip()[:100]
    try:
        sync_limit = max(100, min(int(payload.get('sync_limit', 1000)), 10000))
    except (TypeError, ValueError):
        return jsonify({'error': 'Sync limit must be a number between 100 and 10,000.'}), 400
    if not _valid_sheet_id(sheet_id):
        return jsonify({'error': 'Enter a valid Google Sheet ID.'}), 400
    if not _valid_form_url(form_url):
        return jsonify({'error': 'Form URL must be a Google Forms HTTPS URL.'}), 400
    for key, val in [('enquiry_sheet_id', sheet_id), ('enquiry_form_url', form_url), ('enquiry_worksheet', worksheet), ('enquiry_sync_limit', str(sync_limit))]:
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting: setting.value = val
        else: db.session.add(SystemSetting(key=key, value=val))
    db.session.commit()
    connection = GoogleSyncConnection.query.filter_by(sheet_id=sheet_id).first()
    if not connection:
        connection = GoogleSyncConnection(name='Google Form Enquiries', sheet_id=sheet_id)
        db.session.add(connection)
    connection.worksheet = worksheet
    connection.form_url = form_url
    connection.sync_limit = sync_limit
    db.session.commit()
    _audit('UPDATE', {'sheet_id_changed': True, 'form_url_configured': bool(form_url)})
    db.session.commit()
    return jsonify({'status': 'ok'}), 200

@google_sync_bp.route('/api/google-sync/status')
@login_required
@admin_required
def google_sync_status():
    try:
        import gspread
    except ImportError:
        return jsonify({'connected': False, 'error': 'Google Sheets integration is not installed.'}), 503
    sa_setting = SystemSetting.query.filter_by(key='sa_key').first()
    sheet_setting = SystemSetting.query.filter_by(key='enquiry_sheet_id').first()
    worksheet_setting = SystemSetting.query.filter_by(key='enquiry_worksheet').first()
    if not (sa_setting and sa_setting.value):
        return jsonify({'connected': False, 'error': 'Service account key not found. Complete Step 1 first.'})
    if not (sheet_setting and sheet_setting.value):
        return jsonify({'connected': False, 'error': 'Sheet ID not found. Complete Step 2 first.'})
    try:
        key_dict = json.loads(sa_setting.value)
        if 'client_email' not in key_dict:
            return jsonify({'connected': False, 'error': 'Invalid service account JSON - missing client_email field.'})
        gc = gspread.service_account_from_dict(key_dict, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        book = gc.open_by_key(sheet_setting.value)
        sheet = book.worksheet(worksheet_setting.value) if worksheet_setting and worksheet_setting.value else book.sheet1
        headers = sheet.row_values(1)
        return jsonify({'connected': True, 'headers': headers, 'row_count': len(sheet.get_all_values())})
    except Exception as e:
        return jsonify({'connected': False, 'error': _safe_error(e)})

@google_sync_bp.route('/api/google-sync/preview', methods=['POST'])
@login_required
@admin_required
def google_sync_preview():
    """Fetch a bounded preview without writing enquiries."""
    payload = request.get_json(silent=True) or {}
    mapping = payload.get('mapping') or {}
    sheet_setting = SystemSetting.query.filter_by(key='enquiry_sheet_id').first()
    sa_setting = SystemSetting.query.filter_by(key='sa_key').first()
    if not (sa_setting and sa_setting.value and sheet_setting and sheet_setting.value):
        return jsonify({'error': 'Configure credentials and a Sheet ID first.'}), 400
    try:
        import gspread
        gc = gspread.service_account_from_dict(json.loads(sa_setting.value), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        worksheet_setting = SystemSetting.query.filter_by(key='enquiry_worksheet').first()
        book = gc.open_by_key(sheet_setting.value)
        ws = book.worksheet(worksheet_setting.value) if worksheet_setting and worksheet_setting.value else book.sheet1
        rows = ws.get_all_records()
    except Exception as e:
        return jsonify({'error': _safe_error(e)}), 400
    rows = rows[:100]
    preview = []
    for number, row in enumerate(rows, start=2):
        name = str(row.get(mapping.get('name', 'Student Name')) or '').strip()
        email = str(row.get(mapping.get('email', 'Email')) or '').strip()
        preview.append({'row': number, 'name': name, 'email': email,
                        'valid': bool(name) and (not email or bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)))})
    return jsonify({'total': len(rows), 'preview': preview})

@google_sync_bp.route('/api/google-sync/sync', methods=['POST'])
@login_required
@admin_required
def google_sync_sync():
    payload = request.get_json(silent=True) or {}
    mapping = payload.get('mapping', {})
    if not isinstance(mapping, dict) or not mapping.get('name'):
        return jsonify({'error': 'Map the required Name column before syncing.'}), 400
    sa_setting = SystemSetting.query.filter_by(key='sa_key').first()
    sheet_setting = SystemSetting.query.filter_by(key='enquiry_sheet_id').first()
    if not (sa_setting and sa_setting.value and sheet_setting and sheet_setting.value):
        return jsonify({'error': 'Service account key or Sheet ID not configured'}), 400
    try:
        import gspread
        gc = gspread.service_account_from_dict(json.loads(sa_setting.value), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        worksheet_setting = SystemSetting.query.filter_by(key='enquiry_worksheet').first()
        limit_setting = SystemSetting.query.filter_by(key='enquiry_sync_limit').first()
        try:
            limit = max(100, min(int(limit_setting.value) if limit_setting and limit_setting.value else 1000, 10000))
        except (TypeError, ValueError):
            limit = 1000
        book = gc.open_by_key(sheet_setting.value)
        ws = book.worksheet(worksheet_setting.value) if worksheet_setting and worksheet_setting.value else book.sheet1
        rows = ws.get_all_records()[:limit]
    except Exception as e:
        return jsonify({'error': _safe_error(e)}), 400
    if len(rows) > 10000:
        return jsonify({'error': 'This sheet exceeds the 10,000-row safety limit. Use incremental sync first.'}), 413
    imported = 0
    skipped = 0
    invalid = []
    batch_id = uuid.uuid4().hex
    connection = GoogleSyncConnection.query.filter_by(sheet_id=sheet_setting.value).first()
    if connection:
        connection.last_sync_status = 'running'
        connection.last_sync_error = None
        db.session.commit()
    all_courses = {c.name.lower(): c for c in Course.query.all()}
    for row_number, r in enumerate(rows, start=2):
        source_key = str(r.get('Timestamp') or r.get('Response ID') or row_number).strip()
        row_hash = hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()
        existing_row = GoogleSyncRow.query.filter_by(sheet_id=sheet_setting.value, source_key=source_key).first()
        if existing_row and existing_row.source_hash == row_hash:
            existing_row.last_seen_at = datetime.utcnow()
            skipped += 1
            continue
        name = r.get(mapping.get('name', 'Student Name')) or r.get(mapping.get('name', '')) or ''
        email = r.get(mapping.get('email', 'Email')) or ''
        phone = str(r.get(mapping.get('phone', 'Phone')) or '')
        course_str = r.get(mapping.get('course', 'Course')) or ''
        source = r.get(mapping.get('source', 'Source')) or 'Google Form'
        notes = r.get(mapping.get('notes', 'Notes')) or ''
        if not name or len(str(name).strip()) > 100:
            invalid.append({'row': row_number, 'error': 'Name is missing or too long'})
            skipped += 1
            continue
        if email and (not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', str(email).strip()) or len(str(email).strip()) > 100):
            invalid.append({'row': row_number, 'error': 'Invalid email'})
            skipped += 1
            continue
        course = all_courses.get(course_str.strip().lower())
        if not course and course_str.strip():
            course = Course(name=course_str.strip(), code=f'AUTO-{uuid.uuid4().hex[:6].upper()}', description='Auto-created from Google Form', duration_weeks=0, duration_unit='weeks', fees=0)
            db.session.add(course)
            all_courses[course.name.lower()] = course
        enq = Enquiry(student_name=name.strip(), email=email.strip(), phone=phone.strip(),
            course_id=course.id if course else None, source=source.strip()[:50] or 'Google Form', status='New',
            notes=f'[Google Form] {notes}'.strip())
        db.session.add(enq)
        db.session.flush()
        if existing_row:
            existing_row.source_hash = row_hash
            existing_row.enquiry_id = enq.id
            existing_row.batch_id = batch_id
            existing_row.status = 'imported'
        else:
            db.session.add(GoogleSyncRow(sheet_id=sheet_setting.value, source_key=source_key,
                                         source_hash=row_hash, enquiry_id=enq.id, batch_id=batch_id))
        imported += 1
    db.session.commit()
    now_str = datetime.utcnow().strftime('%d %b %Y %H:%M')
    sys_setting = SystemSetting.query.filter_by(key='enquiry_last_sync').first()
    if sys_setting:
        sys_setting.value = now_str
    else:
        db.session.add(SystemSetting(key='enquiry_last_sync', value=now_str))
    _audit('SYNC', {'batch_id': batch_id, 'imported': imported, 'skipped': skipped, 'invalid': len(invalid)})
    if connection:
        connection.last_sync_at = datetime.utcnow()
        connection.last_sync_status = 'completed'
        db.session.commit()
    db.session.commit()
    return jsonify({'status': 'ok', 'batch_id': batch_id, 'imported': imported,
                    'skipped': skipped, 'invalid': invalid}), 200
