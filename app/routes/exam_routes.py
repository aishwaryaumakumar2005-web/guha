import json
from datetime import datetime, date, timedelta, timezone
from io import BytesIO, StringIO
import csv
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from fpdf import FPDF
from app.extensions import db
from app.models import Course, Student, Exam, ExamScore, McqQuestion, McqAttempt, McqAnswer, ExamAssignment, Tutor, AuditLog, student_courses
from app.models.user import User
from app.helpers import admin_required
from app.forms import ExamForm

exams_bp = Blueprint('exams', __name__, url_prefix='/exams')


def _staff_course_ids():
    tutor = Tutor.query.filter_by(email=current_user.email).first()
    return {c.id for c in tutor.courses if (c.status or 'Active') != 'Archived'} if tutor else set()


def _staff_may_manage(exam):
    return current_user.role.lower() == 'admin' or exam.course_id in _staff_course_ids()


def _parse_optional_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _finalize_expired(exam):
    """Auto-complete in-progress attempts whose window has passed (moderate grace)."""
    try:
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        for a in McqAttempt.query.filter_by(exam_id=exam.id, status='in_progress').all():
            start = a.start_time or datetime.utcnow()
            deadline = start.replace(tzinfo=timezone.utc) + timedelta(minutes=exam.duration_minutes or 0)
            if now > deadline + timedelta(seconds=120):
                a.status = 'completed'
                if a.grade is None:
                    a.grade = 'N/A'
                    a.calculate_grade()
        db.session.commit()
    except Exception:
        db.session.rollback()

# ── Existing manual exam routes ────────────────────────────────────

@exams_bp.route('')
@login_required
def exam_list():
    if current_user.role.lower() == 'staff':
        # Staff: show exams for their assigned courses
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor:
            return render_template('exams.html', exams=[], courses=[],
                filter_course=None, filter_month=None, filter_year=None, filter_status=None, filter_q=None,
                today=date.today(), section='list', is_staff=True)
        course_ids = [c.id for c in tutor.courses if (c.status or 'Active') != 'Archived']
        filter_course = request.args.get('course_id', type=int)
        filter_month = request.args.get('month', type=int)
        filter_year = request.args.get('year', type=int)
        filter_status = request.args.get('status', '')
        filter_q = request.args.get('q', '').strip()
        query = Exam.query.filter(Exam.course_id.in_(course_ids),
                                  db.or_(Exam.status.is_(None), Exam.status != 'Archived'))
        if filter_course and filter_course in course_ids:
            query = query.filter_by(course_id=filter_course)
        if filter_month and filter_year:
            query = query.filter(db.extract('month', Exam.exam_date) == filter_month, db.extract('year', Exam.exam_date) == filter_year)
        elif filter_year:
            query = query.filter(db.extract('year', Exam.exam_date) == filter_year)
        if filter_status == 'published':
            query = query.filter(Exam.is_published.is_(True))
        elif filter_status == 'draft':
            query = query.filter(Exam.is_published.is_(False))
        if filter_q:
            like = f'%{filter_q}%'
            query = query.filter(db.or_(Exam.title.ilike(like), Exam.description.ilike(like)))
        exams = query.order_by(Exam.exam_date.desc()).all()
        courses = tutor.courses
        return render_template('exams.html', exams=exams, courses=courses,
            filter_course=filter_course, filter_month=filter_month, filter_year=filter_year,
            filter_status=filter_status, filter_q=filter_q,
            today=date.today(), section='list', is_staff=True)
    elif current_user.role.lower() != 'admin':
        student = Student.query.filter_by(email=current_user.email).first()
        if not student:
            flash('Student profile not found.', 'warning')
            return redirect(url_for('dashboard.dashboard'))
        assignments = ExamAssignment.query.filter_by(student_id=student.id).order_by(ExamAssignment.assigned_at.desc()).all()
        exams = [a.exam for a in assignments]
        attempt_map = {}
        for e in exams:
            at = McqAttempt.query.filter_by(exam_id=e.id, student_id=student.id, status='completed').first()
            if at:
                attempt_map[e.id] = at
        return render_template('exams.html', exams=exams, attempt_map=attempt_map,
            courses=[], filter_course=None, filter_month=None, filter_year=None, filter_status=None, filter_q=None,
            today=date.today(), section='student_list')
    filter_course = request.args.get('course_id', type=int)
    filter_month = request.args.get('month', type=int)
    filter_year = request.args.get('year', type=int)
    filter_status = request.args.get('status', '')
    filter_q = request.args.get('q', '').strip()
    query = Exam.query.filter(db.or_(Exam.status.is_(None), Exam.status != 'Archived'))
    if filter_course:
        query = query.filter_by(course_id=filter_course)
    if filter_month and filter_year:
        query = query.filter(db.extract('month', Exam.exam_date) == filter_month, db.extract('year', Exam.exam_date) == filter_year)
    elif filter_year:
        query = query.filter(db.extract('year', Exam.exam_date) == filter_year)
    if filter_status == 'published':
        query = query.filter(Exam.is_published.is_(True))
    elif filter_status == 'draft':
        query = query.filter(Exam.is_published.is_(False))
    if filter_q:
        like = f'%{filter_q}%'
        query = query.filter(db.or_(Exam.title.ilike(like), Exam.description.ilike(like)))
    exams = query.order_by(Exam.exam_date.desc()).all()
    courses = Course.query.order_by(Course.name).all()
    return render_template('exams.html', exams=exams, courses=courses,
        filter_course=filter_course, filter_month=filter_month, filter_year=filter_year,
        filter_status=filter_status, filter_q=filter_q,
        today=date.today(), section='list')

