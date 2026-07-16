from datetime import datetime
from flask_login import UserMixin
from app.extensions import db


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Staff')
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    leave_requests = db.relationship('LeaveRequest', backref='staff', cascade="all, delete-orphan", lazy=True)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class LeaveRequest(db.Model):
    __table_args__ = (
        db.Index('idx_leave_user_status', 'user_id', 'status'),
        db.Index('idx_leave_status', 'status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<LeaveRequest Staff:{self.user_id} Status:{self.status}>"
