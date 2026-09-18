"""Regression tests for staff-module UI/UX fixes.

Covers: single edit modal, actions menu, table hooks + avatar + email,
keyboard drop zone, Half Day bucket, admin-only page.
"""
from datetime import date

from app.extensions import db
from app.models import Attendance, Tutor


def _tid(app, email='staff@guha.test'):
    with app.app_context():
        return Tutor.query.filter_by(email=email).first().id


def test_tutors_page_admin_only(staff_client):
    assert staff_client.get('/tutors').status_code == 302


def test_single_edit_modal(admin_client, app):
    tid = _tid(app)
    body = admin_client.get('/tutors').get_data(as_text=True)
    assert body.count('id="editTutorModal"') == 1
    assert 'editTutorModal1' not in body
    assert 'id="editTutorForm"' in body
    assert 'id="editTutorId"' in body
    assert 'function openEditTutor' in body
    assert f'data-edit-url="/tutors/edit/{tid}"' in body


def test_actions_menu(admin_client):
    body = admin_client.get('/tutors').get_data(as_text=True)
    assert 'More actions for' in body
    assert 'Print ID Card</button>' in body
    assert 'Edit Instructor</button>' in body
    assert 'Delete Instructor</button>' in body
    assert "f.method = 'POST'" in body


def test_table_hooks_and_avatar(admin_client):
    body = admin_client.get('/tutors').get_data(as_text=True)
    assert '<th scope="col"' in body
    assert 'no-sort' in body
    assert 'data-label="Instructor"' in body
    assert 'data-label="Actions"' in body
    assert 'staff@guha.test' in body
    # seed tutor has no photo -> initials fallback
    assert 'class="student-initials' in body


def test_drop_zone_accessible(admin_client):
    body = admin_client.get('/tutors').get_data(as_text=True)
    assert 'role="button"' in body
    assert 'tabindex="0"' in body
    assert 'aria-live="polite"' in body
    assert 'Upload & Import' in body
    assert 'accept=".xlsx"' in body


def test_tutor_details_half_day(admin_client, app):
    tid = _tid(app)
    with app.app_context():
        db.session.add(Attendance(person_type='tutor', person_id=tid,
                                  date=date.today(), status='Half Day'))
        db.session.commit()
    data = admin_client.get(f'/api/tutors/{tid}/details').get_json()
    assert data['attendance']['half_day'] == 1
    assert data['attendance']['total_days'] == 1
