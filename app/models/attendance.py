from datetime import datetime
from app.extensions import db


class Attendance(db.Model):
    __table_args__ = (
        db.Index('idx_attendance_person_date', 'person_type', 'person_id', 'date'),
        db.Index('idx_attendance_date', 'date'),
        db.UniqueConstraint('person_type', 'person_id', 'date', name='uq_attendance_person_date'),
    )
    id = db.Column(db.Integer, primary_key=True)
    person_type = db.Column(db.String(10), nullable=False)
    person_id = db.Column(db.Integer, nullable=False)
    # Local calendar date, matching how the whole app computes "today"
    # (lifecycle windows, streak math). UTC defaulting made marks recorded
    # just after midnight local land on the previous day, silently skewing
    # everything that counts sessions within a window.
    date = db.Column(db.Date, default=datetime.now().date, nullable=False)
    status = db.Column(db.String(20), default='Present')
    marked_by = db.Column(db.String(10), default='manual')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Attendance {self.person_type} {self.person_id} - {self.date}: {self.status}>"
