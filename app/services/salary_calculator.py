"""Shared, deterministic salary and commission calculations.

Both the preview screen and payroll draft generation use this service so that
the amount shown to an administrator is the amount eventually recorded.
"""
from decimal import Decimal, ROUND_HALF_UP


MONEY = Decimal("0.01")


def money(value):
    """Return a two-decimal Decimal without floating point drift."""
    try:
        return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (TypeError, ValueError):
        return Decimal("0.00")


def calculate_tutor_salary(tutor, start_date, end_date, percentage=None):
    """Calculate a tutor's salary for an arbitrary date window.

    The returned values remain floats for compatibility with existing models
    and templates, while all intermediate arithmetic is Decimal-based.
    """
    from app.helpers import (active_tutor_count_for_student, tutor_commission_percentage,
                             tutor_overlapping_fees, tutor_students)
    from app.models import TutorPayrollSettings

    settings = TutorPayrollSettings.query.filter_by(tutor_id=tutor.id).first()
    rate = money(percentage if percentage is not None else tutor_commission_percentage(tutor.id))
    rate = max(Decimal("0"), min(Decimal("100"), rate))
    base = money(settings.base_salary if settings else 0)
    bonus = money(settings.bonus if settings else 0)
    tds_pct = money(settings.tds_percentage if settings else 0)
    other_configured = money(settings.other_deductions if settings else 0)

    students = tutor_students(tutor.id)
    fee_records = tutor_overlapping_fees(tutor.id, start_date, end_date)
    fees_by_student = {}
    for record in fee_records:
        sid = record.student_id
        fees_by_student[sid] = fees_by_student.get(sid, Decimal("0")) + money(record.amount_paid)

    breakdown = []
    shared_students = []
    split_collected = Decimal("0")
    for student in students:
        fees = fees_by_student.get(student.id, Decimal("0"))
        tutor_count = active_tutor_count_for_student(student.id)
        if not tutor_count:
            continue
        effective = (fees / Decimal(tutor_count)).quantize(MONEY, rounding=ROUND_HALF_UP)
        split_collected += effective
        if tutor_count > 1:
            shared_students.append({'student': student, 'tutor_count': tutor_count})
        if fees > 0:
            breakdown.append({
                'student': student,
                'student_id': student.id,
                'roll_no': getattr(student, 'roll_no', None) or '',
                'fees': float(fees),
                'tutor_count': tutor_count,
                'effective': float(effective),
                'commission': float((effective * rate / Decimal('100')).quantize(MONEY, rounding=ROUND_HALF_UP)),
            })

    commission = (split_collected * rate / Decimal('100')).quantize(MONEY, rounding=ROUND_HALF_UP)
    gross = base + commission + bonus
    tds = (gross * tds_pct / Decimal('100')).quantize(MONEY, rounding=ROUND_HALF_UP) if tds_pct > 0 else Decimal('0.00')
    other = min(other_configured, max(Decimal('0.00'), gross - tds)) if gross > 0 else Decimal('0.00')
    net = max(Decimal('0.00'), gross - tds - other).quantize(MONEY, rounding=ROUND_HALF_UP)

    return {
        'base': float(base), 'commission': float(commission), 'commission_pct': float(rate),
        'bonus': float(bonus), 'tds': float(tds), 'tds_pct': float(tds_pct),
        'other_ded': float(other), 'net': float(net), 'gross': float(gross),
        'breakdown': breakdown, 'students': students, 'fee_records': fee_records,
        'total_collected': float(sum(fees_by_student.values(), Decimal('0'))),
        'split_collected': float(split_collected), 'shared_students': shared_students,
        'configured': settings is not None,
    }
