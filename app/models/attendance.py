from datetime import datetime
from app.extensions import db


class Attendance(db.Model):
    __table_args__ = (
        db.Index('idx_attendance_person_date', 'person_type', 'person_id', 'date'),
        db.Index('idx_attendance_date', 'date'),
    )
    id = db.Column(db.Integer, primary_key=True)
    person_type = db.Column(db.String(10), nullable=False)
    person_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow().date, nullable=False)
    status = db.Column(db.String(20), default='Present')
    marked_by = db.Column(db.String(10), default='manual')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Attendance {self.person_type} {self.person_id} - {self.date}: {self.status}>"
