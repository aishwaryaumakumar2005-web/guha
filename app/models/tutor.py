import uuid
from app.extensions import db


tutor_courses = db.Table('tutor_courses',
    db.Column('tutor_id', db.Integer, db.ForeignKey('tutor.id', ondelete='CASCADE'), primary_key=True),
    db.Column('course_id', db.Integer, db.ForeignKey('course.id', ondelete='CASCADE'), primary_key=True)
)


class Tutor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    specialization = db.Column(db.String(100))
    status = db.Column(db.String(20), default='Active')
    qr_code_uuid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))

    courses = db.relationship('Course', secondary=tutor_courses, backref=db.backref('tutors', lazy='dynamic'))

    def __repr__(self):
        return f"<Tutor {self.name}>"
