import os
import json
import io
import pytest
from app.helpers import get_backup_dir


def test_extras_page_admin_access(admin_client):
    resp = admin_client.get('/extras')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Extra Features &amp; Utilities' in html or 'Extra Features' in html
    assert 'Database Backups' in html or 'Snapshots' in html


def test_extras_page_staff_blocked(staff_client):
    resp = staff_client.get('/extras')
    # Staff should be blocked by admin_required (302 redirect or 403)
    assert resp.status_code in (302, 403)


def test_extras_backups_list_api(admin_client):
    resp = admin_client.get('/extras/backups')
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)


def test_extras_backup_lifecycle(admin_client, app):
    # 1. Create backup
    resp = admin_client.post('/extras/backup/create',
                             headers={'X-Requested-With': 'fetch'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    filename = data.get('filename')
    assert filename is not None

    # 2. Verify file exists in backup dir
    backup_dir = get_backup_dir(app)
    filepath = os.path.join(backup_dir, filename)
    assert os.path.exists(filepath)

    # 3. Download backup
    dl_resp = admin_client.get(f'/extras/backup/download/{filename}')
    assert dl_resp.status_code == 200
    assert 'attachment' in dl_resp.headers.get('Content-Disposition', '')
    dl_resp.close()

    # 4. Delete backup
    del_resp = admin_client.post(f'/extras/backup/delete/{filename}',
                                 headers={'X-Requested-With': 'fetch'})
    assert del_resp.status_code == 200
    del_data = del_resp.get_json()
    assert del_data['success'] is True
    assert not os.path.exists(filepath)


def test_extras_upload_backup(admin_client, app):
    backup_dir = get_backup_dir(app)
    sample_content = json.dumps({'student': []}).encode('utf-8')
    data = {
        'backup_file': (io.BytesIO(sample_content), 'test_sample_backup.json')
    }
    resp = admin_client.post('/extras/backup/upload', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'uploaded_' in html or 'successfully' in html

    # Clean up uploaded file
    for f in os.listdir(backup_dir):
        if 'test_sample_backup' in f:
            try:
                os.remove(os.path.join(backup_dir, f))
            except Exception:
                pass
