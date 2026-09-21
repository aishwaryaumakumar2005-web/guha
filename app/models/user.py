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

    leave_requests = db.relationship('LeaveRequest', backref='staff', foreign_keys='LeaveRequest.user_id', cascade="all, delete-orphan", lazy=True)
    approved_leave_requests = db.relationship('LeaveRequest', backref='approver', foreign_keys='LeaveRequest.approved_by', lazy=True)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = db.Column(db.String(128), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship('User', backref=db.backref('password_reset_tokens', cascade='all, delete-orphan'))

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > datetime.utcnow()


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
    leave_type = db.Column(db.String(20), nullable=True, default='Casual')
    status = db.Column(db.String(20), nullable=False, default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    actioned_at = db.Column(db.DateTime, nullable=True)
    remarks = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<LeaveRequest Staff:{self.user_id} Status:{self.status}>"
