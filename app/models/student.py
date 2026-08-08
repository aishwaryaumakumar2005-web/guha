import uuid
from datetime import datetime
from sqlalchemy import event
from app.extensions import db
from app.helpers import next_code


student_courses = db.Table('student_courses',
    db.Column('student_id', db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), primary_key=True),
    db.Column('course_id', db.Integer, db.ForeignKey('course.id', ondelete='CASCADE'), primary_key=True),
    db.Column('status', db.String(20), default='Enrolled'),
    db.Column('enrolled_on', db.Date),
    db.Column('completed_on', db.Date),
    db.Column('drop_reason', db.String(200))
)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    roll_no = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    enrollment_date = db.Column(db.Date, default=lambda: datetime.utcnow().date())
    status = db.Column(db.String(20), default='Active')
    qr_code_uuid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    photo = db.Column(db.String(255))
    photo_data = db.Column(db.LargeBinary)
    photo_mime = db.Column(db.String(50))
    courses = db.relationship('Course', secondary=student_courses, backref=db.backref('students', lazy='dynamic'))
    fee_records = db.relationship('FeeRecord', backref='student', cascade="all, delete-orphan", lazy=True)

    def __repr__(self):
        return f"<Student {self.name}>"


@event.listens_for(Student, 'before_insert')
def _assign_roll_no(mapper, connection, target):
    if not target.roll_no:
        target.roll_no = next_code('STU', Student, 'roll_no')
