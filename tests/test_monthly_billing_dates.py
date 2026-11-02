from datetime import date

from app.services.account_service import _billable_months, _item_current_due


def test_monthly_billing_starts_on_one_month_anniversary():
    start = date(2026, 10, 10)

    assert _billable_months(start, date(2026, 11, 9)) == 0
    assert _billable_months(start, date(2026, 11, 10)) == 1
    assert _billable_months(start, date(2026, 12, 10)) == 2


def test_monthly_billing_uses_each_enrollment_day():
    expected = {
        date(2026, 10, 3): date(2026, 11, 3),
        date(2026, 10, 10): date(2026, 11, 10),
        date(2026, 10, 11): date(2026, 11, 11),
        date(2026, 10, 24): date(2026, 11, 24),
    }

    for enrolled_on, first_due in expected.items():
        assert _billable_months(enrolled_on, first_due) == 1
        assert _billable_months(enrolled_on, date(
            first_due.year, first_due.month, first_due.day - 1)) == 0


def test_month_end_enrollment_is_clamped_to_target_month():
    assert _billable_months(date(2026, 1, 31), date(2026, 2, 27)) == 0
    assert _billable_months(date(2026, 1, 31), date(2026, 2, 28)) == 1


def test_fixed_billing_is_not_changed_by_monthly_rule():
    item = {'billing_mode': 'fixed', 'fee': 5000, 'enrolled_on': date(2026, 10, 10)}
    assert _item_current_due(item, date(2026, 10, 10)) == 5000


def test_monthly_due_amount_is_zero_before_first_anniversary():
    item = {
        'billing_mode': 'monthly',
        'monthly_fee': 1500,
        'enrolled_on': date(2026, 10, 24),
    }

    assert _item_current_due(item, date(2026, 11, 23)) == 0
    assert _item_current_due(item, date(2026, 11, 24)) == 1500

