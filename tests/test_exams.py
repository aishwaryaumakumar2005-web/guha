import datetime

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import (
    User, Student, Tutor, Course, Exam, ExamScore,
    McqQuestion, McqAttempt, McqAnswer, ExamAssignment,
)


def _mk_user_and_student(app, username, email, name, enroll=True):
    with app.app_context():
        course = Course.query.filter_by(code='PY').first()
        u = User(username=username, password_hash=generate_password_hash('pw123'),
                 role='Student', name=name, email=email)
        db.session.add(u)
        db.session.flush()
        s = Student(name=name, email=email, phone='9999999990', status='Active')
        db.session.add(s)
        db.session.flush()
        if enroll and course is not None:
            s.courses.append(course)
        db.session.commit()
        return s.id


def _mcq_exam(app, published=True, duration=10, num_questions=2, course=None, **kw):
    with app.app_context():
        if course is None:
            course = Course.query.filter_by(code='PY').first()
        exam = Exam(course_id=course.id, title='Quiz Alpha', exam_date=datetime.date.today(),
                    max_marks=10, passing_marks=4, exam_type='mcq',
                    num_questions=num_questions, duration_minutes=duration,
                    is_published=published, **kw)
        db.session.add(exam)
        db.session.flush()
        for i in range(1, num_questions + 1):
            db.session.add(McqQuestion(
                exam_id=exam.id, question_number=i,
                question_text=f'Sample question {i}?',
                option_a='x', option_b='y', option_c='z', option_d='w',
                correct_option='A'))
        db.session.commit()
        return exam.id


def _assign(app, exam_id, student_id):
    with app.app_context():
        db.session.add(ExamAssignment(exam_id=exam_id, student_id=student_id, assigned_by=1))
        db.session.commit()


def _student_login(client, username):
    return client.post('/login', data={'username': username, 'password': 'pw123'})


# ── Critical: take page renders real questions + correct timer ────────

def test_take_page_renders_questions(app, client):
    sid = _mk_user_and_student(app, 'stu1', 'stu1@guha.test', 'Stu One')
    eid = _mcq_exam(app, published=True)
    _assign(app, eid, sid)
    assert _student_login(client, 'stu1').status_code == 302
    resp = client.get(f'/exams/{eid}/mcq/take')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Sample question 1?' in body
    assert 'Sample question 2?' in body
    assert 'var endTime = ' in body
    assert 'reviewModal' in body


def test_take_blocked_when_unpublished(app, client):
    sid = _mk_user_and_student(app, 'stu2', 'stu2@guha.test', 'Stu Two')
    eid = _mcq_exam(app, published=False)
    _assign(app, eid, sid)
    assert _student_login(client, 'stu2').status_code == 302
    resp = client.get(f'/exams/{eid}/mcq/take')
    assert resp.status_code == 302


def test_take_blocked_past_due(app, client):
    sid = _mk_user_and_student(app, 'stu3', 'stu3@guha.test', 'Stu Three')
    eid = _mcq_exam(app, published=True)
    with app.app_context():
        db.session.add(ExamAssignment(exam_id=eid, student_id=sid, assigned_by=1,
                                      due_date=datetime.date.today() - datetime.timedelta(days=1)))
        db.session.commit()
    assert _student_login(client, 'stu3').status_code == 302
    resp = client.get(f'/exams/{eid}/mcq/take')
    assert resp.status_code == 302


def test_take_blocked_not_enrolled(app, client):
    sid = _mk_user_and_student(app, 'stu4', 'stu4@guha.test', 'Stu Four', enroll=False)
    eid = _mcq_exam(app, published=True)
    with app.app_context():
        db.session.add(ExamAssignment(exam_id=eid, student_id=sid, assigned_by=1))
        db.session.commit()
    assert _student_login(client, 'stu4').status_code == 302
    resp = client.get(f'/exams/{eid}/mcq/take')
    assert resp.status_code == 302


