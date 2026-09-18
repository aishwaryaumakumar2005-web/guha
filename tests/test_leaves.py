from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import LeaveRequest, User

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _staff_id(app):
    with app.app_context():
        return User.query.filter_by(username='staff').first().id


def _admin_id(app):
    with app.app_context():
        return User.query.filter_by(username='admin').first().id


def _add_leave(app, user_id, start, end, status='Pending', reason='sick leave',
               remarks=None, approved_by=None, actioned_at=None, created_at=None):
    with app.app_context():
        row = LeaveRequest(
            user_id=user_id, start_date=start, end_date=end,
            reason=reason, status=status,
            remarks=remarks, approved_by=approved_by, actioned_at=actioned_at,
            created_at=created_at or datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def _submit_staff_leave(client, start, end, reason='sick leave'):
    return client.post('/leaves', data={
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'reason': reason,
    })


# ---- B1: no state change over GET; approve/reject are POST-only ----

def test_action_route_rejects_get(app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today(), date.today())
    with app.test_client() as admin:
        admin.post('/login', data={'username': 'admin', 'password': 'admin123'})
        resp = admin.get(f'/leaves/action/{leave_id}/approve')
        assert resp.status_code == 405  # method not allowed: no state change
        with app.app_context():
            assert LeaveRequest.query.get(leave_id).status == 'Pending'


def test_approve_via_post_sets_meta(admin_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today(), date.today())
    resp = admin_client.post(f'/leaves/action/{leave_id}/approve',
                             data={'remarks': 'Approved by management'})
    assert resp.status_code == 302
    with app.app_context():
        row = LeaveRequest.query.get(leave_id)
        assert row.status == 'Approved'
        assert row.approved_by == _admin_id(app)
        assert row.actioned_at is not None
        assert row.remarks == 'Approved by management'


def test_reject_via_post(admin_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today(), date.today())
    resp = admin_client.post(f'/leaves/action/{leave_id}/reject',
                             data={'remarks': 'Not enough staff cover'})
    assert resp.status_code == 302
    with app.app_context():
        row = LeaveRequest.query.get(leave_id)
        assert row.status == 'Rejected'
        assert row.approved_by == _admin_id(app)
        assert row.remarks == 'Not enough staff cover'


# ---- B2: only Pending requests can be actioned ----

def test_cannot_approve_already_approved(admin_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today(), date.today(), status='Approved')
    resp = admin_client.post(f'/leaves/action/{leave_id}/approve', follow_redirects=True)
    assert resp.status_code == 200
    assert b'already actioned' in resp.data
    with app.app_context():
        assert LeaveRequest.query.get(leave_id).status == 'Approved'


def test_cannot_reject_already_rejected(admin_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today(), date.today(), status='Rejected')
    resp = admin_client.post(f'/leaves/action/{leave_id}/reject', follow_redirects=True)
    assert resp.status_code == 200
    assert b'already actioned' in resp.data
    with app.app_context():
        assert LeaveRequest.query.get(leave_id).status == 'Rejected'


def test_double_action_ajax_returns_400(admin_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today(), date.today())
    resp = admin_client.post(f'/leaves/action/{leave_id}/approve', headers=AJAX)
    assert resp.status_code == 200
    resp2 = admin_client.post(f'/leaves/action/{leave_id}/approve', headers=AJAX)
    assert resp2.status_code == 400
    assert resp2.get_json()['success'] is False


def test_staff_cannot_action_requests(staff_client, app):
    sid = _staff_id(app)
    other_sid = _admin_id(app)
    leave_id = _add_leave(app, other_sid if other_sid != sid else sid,
                          date.today(), date.today())
    resp = staff_client.post(f'/leaves/action/{leave_id}/reject')
    assert resp.status_code == 302  # redirected by admin_required
    with app.app_context():
        assert LeaveRequest.query.get(leave_id).status == 'Pending'


# ---- B3: overlapping requests are blocked ----

def test_overlapping_pending_request_blocked(staff_client, app):
    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=3)
    assert _submit_staff_leave(staff_client, start, end).status_code == 302
    resp = staff_client.post('/leaves', headers=AJAX, data={
        'start_date': start.isoformat(),
        'end_date': (end - timedelta(days=1)).isoformat(),
        'reason': 'overlap attempt',
    })
    assert resp.status_code == 400
    assert 'overlapping' in resp.get_json()['errors'][0]


