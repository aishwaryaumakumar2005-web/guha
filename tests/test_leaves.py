from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import LeaveRequest, User, Attendance, Tutor

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def _staff_id(app):
    with app.app_context():
        return User.query.filter_by(username='staff').first().id


def _admin_id(app):
    with app.app_context():
        return User.query.filter_by(username='admin').first().id


def _add_leave(app, user_id, start, end, status='Pending', reason='sick leave',
               remarks=None, approved_by=None, actioned_at=None, created_at=None,
               leave_type=None):
    with app.app_context():
        row = LeaveRequest(
            user_id=user_id, start_date=start, end_date=end,
            reason=reason, status=status, leave_type=leave_type,
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


# ---- F1: leave types + yearly balance ----

def _approve(app, leave_id, remarks=''):
    with app.test_client() as admin:
        admin.post('/login', data={'username': 'admin', 'password': 'admin123'})
        return admin.post(f'/leaves/action/{leave_id}/approve', data={'remarks': remarks})


def test_submission_saves_default_leave_type(staff_client, app):
    start = date.today() + timedelta(days=1)
    resp = staff_client.post('/leaves', data={
        'start_date': start.isoformat(), 'end_date': start.isoformat(),
        'reason': 'no type chosen'})
    assert resp.status_code == 302
    with app.app_context():
        row = LeaveRequest.query.filter_by(user_id=_staff_id(app)).first()
        assert row.leave_type == 'Casual'


def test_submission_saves_chosen_leave_type(staff_client, app):
    start = date.today() + timedelta(days=1)
    resp = staff_client.post('/leaves', data={
        'start_date': start.isoformat(), 'end_date': start.isoformat(),
        'reason': 'sick', 'leave_type': 'Sick'})
    assert resp.status_code == 302
    with app.app_context():
        row = LeaveRequest.query.filter_by(user_id=_staff_id(app)).first()
        assert row.leave_type == 'Sick'


def test_bogus_leave_type_rejected(staff_client, app):
    start = date.today() + timedelta(days=1)
    resp = staff_client.post('/leaves', data={
        'start_date': start.isoformat(), 'end_date': start.isoformat(),
        'reason': 'x', 'leave_type': 'TimeOff'}, follow_redirects=True)
    assert b'must be one of' in resp.data
    with app.app_context():
        assert LeaveRequest.query.filter_by(user_id=_staff_id(app)).first() is None


def test_staff_page_shows_balance(staff_client, app):
    sid = _staff_id(app)
    year_start = date(date.today().year, 1, 1)
    _add_leave(app, sid, year_start, year_start + timedelta(days=1),
               status='Approved', leave_type='Casual')
    html = staff_client.get('/leaves').data.decode()
    assert 'Leave Balance' in html
    assert '12 used' in html
    assert '10 left' in html
    assert 'Sick' in html


def test_balance_clamps_remaining_at_zero(staff_client, app):
    sid = _staff_id(app)
    year_start = date(date.today().year, 1, 1)
    _add_leave(app, sid, year_start, year_start + timedelta(days=11),
               status='Approved', leave_type='Casual')
    _add_leave(app, sid, year_start + timedelta(days=20), year_start + timedelta(days=21),
               status='Approved', leave_type='Casual')
    html = staff_client.get('/leaves').data.decode()
    assert '12 used' in html
    assert '0 left' in html


# ---- F2: approval syncs the covered dates into attendance ----

def test_approve_marks_dates_in_attendance(app):
    start = date.today() + timedelta(days=1)
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, start, start + timedelta(days=2))
    _approve(app, leave_id)
    with app.app_context():
        tutor = Tutor.query.filter_by(email='staff@guha.test').first()
        rows = Attendance.query.filter_by(
            person_type='tutor', person_id=tutor.id, status='Leave').all()
        assert len(rows) == 3
        assert {r.date for r in rows} == {start, start + timedelta(days=1), start + timedelta(days=2)}
        assert all(r.marked_by == 'auto_leave' for r in rows)