def test_take_blocked_outside_availability_window(app, client):
    sid = _mk_user_and_student(app, 'stu5', 'stu5@guha.test', 'Stu Five')
    future = datetime.date.today() + datetime.timedelta(days=7)
    eid = _mcq_exam(app, published=True, available_from=future)
    _assign(app, eid, sid)
    assert _student_login(client, 'stu5').status_code == 302
    resp = client.get(f'/exams/{eid}/mcq/take')
    assert resp.status_code == 302


# ── Critical: preview is admin-only; deadline enforced on submit ──────

def test_preview_admin_only_blocks_student(app, client):
    sid = _mk_user_and_student(app, 'stu6', 'stu6@guha.test', 'Stu Six')
    eid = _mcq_exam(app, published=True)
    _assign(app, eid, sid)
    assert _student_login(client, 'stu6').status_code == 302
    resp = client.get(f'/exams/{eid}/mcq/preview')
    assert resp.status_code == 302  # admin_required redirect


def test_preview_for_admin(app, admin_client):
    eid = _mcq_exam(app, published=True)
    resp = admin_client.get(f'/exams/{eid}/mcq/preview')
    assert resp.status_code == 200
    assert 'Sample question 1?' in resp.get_data(as_text=True)


def test_submit_enforces_deadline(app, client):
    sid = _mk_user_and_student(app, 'stu7', 'stu7@guha.test', 'Stu Seven')
    eid = _mcq_exam(app, published=True, duration=10)
    _assign(app, eid, sid)
    with app.app_context():
        db.session.add(McqAttempt(exam_id=eid, student_id=sid, total_marks=10,
                                  start_time=datetime.datetime.utcnow() - datetime.timedelta(hours=2)))
        db.session.commit()
    assert _student_login(client, 'stu7').status_code == 302
    resp = client.post(f'/exams/{eid}/mcq/submit', json={'answers': {}})
    assert resp.status_code == 400
    assert 'Time expired' in resp.get_json()['error']


def test_submit_writes_score_and_unifies_examscore(app, client):
    sid = _mk_user_and_student(app, 'stu8', 'stu8@guha.test', 'Stu Eight')
    eid = _mcq_exam(app, published=True)
    _assign(app, eid, sid)
    with app.app_context():
        qids = [q.id for q in McqQuestion.query.filter_by(exam_id=eid).all()]
        db.session.add(McqAttempt(exam_id=eid, student_id=sid, total_marks=10,
                                  start_time=datetime.datetime.utcnow()))
        db.session.commit()
    assert _student_login(client, 'stu8').status_code == 302
    resp = client.post(f'/exams/{eid}/mcq/submit',
                       json={'answers': {str(qids[0]): 'A', str(qids[1]): 'A'}})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['score'] == 10.0
    assert data['grade'] == 'A'
    with app.app_context():
        scored = ExamScore.query.filter_by(exam_id=eid, student_id=sid).first()
        assert scored is not None
        assert scored.marks_obtained == 10.0
        attempt = McqAttempt.query.filter_by(exam_id=eid, student_id=sid).first()
        assert attempt.status == 'completed'


def test_results_page_shows_answer_review(app, client):
    sid = _mk_user_and_student(app, 'stu9', 'stu9@guha.test', 'Stu Nine')
    eid = _mcq_exam(app, published=True)
    _assign(app, eid, sid)
    with app.app_context():
        qids = [q.id for q in McqQuestion.query.filter_by(exam_id=eid).all()]
        at = McqAttempt(exam_id=eid, student_id=sid, total_marks=10,
                        start_time=datetime.datetime.utcnow() - datetime.timedelta(minutes=2),
                        end_time=datetime.datetime.utcnow(), score=5, status='completed')
        at.calculate_grade()
        db.session.add(at)
        db.session.flush()
        db.session.add(McqAnswer(mcq_attempt_id=at.id, mcq_question_id=qids[0],
                                 selected_option='A', is_correct=True))
        db.session.add(McqAnswer(mcq_attempt_id=at.id, mcq_question_id=qids[1],
                                 selected_option='B', is_correct=False))
        db.session.commit()
    assert _student_login(client, 'stu9').status_code == 302
    resp = client.get(f'/exams/{eid}/mcq/results')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Answer Review' in body
    assert 'Sample question 1?' in body


