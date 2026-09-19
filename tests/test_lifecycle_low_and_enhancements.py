"""Low bugs (B5-B11) and UI/UX-functional enhancements (E1-E12).

B5: legacy/unknown student.status strings fold into the Inactive bucket
    instead of creating an unmatchable bucket.
B6: the archived filter lists genuinely archived students.
B8: "Never" renders as an em-dash in Last Activity.
B9: attendance rows default to the local calendar date, not UTC.
B11: attendance APIs report when a same-day mark overwrote an earlier one.
E1: CSV export respects the same filters as the page (staff included).
E3: per-student "reviewed" ack (upsert) + audit, admin-only.
E4: single-row overall-status change, admin-only, audited with from/to.
E5/E6: course retention KPI card renders.
E7/E8: detail drawer gains activity log + lead origin.
E9: threshold rule badge; E12: cohort-year filter.
E10: staff read-only console (page/detail/export OK; writes blocked).
E11: archive suggestion only for stale long-absent actives.
"""
from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Attendance, AuditLog, Course, Enquiry, LifecycleAck, Student, Tutor,
    ensure_enrolled_on,
)
from app.routes.student_lifecycle import (
    _canonical_status, _suggest_archive, _default_thresholds,
)


def _seed_sid(app):
    with app.app_context():
        return Student.query.filter_by(email='student@guha.test').first().id


# ---- B5 / B6: canonical status + archived filter ----

def test_canonical_status_maps_legacy_values():
    assert _canonical_status('Active') == 'Active'
    assert _canonical_status(None) == 'Active'
    assert _canonical_status('Archived') == 'Archived'
    assert _canonical_status('') == 'Inactive'
    assert _canonical_status('Suspended') == 'Inactive'
    assert _canonical_status('Pending Withdrawal') == 'Inactive'


def test_legacy_status_student_lands_in_inactive_filter(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        s = Student(name='Legacy Lady', email='legacy@guha.test',
                    phone='9111111111', status='Suspended')
        db.session.add(s)
        db.session.flush()
        s.courses.append(Course.query.get(cid))
        db.session.flush()
        ensure_enrolled_on(s.id)
        db.session.commit()
        s.status = 'Suspended'
        db.session.commit()
    body = admin_client.get('/students/lifecycle?filter=inactive').get_data(as_text=True)
    assert 'Legacy Lady' in body


def test_archived_filter_lists_archived_student(admin_client, app):
    with app.app_context():
        s = Student(name='Archived Andy', email='arch@guha.test',
                    phone='9222222222', status='Archived')
        db.session.add(s)
        db.session.commit()
    body = admin_client.get('/students/lifecycle?filter=archived').get_data(as_text=True)
    assert 'Archived Andy' in body


# ---- B8: Last Activity dash ----

def test_last_activity_shows_dash_when_never(admin_client, app):
    with app.app_context():
        s = Student(name='Fresh Fred', email='fred@guha.test',
                    phone='9333333333', status='Active')
        db.session.add(s)
        db.session.commit()
    body = admin_client.get('/students/lifecycle').get_data(as_text=True)
    assert 'lc-never' in body
    assert '>Never</span>' not in body


# ---- B9: attendance defaults to the local date ----

def test_attendance_default_is_local_today(app):
    with app.app_context():
        sid = _seed_sid(app)
        rec = Attendance(person_type='student', person_id=sid, status='Present')
        db.session.add(rec)
        db.session.flush()
        assert rec.date == date.today()


# ---- B11: same-day overwrites are disclosed ----

def test_attendance_mark_reports_previous_status(admin_client, app):
    sid = _seed_sid(app)
    r1 = admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Present'})
    assert r1.status_code == 200
    assert 'previous_status' not in r1.get_json()
    r2 = admin_client.post('/api/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Absent'})
    j = r2.get_json()
    assert j['success'] is True
    assert j['previous_status'] == 'Present'