@exams_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create_exam():
    form = ExamForm(request.form)
    if not form.validate():
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('exams.exam_list'))
    course_id = form.cleaned_data.get('course_id')
    title = form.data.get('title', '').strip()
    exam_date = form.cleaned_data.get('exam_date', date.today())
    max_marks = form.cleaned_data.get('max_marks', 0)
    passing_marks = form.cleaned_data.get('passing_marks', 0)
    description = request.form.get('description', '').strip()
    available_from = _parse_optional_date(request.form.get('available_from'))
    available_until = _parse_optional_date(request.form.get('available_until'))
    exam = Exam(course_id=course_id, title=title, exam_date=exam_date, max_marks=max_marks, passing_marks=passing_marks, description=description, available_from=available_from, available_until=available_until)
    db.session.add(exam)
    db.session.commit()
    flash(f"Exam '{title}' created.", "success")
    return redirect(url_for('exams.exam_list'))

@exams_bp.route('/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_exam(id):
    exam = Exam.query.get_or_404(id)
    form = ExamForm(request.form)
    if not form.validate():
        for msg in form.error_messages:
            flash(msg, 'danger')
        return redirect(url_for('exams.exam_list'))
    exam.course_id = form.cleaned_data.get('course_id')
    exam.title = form.data.get('title', '').strip()
    exam.exam_date = form.cleaned_data.get('exam_date', exam.exam_date)
    exam.max_marks = form.cleaned_data.get('max_marks', 0)
    exam.passing_marks = form.cleaned_data.get('passing_marks', 0)
    exam.description = request.form.get('description', '').strip()
    exam.available_from = _parse_optional_date(request.form.get('available_from'))
    exam.available_until = _parse_optional_date(request.form.get('available_until'))
    db.session.commit()
    flash(f"Exam '{exam.title}' updated.", "success")
    return redirect(url_for('exams.exam_list'))

@exams_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_exam(id):
    exam = Exam.query.get_or_404(id)
    title = exam.title
    exam.status = 'Archived'
    db.session.commit()
    flash(f"Exam '{title}' archived. Scores and attempts were preserved.", "info")
    return redirect(url_for('exams.exam_list'))

@exams_bp.route('/<int:id>/scores')
@login_required
def exam_scores(id):
    exam = Exam.query.get_or_404(id)
    if not _staff_may_manage(exam):
        flash('You do not have access to this exam.', 'danger')
        return redirect(url_for('exams.exam_list'))
    students = Student.query.join(student_courses, student_courses.c.student_id == Student.id).filter(
        student_courses.c.course_id == exam.course_id,
        db.or_(student_courses.c.status == 'Enrolled', student_courses.c.status.is_(None)),
        Student.status == 'Active').order_by(Student.name).all()
    score_map = {}
    for s in exam.scores:
        score_map[s.student_id] = s
    ranked = sorted(students, key=lambda s: score_map[s.id].marks_obtained if s.id in score_map else -1, reverse=True)
    rank_map = {}
    prev_marks = None
    prev_rank = 0
    for pos, s in enumerate(ranked, 1):
        if s.id not in score_map:
            continue
        marks = score_map[s.id].marks_obtained
        if prev_marks is None or marks != prev_marks:
            prev_rank = pos
        rank_map[s.id] = prev_rank
        prev_marks = marks
    return render_template('exams.html', exam=exam, students=students, score_map=score_map, rank_map=rank_map, section='scores', today=date.today())

@exams_bp.route('/<int:id>/scores/save', methods=['POST'])
@login_required
def save_scores(id):
    exam = Exam.query.get_or_404(id)
    if not _staff_may_manage(exam):
        flash('You do not have access to this exam.', 'danger')
        return redirect(url_for('exams.exam_list'))
    student_ids = request.form.getlist('student_id[]')
    marks_list = request.form.getlist('marks[]')
    remarks_list = request.form.getlist('remarks[]')
    saved = 0
    for sid, marks, rem in zip(student_ids, marks_list, remarks_list):
        try:
            sid_int = int(sid)
        except (ValueError, TypeError):
            continue
        marks_val = None
        if marks.strip():
            try:
                marks_val = float(marks)
            except (ValueError, TypeError):
                continue
        if marks_val is None:
            continue
        if marks_val < 0 or marks_val > exam.max_marks:
            flash(f'Marks must be between 0 and {exam.max_marks:.0f}. Skipped student #{sid_int}.', 'warning')
            continue
        rem = (rem.strip() or '')[:200]
        existing = ExamScore.query.filter_by(exam_id=exam.id, student_id=sid_int).first()
        if existing:
            previous_marks = existing.marks_obtained
            existing.marks_obtained = marks_val
            existing.remarks = rem
        else:
            previous_marks = None
            score = ExamScore(exam_id=exam.id, student_id=sid_int, marks_obtained=marks_val, remarks=rem)
            db.session.add(score)
        db.session.flush()
        db.session.add(AuditLog(
            user_id=current_user.id, username=current_user.username,
            action='UPDATE', entity_type='ExamScore', entity_id=existing.id if existing else None,
            changes=json.dumps({'exam_id': exam.id, 'student_id': sid_int,
                                'from': previous_marks, 'to': marks_val})))
        saved += 1
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('Scores could not be saved. Check for duplicate rows and try again.', 'danger')
        return redirect(url_for('exams.exam_scores', id=exam.id))
    flash(f"{saved} score(s) saved.", "success")
    return redirect(url_for('exams.exam_scores', id=exam.id))

@exams_bp.route('/<int:id>/scores/export')
@login_required
def export_scores(id):
    exam = Exam.query.get_or_404(id)
    if not _staff_may_manage(exam):
        flash('You do not have access to this exam.', 'danger')
        return redirect(url_for('exams.exam_list'))
    students = Student.query.join(Student.courses).filter(Course.id == exam.course_id).order_by(Student.name).all()
    score_map = {s.student_id: s for s in exam.scores}
    ranked = sorted(students, key=lambda s: score_map[s.id].marks_obtained if s.id in score_map else -1, reverse=True)
    rank_map = {}
    prev_marks = None
    prev_rank = 0
    for pos, s in enumerate(ranked, 1):
        if s.id not in score_map:
            continue
        marks = score_map[s.id].marks_obtained
        if prev_marks is None or marks != prev_marks:
            prev_rank = pos
        rank_map[s.id] = prev_rank
        prev_marks = marks
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Rank', 'Student Name', 'Email', 'Marks', 'Max Marks', 'Percentage', 'Result', 'Remarks'])
    for s in ranked:
        sc = score_map.get(s.id)
        if not sc:
            continue
        pct = round(sc.marks_obtained / exam.max_marks * 100, 1) if exam.max_marks else 0
        writer.writerow([
            rank_map.get(s.id, '-'), s.name, s.email,
            f'{sc.marks_obtained:.2f}', f'{exam.max_marks:.2f}', f'{pct}%',
            'Pass' if sc.marks_obtained >= exam.passing_marks else 'Fail',
            sc.remarks or ''])
    output = buf.getvalue().encode('utf-8-sig')
    return send_file(BytesIO(output), mimetype='text/csv', as_attachment=True,
        download_name=f'{exam.course.code}_{exam.exam_date.strftime("%Y%m%d")}_scores.csv')

@exams_bp.route('/<int:id>/report')
@login_required
def exam_report(id):
    exam = Exam.query.get_or_404(id)
    if not _staff_may_manage(exam):
        flash('You do not have access to this exam.', 'danger')
        return redirect(url_for('exams.exam_list'))
    students = Student.query.join(Student.courses).filter(Course.id == exam.course_id).order_by(Student.name).all()
    score_map = {}
    for s in exam.scores:
        score_map[s.student_id] = s
    ranked = sorted(students, key=lambda s: score_map[s.id].marks_obtained if s.id in score_map else -1, reverse=True)
    pdf = FPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    def text_color(r, g, b):
        pdf.set_text_color(r, g, b)
    def set_font(style='', size=10):
        pdf.set_font('Helvetica', style, size)
    pdf.set_fill_color(10, 30, 46)
    pdf.rect(0, 0, 210, 40, 'F')
    set_font('B', 18)
    text_color(0, 212, 255)
    pdf.set_xy(15, 8)
    pdf.cell(0, 10, 'Guha Academy - Computer Institute', align='L')
    set_font('B', 14)
    text_color(255, 255, 255)
    pdf.set_xy(15, 22)
    pdf.cell(0, 8, f'Exam Report: {exam.title}', align='L')
    set_font('', 8)
    text_color(200, 200, 200)
    pdf.set_xy(15, 32)
    pdf.cell(0, 6, f'Course: {exam.course.name} ({exam.course.code})  |  Date: {exam.exam_date.strftime("%d %b %Y")}  |  Max Marks: {exam.max_marks:.0f}  |  Passing: {exam.passing_marks:.0f}', align='L')
    pdf.ln(10)
    total_students = len(ranked)
    scored = [s for s in ranked if s.id in score_map]
    passed = [s for s in scored if score_map[s.id].marks_obtained >= exam.passing_marks]
    passed_count = len(passed)
    avg_marks = sum(score_map[s.id].marks_obtained for s in scored) / len(scored) if scored else 0
    set_font('B', 10)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Summary', new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    set_font('', 9)
    text_color(60, 60, 60)
    for label, val in [('Total Students', str(total_students)), ('Scored', str(len(scored))), ('Passed', str(passed_count)), ('Failed', str(len(scored) - passed_count)), ('Pass %', f'{(passed_count/len(scored)*100):.1f}%' if scored else 'N/A'), ('Average Marks', f'{avg_marks:.1f}')]:
        pdf.cell(45, 6, label)
        pdf.cell(30, 6, val, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    set_font('B', 10)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Rank List', new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    col_w = [10, 65, 25, 25, 25, 40]
    headers = ['#', 'Student Name', 'Marks', 'Max', 'Result', 'Remarks']
    def table_header():
        set_font('B', 8)
        pdf.set_fill_color(10, 30, 46)
        text_color(255, 255, 255)
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 7, h, border=1, fill=True, align='C')
        pdf.ln()
    def table_row(cols, is_pass=True):
        pdf.set_fill_color(240, 250, 240) if is_pass else pdf.set_fill_color(255, 240, 240)
        text_color(30, 30, 30)
        set_font('', 8)
        for i, c in enumerate(cols):
            pdf.cell(col_w[i], 6, str(c), border=1, fill=True, align='C' if i == 0 else ('L' if i == 1 else 'C'))
        pdf.ln()
    table_header()
    rank = 1
    for s in ranked:
        if s.id not in score_map:
            continue
        sc = score_map[s.id]
        is_pass = sc.marks_obtained >= exam.passing_marks
        result = 'Pass' if is_pass else 'Fail'
        rem = sc.remarks or ''
        table_row([str(rank), s.name, f'{sc.marks_obtained:.0f}', f'{exam.max_marks:.0f}', result, rem], is_pass)
        rank += 1
    pdf.ln(5)
    text_color(150, 150, 150)
    set_font('', 7)
    pdf.cell(0, 5, f'Generated on: {datetime.now().strftime("%d %b %Y %I:%M %p")}', align='C')
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
        download_name=f'exam_report_{exam.course.code}_{exam.exam_date.strftime("%Y%m%d")}.pdf')

