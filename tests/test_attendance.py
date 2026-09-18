"""Regression tests for the attendance module overhaul.

Covers: roster page structure + balanced scripts (unclosed-script bug),
date navigation, hardened mark API (guarded int, status allowlist, admin-only
past dates, tutor-route authz), QR scan semantics (person_id, manual-mark
protection), and the per-person/date uniqueness constraint.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Attendance, Student, Tutor


def _student_id(app):
    with app.app_context():
        return Student.query.filter_by(email='student@guha.test').first().id


def _tutor_id(app):
    with app.app_context():
        return Tutor.query.filter_by(email='staff@guha.test').first().id


def _qr_uuid(app):
    with app.app_context():
        return Student.query.filter_by(email='student@guha.test').first().qr_code_uuid


def test_attendance_page_admin(admin_client):
    body = admin_client.get('/attendance').get_data(as_text=True)
    assert 'Attendance Console' in body
    assert 'id="students-summary"' in body
    assert 'id="tutors-summary"' in body
    assert 'id="aiAttendanceAnalysisModal"' in body
    assert 'function loadAttendanceAnalysis' in body
    assert 'id="btn-start-scanner"' in body
    assert 'attendance-status-select' in body
    assert 'Mark all present' in body
    assert 'Export CSV' in body


def test_attendance_page_script_balanced(admin_client):
    # Regression: the unclosed `<script data-ts="white-fix-v3">` swallowed the
    # AI modal and its function. Open/close script tags must balance and the
    # modal must appear OUTSIDE script data.
    body = admin_client.get('/attendance').get_data(as_text=True)
    assert body.count('<script') == body.count('</script>')
    modal_idx = body.find('id="aiAttendanceAnalysisModal"')
    first_close = body.find('</script>')
    assert modal_idx != -1
    assert first_close == -1 or modal_idx < first_close or body[modal_idx:first_close].count('<script') == 0
    assert '<script data-ts=' not in body


def test_attendance_page_date_navigation(admin_client):
    three_days_ago = (date.today() - timedelta(days=3)).isoformat()
    body = admin_client.get('/attendance?date=' + three_days_ago).get_data(as_text=True)
    assert 'id="att-date-display"' in body
    assert 'date=' + three_days_ago in body or three_days_ago in body
    # Next-day nav link points to two days ago.
    assert 'date=' + (date.today() - timedelta(days=2)).isoformat() in body


def test_attendance_page_invalid_date_falls_back(admin_client):
    body = admin_client.get('/attendance?date=not-a-date').get_data(as_text=True)
    assert date.today().strftime('%d %b %Y') in body
    assert 'showing today' in body


def test_mark_api_rejects_bad_person_id(admin_client):
    resp = admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': 'abc', 'status': 'Present',
    })
    assert resp.status_code == 400
    resp = admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': 0, 'status': 'Present',
    })
    assert resp.status_code == 400


def test_mark_api_rejects_bad_status(admin_client, app):
    resp = admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': _student_id(app), 'status': 'Sleeping',
    })
    assert resp.status_code == 400


def test_admin_marks_past_date(admin_client, app):
    sid = _student_id(app)
    past = (date.today() - timedelta(days=2)).isoformat()
    resp = admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Late', 'date': past,
    })
    assert resp.status_code == 200
    with app.app_context():
        rec = Attendance.query.filter_by(person_type='student', person_id=sid,
                                         date=date.today() - timedelta(days=2)).first()
        assert rec is not None
        assert rec.status == 'Late'
        assert rec.marked_by == 'manual'


def test_staff_cannot_mark_past_date(staff_client, app):
    sid = _student_id(app)
    past = (date.today() - timedelta(days=1)).isoformat()
    resp = staff_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Present', 'date': past,
    })
    assert resp.status_code == 403


def test_staff_marks_own_tutor_attendance(staff_client, app):
    tid = _tutor_id(app)
    resp = staff_client.post('/api/attendance/mark', json={
        'person_type': 'tutor', 'person_id': tid, 'status': 'Present',
    })
    assert resp.status_code == 200
    with app.app_context():
        rec = Attendance.query.filter_by(person_type='tutor', person_id=tid,
                                         date=date.today()).first()
        assert rec is not None
        assert rec.status == 'Present'


def test_tutor_route_self_ok(staff_client, app):
    tid = _tutor_id(app)
    sid = _student_id(app)
    resp = staff_client.post(f'/api/tutor/{tid}/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Present',
    })
    assert resp.status_code == 200


def test_tutor_route_cross_tutor_forbidden(staff_client, app):
    with app.app_context():
        other = Tutor(name='Other Tutor', email='other@guha.test', phone='9000000001', status='Active')
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    resp = staff_client.post(f'/api/tutor/{other_id}/attendance/mark', json={
        'person_type': 'student', 'person_id': 1, 'status': 'Present',
    })
    assert resp.status_code == 403


def test_scan_returns_person_id(admin_client, app):
    resp = admin_client.post('/api/attendance/scan', json={'qr_code_uuid': _qr_uuid(app)})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['person_id'] == _student_id(app)
    assert data['role'] == 'student'


def test_scan_unknown_qr(admin_client):
    resp = admin_client.post('/api/attendance/scan', json={'qr_code_uuid': 'no-such-uuid'})
    assert resp.status_code == 404


def test_scan_does_not_override_manual_mark(admin_client, app):
    sid = _student_id(app)
    # Admin records 'Late' manually, then a QR scan must NOT overwrite it.
    assert admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Late',
    }).status_code == 200
    resp = admin_client.post('/api/attendance/scan', json={'qr_code_uuid': _qr_uuid(app)})
    assert resp.status_code == 409
    with app.app_context():
        rec = Attendance.query.filter_by(person_type='student', person_id=sid, date=date.today()).first()
        assert rec.status == 'Late'
        assert rec.marked_by == 'manual'


def test_unique_person_date_constraint(app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(Attendance(person_type='student', person_id=sid, date=date.today(), status='Present'))
        db.session.commit()
        # Second row for the same person+day violates uniqueness.
        db.session.add(Attendance(person_type='student', person_id=sid, date=date.today(), status='Absent'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        # A different day stays insertable.
        db.session.add(Attendance(person_type='student', person_id=sid,
                                  date=date.today() - timedelta(days=1), status='Absent'))
        db.session.commit()
        rows_today = Attendance.query.filter_by(person_type='student', person_id=sid, date=date.today()).all()
        assert len(rows_today) == 1