def test_tutor_mark_reports_previous_status(staff_client, app):
    with app.app_context():
        sid = _seed_sid(app)
        tid = Tutor.query.order_by(Tutor.id).first().id
    staff_client.post(f'/api/tutor/{tid}/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Late'})
    r2 = staff_client.post(f'/api/tutor/{tid}/attendance/mark', json={
        'person_type': 'student', 'person_id': sid, 'status': 'Absent'})
    j = r2.get_json()
    assert j['success'] is True
    assert j['previous_status'] == 'Late'


# ---- E1: CSV export honours filters, staff included ----

def test_export_csv_includes_seeded_student(admin_client):
    resp = admin_client.get('/students/lifecycle/export')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/csv')
    text = resp.get_data(as_text=True)
    assert 'Name' in text
    assert 'Test Student' in text


def test_export_csv_staff_ok(staff_client):
    resp = staff_client.get('/students/lifecycle/export')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/csv')


def test_export_csv_respects_filter_and_download_name(admin_client, app):
    with app.app_context():
        s = Student(name='Stale Sam', email='sam@guha.test',
                    phone='9444444444', status='Inactive')
        db.session.add(s)
        db.session.commit()
    resp = admin_client.get('/students/lifecycle/export?filter=inactive')
    text = resp.get_data(as_text=True)
    assert 'Stale Sam' in text
    assert 'Test Student' not in text
    cd = resp.headers.get('Content-Disposition', '')
    assert 'lifecycle_inactive_' in cd and '.csv' in cd


# ---- E3: reviewed/acknowledge ----

def test_acknowledge_upserts_and_audits(admin_client, app):
    with app.app_context():
        sid = _seed_sid(app)
        before = AuditLog.query.count()
    resp = admin_client.post(f'/students/lifecycle/{sid}/acknowledge',
                             data={'note': 'called parent'}, follow_redirects=True)
    assert 'Marked Test Student as reviewed' in resp.get_data(as_text=True)
    with app.app_context():
        ack = LifecycleAck.query.filter_by(student_id=sid).first()
        assert ack is not None and ack.note == 'called parent'
        assert ack.acknowledged_by == 'admin'
        assert AuditLog.query.count() == before + 1
    # re-ack refreshes in place, never duplicates rows
    admin_client.post(f'/students/lifecycle/{sid}/acknowledge',
                      data={'note': 'second pass'})
    with app.app_context():
        acks = LifecycleAck.query.filter_by(student_id=sid).all()
        assert len(acks) == 1 and acks[0].note == 'second pass'


def test_acknowledge_admin_only(staff_client, app):
    with app.app_context():
        sid = _seed_sid(app)
    resp = staff_client.post(f'/students/lifecycle/{sid}/acknowledge',
                             data={'note': 'x'})
    assert resp.status_code == 302
    with app.app_context():
        assert LifecycleAck.query.filter_by(student_id=sid).first() is None


# ---- E4: single-row status change ----

def test_set_status_changes_and_records_from_to(admin_client, app):
    with app.app_context():
        sid = _seed_sid(app)
        before = AuditLog.query.count()
    admin_client.post(f'/students/lifecycle/{sid}/status',
                      data={'status': 'Inactive'})
    with app.app_context():
        assert Student.query.get(sid).status == 'Inactive'
        # +1: the Student before_update audit listener logs the from/to.
        assert AuditLog.query.count() == before + 1
        last = AuditLog.query.order_by(AuditLog.id.desc()).first()
        assert last.action == 'UPDATE'
        assert last.changes_dict()['status'] == {'from': 'Active', 'to': 'Inactive'}


def test_set_status_invalid_value_rejected(admin_client, app):
    sid = _seed_sid(app)
    admin_client.post(f'/students/lifecycle/{sid}/status',
                      data={'status': 'Suspended'})
    with app.app_context():
        assert Student.query.get(sid).status == 'Active'


def test_status_admin_only(staff_client, app):
    with app.app_context():
        sid = _seed_sid(app)
    assert staff_client.post(f'/students/lifecycle/{sid}/status',
                             data={'status': 'Inactive'}).status_code == 302
    with app.app_context():
        assert Student.query.get(sid).status == 'Active'


