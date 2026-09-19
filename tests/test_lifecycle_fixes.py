"""Regression tests for high/medium lifecycle enhancements.

B1: single-row transitions (complete/drop/reactivate) reject ineligible
    source statuses instead of silently proceeding.
B2: attendance metrics load only needed columns (behavior preserved).
B3: the rate rule judges students on whatever marks exist (gate of 1),
    so a student who missed their only session gets flagged.
B4: bulk buttons are scoped to the current filter and bulk runs report
    how many selected students were skipped.
"""
from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Attendance, AuditLog, Course, Student, ensure_enrolled_on, student_courses,
)
from app.routes.student_lifecycle import _attendance_metrics, _derive_bucket


def _enrollment(app, sid, cid):
    with app.app_context():
        return db.session.execute(
            student_courses.select().where(
                student_courses.c.student_id == sid,
                student_courses.c.course_id == cid)
        ).first()


def _seed_sid(app):
    with app.app_context():
        return Student.query.filter_by(email='student@guha.test').first().id


def _cid(app):
    with app.app_context():
        return Course.query.filter_by(code='PY').first().id


def _mark(app, person_type, person_id, day_offset, status='Absent'):
    with app.app_context():
        rec = Attendance.query.filter_by(
            person_type=person_type, person_id=person_id,
            date=date.today() - timedelta(days=day_offset)).first()
        if rec:
            rec.status = status
        else:
            db.session.add(Attendance(
                person_type=person_type, person_id=person_id,
                date=date.today() - timedelta(days=day_offset), status=status))
        db.session.commit()


def _mk_student(app, name, email, course_ids=()):
    with app.app_context():
        s = Student(name=name, email=email, phone='9000000099', status='Active')
        db.session.add(s)
        db.session.flush()
        for cid in course_ids:
            course = Course.query.get(cid)
            if course:
                s.courses.append(course)
        db.session.flush()
        ensure_enrolled_on(s.id)
        db.session.commit()
        return s.id


def _bulk_follow(client, action, sids, reason=None):
    data = {'bulk_action': action, 'filter': 'all',
            'selected': [str(s) for s in sids]}
    if reason is not None:
        data['bulk_reason'] = reason
    return client.post('/students/enrollment/bulk', data=data,
                       follow_redirects=True)


# ---- B1: transitions validate their source status ----

def test_drop_rejects_already_completed_enrollment(admin_client, app):
    sid, cid = _seed_sid(app), _cid(app)
    admin_client.post(f'/students/enrollment/complete/{sid}/{cid}',
                      data={'filter': 'all'})
    with app.app_context():
        audits = AuditLog.query.count()
        past = date.today() - timedelta(days=5)
        db.session.execute(
            student_courses.update().where(
                student_courses.c.student_id == sid,
                student_courses.c.course_id == cid
            ).values(completed_on=past))
        db.session.commit()
    resp = admin_client.post(f'/students/enrollment/drop/{sid}/{cid}',
                             data={'filter': 'all', 'drop_reason': 'nope'})
    assert resp.status_code == 302
    row = _enrollment(app, sid, cid)
    assert row.status == 'Completed'
    assert row.drop_reason is None
    assert row.completed_on == past
    with app.app_context():
        assert AuditLog.query.count() == audits, 'rejected drop still audited'


def test_complete_on_completed_preserves_completed_date(admin_client, app):
    sid, cid = _seed_sid(app), _cid(app)
    admin_client.post(f'/students/enrollment/complete/{sid}/{cid}',
                      data={'filter': 'all'})
    with app.app_context():
        past = date.today() - timedelta(days=9)
        db.session.execute(
            student_courses.update().where(
                student_courses.c.student_id == sid,
                student_courses.c.course_id == cid
            ).values(completed_on=past))
        db.session.commit()
    admin_client.post(f'/students/enrollment/complete/{sid}/{cid}',
                      data={'filter': 'all'})
    row = _enrollment(app, sid, cid)
    assert row.status == 'Completed'
    assert row.completed_on == past, 'double-submit re-stamped completed_on'


