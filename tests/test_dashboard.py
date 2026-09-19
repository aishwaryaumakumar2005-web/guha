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
        dues, total, ageing = _fee_dues()
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
        dues, total, ageing = _fee_dues()
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


# ---- Batch 2: labelling, money formatting, deep links, staff scope ----

def test_dashboard_recent_payments_label(admin_client, app):
    sid = _seed_student_id(app)
    with app.app_context():
        db.session.add(FeeRecord(student_id=sid, amount_paid=500.0,
                                 payment_date=date.today()))
        db.session.commit()
    html = admin_client.get('/').data.decode()
    assert 'Recent Payments' in html
    assert 'Recent Enrollments' not in html


def test_dashboard_recent_payments_empty_state(admin_client):
    html = admin_client.get('/').data.decode()
    assert 'No recent payments' in html
    assert 'No recent enrollments' not in html


def test_outstanding_card_microcopy_and_deep_link(app, admin_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        s = Student(name='Linked Dues', email='linkeddues@guha.test',
                    phone='9000000093', status='Active')
        db.session.add(s)
        db.session.flush()
        s.courses.append(Course.query.get(cid))
        db.session.flush()
        db.session.add(FeeRecord(student_id=s.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        db.session.commit()
        sid = s.id
    html = admin_client.get('/').data.decode()
    assert '(incl. GST)' in html
    assert 'total due &middot; incl. GST' in html
    assert '₹4,900.00' in html          # per-row balance matches the fees matrix
    assert f'/fees?student_id={sid}' in html


def test_fees_page_filters_single_student(admin_client, app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        a = Student(name='Filter A', email='filtera@guha.test',
                    phone='9000000095', status='Active')
        b = Student(name='Filter B', email='filterb@guha.test',
                    phone='9000000096', status='Active')
        db.session.add_all([a, b])
        db.session.flush()
        course = Course.query.get(cid)
        a.courses.append(course)
        b.courses.append(course)
        db.session.flush()
        db.session.add(FeeRecord(student_id=a.id, amount_paid=1111.0,
                                 payment_date=date.today()))
        db.session.add(FeeRecord(student_id=b.id, amount_paid=2222.0,
                                 payment_date=date.today()))
        db.session.commit()
        aid = a.id
    html = admin_client.get(f'/fees?student_id={aid}').data.decode()
    assert 'Filter A' in html
    assert 'Filter B' not in html
    assert '₹1,111.00' in html
    assert '₹2,222.00' not in html
    assert admin_client.get('/fees?student_id=abc').status_code == 200


def test_staff_attendance_scoped_to_own_students(app, staff_client):
    from app.models import Attendance
    with app.app_context():
        sid = _seed_student_id(app)     # enrolled in PY, which staff teaches
        other = Student(name='Other Attn', email='otherattn@guha.test',
                        phone='9000000094', status='Active')
        otc = Course(name='Attn Other', code='AOT', description='',
                     duration_weeks=8, duration_unit='weeks',
                     fees=1000.0, gst_applicable=False)
        db.session.add_all([other, otc])
        db.session.flush()
        other.courses.append(otc)
        db.session.flush()
        # Own student: present today + yesterday -> 100%, 1 marked today.
        db.session.add(Attendance(person_type='student', person_id=sid,
                                  date=date.today(), status='Present'))
        db.session.add(Attendance(person_type='student', person_id=sid,
                                  date=date.today() - timedelta(days=1),
                                  status='Present'))
        # Non-staff student: 4 absences + 1 absent today. A global average
        # would drop to 33% and today's count to 2 — neither may surface.
        for i in range(4):
            db.session.add(Attendance(person_type='student', person_id=other.id,
                                      date=date.today() - timedelta(days=1 + i),
                                      status='Absent'))
        db.session.add(Attendance(person_type='student', person_id=other.id,
                                  date=date.today(), status='Absent'))
        db.session.commit()
    html = staff_client.get('/').data.decode()
    assert 'My students' in html
    assert '100%' in html
    assert '33%' not in html
    assert '1 attendance logged today' in html
    assert '2 attendance logged today' not in html


# ---- Batch 3: reminder GST parity + ageing hints on the dues card ----

def test_sms_reminder_uses_gst_inclusive_balance(app, monkeypatch):
    from app.services.sms_service import SmsService
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        condue = Student(name='Concession Dues', email='condue@guha.test',
                         phone='9000000099', status='Active')
        db.session.add(condue)
        db.session.flush()
        condue.courses.append(Course.query.get(cid))
        db.session.flush()
        db.session.add(FeeRecord(student_id=condue.id, amount_paid=1000.0,
                                 concession=500.0, payment_date=date.today()))
        db.session.commit()
    captured = []
    svc = SmsService()
    monkeypatch.setattr(svc, 'send_sms',
                        lambda phone, msg: captured.append((phone, msg)) or True)
    with app.app_context():
        result = svc.batch_fee_reminders()
    assert result['sent'] == 2
    texts = ' | '.join(m for _, m in captured)
    # GST-inclusive due (5000 fee + 900 GST = 5900), not the taxable 5000.
    assert '5,900' in texts
    assert '5,000' not in texts
    # Concessions are honoured: 5900 - 1000 paid - 500 concession = 4400.
    assert '4,400' in texts


def test_messenger_reminder_uses_gst_inclusive_balance(app, monkeypatch):
    from app.services.messenger import Messenger
    captured = []
    m = Messenger()
    monkeypatch.setattr(m, '_send_sms_direct',
                        lambda phone, text: captured.append((phone, text)) or True)
    with app.app_context():
        result = m.batch_fee_reminders()
    assert result['sent'] == 1
    text = captured[0][1]
    assert '5,900' in text      # GST-inclusive balance in the reminder body
    assert '5,000' not in text


def test_fee_dues_ageing_buckets(app):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        old = Student(name='Aged 120', email='aged120@guha.test',
                      phone='9000000103', status='Active')
        mid = Student(name='Aged 60', email='aged60@guha.test',
                      phone='9000000104', status='Active')
        db.session.add_all([old, mid])
        db.session.flush()
        old.courses.append(Course.query.get(cid))
        mid.courses.append(Course.query.get(cid))
        db.session.flush()
        db.session.add(FeeRecord(student_id=old.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        db.session.add(FeeRecord(student_id=mid.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        old.enrollment_date = date.today() - timedelta(days=120)
        mid.enrollment_date = date.today() - timedelta(days=60)
        db.session.commit()
        dues, _, ageing = _fee_dues()
        row_old = next(d for d in dues if d['name'] == 'Aged 120')
        assert row_old['days_due'] == 120
        assert ageing['over_90'] == 4900.0
        assert ageing['over_30'] == 4900.0
        assert ageing['recent'] >= 0.0


def test_outstanding_card_ageing_hints(app, admin_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        old = Student(name='Old Dues', email='olddues2@guha.test',
                      phone='9000000101', status='Active')
        fresh = Student(name='Fresh Dues', email='freshdues@guha.test',
                        phone='9000000102', status='Active')
        db.session.add_all([old, fresh])
        db.session.flush()
        old.courses.append(Course.query.get(cid))
        fresh.courses.append(Course.query.get(cid))
        db.session.flush()
        db.session.add(FeeRecord(student_id=old.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        db.session.add(FeeRecord(student_id=fresh.id, amount_paid=1000.0,
                                 payment_date=date.today()))
        old.enrollment_date = date.today() - timedelta(days=120)
        fresh.enrollment_date = date.today() - timedelta(days=10)
        db.session.commit()
    html = admin_client.get('/').data.decode()
    assert '120d overdue' in html
    assert '10d overdue' in html
    assert '&gt;90d' in html
    assert '0&ndash;30d' in html


def test_outstanding_card_plus_n_more(app, admin_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        for i in range(7):
            s = Student(name=f'More Dues {i}', email=f'moredues{i}@guha.test',
                        phone=f'90000002{i:02d}', status='Active')
            db.session.add(s)
            db.session.flush()
            s.courses.append(Course.query.get(cid))
            db.session.flush()
            db.session.add(FeeRecord(student_id=s.id, amount_paid=1000.0,
                                     payment_date=date.today()))
        db.session.commit()
        dues, _, _ = _fee_dues()
        # Seeded Test Student also owes, so the list outgrows the top-5 cut.
        assert len(dues) >= 8
        expected = len(dues) - 5
    html = admin_client.get('/').data.decode()
    assert f'+{expected} more with dues' in html


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
