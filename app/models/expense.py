from datetime import date, datetime
from app.extensions import db


class ExpenseCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)

    def __repr__(self):
        return f"<ExpenseCategory {self.name}>"


class Expense(db.Model):
    __table_args__ = (
        db.Index('idx_expense_date', 'expense_date'),
        db.Index('idx_expense_category', 'category_id'),
        db.Index('idx_expense_payment_method', 'payment_method'),
        # W3: refund link — nullable FK; only refund Expenses need a student.
        db.Index('idx_expense_student', 'student_id'),
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

    category = db.relationship('ExpenseCategory', backref='expenses', lazy=True)
    creator = db.relationship('User', backref='expenses', lazy=True)
    student = db.relationship('Student', backref=db.backref('refunds', lazy='dynamic'))

    def __repr__(self):
        return f"<Expense {self.category.name} ₹{self.amount} on {self.expense_date}>"
