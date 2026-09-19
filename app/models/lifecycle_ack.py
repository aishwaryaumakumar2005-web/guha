from datetime import datetime
from app.extensions import db


class LifecycleAck(db.Model):
    """Per-student "reviewed" marker for the lifecycle console.

    One row per student (there is only one current overall status): an admin
    works through the long-absent/inactive lists and taps "Mark reviewed",
    which records who and when. This is mutable current-state (upserted on
    re-review), so it lives here rather than in the append-only AuditLog.
    """
    __tablename__ = 'lifecycle_ack'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'),
                           unique=True, nullable=False)
    acknowledged_on = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_by = db.Column(db.String(100))
    note = db.Column(db.String(500))

    def __repr__(self):
        return f"<LifecycleAck student={self.student_id}>"