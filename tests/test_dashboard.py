from datetime import date, timedelta

from app.extensions import db
from app.models import Attendance, Course, Enquiry, Exam, FeeRecord, LeaveRequest, Student, User
from app.routes import dashboard as dashboard_mod
from app.routes.dashboard import _fee_dues, get_dashboard_stats


def _seed_student_id(app):
    with app.app_context():
        return Student.query.filter_by(email='student@guha.test').first().id


# ---- Bug 1: todays-activities must survive an exam scheduled today ----

def test_todays_activities_with_exam_today(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        db.session.add(Exam(course_id=cid, title='Physics Final',
                            exam_date=date.today(), max_marks=100,
                            passing_marks=40, exam_type='written'))
        db.session.commit()
    resp = admin_client.get('/api/dashboard/todays-activities')
    assert resp.status_code == 200
    data = resp.get_json()
    exam_tasks = [t for t in data['tasks']
                  if (t.get('action_label') or '') == 'View Exams']
    assert exam_tasks, 'expected an exam task when an exam is scheduled today'
    assert exam_tasks[0]['action_url'] == '/exams'


# ---- Bug 2: staff requests must not poison the shared stats cache ----

def test_staff_dashboard_does_not_poison_stats_cache(staff_client, app):
    sid = _seed_student_id(app)
    with app.app_context():
        db.session.add(FeeRecord(student_id=sid, amount_paid=1000.0,
                                 payment_date=date.today()))
        staff_user = User.query.filter_by(username='staff').first()
        db.session.add(LeaveRequest(user_id=staff_user.id, start_date=date.today(),
                                    end_date=date.today(), reason='sick',
                                    status='Pending'))
        db.session.commit()
    assert staff_client.get('/').status_code == 200
    with app.app_context():
        stats = get_dashboard_stats()
        assert stats['monthly_fees_collected'] == 1000.0
        assert 'pending_leaves_count' not in stats
        assert 'approved_leaves_count' not in stats


# ---- Bug 3: no fabricated attendance stats ----

def test_no_fabricated_attendance_stats(app):
    with app.app_context():
        stats = get_dashboard_stats()
        assert stats['avg_student_attendance'] is None
        assert stats['low_attendance_count'] == 0


def test_dashboard_renders_with_no_attendance_data_admin(admin_client):
    page = admin_client.get('/')
    assert page.status_code == 200
    assert b'None%' not in page.data


def test_dashboard_renders_with_no_attendance_data_staff(staff_client):
    page = staff_client.get('/')
    assert page.status_code == 200
    assert b'None%' not in page.data


# ---- Robustness: one failing section must not 500 the whole page ----

def test_dashboard_survives_section_failure(admin_client, app, monkeypatch):
    def boom():
        raise RuntimeError('simulated dues outage')
    monkeypatch.setattr(dashboard_mod, '_fee_dues', boom)
    monkeypatch.setattr(dashboard_mod, '_capacity', boom)
    page = admin_client.get('/')
    assert page.status_code == 200


def test_dashboard_survives_stats_failure(admin_client, app, monkeypatch):
    def boom():
        raise RuntimeError('simulated stats outage')
    monkeypatch.setattr(dashboard_mod, 'get_dashboard_stats', boom)
    page = admin_client.get('/')
    assert page.status_code == 200


# ---- Perf: per-person attendance bound to the 14-day window ----

def test_stale_attendance_ignored_in_low_count(app):
    sid = _seed_student_id(app)
    with app.app_context():
        for i in range(5):
            db.session.add(Attendance(person_type='student', person_id=sid,
                                      date=date.today() - timedelta(days=40 + i),
                                      status='Absent'))
        for i in range(3):
            db.session.add(Attendance(person_type='student', person_id=sid,
                                      date=date.today() - timedelta(days=i),
                                      status='Present'))
        db.session.commit()
        stats = get_dashboard_stats()
        assert stats['avg_student_attendance'] == 100
        assert stats['low_attendance_count'] == 0


# ---- Perf: fee dues in one aggregated query, same results ----

def test_fee_dues_match_expected_balances(app):
    sid = _seed_student_id(app)
    with app.app_context():
        course = Course.query.filter_by(code='PY').first()
        db.session.add(FeeRecord(student_id=sid, amount_paid=2000.0,
                                 payment_date=date.today()))
        paid_off = Student(name='Paid Off', email='paidoff@guha.test',
                           phone='9000000098', status='Active')
        paid_off.courses.append(course)
        db.session.add(paid_off)
        db.session.flush()
        db.session.add(FeeRecord(student_id=paid_off.id, amount_paid=5000.0,
                                 payment_date=date.today()))
        inactive = Student(name='Inactive Due', email='inactive@guha.test',
                           phone='9000000097', status='Inactive')
        inactive.courses.append(course)
        db.session.add(inactive)
        db.session.commit()
        dues, total = _fee_dues()
        assert total == 3000.0
        assert len(dues) == 1
        assert dues[0]['name'] == 'Test Student'
        assert dues[0]['balance'] == 3000.0


# ---- Bug 4: Visited leads count toward the enquiry total ----

def test_total_enquiries_includes_visited(app):
    with app.app_context():
        for i, status in enumerate(['New', 'Contacted', 'Visited', 'Converted', 'Lost']):
            db.session.add(Enquiry(student_name=f'L{i}', phone=f'900000050{i}',
                                   status=status))
        db.session.commit()
        stats = get_dashboard_stats()
        assert stats['enquiries_visited'] == 1
        assert stats['enquiries'] == 5
