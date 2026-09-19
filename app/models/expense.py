from datetime import date, datetime
from app.extensions import db


class ExpenseCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    # Enhancement: expected monthly spend cap. NULL = no budget tracked.
    budget_limit = db.Column(db.Float)
    # Enhancement: archived categories stay on history but disappear from
    # booking dropdowns.
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<ExpenseCategory {self.name}>"


class Expense(db.Model):
    __table_args__ = (
        db.Index('idx_expense_date', 'expense_date'),
        db.Index('idx_expense_category', 'category_id'),
        db.Index('idx_expense_payment_method', 'payment_method'),
        # W3: refund link — nullable FK; only refund Expenses need a student.
        db.Index('idx_expense_student', 'student_id'),
        # Enhancement: explicit billing-entity attribution for reports.
        db.Index('idx_expense_company', 'company_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('expense_category.id', ondelete='CASCADE'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=False)
    expense_date = db.Column(db.Date, default=date.today, nullable=False)
    payment_method = db.Column(db.String(50), default='Cash')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # W3: nullable link to the student whose dues a refund reduces. NULL for
    # non-refund expenses. ON DELETE SET NULL avoids orphan errors if a
    # student record is later purged.
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='SET NULL'))
    # Enhancement: optional explicit company (billing entity) attribution.
    # NULL means "infer from the payment account", as legacy reports do.
    company_id = db.Column(db.Integer, db.ForeignKey('company.id', ondelete='SET NULL'))
    # Enhancement: cheque no. / UTR / transaction reference for reconciliation.
    payment_ref = db.Column(db.String(100))
    # Enhancement: digital receipt (stored in DB, mirrors photo_data pattern).
    attachment_data = db.Column(db.LargeBinary)
    attachment_mime = db.Column(db.String(50))
    attachment_name = db.Column(db.String(255))

    category = db.relationship('ExpenseCategory', backref='expenses', lazy=True)
    creator = db.relationship('User', backref='expenses', lazy=True)
    student = db.relationship('Student', backref=db.backref('refunds', lazy='dynamic'))
    company = db.relationship('Company', backref='expenses', lazy=True)

    def __repr__(self):
        return f"<Expense {self.category.name} ₹{self.amount} on {self.expense_date}>"
