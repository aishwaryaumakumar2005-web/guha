from datetime import datetime
from app.extensions import db


class OwnerFunding(db.Model):
    __tablename__ = 'owner_funding'

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    funding_date = db.Column(db.Date, default=datetime.utcnow().date, nullable=False)
    method = db.Column(db.String(50), default='Cash', nullable=False)
    purpose = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref='owner_fundings', lazy=True)

    def __repr__(self):
        return f"<OwnerFunding ₹{self.amount} on {self.funding_date}>"
