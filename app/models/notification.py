from datetime import datetime
from app.extensions import db


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id', ondelete='CASCADE'), nullable=True, index=True)
    message = db.Column(db.String(500), nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    user = db.relationship('User', backref=db.backref('notifications', cascade='all, delete-orphan'))
    task = db.relationship('Task', backref=db.backref('notifications', cascade='all, delete-orphan'))
