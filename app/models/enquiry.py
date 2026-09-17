from datetime import datetime
from app.extensions import db


class Enquiry(db.Model):
    __table_args__ = (
        db.Index('idx_enquiry_status', 'status'),
        db.Index('idx_enquiry_course', 'course_id'),
        db.Index('idx_enquiry_followup', 'follow_up_date'),
    )
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20), nullable=False)
    # Nullable + SET NULL: deleting a course detaches its leads instead of
    # destroying the lead history with it.
    course_id = db.Column(db.Integer, db.ForeignKey('course.id', ondelete='SET NULL'))
    source = db.Column(db.String(50), default='Walk-in')
    status = db.Column(db.String(20), default='New')
    notes = db.Column(db.Text)
    follow_up_date = db.Column(db.Date)
    # Last time an advisor actually touched this lead (edit/status/conversion).
    # Staleness is measured from here, falling back to created_at.
    last_contacted_at = db.Column(db.DateTime)
    converted_student_id = db.Column(
        db.Integer, db.ForeignKey('student.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    converted_student = db.relationship('Student', foreign_keys=[converted_student_id])

    def __repr__(self):
        return f"<Enquiry {self.student_name} for Course:{self.course_id}>"