def test_approve_does_not_clobber_existing_attendance(app):
    sid = _staff_id(app)
    start = date.today() + timedelta(days=1)
    mid = start + timedelta(days=1)
    with app.app_context():
        tutor = Tutor.query.filter_by(email='staff@guha.test').first()
        db.session.add(Attendance(person_type='tutor', person_id=tutor.id,
                                  date=mid, status='Present', marked_by='manual'))
        db.session.commit()
    leave_id = _add_leave(app, sid, start, start + timedelta(days=2))
    _approve(app, leave_id)
    with app.app_context():
        tutor = Tutor.query.filter_by(email='staff@guha.test').first()
        rows = Attendance.query.filter_by(
            person_type='tutor', person_id=tutor.id).order_by(Attendance.date).all()
        assert len(rows) == 3
        assert [r.date for r in rows] == [start, mid, start + timedelta(days=2)]
        assert any(r.date == mid and r.status == 'Present' and r.marked_by == 'manual'
                   for r in rows)


def test_approve_without_tutor_does_not_crash(app):
    with app.app_context():
        from werkzeug.security import generate_password_hash
        u = User(username='staff2', password_hash=generate_password_hash('x'),
                 role='Staff', name='Staff Two', email='staff2@guha.test')
        db.session.add(u)
        db.session.flush()
        uid = u.id
        start = date.today() + timedelta(days=1)
        leave_id = _add_leave(app, uid, start, start + timedelta(days=1))
    with app.test_client() as admin:
        admin.post('/login', data={'username': 'admin', 'password': 'admin123'})
        resp = admin.post(f'/leaves/action/{leave_id}/approve')
        assert resp.status_code == 302
    with app.app_context():
        assert LeaveRequest.query.get(leave_id).status == 'Approved'


# ---- F3: status-change notifications (best effort) ----

def test_status_change_sends_notification(app, monkeypatch):
    calls = {}
    with app.app_context():
        notifier = app.notifier
        messenger = app.messenger
        monkeypatch.setattr(
            notifier, 'notify_leave_status',
            lambda to, staff_name, dates_text, status, remarks=None: calls.update(
                email=(to, status, remarks)) or True)
        monkeypatch.setattr(
            messenger, 'send_leave_status',
            lambda phone, staff_name, dates_text, status, remarks=None: calls.update(
                sms=(phone, status, remarks)) or True)
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today() + timedelta(days=1), date.today() + timedelta(days=1))
    with app.test_client() as admin:
        admin.post('/login', data={'username': 'admin', 'password': 'admin123'})
        admin.post(f'/leaves/action/{leave_id}/reject', data={'remarks': 'no cover'})
    assert calls.get('email') == ('staff@guha.test', 'Rejected', 'no cover')
    assert calls.get('sms') == ('9876543210', 'Rejected', 'no cover')


def test_approve_fails_notification_still_approves(app, monkeypatch):
    with app.app_context():
        def boom(*a, **k):
            raise RuntimeError('smtp down')
        monkeypatch.setattr(app.notifier, 'notify_leave_status', boom)
        monkeypatch.setattr(app.messenger, 'send_leave_status', boom)
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today() + timedelta(days=1), date.today() + timedelta(days=1))
    resp = _approve(app, leave_id)
    assert resp.status_code == 302
    with app.app_context():
        assert LeaveRequest.query.get(leave_id).status == 'Approved'


# ---- F4: staff can withdraw their own pending request ----

def test_staff_withdraws_own_pending(staff_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today() + timedelta(days=1), date.today() + timedelta(days=2))
    resp = staff_client.post(f'/leaves/withdraw/{leave_id}')
    assert resp.status_code == 302
    with app.app_context():
        assert LeaveRequest.query.get(leave_id) is None


def test_staff_withdraws_own_pending_ajax(staff_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today() + timedelta(days=1), date.today() + timedelta(days=2))
    resp = staff_client.post(f'/leaves/withdraw/{leave_id}', headers=AJAX)
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    with app.app_context():
        assert LeaveRequest.query.get(leave_id) is None


