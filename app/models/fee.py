from datetime import date
from app.extensions import db


class FeeRecord(db.Model):
    __table_args__ = (
        db.Index('idx_fee_date', 'payment_date'),
        db.Index('idx_fee_student', 'student_id'),
        db.Index('idx_fee_company', 'company_id'),
        db.Index('idx_fee_payment_method', 'payment_method'),
    )
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id', ondelete='SET NULL'), nullable=True)
    receipt_number = db.Column(db.String(50), nullable=True)
    amount_paid = db.Column(db.Float, nullable=False)
    taxable_amount = db.Column(db.Float, default=0.0)
    gst_amount = db.Column(db.Float, default=0.0)
    payment_date = db.Column(db.Date, default=date.today, nullable=False)
    payment_method = db.Column(db.String(50), default='Cash')
    remarks = db.Column(db.String(200))
    # Concession / waiver granted on this receipt: counts as settled for dues
    # (balance = due - paid - concessions) but is NOT cash collected.
    concession = db.Column(db.Float, default=0.0)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    creator = db.relationship('User', backref='fee_records', lazy=True)

    def __repr__(self):
        return f"<FeeRecord Student:{self.student_id} Amount:{self.amount_paid}>"
