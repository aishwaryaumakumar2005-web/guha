from datetime import datetime
from app.extensions import db


class FeeRecord(db.Model):
    __table_args__ = (
        db.Index('idx_fee_date', 'payment_date'),
        db.Index('idx_fee_student', 'student_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, default=datetime.utcnow().date, nullable=False)
    payment_method = db.Column(db.String(50), default='Cash')
    remarks = db.Column(db.String(200))

    def __repr__(self):
        return f"<FeeRecord Student:{self.student_id} Amount:{self.amount_paid}>"