def test_cannot_withdraw_others_leave(staff_client, app):
    aid = _admin_id(app)
    leave_id = _add_leave(app, aid, date.today() + timedelta(days=1), date.today() + timedelta(days=2))
    resp = staff_client.post(f'/leaves/withdraw/{leave_id}', headers=AJAX)
    assert resp.status_code == 403
    with app.app_context():
        assert LeaveRequest.query.get(leave_id) is not None


def test_cannot_withdraw_approved_leave(staff_client, app):
    sid = _staff_id(app)
    leave_id = _add_leave(app, sid, date.today() + timedelta(days=1),
                          date.today() + timedelta(days=2), status='Approved')
    resp = staff_client.post(f'/leaves/withdraw/{leave_id}', follow_redirects=True)
    assert b'Only pending requests can be cancelled' in resp.data
    with app.app_context():
        assert LeaveRequest.query.get(leave_id).status == 'Approved'


# ---- F5: pending aging view ----

def test_pending_older_than_threshold_shows_aging_badge(admin_client, app):
    sid = _staff_id(app)
    old = datetime.utcnow() - timedelta(days=10)
    _add_leave(app, sid, date.today() + timedelta(days=1), date.today() + timedelta(days=1),
               created_at=old)
    html = admin_client.get('/leaves').data.decode()
    assert '10d pending' in html


def test_fresh_pending_has_no_aging_badge(admin_client, app):
    sid = _staff_id(app)
    _add_leave(app, sid, date.today() + timedelta(days=1), date.today() + timedelta(days=1))
    html = admin_client.get('/leaves').data.decode()
    assert 'd pending' not in html


# ---- F6: CSV export ----

def test_export_csv_returns_attachment_with_bom(admin_client, app):
    sid = _staff_id(app)
    future = date.today() + timedelta(days=1)
    _add_leave(app, sid, future, future + timedelta(days=1),
               status='Approved', leave_type='Sick')
    resp = admin_client.get('/leaves/export')
    assert resp.status_code == 200
    assert resp.headers['Content-Disposition'].startswith('attachment')
    assert resp.data.startswith(b'\xef\xbb\xbf')
    text = resp.data.decode('utf-8-sig')
    lines = text.strip().splitlines()
    header = lines[0].split(',')
    for col in ('Staff Name', 'Leave Type', 'Start Date', 'Duration Days', 'Status', 'Approved By'):
        assert col in header
    assert any('Sick' in line and 'Approved' in line for line in lines[1:])


def test_export_staff_sees_only_own_rows(staff_client, app):
    sid = _staff_id(app)
    aid = _admin_id(app)
    future = date.today() + timedelta(days=1)
    _add_leave(app, sid, future, future, status='Approved', leave_type='Casual')
    _add_leave(app, aid, future, future, status='Approved', leave_type='Casual')
    text = staff_client.get('/leaves/export').data.decode('utf-8-sig')
    assert 'Staff User' in text
    assert 'Admin User' not in text


def test_export_filters_by_status(admin_client, app):
    sid = _staff_id(app)
    future = date.today() + timedelta(days=1)
    _add_leave(app, sid, future, future, status='Approved', leave_type='Casual')
    _add_leave(app, sid, future + timedelta(days=5), future + timedelta(days=5), status='Rejected')
    text = admin_client.get('/leaves/export?status=Rejected').data.decode('utf-8-sig')
    lines = text.strip().splitlines()
    assert any('Rejected' in line for line in lines[1:])
    assert not any('Approved' in line for line in lines[1:])


# ---- F7: dashboard stat cards ----

def test_admin_dashboard_shows_pending_leaves_card(admin_client, app):
    sid = _staff_id(app)
    _add_leave(app, sid, date.today() + timedelta(days=1), date.today() + timedelta(days=1))
    html = admin_client.get('/').data.decode()
    assert 'Leave requests to review' in html


def test_staff_dashboard_shows_days_used_card(staff_client, app):
    sid = _staff_id(app)
    today = date.today()
    month_start = today.replace(day=1)
    if today > month_start:
        _add_leave(app, sid, month_start, today - timedelta(days=1), status='Approved')
    html = staff_client.get('/').data.decode()
    assert 'Leave days' in html
    assert 'Used so far' in html