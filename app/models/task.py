from datetime import datetime
from app.extensions import db


class Task(db.Model):
    __table_args__ = (
        db.Index('idx_task_tutor_status', 'tutor_id', 'status'),
        db.Index('idx_task_due_status', 'due_date', 'status'),
        db.Index('idx_task_priority', 'priority'),
    )
    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assigned_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='Pending')
    priority = db.Column(db.String(20), default='Medium')
    category = db.Column(db.String(50), default='General')
    completed_date = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Workflow and retention fields. Existing rows remain compatible.
    start_date = db.Column(db.Date)
    acknowledged_at = db.Column(db.DateTime)
    verified_at = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime)
    archived_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    blocked_reason = db.Column(db.Text)
    version = db.Column(db.Integer, default=1, nullable=False)

    tutor = db.relationship('Tutor', backref='tasks')
    assigner = db.relationship('User', backref='assigned_tasks')
    archiver = db.relationship('User', foreign_keys=[archived_by], backref='archived_tasks')

    def __repr__(self):
        return f"<Task {self.title} for {self.tutor_id}>"


class TaskHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    action = db.Column(db.String(40), nullable=False)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    task = db.relationship('Task', backref=db.backref('history', lazy='dynamic'))
    user = db.relationship('User', backref='task_history')