# ── Staff grading ─────────────────────────────────────────────────────

def test_staff_can_grade_exams_for_own_courses(app, staff_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        exam = Exam(course_id=cid, title='Manual Test', exam_date=datetime.date.today(),
                    max_marks=50, passing_marks=20)
        db.session.add(exam)
        db.session.commit()
        eid = exam.id
        sid = Student.query.filter_by(email='student@guha.test').first().id
    resp = staff_client.get(f'/exams/{eid}/scores')
    assert resp.status_code == 200
    resp = staff_client.post(f'/exams/{eid}/scores/save',
                             data={'student_id[]': [str(sid)], 'marks[]': ['40'],
                                   'remarks[]': ['Good']})
    assert resp.status_code == 302
    with app.app_context():
        sc = ExamScore.query.filter_by(exam_id=eid, student_id=sid).first()
        assert sc is not None and sc.marks_obtained == 40.0
    resp = staff_client.get(f'/exams/{eid}/report')
    assert resp.status_code == 200
    assert resp.content_type.startswith('application/pdf')
    resp = staff_client.get(f'/exams/{eid}/scores/export')
    assert resp.status_code == 200
    assert 'text/csv' in resp.content_type


def test_staff_blocked_from_other_course_exam(app, staff_client):
    with app.app_context():
        other = Course(name='Java', code='JA', description='Java',
                       duration_weeks=6, duration_unit='weeks', fees=4000.0,
                       gst_applicable=False)
        db.session.add(other)
        db.session.flush()
        exam = Exam(course_id=other.id, title='Java Mid', exam_date=datetime.date.today(),
                    max_marks=50, passing_marks=20)
        db.session.add(exam)
        db.session.commit()
        eid = exam.id
    resp = staff_client.get(f'/exams/{eid}/scores')
    assert resp.status_code == 302


def test_staff_list_hides_create_cta(app, staff_client):
    resp = staff_client.get('/exams')
    assert resp.status_code == 200
    assert 'Create MCQ Exam with AI' not in resp.get_data(as_text=True)


# ── Assign / unassign / due date ──────────────────────────────────────

def test_assign_restricted_to_course_students(app, admin_client):
    eid = _mcq_exam(app)
    with app.app_context():
        outer = Student(name='Outsider', email='out@guha.test', phone='1111111111',
                        status='Active')
        db.session.add(outer)
        db.session.commit()
        outer_id = outer.id
        enrolled_id = Student.query.filter_by(email='student@guha.test').first().id
    resp = admin_client.get(f'/exams/{eid}/mcq/assign')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Outsider' not in body
    resp = admin_client.post(f'/exams/{eid}/mcq/assign',
                             data={'student_ids': [str(enrolled_id), str(outer_id)],
                                   'due_date': ''})
    assert resp.status_code == 302
    with app.app_context():
        assigned = [a.student_id for a in ExamAssignment.query.filter_by(exam_id=eid).all()]
        assert enrolled_id in assigned
        assert outer_id not in assigned


def test_assign_uncheck_removes_and_sets_due(app, admin_client):
    eid = _mcq_exam(app)
    with app.app_context():
        enrolled_id = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(ExamAssignment(exam_id=eid, student_id=enrolled_id, assigned_by=1))
        db.session.commit()
    due = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    resp = admin_client.post(f'/exams/{eid}/mcq/assign',
                             data={'student_ids': [str(enrolled_id)], 'due_date': due})
    assert resp.status_code == 302
    with app.app_context():
        a = ExamAssignment.query.filter_by(exam_id=eid, student_id=enrolled_id).first()
        assert a.due_date.isoformat() == due
    resp = admin_client.post(f'/exams/{eid}/mcq/assign', data={'student_ids': [], 'due_date': ''})
    assert resp.status_code == 302
    with app.app_context():
        assert ExamAssignment.query.filter_by(exam_id=eid).first() is None


# ── Misc bugs ─────────────────────────────────────────────────────────

def test_exam_scores_rank_ties_share_rank(app, admin_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        exam = Exam(course_id=cid, title='Tie Test', exam_date=datetime.date.today(),
                    max_marks=50, passing_marks=20)
        db.session.add(exam)
        db.session.flush()
        eid = exam.id
        s1 = Student.query.filter_by(email='student@guha.test').first()
        s2 = Student(name='Other Enrolled', email='other@guha.test', phone='2222222222',
                     status='Active')
        db.session.add(s2)
        db.session.flush()
        s2.courses.append(s1.courses[0])
        db.session.add(ExamScore(exam_id=eid, student_id=s1.id, marks_obtained=40, remarks=''))
        db.session.add(ExamScore(exam_id=eid, student_id=s2.id, marks_obtained=40, remarks=''))
        db.session.commit()
    resp = admin_client.get(f'/exams/{eid}/scores')
    assert resp.status_code == 200
    assert resp.get_data(as_text=True).count('rank-badge rank-1') == 2


def test_regenerate_blocked_after_completed_attempt(app, admin_client):
    eid = _mcq_exam(app)
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(McqAttempt(exam_id=eid, student_id=sid, total_marks=10,
                                  start_time=datetime.datetime.utcnow() - datetime.timedelta(minutes=2),
                                  end_time=datetime.datetime.utcnow(), score=5, status='completed'))
        db.session.commit()
        count_before = McqQuestion.query.filter_by(exam_id=eid).count()
    resp = admin_client.post(f'/exams/{eid}/mcq/regenerate')
    assert resp.status_code == 302
    with app.app_context():
        assert McqQuestion.query.filter_by(exam_id=eid).count() == count_before


def test_unpublish_flow(app, admin_client):
    eid = _mcq_exam(app, published=True)
    resp = admin_client.post(f'/exams/{eid}/mcq/unpublish')
    assert resp.status_code == 302
    with app.app_context():
        assert Exam.query.get(eid).is_published is False


def test_stale_in_progress_attempt_finalized_on_analysis(app, admin_client):
    eid = _mcq_exam(app)
    with app.app_context():
        sid = Student.query.filter_by(email='student@guha.test').first().id
        db.session.add(McqAttempt(exam_id=eid, student_id=sid, total_marks=10,
                                  start_time=datetime.datetime.utcnow() - datetime.timedelta(hours=3)))
        db.session.commit()
    resp = admin_client.get(f'/exams/{eid}/mcq/analysis')
    assert resp.status_code == 200
    with app.app_context():
        at = McqAttempt.query.filter_by(exam_id=eid, student_id=sid).first()
        assert at.status == 'completed'


def test_create_manual_exam_with_window_fields(app, admin_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
    af = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    au = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
    resp = admin_client.post('/exams/create', data={
        'course_id': str(cid), 'title': 'Windowed Exam', 'exam_date': datetime.date.today().isoformat(),
        'max_marks': '50', 'passing_marks': '20', 'description': '',
        'available_from': af, 'available_until': au,
    })
    assert resp.status_code == 302
    with app.app_context():
        e = Exam.query.filter_by(title='Windowed Exam').first()
        assert e is not None
        assert e.available_from.isoformat() == af
        assert e.available_until.isoformat() == au


def test_list_filter_by_status_and_search(app, admin_client):
    with app.app_context():
        cid = Course.query.filter_by(code='PY').first().id
        draft = Exam(course_id=cid, title='Secret Draft Exam', exam_date=datetime.date.today(),
                     max_marks=10, passing_marks=4)
        db.session.add(draft)
        db.session.commit()
    resp = admin_client.get('/exams?status=draft')
    assert 'Secret Draft Exam' in resp.get_data(as_text=True)
    resp = admin_client.get('/exams?status=published')
    assert 'Secret Draft Exam' not in resp.get_data(as_text=True)
    resp = admin_client.get('/exams?q=Secret')
    assert 'Secret Draft Exam' in resp.get_data(as_text=True)