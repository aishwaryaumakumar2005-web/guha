"""Operation-role smoke coverage for business-domain access and mutations."""

import io

from app.extensions import db
from app.models import Course, Student, Tutor


def test_operation_can_access_business_pages(operation_client):
    for path in ('/', '/students', '/courses', '/tutors', '/enquiries',
                 '/fees', '/attendance', '/leaves', '/reports', '/tasks'):
        assert operation_client.get(path).status_code < 400, path


def test_operation_can_create_student_without_email(operation_client, app):
    response = operation_client.post('/students', data={
        'name': 'Operation Student', 'phone': '9000000123',
        'status': 'Active',
    })
    assert response.status_code == 302
    with app.app_context():
        student = Student.query.filter_by(name='Operation Student').one()
        assert student.email is None


def test_operation_can_upload_and_render_tutor_photo(operation_client, app):
    with app.app_context():
        tutor = Tutor.query.filter_by(email='staff@guha.test').one()
        tid = tutor.id
    response = operation_client.post(f'/tutors/edit/{tid}', data={
        'name': 'Staff User', 'email': 'staff@guha.test',
        'phone': '9876543210', 'status': 'Active',
        'photo': (io.BytesIO(b'fake-image'), 'staff.jpg'),
    }, content_type='multipart/form-data')
    assert response.status_code == 302
    photo = operation_client.get(f'/tutors/photo/{tid}')
    assert photo.status_code == 200
    assert photo.headers['Cache-Control'].startswith('no-store')


def test_operation_can_upload_and_render_student_photo(operation_client, app):
    with app.app_context():
        student = Student.query.filter_by(email='student@guha.test').one()
        sid = student.id
    response = operation_client.post(f'/students/edit/{sid}', data={
        'name': 'Test Student', 'email': 'student@guha.test',
        'phone': '9876543210', 'status': 'Active',
        'photo': (io.BytesIO(b'fake-image'), 'student.jpg'),
    }, content_type='multipart/form-data')
    assert response.status_code == 302
    photo = operation_client.get(f'/students/photo/{sid}')
    assert photo.status_code == 200
    assert photo.headers['Cache-Control'].startswith('no-store')


def test_operation_cannot_open_admin_console(operation_client):
    assert operation_client.get('/admin').status_code == 302
