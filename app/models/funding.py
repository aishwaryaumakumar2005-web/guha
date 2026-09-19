from datetime import date, datetime
from app.extensions import db


class OwnerFunding(db.Model):
    __tablename__ = 'owner_funding'
    __table_args__ = (
        db.Index('idx_funding_method', 'method'),
        db.Index('idx_funding_date', 'funding_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    funding_date = db.Column(db.Date, default=date.today, nullable=False)
    method = db.Column(db.String(50), default='Cash', nullable=False)
    purpose = db.Column(db.Text)
    # F4/F5 (Batch 2): optional tracking reference (cheque/UTR/note) and the
    # nature of the injection — owner capital vs a director loan.
    reference = db.Column(db.String(100))
    investment_type = db.Column(db.String(20), default='Capital', nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref='owner_fundings', lazy=True)

    def __repr__(self):
        return f"<OwnerFunding ₹{self.amount} on {self.funding_date}>"
