"""Regression tests for student-module UI/UX fixes (7 points).

Covers: single edit modal, actions menu, email/DOB/avatar, keyboard
drop zone, lifecycle a11y hooks, fetch live search hooks, staff scope line.
"""
import re
from datetime import date

from app.extensions import db
from app.models import Student


# ---- P1: single edit modal ----

def test_single_edit_modal(admin_client):
    body = admin_client.get('/students').get_data(as_text=True)
    assert body.count('id="editStudentModal"') == 1
    assert 'editStudentModal1' not in body
    assert 'id="editStudentForm"' in body
    assert 'id="editStudentId"' in body
    assert 'id="editCourses"' in body
    assert 'function openEditStudent' in body


def test_edit_button_carries_row_data(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    body = admin_client.get('/students').get_data(as_text=True)
    assert f'data-edit-url="/students/edit/{sid}"' in body
    assert 'data-course-ids=' in body


# ---- P2: actions overflow menu ----

def test_actions_menu_admin(admin_client):
    body = admin_client.get('/students').get_data(as_text=True)
    assert 'More actions for' in body
    assert 'AI Performance Insights</button>' in body
    assert 'Edit Student</button>' in body
    assert 'Delete Student</button>' in body
    # delete still goes through the POST form flow
    assert "f.method = 'POST'" in body


def test_actions_menu_staff(staff_client):
    body = staff_client.get('/students').get_data(as_text=True)
    assert 'More actions for' in body
    assert 'Edit Student</button>' not in body
    assert 'Delete Student</button>' not in body
    assert 'AI Performance Insights</button>' in body


# ---- P3: email, DOB, initials avatar ----

def test_directory_shows_email_and_initials(admin_client, app):
    body = admin_client.get('/students').get_data(as_text=True)
    assert 'student@guha.test' in body
    # seed student has no photo -> initials fallback keeps row alignment
    assert 'class="student-initials' in body


def test_directory_shows_dob(admin_client, app):
    with app.app_context():
        s = Student(name='Cake', email='cake@guha.test', phone='9000000060',
                    status='Active', date_of_birth=date(2010, 5, 4))
        db.session.add(s)
        db.session.commit()
    body = admin_client.get('/students').get_data(as_text=True)
    assert 'bi-cake' in body
    assert '04 May 2010' in body


# ---- P4: keyboard drop zone + live regions ----

def test_drop_zone_accessible(admin_client):
    body = admin_client.get('/students').get_data(as_text=True)
    assert 'id="studentDropZone"' in body
    assert 'role="button"' in body
    assert 'tabindex="0"' in body
    assert 'aria-live="polite"' in body
    assert 'Upload & Import' in body
    assert 'accept=".xlsx"' in body


# ---- P5: lifecycle a11y ----

def test_lifecycle_a11y_hooks(admin_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    from app.models import Attendance
    with app.app_context():
        db.session.add(Attendance(person_type='student', person_id=sid,
                                  date=date.today(), status='Present'))
        db.session.commit()
    body = admin_client.get('/students/lifecycle').get_data(as_text=True)
    assert 'stat-icon" aria-hidden="true"' in body
    assert 'role="progressbar"' in body
    assert 'aria-valuenow=' in body
    assert 'id="lcFilterForm"' in body
    assert 'id="lcCountLine"' in body
    assert 'id="lcTableCard"' in body
    assert 'onclick="lcResetSearch()"' in body
    assert 'function lcFetchList' in body


# ---- P7: staff scope context ----

def test_staff_scope_line(staff_client):
    body = staff_client.get('/students').get_data(as_text=True)
    assert 'Showing students from:' in body
    assert 'Python Programming' in body
    assert 'id="student-search"' in body
