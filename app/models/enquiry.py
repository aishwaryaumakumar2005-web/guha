from datetime import datetime
from app.extensions import db


class Enquiry(db.Model):
    __table_args__ = (
        db.Index('idx_enquiry_status', 'status'),
        db.Index('idx_enquiry_course', 'course_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id', ondelete='CASCADE'), nullable=False)
    source = db.Column(db.String(50), default='Walk-in')
    status = db.Column(db.String(20), default='New')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Enquiry {self.student_name} for Course:{self.course_id}>"