# ---- E5/E6: course retention KPIs ----

def test_kpi_card_renders_retention(admin_client):
    body = admin_client.get('/students/lifecycle').get_data(as_text=True)
    assert 'lcKpiCard' in body
    assert 'Course retention' in body
    assert 'Retention' in body


# ---- E7/E8: drawer enrichment (activity log, lead origin, ack state) ----

def test_detail_includes_enquiry_activity_and_ack(admin_client, app):
    with app.app_context():
        sid = _seed_sid(app)
        cid = Course.query.filter_by(code='PY').first().id
        enq = Enquiry(student_name='Test Student', email='student@guha.test',
                      phone='9876543210', course_id=cid, status='New',
                      source='Website')
        db.session.add(enq)
        db.session.commit()
    j = admin_client.get(f'/students/lifecycle/{sid}/detail').get_json()
    assert j['enquiry'] is not None and j['enquiry']['source'] == 'Website'
    assert isinstance(j['activity'], list)
    assert 'ack' in j
    assert j['is_admin'] is True


def test_detail_enquiry_matches_email_case_insensitively(admin_client, app):
    with app.app_context():
        sid = _seed_sid(app)
        cid = Course.query.filter_by(code='PY').first().id
        enq = Enquiry(student_name='Test Student', email='STUDENT@GUHA.TEST',
                      phone='9876543210', course_id=cid, status='New',
                      source='Instagram')
        db.session.add(enq)
        db.session.commit()
    j = admin_client.get(f'/students/lifecycle/{sid}/detail').get_json()
    assert j['enquiry']['source'] == 'Instagram'


# ---- E9/E12: badge + year filter ----

def test_threshold_rule_badge_present(admin_client):
    body = admin_client.get('/students/lifecycle').get_data(as_text=True)
    assert 'Rule:' in body


def test_year_filter_renders_current_year(admin_client):
    body = admin_client.get('/students/lifecycle').get_data(as_text=True)
    assert 'lcYear' in body
    assert 'Any year' in body
    assert str(date.today().year) in body


# ---- E10: staff read-only console ----

def test_staff_lifecycle_console_read_only(staff_client):
    body = staff_client.get('/students/lifecycle').get_data(as_text=True)
    assert 'Student Records' in body
    assert 'class="lc-check"' not in body
    assert 'id="checkAll"' not in body
    assert 'id="bulkBar"' not in body
    assert 'onclick="bulkPrompt(' not in body
    assert 'data-lc-action=' not in body
    # Drawer buttons (ack/status) only render client-side when is_admin; the
    # JS source legitimately references lcAckPrompt/lcStatusPrompt.
    assert 'Archive?' not in body


def test_staff_lifecycle_page_status_ok(staff_client):
    assert staff_client.get('/students/lifecycle').status_code == 200


# ---- E11: archive suggestion ----

def _row(student, bucket, last_attendance_date):
    return {'student': student, 'enrollments': [], 'bucket': bucket,
            'metrics': {'last_attendance_date': last_attendance_date, 'max_run': 0,
                        'last_streak': 0, 'att_rate': None, 'total_marks': 0}}


def test_suggest_archive_only_for_stale_long_absent(app):
    with app.app_context():
        s = db.session.get(Student, _seed_sid(app))
        s.status = 'Active'
        thresholds = _default_thresholds()
        stale = _row(s, 'Long Absent',
                     date.today() - timedelta(days=thresholds['window'] * 2 + 1))
        assert _suggest_archive(stale, thresholds) is True
        recent = _row(s, 'Long Absent', date.today() - timedelta(days=3))
        assert _suggest_archive(recent, thresholds) is False
        enrolled = _row(s, 'Enrolled',
                        date.today() - timedelta(days=thresholds['window'] * 2 + 1))
        assert _suggest_archive(enrolled, thresholds) is False