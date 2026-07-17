import json
import uuid
import hashlib
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash
from flask_login import login_required
from app.extensions import db
from app.models import Enquiry, Course, SystemSetting
from app.helpers import admin_required

google_sync_bp = Blueprint('google_sync', __name__)

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
        form_url=form_url, synced_enquiries=synced_enquiries, courses=Course.query.all())

@google_sync_bp.route('/api/google-sync/upload-key', methods=['POST'])
@login_required
@admin_required
def google_sync_upload_key():
    key_json = request.json.get('key_json', '').strip()
    if not key_json:
        return jsonify({'error': 'No key provided'}), 400
    try:
        json.loads(key_json)
    except json.decoder.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON'}), 400
    setting = SystemSetting.query.filter_by(key='sa_key').first()
    if setting:
        setting.value = key_json
    else:
        db.session.add(SystemSetting(key='sa_key', value=key_json))
    db.session.commit()
    return jsonify({'status': 'ok'}), 200

@google_sync_bp.route('/api/google-sync/save-sheet', methods=['POST'])
@login_required
@admin_required
def google_sync_save_sheet():
    sheet_id = request.json.get('sheet_id', '').strip()
    form_url = request.json.get('form_url', '').strip()
    for key, val in [('enquiry_sheet_id', sheet_id), ('enquiry_form_url', form_url)]:
        if val:
            setting = SystemSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = val
            else:
                db.session.add(SystemSetting(key=key, value=val))
    db.session.commit()
    return jsonify({'status': 'ok'}), 200

@google_sync_bp.route('/api/google-sync/status')
@login_required
@admin_required
def google_sync_status():
    import gspread
    sa_setting = SystemSetting.query.filter_by(key='sa_key').first()
    sheet_setting = SystemSetting.query.filter_by(key='enquiry_sheet_id').first()
    if not (sa_setting and sa_setting.value):
        return jsonify({'connected': False, 'error': 'Service account key not found. Complete Step 1 first.'})
    if not (sheet_setting and sheet_setting.value):
        return jsonify({'connected': False, 'error': 'Sheet ID not found. Complete Step 2 first.'})
    try:
        key_dict = json.loads(sa_setting.value)
        if 'client_email' not in key_dict:
            return jsonify({'connected': False, 'error': 'Invalid service account JSON - missing client_email field.'})
        gc = gspread.service_account_from_dict(key_dict, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        sheet = gc.open_by_key(sheet_setting.value).sheet1
        headers = sheet.row_values(1)
        return jsonify({'connected': True, 'headers': headers, 'row_count': len(sheet.get_all_values())})
    except Exception as e:
        msg = str(e)
        if not msg and e.__cause__:
            msg = str(e.__cause__)
        return jsonify({'connected': False, 'error': msg or 'Unknown error (check API permissions)'})

@google_sync_bp.route('/api/google-sync/sync', methods=['POST'])
@login_required
@admin_required
def google_sync_sync():
    mapping = request.json.get('mapping', {})
    sa_setting = SystemSetting.query.filter_by(key='sa_key').first()
    sheet_setting = SystemSetting.query.filter_by(key='enquiry_sheet_id').first()
    if not (sa_setting and sa_setting.value and sheet_setting and sheet_setting.value):
        return jsonify({'error': 'Service account key or Sheet ID not configured'}), 400
    synced_ids_setting = SystemSetting.query.filter_by(key='enquiry_synced_ids').first()
    synced_ids = synced_ids_setting.value.split(',') if synced_ids_setting and synced_ids_setting.value else []
    try:
        import gspread
        gc = gspread.service_account_from_dict(json.loads(sa_setting.value), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        ws = gc.open_by_key(sheet_setting.value).sheet1
        rows = ws.get_all_records()
    except Exception as e:
        msg = str(e)
        if not msg and e.__cause__:
            msg = str(e.__cause__)
        return jsonify({'error': f'Sheet read failed: {msg}'}), 400
    imported = 0
    skipped = 0
    all_courses = {c.name.lower(): c for c in Course.query.all()}
    for r in rows:
        row_hash = hashlib.md5(str(r).encode()).hexdigest()
        if row_hash in synced_ids:
            skipped += 1
            continue
        name = r.get(mapping.get('name', 'Student Name')) or r.get(mapping.get('name', '')) or ''
        email = r.get(mapping.get('email', 'Email')) or ''
        phone = str(r.get(mapping.get('phone', 'Phone')) or '')
        course_str = r.get(mapping.get('course', 'Course')) or ''
        source = r.get(mapping.get('source', 'Source')) or 'Google Form'
        notes = r.get(mapping.get('notes', 'Notes')) or ''
        if not name:
            skipped += 1
            continue
        course = all_courses.get(course_str.strip().lower())
        if not course and course_str.strip():
            course = Course(name=course_str.strip(), code=f'AUTO-{uuid.uuid4().hex[:6].upper()}', description='Auto-created from Google Form', duration_weeks=0, duration_unit='weeks', fees=0)
            db.session.add(course)
            all_courses[course.name.lower()] = course
        enq = Enquiry(student_name=name.strip(), email=email.strip(), phone=phone.strip(),
            course_id=course.id if course else 1, source=source.strip() or 'Google Form', status='New',
            notes=f'[Google Form] {notes}'.strip())
        db.session.add(enq)
        synced_ids.append(row_hash)
        imported += 1
    db.session.commit()
    now_str = datetime.utcnow().strftime('%d %b %Y %H:%M')
    sys_setting = SystemSetting.query.filter_by(key='enquiry_last_sync').first()
    if sys_setting:
        sys_setting.value = now_str
    else:
        db.session.add(SystemSetting(key='enquiry_last_sync', value=now_str))
    if synced_ids_setting:
        synced_ids_setting.value = ','.join(synced_ids)
    else:
        db.session.add(SystemSetting(key='enquiry_synced_ids', value=','.join(synced_ids)))
    db.session.commit()
    return jsonify({'status': 'ok', 'imported': imported, 'skipped': skipped}), 200
