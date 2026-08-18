from datetime import datetime
from app.extensions import db


class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    max_marks = db.Column(db.Float, nullable=False)
    passing_marks = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    exam_type = db.Column(db.String(10), default='manual')
    num_questions = db.Column(db.Integer, default=0)
    duration_minutes = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', backref=db.backref('exams', lazy=True, cascade='all, delete-orphan'))
    scores = db.relationship('ExamScore', backref='exam', lazy=True, cascade='all, delete-orphan')
    mcq_questions = db.relationship('McqQuestion', backref='exam', lazy=True, cascade='all, delete-orphan')
    mcq_attempts = db.relationship('McqAttempt', backref='exam', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Exam {self.title} ({self.course.code})>"


class ExamScore(db.Model):
    __table_args__ = (
        db.UniqueConstraint('exam_id', 'student_id', name='uq_exam_student'),
        db.Index('idx_examscore_exam', 'exam_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False)
    marks_obtained = db.Column(db.Float, nullable=False)
    remarks = db.Column(db.String(200))

    student = db.relationship('Student', backref=db.backref('exam_scores', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<ExamScore {self.exam.title} - {self.student.name}: {self.marks_obtained}>"


class McqQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id', ondelete='CASCADE'), nullable=False)
    question_number = db.Column(db.Integer, nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(500), nullable=False)
    option_b = db.Column(db.String(500), nullable=False)
    option_c = db.Column(db.String(500), nullable=False)
    option_d = db.Column(db.String(500), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)

    answers = db.relationship('McqAnswer', backref='question', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<McqQuestion {self.question_number}: {self.question_text[:50]}>'


class McqAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    score = db.Column(db.Float, default=0)
    total_marks = db.Column(db.Float, default=0)
    percentage = db.Column(db.Float, default=0)
    grade = db.Column(db.String(2))
    status = db.Column(db.String(20), default='in_progress')

    student = db.relationship('Student', backref=db.backref('mcq_attempts', lazy=True, cascade='all, delete-orphan'))
    answers = db.relationship('McqAnswer', backref='attempt', lazy=True, cascade='all, delete-orphan')

    def calculate_grade(self):
        if self.total_marks <= 0:
            self.grade = 'N/A'
            return
        pct = (self.score / self.total_marks) * 100
        self.percentage = round(pct, 1)
        if pct >= 90:
            self.grade = 'A'
        elif pct >= 75:
            self.grade = 'B'
        elif pct >= 60:
            self.grade = 'C'
        elif pct >= 45:
            self.grade = 'D'
        else:
            self.grade = 'F'

    def __repr__(self):
        return f'<McqAttempt student={self.student_id} exam={self.exam_id} grade={self.grade}>'


class McqAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mcq_attempt_id = db.Column(db.Integer, db.ForeignKey('mcq_attempt.id', ondelete='CASCADE'), nullable=False)
    mcq_question_id = db.Column(db.Integer, db.ForeignKey('mcq_question.id', ondelete='CASCADE'), nullable=False)
    selected_option = db.Column(db.String(1))
    is_correct = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<McqAnswer Q{self.mcq_question_id}: {self.selected_option}>'


class ExamAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='assigned')

    exam = db.relationship('Exam', backref=db.backref('assignments', lazy=True, cascade='all, delete-orphan'))
    student = db.relationship('Student', backref=db.backref('exam_assignments', lazy=True, cascade='all, delete-orphan'))
    assigner = db.relationship('User', backref=db.backref('assigned_exams', lazy=True))

    def __repr__(self):
        return f'<ExamAssignment exam={self.exam_id} student={self.student_id} status={self.status}>'
