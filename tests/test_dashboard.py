from datetime import date, timedelta

from app.extensions import db
from app.models import Attendance, Course, Enquiry, Exam, FeeRecord, LeaveRequest, Student, User
from app.routes import dashboard as dashboard_mod
from app.routes.dashboard import _fee_dues, _fee_due_rows, get_dashboard_stats
from app.services.account_service import student_outstanding_bulk


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


# ---- Batch 1: GST-inclusive dues (balance == fees-page rule) ----

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
        # PY is GST-applicable: due is 5000 + 18% GST = 5900 per student.
        assert total == 4800.0
        assert len(dues) == 2
        for d in dues:
            assert d['total_fee'] == 5900.0
        balances = {d['name']: d['balance'] for d in dues}
        assert balances['Test Student'] == 3900.0
        assert balances['Paid Off'] == 900.0


def _matches_fees_rule(app, sid):
    with app.app_context():
        row = _fee_due_rows([sid])[0]
        return row['balance'] == student_outstanding_bulk([sid])[sid]


def test_dashboard_dues_include_gst(app, admin_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        s = Student(name='GST Dues', email='gstdues@guha.test',
                    phone='9000000081', status='Active')
        db.session.add(s)
        db.session.flush()
        s.courses.append(Course.query.get(cid))
        db.session.flush()
        sid = s.id
        db.session.add(FeeRecord(student_id=sid, amount_paid=1000.0,
                                 payment_date=date.today()))
        db.session.commit()
    with app.app_context():
        row = _fee_due_rows([sid])[0]
        assert row['total_fee'] == 5900.0       # 5000 taxable + 900 GST (18%)
        assert row['gst_amount'] == 900.0
        assert row['balance'] == 4900.0
    assert _matches_fees_rule(app, sid)
    page = admin_client.get('/').data.decode()
    assert '₹4,900' in page
    assert '₹4,000' not in page


def test_dashboard_dues_count_concessions(app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        s = Student(name='Concession Dues', email='concdue@guha.test',
                    phone='9000000082', status='Active')
        db.session.add(s)
        db.session.flush()
        s.courses.append(Course.query.get(cid))
        db.session.flush()
        sid = s.id
        db.session.add(FeeRecord(student_id=sid, amount_paid=4000.0,
                                 concession=1000.0, payment_date=date.today()))
        db.session.commit()
    with app.app_context():
        row = _fee_due_rows([sid])[0]
        assert row['paid'] == 4000.0
        assert row['concession'] == 1000.0
        assert row['balance'] == 900.0          # 5900 - 4000 - 1000
    assert _matches_fees_rule(app, sid)


def test_dashboard_dues_net_of_refunds(app):
    from app.models import Expense, ExpenseCategory
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        s = Student(name='Refund Dues', email='refunddue@guha.test',
                    phone='9000000083', status='Active')
        db.session.add(s)
        db.session.flush()
        s.courses.append(Course.query.get(cid))
        db.session.flush()
        sid = s.id
        db.session.add(FeeRecord(student_id=sid, amount_paid=5400.0,
                                 payment_date=date.today()))
        cat = ExpenseCategory.query.filter_by(name='Rent').first()
        db.session.add(Expense(amount=500.0, expense_date=date.today(),
                               category_id=cat.id, description='refund',
                               student_id=sid))
        db.session.commit()
    with app.app_context():
        row = _fee_due_rows([sid])[0]
        assert row['refunded'] == 500.0
        assert row['balance'] == 1000.0         # 5900 - 5400 + 500
    assert _matches_fees_rule(app, sid)


def test_dashboard_mixed_gst_and_plain_courses(app):
    with app.app_context():
        gst_course = Course.query.filter_by(code='PY').first()
        plain = Course(name='Plain', code='PL', description='',
                       duration_weeks=8, duration_unit='weeks',
                       fees=1000.0, gst_applicable=False)
        db.session.add(plain)
        db.session.flush()
        s = Student(name='Mixed Dues', email='mixeddue@guha.test',
                    phone='9000000084', status='Active')
        db.session.add(s)
        db.session.flush()
        s.courses.extend([gst_course, plain])
        db.session.flush()
        sid = s.id
        db.session.add(FeeRecord(student_id=sid, amount_paid=3000.0,
                                 payment_date=date.today()))
        db.session.commit()
    with app.app_context():
        row = _fee_due_rows([sid])[0]
        assert row['total_fee'] == 6900.0       # 5900 + 1000
        assert row['balance'] == 3900.0
    assert _matches_fees_rule(app, sid)


def test_dashboard_paid_in_full_and_credit_not_due(app):
    with app.app_context():
        # Neutralize the seeded student (who would otherwise owe 5900).
        seeded = Student.query.filter_by(email='student@guha.test').first()
        seeded.courses = []
        cid = Course.query.filter_by(code='PY').first().id
        full = Student(name='Full Dues', email='fulldue@guha.test',
                       phone='9000000085', status='Active')
        credit = Student(name='Credit Dues', email='creditdue@guha.test',
                         phone='9000000086', status='Active')
        db.session.add_all([full, credit])
        db.session.flush()
        full.courses.append(Course.query.get(cid))
        credit.courses.append(Course.query.get(cid))
        db.session.flush()
        db.session.add(FeeRecord(student_id=full.id, amount_paid=5900.0,
                                 payment_date=date.today()))
        db.session.add(FeeRecord(student_id=credit.id, amount_paid=6000.0,
                                 payment_date=date.today()))
        db.session.commit()
        dues, total = _fee_dues()
        assert len(dues) == 0
        assert total == 0.0


# ---- Batch 1/F2: today-tasks counts use the real GST-inclusive balance ----

def test_todays_tasks_admin_counts_real_dues(admin_client, app):
    with app.app_context():
        # Neutralize the seeded student (who would otherwise owe 5900).
        seeded = Student.query.filter_by(email='student@guha.test').first()
        seeded.courses = []
        cid = Course.query.filter_by(code='PY').first().id
        recent_owe = Student(name='Recent Owe', email='recentowe@guha.test',
                             phone='9000000087', status='Active')
        old_owe = Student(name='Old Owe', email='oldowe@guha.test',
                          phone='9000000088', status='Active')
        settled = Student(name='Settled', email='settled@guha.test',
                          phone='9000000089', status='Active')
        overpaid = Student(name='Overpaid', email='overpaid@guha.test',
                           phone='9000000090', status='Active')
        db.session.add_all([recent_owe, old_owe, settled, overpaid])
        db.session.flush()
        for s in (recent_owe, old_owe, settled, overpaid):
            s.courses.append(Course.query.get(cid))
        db.session.flush()
        db.session.add(FeeRecord(student_id=recent_owe.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        db.session.add(FeeRecord(student_id=old_owe.id, amount_paid=1000.0,
                                 payment_date=date.today() - timedelta(days=45)))
        db.session.add(FeeRecord(student_id=settled.id, amount_paid=5900.0,
                                 payment_date=date.today() - timedelta(days=6)))
        db.session.add(FeeRecord(student_id=overpaid.id, amount_paid=6000.0,
                                 payment_date=date.today()))
        db.session.commit()
    data = admin_client.get('/api/dashboard/todays-activities').get_json()
    # Real rule counts every balance > 0 (recent_owe + old_owe = 2); the old
    # "no payment in 30 days" heuristic would have flagged only old_owe (1).
    assert data['meta']['fee_due_count'] == 2


def test_todays_tasks_staff_scopes_real_dues(staff_client, app):
    with app.app_context():
        seeded = Student.query.filter_by(email='student@guha.test').first()
        seeded.courses = []
        in_scope = Student(name='Staff In Dues', email='staffin@guha.test',
                           phone='9000000091', status='Active')
        out_course = Course(name='Other', code='OTH', description='',
                            duration_weeks=8, duration_unit='weeks',
                            fees=5000.0, gst_applicable=True)
        out_scope = Student(name='Staff Out Dues', email='staffout@guha.test',
                            phone='9000000092', status='Active')
        db.session.add_all([in_scope, out_scope, out_course])
        db.session.flush()
        in_scope.courses.append(Course.query.filter_by(code='PY').first())
        out_scope.courses.append(out_course)
        db.session.flush()
        db.session.add(FeeRecord(student_id=in_scope.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        db.session.add(FeeRecord(student_id=out_scope.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        db.session.commit()
    data = staff_client.get('/api/dashboard/todays-activities').get_json()
    assert data['meta']['fee_due_count'] == 1
    labels = [t.get('action_label') for t in data['tasks']]
    assert 'Follow up on fee dues' in labels


# ---- UI/UX: no duplicated Quick Stats; role-aware header badges ----

def test_admin_header_badges_show_financials(admin_client):
    page = admin_client.get('/')
    html = page.data.decode()
    assert 'quick-stats-container' not in html
    assert 'this month' in html
    assert 'unresolved enquiries' in html
    assert 'collected today' in html


def test_staff_header_badges_hide_financials(staff_client):
    page = staff_client.get('/')
    html = page.data.decode()
    assert 'quick-stats-container' not in html
    assert 'collected today' not in html
    assert 'this month' not in html
    assert 'attendance logged today' in html


# ---- UI/UX: recent table hooks + keyboard-operable AI toggle ----

def test_recent_table_accessibility_hooks(admin_client):
    app = admin_client.application
    sid = _seed_student_id(app)
    with app.app_context():
        db.session.add(FeeRecord(student_id=sid, amount_paid=500.0,
                                 payment_date=date.today()))
        db.session.commit()
    page = admin_client.get('/')
    html = page.data.decode()
    assert '<th scope="col"' in html
    assert 'no-sort' in html
    assert 'data-label="Student"' in html
    assert 'data-label="Method"' in html


def test_ai_toggle_is_keyboard_operable_button(admin_client):
    page = admin_client.get('/')
    html = page.data.decode()
    assert 'id="aiAdvisorToggle"' in html
    assert 'aria-controls="aiContent"' in html
    assert 'aria-expanded=' in html


# ---- UI/UX: unmatched AI labels get no action button (not kanban) ----

def test_unmatched_task_label_gets_no_action_url(admin_client, monkeypatch):
    app = admin_client.application
    monkeypatch.setattr(
        app.ai_engine, 'generate_todays_tasks',
        lambda data: [{'title': 'Read the monthly report', 'detail': 'See admin',
                        'priority': 'low', 'action_label': 'View Report'}])
    resp = admin_client.get('/api/dashboard/todays-activities')
    assert resp.status_code == 200
    tasks = resp.get_json()['tasks']
    assert len(tasks) == 1
    assert 'action_url' not in tasks[0]


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
