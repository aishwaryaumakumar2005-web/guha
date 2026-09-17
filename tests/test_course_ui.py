"""Regression tests for course-module UI/UX fixes.

Covers: single edit modal (+ staff-DOM guard), seats-fill footer,
working empty-state CTA, GST notice plumbing, staff AI gating, icons.
"""
from app.extensions import db
from app.models import Course


def _cid(app, code='PY'):
    with app.app_context():
        return Course.query.filter_by(code=code).first().id


# ---- Single edit modal ----

def test_single_edit_modal(admin_client, app):
    cid = _cid(app)
    body = admin_client.get('/courses').get_data(as_text=True)
    assert body.count('id="editCourseModal"') == 1
    assert 'editCourseModal1' not in body
    assert 'id="editCourseForm"' in body
    assert 'function openEditCourse' in body
    assert f'data-edit-url="/courses/edit/{cid}"' in body
    assert 'data-gst-preview' in body


def test_staff_gets_no_modals_or_ai(staff_client):
    body = staff_client.get('/courses').get_data(as_text=True)
    assert 'id="editCourseModal"' not in body
    assert 'id="addCourseModal"' not in body
    assert 'AI Optimize' not in body


# ---- Seats-fill footer ----

def test_seats_filled_footer(admin_client):
    body = admin_client.get('/courses').get_data(as_text=True)
    assert '1 Learner' in body
    assert '1 of 30 seats filled' in body


# ---- Working empty-state CTA ----

def test_empty_state_cta_opens_modal(admin_client, app):
    admin_client.post(f'/courses/delete/{_cid(app)}')
    body = admin_client.get('/courses').get_data(as_text=True)
    assert 'No courses added yet' in body
    region = body.split('No courses added yet')[1].split('</div>')[0:8]
    region = ''.join(region)
    assert 'data-bs-target="#addCourseModal"' in region
    assert '<a href="#"' not in region


# ---- GST notice plumbing + icons ----

def test_gst_notice_and_rates(admin_client):
    body = admin_client.get('/courses').get_data(as_text=True)
    assert 'window.GST_RATES' in body
    assert 'GST applicability set from the company record' in body
    assert 'bi-clock me-1" aria-hidden="true"' in body
    assert 'bi-people-fill me-1" aria-hidden="true"' in body
