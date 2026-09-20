from datetime import datetime
from app.extensions import db


class GoogleSyncRow(db.Model):
    """Durable source-row ledger used for idempotent Google Sheet imports."""
    __tablename__ = 'google_sync_row'
    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.String(200), nullable=False, index=True)
    source_key = db.Column(db.String(255), nullable=False)
    source_hash = db.Column(db.String(64), nullable=False)
    enquiry_id = db.Column(db.Integer, db.ForeignKey('enquiry.id', ondelete='SET NULL'), nullable=True)
    batch_id = db.Column(db.String(64), nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='imported')
    error_message = db.Column(db.String(500), nullable=True)
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('sheet_id', 'source_key', name='uq_google_sync_sheet_source'),)
