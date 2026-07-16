import json
from datetime import datetime
from app.extensions import db

class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    username = db.Column(db.String(50), nullable=True)
    action = db.Column(db.String(10), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    changes = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))

    def __repr__(self):
        return f'<AuditLog {self.action} {self.entity_type}#{self.entity_id}>'

    def changes_dict(self):
        if self.changes:
            try:
                return json.loads(self.changes)
            except (json.JSONDecodeError, TypeError):
                return {'raw': self.changes}
        return {}
