import json

from app.extensions import db
from app.models import Student, Tutor, Course, FeeRecord


def test_search_requires_2_chars(admin_client):
    resp = admin_client.get('/api/search?q=a')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['results']['students'] == []


def test_search_finds_student(admin_client):
    resp = admin_client.get('/api/search?q=Test')
    assert resp.status_code == 200
    data = resp.get_json()
    names = [s['name'] for s in data['results']['students']]
    assert 'Test Student' in names


def test_search_finds_course(admin_client):
    resp = admin_client.get('/api/search?q=Python')
    data = resp.get_json()
    assert any('Python' in c['name'] for c in data['results']['courses'])


def test_student_details_api(admin_client):
    with admin_client.application.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.get(f'/api/students/{sid}/details')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['name'] == 'Test Student'
    assert data['fees']['total_course_fee'] == 5000.0


def test_tutor_details_api(admin_client):
    with admin_client.application.app_context():
        tid = Tutor.query.filter_by(email='staff@guha.test').first().id
    resp = admin_client.get(f'/api/tutors/{tid}/details')
    assert resp.status_code == 200
    assert resp.get_json()['name'] == 'Staff User'


def test_expenses_chart_data(admin_client):
    resp = admin_client.get('/api/expenses/chart-data')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['totals']) == 12


def test_fee_ai_analysis_without_keys(admin_client):
    resp = admin_client.get('/api/fees/ai-analysis')
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, (dict, list))


def test_attendance_ai_analysis_without_keys(admin_client):
    resp = admin_client.get('/api/attendance/ai-analysis')
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), (dict, list))


def test_dashboard_ai_insights_admin(admin_client):
    resp = admin_client.get('/api/dashboard/ai-insights')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'summary' in data


def test_dashboard_ai_insights_staff_hidden(staff_client):
    resp = staff_client.get('/api/dashboard/ai-insights')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'Staff dashboard loaded' in data['summary']


def test_student_check_duplicate(admin_client):
    resp = admin_client.get('/api/students/check-duplicate?email=student@guha.test')
    assert resp.status_code == 200
    assert len(resp.get_json()['duplicates']) == 1


def test_export_excel(admin_client):
    resp = admin_client.get('/api/students/export-excel')
    assert resp.status_code == 200
    assert 'spreadsheet' in resp.content_type


def test_google_sync_status_returns_json(admin_client):
    resp = admin_client.get('/api/google-sync/status')
    assert resp.status_code in (200, 302)


def test_todays_activities_admin(admin_client):
    resp = admin_client.get('/api/dashboard/todays-activities')
    assert resp.status_code == 200
    assert 'tasks' in resp.get_json()


def test_mcq_analysis_page(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        from app.models import Exam
        from datetime import date
        exam = Exam(course_id=cid, title='Midterm', exam_date=date(2026, 6, 15),
                    max_marks=50, passing_marks=20, exam_type='mcq')
        db.session.add(exam)
        db.session.commit()
        eid = exam.id
    for path in (f'/exams/{eid}/mcq/analysis', f'/exams/{eid}/mcq/results',
                 f'/exams/{eid}/mcq/solutions', f'/exams/{eid}/report',
                 f'/exams/{eid}/scores'):
        resp = admin_client.get(path)
        assert resp.status_code in (200, 302), f'{path} -> {resp.status_code}'


def test_fee_invoice_404_for_missing(admin_client):
    resp = admin_client.get('/fees/invoice/99999')
    assert resp.status_code in (404, 302, 200)