@exams_bp.route('/student-report/<int:student_id>')
@login_required
@admin_required
def student_report(student_id):
    student = Student.query.get_or_404(student_id)
    scores = ExamScore.query.filter_by(student_id=student_id).join(Exam).order_by(Exam.exam_date.desc()).all()
    pdf = FPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    def text_color(r, g, b):
        pdf.set_text_color(r, g, b)
    def set_font(style='', size=10):
        pdf.set_font('Helvetica', style, size)
    pdf.set_fill_color(10, 30, 46)
    pdf.rect(0, 0, 210, 40, 'F')
    set_font('B', 18)
    text_color(0, 212, 255)
    pdf.set_xy(15, 8)
    pdf.cell(0, 10, 'Guha Academy - Computer Institute', align='L')
    set_font('B', 14)
    text_color(255, 255, 255)
    pdf.set_xy(15, 22)
    pdf.cell(0, 8, 'Student Performance Report', align='L')
    set_font('', 9)
    text_color(200, 200, 200)
    pdf.set_xy(15, 32)
    pdf.cell(0, 6, f'{student.name}  |  {student.email}  |  {student.phone}', align='L')
    pdf.ln(10)
    set_font('B', 10)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Course Enrollment', new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    set_font('', 9)
    text_color(60, 60, 60)
    for c in student.courses:
        pdf.cell(0, 6, f'- {c.name} ({c.code})', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    set_font('B', 10)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Exam Scores', new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    if scores:
        col_w = [60, 30, 25, 25, 20, 30]
        headers = ['Exam', 'Date', 'Marks', 'Max', '%', 'Result']
        def table_header():
            set_font('B', 8)
            pdf.set_fill_color(10, 30, 46)
            text_color(255, 255, 255)
            for i, h in enumerate(headers):
                pdf.cell(col_w[i], 7, h, border=1, fill=True, align='C')
            pdf.ln()
        def table_row(cols, is_pass=True):
            pdf.set_fill_color(240, 250, 240) if is_pass else pdf.set_fill_color(255, 240, 240)
            text_color(30, 30, 30)
            set_font('', 8)
            for i, c in enumerate(cols):
                pdf.cell(col_w[i], 6, str(c), border=1, fill=True, align='C')
            pdf.ln()
        table_header()
        total_pct = 0
        count = 0
        for sc in scores:
            e = sc.exam
            pct = (sc.marks_obtained / e.max_marks) * 100 if e.max_marks > 0 else 0
            is_pass = sc.marks_obtained >= e.passing_marks
            total_pct += pct
            count += 1
            table_row([e.title, e.exam_date.strftime('%d/%m/%y'), f'{sc.marks_obtained:.0f}', f'{e.max_marks:.0f}', f'{pct:.0f}%', 'Pass' if is_pass else 'Fail'], is_pass)
        if count > 0:
            pdf.ln(3)
            set_font('B', 10)
            text_color(30, 60, 80)
            pdf.cell(0, 7, f'Overall Average: {total_pct/count:.1f}%', new_x="LMARGIN", new_y="NEXT")
    else:
        set_font('', 9)
        text_color(150, 150, 150)
        pdf.cell(0, 6, 'No exam scores recorded yet.', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    text_color(150, 150, 150)
    set_font('', 7)
    pdf.cell(0, 5, f'Generated on: {datetime.now().strftime("%d %b %Y %I:%M %p")}', align='C')
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
        download_name=f'performance_{student.name.replace(" ", "_")}.pdf')

# ── MCQ routes (integrated into same blueprint) ────────────────────

@exams_bp.route('/mcq/create')
@login_required
@admin_required
def mcq_create():
    courses = Course.query.order_by(Course.name).all()
    return render_template('exams_mcq_create.html', courses=courses, today=date.today())

@exams_bp.route('/mcq/generate', methods=['POST'])
@login_required
@admin_required
def mcq_generate():
    course_id = request.form.get('course_id', type=int)
    title = request.form.get('title', '').strip()
    num_questions = request.form.get('num_questions', type=int) or 10
    duration_mins = request.form.get('duration_mins', type=int) or 30
    total_marks = request.form.get('total_marks', type=float) or 100
    available_from = _parse_optional_date(request.form.get('available_from'))
    available_until = _parse_optional_date(request.form.get('available_until'))

    course = Course.query.get_or_404(course_id)
    questions = current_app.ai_engine.generate_mcq_questions(
        course.name, course.description or '',
        num_questions=num_questions, duration_mins=duration_mins, total_marks=total_marks
    )
    if not questions:
        flash('Failed to generate questions. Ensure an AI API key is configured (Gemini or OpenAI).', 'danger')
        return redirect(url_for('exams.mcq_create'))

    exam = Exam(
        course_id=course_id, title=title, exam_date=date.today(),
        max_marks=total_marks, passing_marks=round(total_marks * 0.35),
        exam_type='mcq', num_questions=len(questions),
        duration_minutes=duration_mins, is_published=False,
        available_from=available_from, available_until=available_until,
    )
    db.session.add(exam)
    db.session.flush()

    for q in questions:
        db.session.add(McqQuestion(exam_id=exam.id, **q))
    db.session.commit()
    flash(f'AI generated {len(questions)} questions for "{title}"! Review and publish when ready.', 'success')
    return redirect(url_for('exams.mcq_preview', id=exam.id))

@exams_bp.route('/<int:id>/mcq/preview')
@login_required
@admin_required
def mcq_preview(id):
    exam = Exam.query.get_or_404(id)
    return render_template('exams_mcq_preview.html', exam=exam)

@exams_bp.route('/<int:id>/mcq/unpublish', methods=['POST'])
@login_required
@admin_required
def mcq_unpublish(id):
    exam = Exam.query.get_or_404(id)
    exam.is_published = False
    db.session.commit()
    flash(f'"{exam.title}" is back to draft. Students can no longer take it.', 'info')
    return redirect(url_for('exams.mcq_preview', id=exam.id))

@exams_bp.route('/<int:id>/mcq/regenerate', methods=['POST'])
@login_required
@admin_required
def mcq_regenerate(id):
    exam = Exam.query.get_or_404(id)
    if McqAttempt.query.filter_by(exam_id=exam.id, status='completed').first():
        flash('Cannot regenerate questions: students have already attempted this exam.', 'warning')
        return redirect(url_for('exams.mcq_preview', id=exam.id))
    course = exam.course
    questions = current_app.ai_engine.generate_mcq_questions(
        course.name, course.description or '',
        num_questions=exam.num_questions, duration_mins=exam.duration_minutes,
        total_marks=exam.max_marks
    )
    if not questions:
        flash('Failed to regenerate questions.', 'danger')
        return redirect(url_for('exams.mcq_preview', id=exam.id))
    McqQuestion.query.filter_by(exam_id=exam.id).delete()
    for q in questions:
        db.session.add(McqQuestion(exam_id=exam.id, **q))
    db.session.commit()
    flash('Questions regenerated!', 'success')
    return redirect(url_for('exams.mcq_preview', id=exam.id))

@exams_bp.route('/<int:id>/mcq/publish', methods=['POST'])
@login_required
@admin_required
def mcq_publish(id):
    exam = Exam.query.get_or_404(id)
    questions = list(exam.mcq_questions)
    if not questions or any(q.correct_option not in ('A', 'B', 'C', 'D') for q in questions):
        flash('Cannot publish: add valid questions and correct answers first.', 'danger')
        return redirect(url_for('exams.mcq_preview', id=exam.id))
    exam.num_questions = len(questions)
    exam.is_published = True
    db.session.commit()
    flash(f'"{exam.title}" is now published. Students can take the exam.', 'success')
    return redirect(url_for('exams.exam_list'))

@exams_bp.route('/<int:id>/mcq/edit-question', methods=['POST'])
@login_required
@admin_required
def mcq_edit_question(id):
    q = McqQuestion.query.get_or_404(id)
    q.question_text = request.form.get('question_text', q.question_text)
    q.option_a = request.form.get('option_a', q.option_a)
    q.option_b = request.form.get('option_b', q.option_b)
    q.option_c = request.form.get('option_c', q.option_c)
    q.option_d = request.form.get('option_d', q.option_d)
    correct = request.form.get('correct_option', q.correct_option).upper()
    if correct not in ('A', 'B', 'C', 'D'):
        flash('Correct answer must be A, B, C, or D.', 'danger')
        return redirect(request.referrer or url_for('exams.mcq_preview', id=q.exam_id))
    q.correct_option = correct
    db.session.commit()
    flash('Question updated!', 'success')
    return redirect(request.referrer or url_for('exams.mcq_preview', id=q.exam_id))

@exams_bp.route('/<int:id>/mcq/take')
@login_required
def mcq_take(id):
    exam = Exam.query.get_or_404(id)
    _finalize_expired(exam)
    if (exam.status or 'Active') == 'Archived':
        flash('This exam is archived.', 'warning')
        return redirect(url_for('dashboard.dashboard'))
    if not exam.is_published:
        flash('This exam has not been published yet.', 'warning')
        return redirect(url_for('dashboard.dashboard'))
    today = date.today()
    if exam.available_from and today < exam.available_from:
        flash('This exam has not opened yet.', 'warning')
        return redirect(url_for('dashboard.dashboard'))
    if exam.available_until and today > exam.available_until:
        flash('This exam has closed.', 'warning')
        return redirect(url_for('dashboard.dashboard'))
    student = Student.query.filter_by(email=current_user.email).first()
    if not student:
        flash('Only students can take exams.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    if exam.course not in student.courses:
        flash('You are not enrolled in this exam\'s course.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    assignment = ExamAssignment.query.filter_by(exam_id=exam.id, student_id=student.id).first()
    if not assignment:
        flash('This exam is not assigned to you.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    if assignment.due_date and today > assignment.due_date:
        flash('This exam is past its due date.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    existing = McqAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='completed').first()
    if existing:
        flash('You have already completed this exam.', 'warning')
        return redirect(url_for('exams.mcq_results', id=exam.id))
    attempt = McqAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='in_progress').first()
    if not attempt:
        attempt = McqAttempt(exam_id=exam.id, student_id=student.id, total_marks=exam.max_marks)
        db.session.add(attempt)
        db.session.flush()
    assignment.status = 'in_progress'
    db.session.commit()
    start = attempt.start_time or datetime.utcnow()
    end_epoch = int((start.replace(tzinfo=timezone.utc) + timedelta(minutes=exam.duration_minutes or 1)).timestamp())
    return render_template('exams_mcq_take.html', exam=exam, attempt=attempt, end_epoch=end_epoch)

@exams_bp.route('/<int:id>/mcq/submit', methods=['POST'])
@login_required
def mcq_submit(id):
    exam = Exam.query.get_or_404(id)
    if (exam.status or 'Active') == 'Archived' or not exam.is_published:
        return jsonify({'error': 'This exam is not accepting submissions.'}), 403
    student = Student.query.filter_by(email=current_user.email).first()
    if not student:
        return jsonify({'error': 'Not a student'}), 403
    attempt = McqAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='in_progress').first()
    if not attempt:
        return jsonify({'error': 'No active attempt'}), 400
    start = attempt.start_time or datetime.utcnow()
    deadline = start.replace(tzinfo=timezone.utc) + timedelta(minutes=exam.duration_minutes or 0)
    if datetime.utcnow().replace(tzinfo=timezone.utc) > deadline + timedelta(seconds=60):
        return jsonify({'error': 'Time expired. Your attempt has been closed.'}), 400
    data = request.get_json()
    today = date.today()
    if exam.available_from and today < exam.available_from:
        return jsonify({'error': 'This exam is not open yet.'}), 403
    if exam.available_until and today > exam.available_until:
        return jsonify({'error': 'This exam is closed.'}), 403
    assignment = ExamAssignment.query.filter_by(exam_id=exam.id, student_id=student.id).first()
    if not assignment or (assignment.due_date and today > assignment.due_date):
        return jsonify({'error': 'This exam assignment is no longer valid.'}), 403
    answers = data.get('answers', {}) if data else {}
    score = 0
    actual_questions = list(exam.mcq_questions)
    if not actual_questions:
        return jsonify({'error': 'This exam has no questions.'}), 409
    marks_per_q = exam.max_marks / len(actual_questions)
    for q in actual_questions:
        selected = answers.get(str(q.id))
        is_correct = selected and selected.upper() == q.correct_option
        if is_correct:
            score += marks_per_q
        db.session.add(McqAnswer(
            mcq_attempt_id=attempt.id, mcq_question_id=q.id,
            selected_option=selected.upper() if selected else None,
            is_correct=is_correct
        ))
    attempt.score = round(score, 1)
    attempt.total_marks = exam.max_marks
    attempt.end_time = datetime.utcnow()
    attempt.status = 'completed'
    attempt.calculate_grade()
    assignment = ExamAssignment.query.filter_by(exam_id=exam.id, student_id=student.id).first()
    if assignment:
        assignment.status = 'completed'
    # Unify scoring so manual reports / student performance PDFs include MCQ results.
    score_row = ExamScore.query.filter_by(exam_id=exam.id, student_id=student.id).first()
    if score_row:
        score_row.marks_obtained = attempt.score
        score_row.remarks = f'MCQ {attempt.grade} ({attempt.percentage}%)'
    else:
        db.session.add(ExamScore(
            exam_id=exam.id, student_id=student.id,
            marks_obtained=attempt.score, remarks=f'MCQ {attempt.grade} ({attempt.percentage}%)'))
    db.session.commit()
    return jsonify({
        'score': attempt.score,
        'total': attempt.total_marks,
        'percentage': attempt.percentage,
        'grade': attempt.grade
    })

@exams_bp.route('/<int:id>/mcq/results')
@login_required
def mcq_results(id):
    exam = Exam.query.get_or_404(id)
    _finalize_expired(exam)
    student = Student.query.filter_by(email=current_user.email).first()
    attempt = McqAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='completed').first() if student else None
    return render_template('exams_mcq_results.html', exam=exam, attempt=attempt)

@exams_bp.route('/<int:id>/mcq/analysis')
@login_required
@admin_required
def mcq_analysis(id):
    exam = Exam.query.get_or_404(id)
    _finalize_expired(exam)
    attempts = McqAttempt.query.filter_by(exam_id=exam.id, status='completed').order_by(McqAttempt.percentage.desc()).all()
    return render_template('exams_mcq_analysis.html', exam=exam, attempts=attempts)

@exams_bp.route('/<int:id>/mcq/question-stats')
@login_required
@admin_required
def mcq_question_stats(id):
    exam = Exam.query.get_or_404(id)
    _finalize_expired(exam)
    attempts = McqAttempt.query.filter_by(exam_id=exam.id, status='completed').all()
    total = len(attempts)
    stats = []
    for q in exam.mcq_questions:
        correct = 0
        option_counts = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'N/A': 0}
        for a in attempts:
            ans = McqAnswer.query.filter_by(mcq_attempt_id=a.id, mcq_question_id=q.id).first()
            if ans:
                if ans.selected_option in option_counts:
                    option_counts[ans.selected_option] += 1
                if ans.is_correct:
                    correct += 1
            else:
                option_counts['N/A'] += 1
        stats.append({
            'question': q,
            'correct': correct,
            'total': total,
            'pct': round(correct / total * 100, 1) if total else 0,
            'option_counts': option_counts
        })
    return render_template('exams_mcq_question_stats.html', exam=exam, stats=stats)

@exams_bp.route('/<int:id>/mcq/report/pdf')
@login_required
@admin_required
def mcq_report_pdf(id):
    exam = Exam.query.get_or_404(id)
    _finalize_expired(exam)
    attempts = McqAttempt.query.filter_by(exam_id=exam.id, status='completed').order_by(McqAttempt.percentage.desc()).all()
    pdf = FPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    def text_color(r, g, b):
        pdf.set_text_color(r, g, b)
    def set_font(style='', size=10):
        pdf.set_font('Helvetica', style, size)
    pdf.set_fill_color(10, 30, 46)
    pdf.rect(0, 0, 210, 45, 'F')
    set_font('B', 18)
    text_color(0, 212, 255)
    pdf.set_xy(15, 8)
    pdf.cell(0, 10, 'Guha Academy - Computer Institute', align='L')
    set_font('B', 14)
    text_color(255, 255, 255)
    pdf.set_xy(15, 22)
    pdf.cell(0, 8, f'MCQ Exam Report: {exam.title}', align='L')
    set_font('', 8)
    text_color(200, 200, 200)
    pdf.set_xy(15, 32)
    pdf.cell(0, 6, f'Course: {exam.course.name} ({exam.course.code})  |  Questions: {exam.num_questions}  |  Duration: {exam.duration_minutes} min  |  Total Marks: {exam.max_marks:.0f}', align='L')
    pdf.ln(10)
    passed = [a for a in attempts if a.grade not in ('F', 'N/A')]
    set_font('B', 10)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Summary', new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    set_font('', 9)
    text_color(60, 60, 60)
    avg_pct = sum(a.percentage for a in attempts) / len(attempts) if attempts else 0
    for label, val in [('Total Students', str(len(attempts))), ('Passed', str(len(passed))), ('Failed', str(len(attempts) - len(passed))), ('Pass %', f'{(len(passed)/len(attempts)*100):.1f}%' if attempts else 'N/A'), ('Average Score', f'{avg_pct:.1f}%')]:
        pdf.cell(45, 6, label)
        pdf.cell(30, 6, val, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    set_font('B', 10)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Grade Distribution', new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    set_font('', 9)
    for grade in ['A', 'B', 'C', 'D', 'F']:
        count = sum(1 for a in attempts if a.grade == grade)
        pdf.cell(30, 6, f'Grade {grade}')
        pdf.cell(20, 6, str(count), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    set_font('B', 10)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Rank List', new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    col_w = [10, 55, 25, 20, 20, 15, 40]
    headers = ['#', 'Student Name', 'Score', 'Total', '%', 'Grade', 'Duration']
    set_font('B', 8)
    pdf.set_fill_color(10, 30, 46)
    text_color(255, 255, 255)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, fill=True, align='C')
    pdf.ln()
    set_font('', 8)
    for rank, a in enumerate(attempts, 1):
        is_pass = a.grade not in ('F', 'N/A')
        pdf.set_fill_color(240, 250, 240) if is_pass else pdf.set_fill_color(255, 240, 240)
        text_color(30, 30, 30)
        dur = ''
        if a.start_time and a.end_time:
            diff = (a.end_time - a.start_time).total_seconds()
            dur = f'{int(diff//60)}m {int(diff%60)}s'
        for i, val in enumerate([str(rank), a.student.name, f'{a.score:.0f}', f'{a.total_marks:.0f}', f'{a.percentage:.1f}%', a.grade or '-', dur]):
            pdf.cell(col_w[i], 6, val, border=1, fill=True, align='C' if i != 1 else 'L')
        pdf.ln()
    pdf.ln(5)
    text_color(150, 150, 150)
    set_font('', 7)
    pdf.cell(0, 5, f'Generated on: {datetime.now().strftime("%d %b %Y %I:%M %p")}', align='C')
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
        download_name=f'mcq_report_{exam.course.code}_{exam.id}.pdf')

@exams_bp.route('/<int:id>/mcq/student-report/<int:student_id>/pdf')
@login_required
@admin_required
def mcq_student_report_pdf(id, student_id):
    exam = Exam.query.get_or_404(id)
    _finalize_expired(exam)
    student = Student.query.get_or_404(student_id)
    attempt = McqAttempt.query.filter_by(exam_id=exam.id, student_id=student.id, status='completed').first()
    if not attempt:
        flash('Student has not completed this exam.', 'warning')
        return redirect(url_for('exams.mcq_analysis', id=exam.id))
    pdf = FPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    def text_color(r, g, b):
        pdf.set_text_color(r, g, b)
    def set_font(style='', size=10):
        pdf.set_font('Helvetica', style, size)
    pdf.set_fill_color(10, 30, 46)
    pdf.rect(0, 0, 210, 45, 'F')
    set_font('B', 18)
    text_color(0, 212, 255)
    pdf.set_xy(15, 8)
    pdf.cell(0, 10, 'Guha Academy - Computer Institute', align='L')
    set_font('B', 14)
    text_color(255, 255, 255)
    pdf.set_xy(15, 22)
    pdf.cell(0, 8, 'MCQ Student Report', align='L')
    set_font('', 8)
    text_color(200, 200, 200)
    pdf.set_xy(15, 32)
    pdf.cell(0, 6, f'{student.name}  |  {student.email}  |  Exam: {exam.title}', align='L')
    pdf.ln(10)
    set_font('B', 11)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Score Summary', new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    set_font('', 9)
    text_color(60, 60, 60)
    for label, val in [('Score', f'{attempt.score:.0f} / {attempt.total_marks:.0f}'), ('Percentage', f'{attempt.percentage:.1f}%'), ('Grade', attempt.grade or '-'), ('Result', 'PASS' if attempt.grade not in ('F', 'N/A') else 'FAIL')]:
        pdf.cell(45, 6, label)
        pdf.cell(30, 6, val, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    set_font('B', 11)
    text_color(30, 60, 80)
    pdf.cell(0, 7, 'Answer Details', new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    answer_map = {a.mcq_question_id: a for a in attempt.answers}
    for q in exam.mcq_questions:
        ans = answer_map.get(q.id)
        selected = ans.selected_option if ans else '-'
        correct = q.correct_option
        status_mark = 'CORRECT' if (ans and ans.is_correct) else 'WRONG' if ans else 'NOT ANSWERED'
        set_font('B', 8)
        text_color(30, 30, 30)
        pdf.multi_cell(0, 5, f'Q{q.question_number}. {q.question_text}')
        set_font('', 8)
        text_color(80, 80, 80)
        pdf.cell(0, 4, f'  Your answer: {selected} ({status_mark})  |  Correct: {correct}', new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.ln(3)
    text_color(150, 150, 150)
    set_font('', 7)
    pdf.cell(0, 5, f'Generated on: {datetime.now().strftime("%d %b %Y %I:%M %p")}', align='C')
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
        download_name=f'mcq_{student.name.replace(" ","_")}_{exam.id}.pdf')


# ── Exam Assignment routes ──────────────────────────────────────────

@exams_bp.route('/<int:id>/mcq/assign', methods=['GET', 'POST'])
@login_required
@admin_required
def mcq_assign(id):
    exam = Exam.query.get_or_404(id)
    enrolled = Student.query.filter(Student.courses.any(id=exam.course_id)).order_by(Student.name).all()
    allowed_ids = {s.id for s in enrolled}
    if request.method == 'POST':
        student_ids = request.form.getlist('student_ids')
        posted = set()
        for sid in student_ids:
            try:
                posted.add(int(sid))
            except (ValueError, TypeError):
                continue
        posted &= allowed_ids
        due_raw = request.form.get('due_date', '').strip()
        due_date = None
        if due_raw:
            try:
                due_date = datetime.strptime(due_raw, '%Y-%m-%d').date()
            except ValueError:
                due_date = None
        before = {a.student_id for a in exam.assignments}
        added = 0
        removed = 0
        changed = 0
        for sid in allowed_ids:
            assignment = ExamAssignment.query.filter_by(exam_id=exam.id, student_id=sid).first()
            if sid in posted:
                if not assignment:
                    db.session.add(ExamAssignment(
                        exam_id=exam.id, student_id=sid,
                        assigned_by=current_user.id, due_date=due_date))
                    added += 1
                elif assignment.due_date != due_date:
                    assignment.due_date = due_date
                    changed += 1
            elif assignment:
                db.session.delete(assignment)
                removed += 1
        db.session.commit()
        msg = f'{added} added, {removed} removed'
        if changed:
            msg += f', {changed} updated'
        flash(f'Assignments: {msg}.', 'success')
        return redirect(url_for('exams.mcq_assign', id=exam.id))
    assigned_ids = {a.student_id for a in exam.assignments}
    return render_template('exams_mcq_assign.html', exam=exam, students=enrolled,
        assigned_ids=assigned_ids, today=date.today())


@exams_bp.route('/<int:id>/mcq/solutions')
@login_required
@admin_required
def mcq_solutions(id):
    exam = Exam.query.get_or_404(id)
    _finalize_expired(exam)
    attempts = McqAttempt.query.filter_by(exam_id=exam.id, status='completed').order_by(McqAttempt.percentage.desc()).all()
    return render_template('exams_mcq_solutions.html', exam=exam, attempts=attempts)
