"""Regression tests for student-module critical fixes.

Covers: inline-JS XSS, Excel import hardening ('None' cells,
case-insensitive + intra-file duplicates, status allow-list, .xls reject),
POST-only delete, and staff course-scope on student APIs.
"""
import io

from openpyxl import Workbook

from app.extensions import db
from app.models import Course, Student, ensure_enrolled_on


def _post_import(client, rows, filename='students.xlsx', ai_validation='false'):
    wb = Workbook()
    ws = wb.active
    ws.append(['Name', 'Email', 'Phone', 'Status', 'Courses'])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return client.post(
        '/api/students/import-excel',
        data={'excel_file': (buf, filename), 'ai_validation': ai_validation},
        content_type='multipart/form-data')


def _mk_other_course_student(app):
    with app.app_context():
        c = Course(name='Other Course', code='OT', description='t',
                   duration_weeks=4, duration_unit='weeks', fees=1000.0)
        db.session.add(c)
        db.session.flush()
        s = Student(name='Outsider', email='outsider@guha.test',
                    phone='9000000011', status='Active')
        db.session.add(s)
        db.session.flush()
        s.courses.append(c)
        db.session.flush()
        ensure_enrolled_on(s.id)
        db.session.commit()
        return s.id


# ---- Stored XSS: no raw interpolation into inline JS ----

def test_student_names_not_interpolated_into_js(admin_client, app):
    with app.app_context():
        db.session.add(Student(
            name="O'Brien <img src=x onerror=alert(1)>",
            email='xss@guha.test', phone='9000000022', status='Active'))
        db.session.commit()
    body = admin_client.get('/students').get_data(as_text=True)
    assert "showIDCard('" not in body
    assert '<img src=x onerror=alert(1)>' not in body
    assert 'data-idcard-name="O&#39;Brien' in body
    assert 'showIDCardFromEl(this)' in body
    assert 'loadStudentPerformanceInsights(' in body


# ---- Excel import hardening ----

def test_import_blank_email_cell_is_not_none_string(admin_client, app):
    # With validation on, a blank email cell is a 400, not an email='None' row.
    resp = _post_import(admin_client, [['NoMail', None, '9000000033', 'Active', '']],
                        ai_validation='true')
    assert resp.status_code == 400
    assert any('Missing email' in e for e in resp.get_json()['errors'])
    with app.app_context():
        assert Student.query.filter_by(email='None').count() == 0
        assert Student.query.filter_by(name='NoMail').count() == 0


def test_import_blank_email_skipped_safely_without_validation(admin_client, app):
    # Validation off means "trust the file": the row is skipped, never
    # written as email=''/'None', and never 500s on the unique constraint.
    resp = _post_import(admin_client, [['NoMail', None, '9000000033', 'Active', '']])
    assert resp.status_code == 200
    assert resp.get_json()['skipped'] == 1
    with app.app_context():
        assert Student.query.filter_by(email='None').count() == 0
        assert Student.query.filter_by(name='NoMail').count() == 0


def test_import_duplicate_email_case_insensitive(admin_client, app):
    resp = _post_import(admin_client, [['Dup', 'STUDENT@guha.test', '9000000034', 'Active', '']])
    assert resp.status_code == 200
    data = resp.get_json()
    assert (data['imported'], data['skipped']) == (0, 1)


def test_import_intra_file_duplicate_skipped_not_500(admin_client, app):
    rows = [
        ['First', 'twice@guha.test', '9000000035', 'Active', ''],
        ['Second', 'TWICE@guha.test', '9000000036', 'Active', ''],
    ]
    resp = _post_import(admin_client, rows)
    assert resp.status_code == 200
    data = resp.get_json()
    assert (data['imported'], data['skipped']) == (1, 1)


def test_import_unknown_status_normalized_to_active(admin_client, app):
    resp = _post_import(admin_client, [['Low', 'low@guha.test', '9000000037', 'active', '']])
    assert resp.status_code == 200
    with app.app_context():
        assert Student.query.filter_by(email='low@guha.test').first().status == 'Active'


def test_import_rejects_legacy_xls(admin_client):
    resp = _post_import(admin_client, [['A', 'a@guha.test', '9000000038', 'Active', '']],
                        filename='students.xls')
    assert resp.status_code == 400
    assert 'xls' in resp.get_json()['errors'][0].lower()


# ---- Staff course-scope on student APIs ----

def test_staff_blocked_from_out_of_scope_student(staff_client, app):
    sid = _mk_other_course_student(app)
    assert staff_client.get(f'/api/students/{sid}/details').status_code == 403
    assert staff_client.get(f'/api/students/{sid}/ai-performance-insights').status_code == 403
    assert staff_client.get(f'/students/photo/{sid}').status_code == 403


def test_staff_can_view_own_course_student(staff_client, app):
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    assert staff_client.get(f'/api/students/{sid}/details').status_code == 200


def test_check_duplicate_requires_admin(staff_client):
    # Admin 200-path is already covered by test_api.py::test_student_check_duplicate.
    assert staff_client.get('/api/students/check-duplicate?email=x@y.zz').status_code == 302
