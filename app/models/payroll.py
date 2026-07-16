from datetime import datetime
from app.extensions import db


class TutorPayrollSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id', ondelete='CASCADE'), nullable=False, unique=True)
    base_salary = db.Column(db.Float, default=0.0)
    commission_percentage = db.Column(db.Float, default=0.0)
    tds_percentage = db.Column(db.Float, default=10.0)
    bonus = db.Column(db.Float, default=0.0)
    other_deductions = db.Column(db.Float, default=0.0)
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(50))
    ifsc_code = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tutor = db.relationship('Tutor', backref=db.backref('payroll_settings', uselist=False))

    def __repr__(self):
        return f"<TutorPayrollSettings {self.tutor_id}>"


class PayrollRecord(db.Model):
    __table_args__ = (
        db.UniqueConstraint('tutor_id', 'month', 'year', name='uq_payroll_tutor_period'),
        db.Index('idx_payroll_period', 'month', 'year'),
        db.Index('idx_payroll_status', 'status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id', ondelete='CASCADE'), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    base_amount = db.Column(db.Float, default=0.0)
    commission_amount = db.Column(db.Float, default=0.0)
    bonus_amount = db.Column(db.Float, default=0.0)
    tds_amount = db.Column(db.Float, default=0.0)
    other_deductions = db.Column(db.Float, default=0.0)
    net_amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='Draft')
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'))
    paid_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tutor = db.relationship('Tutor', backref='payroll_records')
    expense = db.relationship('Expense', backref=db.backref('payroll_records', lazy=True))

    def __repr__(self):
        return f"<PayrollRecord {self.tutor_id} {self.month}/{self.year} ₹{self.net_amount}>"