def test_reactivate_rejects_enrolled(admin_client, app):
    sid, cid = _seed_sid(app), _cid(app)
    with app.app_context():
        audits = AuditLog.query.count()
    resp = admin_client.post(f'/students/enrollment/reactivate/{sid}/{cid}',
                             data={'filter': 'all'})
    assert resp.status_code == 302
    row = _enrollment(app, sid, cid)
    assert (row.status or 'Enrolled') == 'Enrolled'
    assert row.completed_on is None and row.drop_reason is None
    with app.app_context():
        assert AuditLog.query.count() == audits


def test_reactivate_still_works_from_dropped(admin_client, app):
    sid, cid = _seed_sid(app), _cid(app)
    admin_client.post(f'/students/enrollment/drop/{sid}/{cid}',
                      data={'filter': 'all', 'drop_reason': 'gone'})
    resp = admin_client.post(f'/students/enrollment/reactivate/{sid}/{cid}',
                             data={'filter': 'all'})
    assert resp.status_code == 302
    row = _enrollment(app, sid, cid)
    assert row.status == 'Enrolled'
    assert row.drop_reason is None and row.completed_on is None


def test_complete_still_works_from_enrolled(admin_client, app):
    sid, cid = _seed_sid(app), _cid(app)
    resp = admin_client.post(f'/students/enrollment/complete/{sid}/{cid}',
                             data={'filter': 'all'})
    assert resp.status_code == 302
    row = _enrollment(app, sid, cid)
    assert row.status == 'Completed' and row.completed_on == date.today()


def test_missing_enrollment_still_404(admin_client, app):
    assert admin_client.post(
        '/students/enrollment/complete/9999/9999',
        data={'filter': 'all'}).status_code == 404


# ---- B3: rate rule flags single-session absences ----

def test_single_absent_mark_flags_long_absent(app):
    sid = _seed_sid(app)
    _mark(app, 'student', sid, 1, 'Absent')
    with app.app_context():
        m = _attendance_metrics()[sid]
        assert m['total_marks'] == 1 and m['att_rate'] == 0.0
        s = Student.query.get(sid)
        enrolls = [{'status': 'Enrolled', 'enrolled_on': date.today()}]
        assert _derive_bucket(s, enrolls, m) == 'Long Absent'


def test_single_present_mark_stays_enrolled(app):
    sid = _seed_sid(app)
    _mark(app, 'student', sid, 1, 'Present')
    with app.app_context():
        m = _attendance_metrics()[sid]
        assert m['total_marks'] == 1 and m['att_rate'] == 100.0
        s = Student.query.get(sid)
        enrolls = [{'status': 'Enrolled', 'enrolled_on': date.today()}]
        assert _derive_bucket(s, enrolls, m) == 'Enrolled'


# ---- B4: filter-scoped bulk UI + transparent skip reporting ----

def test_bulk_buttons_hidden_for_not_enrolled(admin_client, app):
    body = admin_client.get(
        '/students/lifecycle?filter=not_enrolled').get_data(as_text=True)
    for action in ('complete', 'drop', 'reactivate'):
        assert f"bulkPrompt('{action}')" not in body


def test_bulk_buttons_scoped_for_completed_filter(admin_client, app):
    body = admin_client.get(
        '/students/lifecycle?filter=completed').get_data(as_text=True)
    assert "bulkPrompt('reactivate')" in body
    assert "bulkPrompt('complete')" not in body
    assert "bulkPrompt('drop')" not in body


def test_bulk_complete_reports_skipped(admin_client, app):
    cid = _cid(app)
    aid = _mk_student(app, 'Bulky Alpha', 'bulky-a@guha.test', [cid])
    bid = _mk_student(app, 'Bulky Bravo', 'bulky-b@guha.test', [cid])
    admin_client.post(f'/students/enrollment/complete/{bid}/{cid}',
                      data={'filter': 'all'})
    resp = _bulk_follow(admin_client, 'complete', [aid, bid])
    body = resp.get_data(as_text=True)
    assert '1 enrollment(s) updated' in body
    assert '1 selected student(s) had no eligible enrollment' in body
    assert _enrollment(app, aid, cid).status == 'Completed'
    assert _enrollment(app, bid, cid).status == 'Completed'