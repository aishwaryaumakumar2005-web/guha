"""Regression tests for course-module critical fixes.

Covers: POST-only delete, GST-rate sanitization (reads + save),
active-only enrollment counts (cards + dashboard capacity).
"""
from app.extensions import db
from app.helpers import get_gst_rates
from app.models import Course, Student, SystemSetting, student_courses


def _ids(app):
    with app.app_context():
        s = Student.query.filter_by(email='student@guha.test').first()
        c = Course.query.filter_by(code='PY').first()
        return s.id, c.id


# ---- POST-only delete ----

def test_course_delete_post_only(admin_client, app):
    _, cid = _ids(app)
    assert admin_client.get(f'/courses/delete/{cid}').status_code == 405
    assert admin_client.post(f'/courses/delete/{cid}').status_code == 302
    with app.app_context():
        assert Course.query.get(cid) is None


# ---- GST sanitization ----

def test_gst_garbage_falls_back(admin_client, app):
    with app.app_context():
        db.session.add(SystemSetting(key='CGST_PCT', value='bogus'))
        db.session.add(SystemSetting(key='SGST_PCT', value='-5'))
        db.session.commit()
        assert get_gst_rates() == (9.0, 9.0)
    assert admin_client.get('/courses').status_code == 200
    assert admin_client.get('/fees').status_code == 200


def test_save_org_rejects_bad_gst(admin_client, app):
    resp = admin_client.post('/admin', data={
        'action': 'save_org', 'CGST_PCT': 'bogus', 'SGST_PCT': '9',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert SystemSetting.query.filter_by(key='CGST_PCT').first() is None
        assert get_gst_rates() == (9.0, 9.0)


def test_save_org_accepts_good_gst(admin_client, app):
    resp = admin_client.post('/admin', data={
        'action': 'save_org', 'CGST_PCT': '6', 'SGST_PCT': '6',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert get_gst_rates() == (6.0, 6.0)


# ---- Active-only enrollment counts ----

def test_course_cards_count_active_only(admin_client, app):
    sid, cid = _ids(app)
    body = admin_client.get('/courses').get_data(as_text=True)
    assert '1 Learner' in body
    admin_client.post(f'/students/enrollment/drop/{sid}/{cid}',
                      data={'filter': 'all', 'drop_reason': 'moved'})
    body = admin_client.get('/courses').get_data(as_text=True)
    assert '0 Learners' in body
    assert 'No Enrollments' in body
    from app.routes.dashboard import _capacity
    with app.app_context():
        courses, _ = _capacity()
        row = next(c for c in courses if c['code'] == 'PY')
        assert row['enrolled'] == 0


def test_null_status_counts_as_enrolled(admin_client, app):
    sid, cid = _ids(app)
    admin_client.post(f'/students/enrollment/drop/{sid}/{cid}',
                      data={'filter': 'all', 'drop_reason': 'moved'})
    with app.app_context():
        db.session.execute(
            student_courses.update().where(
                student_courses.c.student_id == sid,
                student_courses.c.course_id == cid).values(status=None))
        db.session.commit()
    body = admin_client.get('/courses').get_data(as_text=True)
    assert '1 Learner' in body
