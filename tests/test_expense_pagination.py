from datetime import date

from app.extensions import db
from app.models import Expense, ExpenseCategory


def test_expenses_without_year_filter_include_historical_records(app, admin_client):
    with app.app_context():
        category = ExpenseCategory.query.first()
        db.session.add_all([
            Expense(category_id=category.id, amount=10, description='historical-march-expense',
                    expense_date=date(2025, 3, 15), payment_method='Cash'),
            Expense(category_id=category.id, amount=11, description='current-april-expense',
                    expense_date=date(2026, 4, 17), payment_method='Cash'),
        ])
        db.session.commit()
    response = admin_client.get('/expenses')
    assert response.status_code == 200
    assert b'historical-march-expense' in response.data
    assert b'current-april-expense' in response.data