def test_non_overlapping_request_allowed(staff_client, app):
    start = date.today() + timedelta(days=1)
    _submit_staff_leave(staff_client, start, start + timedelta(days=1))
    later = start + timedelta(days=10)
    resp = staff_client.post('/leaves', headers=AJAX, data={
        'start_date': later.isoformat(),
        'end_date': (later + timedelta(days=1)).isoformat(),
        'reason': 'another leave',
    })
    assert resp.status_code == 201


def test_overlapping_approved_leave_blocked(staff_client, app):
    sid = _staff_id(app)
    start = date.today() + timedelta(days=1)
    _add_leave(app, sid, start, start + timedelta(days=2), status='Approved')
    resp = staff_client.post('/leaves', headers=AJAX, data={
        'start_date': start.isoformat(),
        'end_date': start.isoformat(),
        'reason': 'clashes with approved leave',
    })
    assert resp.status_code == 400
    assert 'overlapping' in resp.get_json()['errors'][0]


# ---- B4: server-side date/reason sanity ----

def test_past_start_date_rejected(staff_client):
    yesterday = date.today() - timedelta(days=1)
    resp = staff_client.post('/leaves', follow_redirects=True, data={
        'start_date': yesterday.isoformat(),
        'end_date': date.today().isoformat(),
        'reason': 'backdate',
    })
    assert b'cannot be in the past' in resp.data


def test_too_long_leave_rejected(staff_client):
    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=31)
    resp = staff_client.post('/leaves', follow_redirects=True, data={
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'reason': 'long leave',
    })
    assert b'cannot exceed' in resp.data


def test_reason_length_enforced(staff_client):
    start = date.today() + timedelta(days=1)
    resp = staff_client.post('/leaves', follow_redirects=True, data={
        'start_date': start.isoformat(),
        'end_date': (start + timedelta(days=1)).isoformat(),
        'reason': 'x' * 501,
    })
    assert b'cannot exceed' in resp.data


# ---- B5: remarks + approver shown on history ----

def test_history_shows_approver_and_remarks(admin_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today(), date.today())
    admin_client.post(f'/leaves/action/{leave_id}/approve',
                      data={'remarks': 'certificate attached'})
    page = admin_client.get('/leaves')
    html = page.data.decode()
    assert 'by Admin User' in html
    assert 'certificate attached' in html


# ---- B6: server-side cap stops unbounded page loads ----

def test_history_capped_at_limit(admin_client, app):
    sid = _staff_id(app)
    now = datetime.utcnow()
    for i in range(60):
        _add_leave(app, sid, date.today(), date.today(),
                   status='Approved', reason=f'reason-{i:03d}',
                   created_at=now - timedelta(minutes=60 - i))
    html = admin_client.get('/leaves').data.decode()
    assert 'Showing the 50 most recent requests (60 total)' in html
    assert 'reason-059' in html      # newest shown first
    assert 'reason-000' not in html  # oldest 10 hidden


def test_pending_capped_at_limit(admin_client, app):
    sid = _staff_id(app)
    now = datetime.utcnow()
    for i in range(60):
        _add_leave(app, sid, date.today(), date.today(),
                   status='Pending', reason=f'pend-{i:03d}',
                   created_at=now - timedelta(minutes=60 - i))
    html = admin_client.get('/leaves').data.decode()
    assert 'Showing the 50 oldest pending requests (60 total)' in html
    assert 'pend-000' in html        # oldest shown first
    assert 'pend-059' not in html    # newest 10 hidden


def test_staff_history_capped_at_limit(staff_client, app):
    sid = _staff_id(app)
    now = datetime.utcnow()
    for i in range(60):
        _add_leave(app, sid, date.today(), date.today(),
                   status='Approved', reason=f'staff-{i:03d}',
                   created_at=now - timedelta(minutes=60 - i))
    html = staff_client.get('/leaves').data.decode()
    assert 'Showing the 50 most recent requests (60 total)' in html
    assert 'staff-059' in html
    assert 'staff-000' not in html