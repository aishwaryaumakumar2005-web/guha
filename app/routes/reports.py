from datetime import datetime, date, timedelta
from io import BytesIO
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, current_app, g, has_request_context
from flask_login import login_required, current_user
from app.extensions import db
from app.models import FeeRecord, Expense, ExpenseCategory, Course, Student, student_courses, Attendance, Tutor, OwnerFunding, Company, Account
from app.helpers import admin_required
from app.services.payment_methods import PAYMENT_METHODS, classify_method, METHOD_TYPE, METHOD_COLORS, ACCOUNT_TYPE_ICONS, method_icon
from sqlalchemy.orm import joinedload

reports_bp = Blueprint('reports', __name__)

def filter_by_company_methods(query, model_attr, company_id):
    """Filter Expense/FeeRecord/OwnerFunding queries by the owning company.

    Attribution is identical for income and expenses: a record's own company_id
    wins, and payment-method matching against the company's Account rows only
    pulls in UNATTRIBUTED records (company_id NULL) so a shared method like
    Cash is never double-counted across companies. If the company has no
    accounts at all, the record's company_id is the only signal. Account +
    distinct-payment-method lookups are cached on flask.g for the current
    request, since this helper is called many times per page load.
    """
    # All financial report paths pass through this helper. Keep the validity
    # rule here so HTML, PDF, Excel, and course/payment-method summaries never
    # accidentally include voided transactions.
    model = getattr(model_attr, 'class_', None)
    status = getattr(model, 'status', None)
    if status is not None:
        query = query.filter(status.notin_(['Voided', 'Cancelled', 'Reversed']))
    if not company_id:
        return query
    if has_request_context():
        cache = getattr(g, '_company_method_match', None)
        if cache is None:
            cache = g._company_method_match = {}
        if company_id not in cache:
            cache[company_id] = _company_method_match(company_id)
        matched = cache[company_id]
    else:
        matched = _company_method_match(company_id)
    direct = getattr(model_attr.class_, 'company_id', None)
    if matched is None:
        # The company has no configured accounts (or no records use a matching
        # method). Blind-filtering everything away silently hides its flows, so
        # fall back to the record's own company attribution when it exists.
        return query.filter(direct == company_id) if direct is not None else query.filter(False)
    if direct is not None:
        return query.filter(db.or_(
            direct == company_id,
            db.and_(direct.is_(None), db.func.coalesce(model_attr, '').in_(matched)),
        ))
    return query.filter(db.func.coalesce(model_attr, '').in_(matched))


def _company_has_accounts(company_id):
    """True if the company has at least one active Account (payment method) configured."""
    if not company_id:
        return False
    return db.session.query(Account.id).filter_by(company_id=company_id, is_active=True).first() is not None


def _company_method_match(company_id):
    """Return observed payment methods matching the company's accounts (or None if none)."""
    accounts = Account.query.filter_by(company_id=company_id, is_active=True).all()
    if not accounts:
        return None
    canonical_names = {acc.name for acc in accounts}  # e.g. {'Cash', 'Savings Account', ...}
    # Get all distinct payment methods actually used in the DB
    observed = set()
    for (m,) in db.session.query(FeeRecord.payment_method).distinct().all():
        if m: observed.add(m)
    for (m,) in db.session.query(Expense.payment_method).distinct().all():
        if m: observed.add(m)
    for (m,) in db.session.query(OwnerFunding.method).distinct().all():
        if m: observed.add(m)
    # Find which observed methods classify to one of this company's account names
    matched = [m for m in observed if classify_method(m) in canonical_names]
    return matched or None


def course_wise_income_summary(start_date, end_date, company_id=None):
    """Per-course income, prorated across each payment's *active* enrollments.

    A fee belongs to a student, not a course. To avoid counting a payment once
    per enrolled course, every payment is split equally across the student's
    enrollments that were active on the payment date (status + enrollment
    dates), with cent rounding (remainder goes to the last course) so per-course
    totals sum back exactly to the collected amount. If no enrollment is active
    on that date, the payment falls back to a split across all of the student's
    enrollments so totals still reconcile. Payments that cannot be attributed
    to any course are keyed as None and rendered as an "Unassigned" row.
    """
    fee_q = FeeRecord.query.filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date)
    fee_q = filter_by_company_methods(fee_q, FeeRecord.payment_method, company_id)
    fees = fee_q.options(joinedload(FeeRecord.student)).all()

    student_ids = sorted({f.student_id for f in fees})
    enroll_rows = db.session.query(
        student_courses.c.student_id,
        student_courses.c.course_id,
        student_courses.c.status,
        student_courses.c.enrolled_on,
        student_courses.c.completed_on,
    ).filter(student_courses.c.student_id.in_(student_ids)).all()
    enroll_by_student = {}
    for sid, cid, status, enrolled_on, completed_on in enroll_rows:
        enroll_by_student.setdefault(sid, []).append({
            'course_id': cid, 'status': status, 'enrolled_on': enrolled_on,
            'completed_on': completed_on,
        })

    def _active_courses(rows, pay_date):
        active = [r['course_id'] for r in rows
                  if r['status'] != 'Dropped'
                  and (r['enrolled_on'] is None or r['enrolled_on'] <= pay_date)
                  and not (r['status'] == 'Completed' and r['completed_on'] is not None and r['completed_on'] < pay_date)]
        return active or [r['course_id'] for r in rows]

    per_course_cents = {}
    for fee in fees:
        amount_cents = int(round(fee.amount_paid * 100))
        if not fee.student:
            per_course_cents[None] = per_course_cents.get(None, 0) + amount_cents
            continue
        courses = _active_courses(enroll_by_student.get(fee.student_id, []), fee.payment_date)
        if not courses:
            # No enrollment to attribute the payment to — surface it separately
            # (rendered as an "Unassigned" row) so per-course totals still add
            # up to the collected amount.
            per_course_cents[None] = per_course_cents.get(None, 0) + amount_cents
            continue
        n = len(courses)
        shares = [amount_cents // n] * n
        shares[-1] += amount_cents - sum(shares)
        for course, share in zip(courses, shares):
            per_course_cents[course] = per_course_cents.get(course, 0) + share
    return {course_id: cents / 100.0 for course_id, cents in per_course_cents.items()}


REPORT_TABS = ('income', 'fees', 'expense', 'overall', 'payment_methods')

# Daily Collections table paginates 25 rows/page; per-method detail caps at this many rows.
DAILY_PAGE_SIZE = 25
PM_DETAIL_LIMIT = 50
# PDF/Excel exports cap per-method detail rows at this many (most recent first).
PM_EXPORT_DETAIL_LIMIT = 200


def payment_method_period_breakdown(start_date, end_date, company_id=None,
                                    detail_limit=PM_DETAIL_LIMIT):
    """Aggregate fee payments by canonical method for a period (web/PDF/Excel).

    Totals/counts cover every payment in the period; detail rows ("records")
    are capped at detail_limit (most recent first) with "truncated" set so
    callers can disclose how many older rows were dropped.
    Returns (report, total); report[method] -> {total, gst_total, count, records, truncated}.
    """
    base_q = filter_by_company_methods(
        FeeRecord.query.filter(
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        ),
        FeeRecord.payment_method, company_id)

    report = {m: {'total': 0.0, 'gst_total': 0.0, 'count': 0, 'records': [], 'truncated': 0} for m in PAYMENT_METHODS}
    report['Others'] = {'total': 0.0, 'gst_total': 0.0, 'count': 0, 'records': [], 'truncated': 0}

    pm_counts = base_q.with_entities(
        FeeRecord.payment_method, db.func.count(FeeRecord.id),
        db.func.sum(FeeRecord.amount_paid), db.func.sum(FeeRecord.gst_amount)
    ).group_by(FeeRecord.payment_method).all()
    raw_methods_by_key = {}
    for raw, cnt, tot, gst in pm_counts:
        key = classify_method(raw)
        if key not in report:
            key = 'Others'
        d = report[key]
        d['total'] += float(tot or 0.0)
        d['gst_total'] += float(gst or 0.0)
        d['count'] += int(cnt or 0)
        raw_methods_by_key.setdefault(key, []).append(raw)

    for key, raw_methods in raw_methods_by_key.items():
        records = base_q.filter(FeeRecord.payment_method.in_(raw_methods)).options(
            joinedload(FeeRecord.student), joinedload(FeeRecord.company)
        ).order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).limit(detail_limit).all()
        report[key]['records'] = records
        report[key]['truncated'] = max(0, report[key]['count'] - len(records))

    return report, sum(d['total'] for d in report.values())


def _month_bounds(year, month):
    """First and last day of the given month (month clamped to 1..12)."""
    month = month if 1 <= month <= 12 else 1
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def resolve_date_range(today, filter_mode, filter_month, filter_year, start_date_str, end_date_str, quick=''):
    """Resolve the active period (quick chip / custom / yearly / monthly) into concrete start & end dates.

    Malformed custom dates fall back to the monthly range so bad query strings
    never raise; callers should still clamp month/year at parse time.
    """
    def _quick_range(key):
        if key == 'today':
            return today, today
        if key == 'this_week':
            return today - timedelta(days=today.weekday()), today
        if key == 'this_month':
            return date(today.year, today.month, 1), today
        if key == 'last_month':
            end = date(today.year, today.month, 1) - timedelta(days=1)
            return date(end.year, end.month, 1), end
        if key == 'this_quarter':
            q = (today.month - 1) // 3 + 1
            qs = (q - 1) * 3 + 1
            return date(today.year, qs, 1), today
        if key == 'ytd':
            return date(today.year, 1, 1), today
        if key == 'all':
            return date(2000, 1, 1), date(2100, 12, 31)
        return None

    range_note = None
    qrange = _quick_range(quick) if quick else None
    if qrange:
        start_date, end_date = qrange
        filter_mode = 'custom'
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
    elif filter_mode == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            filter_mode = 'monthly'
            start_date, end_date = _month_bounds(filter_year, filter_month)
            start_date_str = end_date_str = None
            range_note = 'The custom dates were invalid, so the current month is shown instead.'
        else:
            if start_date > end_date:
                start_date, end_date = end_date, start_date
                start_date_str = start_date.strftime('%Y-%m-%d')
                end_date_str = end_date.strftime('%Y-%m-%d')
                range_note = 'The start date was after the end date, so the range was swapped.'
    elif filter_mode == 'yearly':
        start_date = date(filter_year, 1, 1)
        end_date = date(filter_year, 12, 31)
    else:
        # Monthly range; the filter dropdown offers Monthly/Yearly/Custom only.
        start_date, end_date = _month_bounds(filter_year, filter_month)
    return start_date, end_date, filter_mode, start_date_str, end_date_str, range_note


@reports_bp.route('/reports')
@login_required
def reports():
    # Staff: show simplified reports for their courses
    if current_user.role == 'Staff':
        tutor = Tutor.query.filter_by(email=current_user.email).first()
        if not tutor:
            return render_template('reports.html', tab='staff', today=date.today(), is_staff=True,
                staff_data={'students': [], 'courses': [], 'attendance_rate': 0, 'total_collected': 0, 'recent_fees': []})
        
        course_ids = [c.id for c in tutor.courses]
        student_subquery = db.session.query(student_courses.c.student_id).filter(
            student_courses.c.course_id.in_(course_ids)
        ).distinct()
        students = Student.query.filter(Student.id.in_(student_subquery)).all()
        
        # Get attendance data for staff's students
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)
        attendance_records = Attendance.query.filter(
            Attendance.person_type == 'student',
            Attendance.person_id.in_([s.id for s in students]),
            Attendance.date >= thirty_days_ago
        ).all()
        
        # Calculate attendance rates
        total_records = len(attendance_records)
        present_records = sum(1 for r in attendance_records if r.status == 'Present')
        attendance_rate = (present_records / total_records * 100) if total_records > 0 else 0
        
        # Get fee data for staff's students — same 30-day window as attendance
        # so every metric on the card sheet shares one scope.
        fee_records = FeeRecord.query.filter(
            FeeRecord.student_id.in_([s.id for s in students]),
            FeeRecord.payment_date >= thirty_days_ago,
            FeeRecord.status != 'Voided'
        ).order_by(FeeRecord.payment_date.desc()).limit(50).all()

        total_collected = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
            FeeRecord.student_id.in_([s.id for s in students]),
            FeeRecord.payment_date >= thirty_days_ago,
            FeeRecord.status != 'Voided'
        ).scalar() or 0.0
        
        return render_template('reports.html', 
            tab='staff', 
            today=today,
            is_staff=True,
            staff_data={
                'students': students,
                'courses': tutor.courses,
                'attendance_rate': round(attendance_rate, 1),
                'total_collected': total_collected,
                'recent_fees': fee_records[:20]
            })

    today = date.today()
    tab = request.args.get('tab', 'income')
    if tab not in REPORT_TABS:
        tab = 'income'
    filter_mode = request.args.get('filter_mode', 'monthly')
    if filter_mode not in ('monthly', 'yearly', 'custom'):
        filter_mode = 'monthly'
    filter_month = request.args.get('month', type=int) or today.month
    if not 1 <= filter_month <= 12:
        filter_month = today.month
    filter_year = request.args.get('year', type=int) or today.year
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    quick = request.args.get('quick', '').strip().lower()
    selected_company_id = request.args.get('company_id', type=int)

    companies = Company.query.filter_by(is_active=True).all()
    selected_company_name = next(
        (c.name for c in companies if c.id == selected_company_id), ''
    ) if selected_company_id else ''

    start_date, end_date, filter_mode, start_date_str, end_date_str, range_note = resolve_date_range(
        today, filter_mode, filter_month, filter_year, start_date_str, end_date_str, quick)

    months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    
    # Query builder helper for FeeRecord with the shared company filtering
    # (direct company tag first, unattributed method match second)
    fee_q = filter_by_company_methods(FeeRecord.query, FeeRecord.payment_method, selected_company_id)

    # ---- Safe defaults for inactive tabs (hidden panes still need renderable values) ----
    total_income = 0.0
    tax_monthly, gst_monthly = [], []
    fees_monthly, course_wise_income, daily_collections = [], [], []
    daily_page, daily_pages, daily_total_count = 1, 1, 0
    daily_total_amount = daily_total_gst = 0.0
    monthly_expense, category_wise_expense, expense_by_type, expense_by_account = [], [], [], []
    funding_monthly, pl_monthly = [], []
    company_pl = []
    payment_labels, payment_data, payment_colors = [], [], []
    payment_methods_report = {}
    total_collected_period = 0.0
    total_income_filtered = total_taxable_filtered = total_gst_filtered = 0.0
    total_expense_filtered = total_funding_filtered = 0.0
    net_balance = 0.0
    prev_income = prev_taxable = prev_gst = 0.0
    prev_expense = prev_funding = 0.0
    prev_label = 'last month'
    no_income_data = no_fees_data = no_expense_data = no_overall_data = no_payment_data = True
    insights = {}

    # ---- KPI totals + previous-period trends (shared by Income and Overall tabs) ----
    if tab in ('income', 'overall'):
        tot_inc_query = db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        )
        tot_gst_query = db.session.query(db.func.sum(FeeRecord.gst_amount)).filter(
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        )
        tot_tax_query = db.session.query(db.func.sum(FeeRecord.taxable_amount)).filter(
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        )
        tot_inc_query = filter_by_company_methods(tot_inc_query, FeeRecord.payment_method, selected_company_id)
        tot_gst_query = filter_by_company_methods(tot_gst_query, FeeRecord.payment_method, selected_company_id)
        tot_tax_query = filter_by_company_methods(tot_tax_query, FeeRecord.payment_method, selected_company_id)

        total_income_filtered = tot_inc_query.scalar() or 0.0
        total_gst_filtered = tot_gst_query.scalar() or 0.0
        total_taxable_filtered = tot_tax_query.scalar() or 0.0

        total_expense_query = db.session.query(db.func.sum(Expense.amount)).filter(
            Expense.expense_date >= start_date, Expense.expense_date <= end_date
        )
        total_expense_query = filter_by_company_methods(total_expense_query, Expense.payment_method, selected_company_id)
        total_expense_filtered = total_expense_query.scalar() or 0.0

        total_funding_query = db.session.query(db.func.sum(OwnerFunding.amount)).filter(
            OwnerFunding.funding_date >= start_date, OwnerFunding.funding_date <= end_date
        )
        total_funding_query = filter_by_company_methods(total_funding_query, OwnerFunding.method, selected_company_id)
        total_funding_filtered = total_funding_query.scalar() or 0.0

        net_balance = float(total_income_filtered) + float(total_funding_filtered) - float(total_expense_filtered)

        span_days = (end_date - start_date).days + 1
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span_days - 1)

        prev_tot_query = db.session.query(
            db.func.sum(FeeRecord.amount_paid).label('income'),
            db.func.sum(FeeRecord.taxable_amount).label('tax'),
            db.func.sum(FeeRecord.gst_amount).label('gst'),
        ).filter(FeeRecord.payment_date >= prev_start, FeeRecord.payment_date <= prev_end)
        prev_tot_query = filter_by_company_methods(prev_tot_query, FeeRecord.payment_method, selected_company_id)
        prev_tot = prev_tot_query.one_or_none()
        prev_income = float(prev_tot.income or 0) if prev_tot else 0.0
        prev_taxable = float(prev_tot.tax or 0) if prev_tot else 0.0
        prev_gst = float(prev_tot.gst or 0) if prev_tot else 0.0

        prev_expense_query = db.session.query(db.func.sum(Expense.amount)).filter(
            Expense.expense_date >= prev_start, Expense.expense_date <= prev_end)
        prev_expense_query = filter_by_company_methods(prev_expense_query, Expense.payment_method, selected_company_id)
        prev_expense = float(prev_expense_query.scalar() or 0.0)

        prev_funding_query = db.session.query(db.func.sum(OwnerFunding.amount)).filter(
            OwnerFunding.funding_date >= prev_start, OwnerFunding.funding_date <= prev_end)
        prev_funding_query = filter_by_company_methods(prev_funding_query, OwnerFunding.method, selected_company_id)
        prev_funding = float(prev_funding_query.scalar() or 0.0)

        prev_span = (
            f"{prev_start.strftime('%d %b')} – {prev_end.strftime('%d %b %Y')}"
            if prev_start.year == prev_end.year
            else f"{prev_start.strftime('%d %b %Y')} – {prev_end.strftime('%d %b %Y')}"
        )
        if filter_mode == 'yearly':
            prev_label = f'last year ({prev_start.strftime("%Y")})'
        elif filter_mode == 'custom':
            prev_label = f'previous period ({prev_span})'
        else:
            prev_label = f'last month ({prev_span})'

    # ---- Income tab: all-time card, monthly Taxable+GST split ----
    if tab == 'income':
        ta_query = db.session.query(db.func.sum(FeeRecord.amount_paid))
        ta_query = filter_by_company_methods(ta_query, FeeRecord.payment_method, selected_company_id)
        total_income = ta_query.scalar() or 0.0

        fee_breakdown_query = db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'),
            db.func.sum(FeeRecord.taxable_amount).label('tax'),
            db.func.sum(FeeRecord.gst_amount).label('gst')
        ).filter(db.extract('year', FeeRecord.payment_date) == filter_year)
        fee_breakdown_query = filter_by_company_methods(fee_breakdown_query, FeeRecord.payment_method, selected_company_id)
        fee_breakdown_rows = fee_breakdown_query.group_by(db.extract('month', FeeRecord.payment_date)).all()
        tax_map, gst_map = {}, {}
        for r in fee_breakdown_rows:
            tax_map[int(r.m)] = float(r.tax or 0)
            gst_map[int(r.m)] = float(r.gst or 0)
        tax_monthly = [tax_map.get(m, 0.0) for m in range(1, 13)]
        gst_monthly = [gst_map.get(m, 0.0) for m in range(1, 13)]
        no_income_data = sum(tax_monthly) + sum(gst_monthly) <= 0

    # ---- Expense tab: monthly expense, categories, account type & source account ----
    if tab == 'expense':
        expense_categories = ExpenseCategory.query.all()
        exp_monthly_query = db.session.query(
            db.extract('month', Expense.expense_date).label('m'),
            db.func.sum(Expense.amount).label('total')
        ).filter(db.extract('year', Expense.expense_date) == filter_year)
        exp_monthly_query = filter_by_company_methods(exp_monthly_query, Expense.payment_method, selected_company_id)
        exp_monthly_rows = exp_monthly_query.group_by(db.extract('month', Expense.expense_date)).all()
        exp_monthly_map = {int(r.m): float(r.total) for r in exp_monthly_rows}
        monthly_expense = [{"month": months_names[m-1], "total": exp_monthly_map.get(m, 0.0)} for m in range(1, 13)]
        no_expense_data = sum(m['total'] for m in monthly_expense) <= 0

        cat_exp_query = db.session.query(
            Expense.category_id, db.func.count(Expense.id).label('cnt'), db.func.sum(Expense.amount).label('total')
        ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        cat_exp_query = filter_by_company_methods(cat_exp_query, Expense.payment_method, selected_company_id)
        cat_exp_rows = cat_exp_query.group_by(Expense.category_id).all()
        cat_exp_map = {r.category_id: {'total': float(r.total), 'count': r.cnt} for r in cat_exp_rows}
        category_wise_expense = []
        expense_cat_map = {cat.id: cat for cat in expense_categories}
        for cat in expense_categories:
            d = cat_exp_map.get(cat.id, {'total': 0.0, 'count': 0})
            if d['total'] > 0:
                category_wise_expense.append({"name": cat.name, "total": d['total'], "count": d['count']})

        # Expense grouped by the source account (canonical payment method) and by
        # account type so the report answers "which account" and "what type".
        acct_exp_query = db.session.query(
            Expense.payment_method, db.func.count(Expense.id).label('cnt'), db.func.sum(Expense.amount).label('total')
        ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        acct_exp_query = filter_by_company_methods(acct_exp_query, Expense.payment_method, selected_company_id)
        acct_exp_rows = acct_exp_query.group_by(Expense.payment_method).all()
        account_map = {}
        type_map = {}
        for method, cnt, total in acct_exp_rows:
            canonical = classify_method(method)
            amt = float(total)
            a = account_map.setdefault(canonical, {'total': 0.0, 'count': 0})
            a['total'] += amt
            a['count'] += cnt
            atype = METHOD_TYPE.get(canonical, 'Other')
            t = type_map.setdefault(atype, {'total': 0.0, 'count': 0})
            t['total'] += amt
            t['count'] += cnt
        type_order = ['Cash', 'UPI', 'Bank', 'Card', 'Other']
        expense_by_type = [
            {'type': k, 'total': type_map[k]['total'], 'count': type_map[k]['count'],
             'color': METHOD_COLORS.get(k, '#FFC107'), 'icon': ACCOUNT_TYPE_ICONS.get(k, 'wallet-fill')}
            for k in type_order if k in type_map
        ] + [
            {'type': k, 'total': v['total'], 'count': v['count'],
             'color': METHOD_COLORS.get(k, '#FFC107'), 'icon': ACCOUNT_TYPE_ICONS.get(k, 'wallet-fill')}
            for k, v in type_map.items() if k not in type_order
        ]
        account_order = list(PAYMENT_METHODS) + ['Others']
        expense_by_account = [
            {'account': k, 'total': account_map[k]['total'], 'count': account_map[k]['count'],
             'color': METHOD_COLORS.get(k, '#FFC107'), 'icon': method_icon(k)}
            for k in account_order if k in account_map
        ] + [
            {'account': k, 'total': v['total'], 'count': v['count'],
             'color': METHOD_COLORS.get(k, '#FFC107'), 'icon': method_icon(k)}
            for k, v in account_map.items() if k not in account_order
        ]

    # ---- Fees tab: monthly collections, course-wise income, daily collections ----
    if tab == 'fees':
        fee_monthly_query = db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'),
            db.func.sum(FeeRecord.amount_paid).label('total')
        ).filter(db.extract('year', FeeRecord.payment_date) == filter_year)
        fee_monthly_query = filter_by_company_methods(fee_monthly_query, FeeRecord.payment_method, selected_company_id)
        fee_monthly_rows = fee_monthly_query.group_by(db.extract('month', FeeRecord.payment_date)).all()
        fee_monthly_map = {int(r.m): float(r.total) for r in fee_monthly_rows}
        fees_monthly = [{"month": months_names[m-1], "total": fee_monthly_map.get(m, 0.0)} for m in range(1, 13)]
        no_fees_data = sum(m['total'] for m in fees_monthly) <= 0

        course_fee_map = course_wise_income_summary(start_date, end_date, selected_company_id)
        course_wise_income = []
        for course in Course.query.all():
            total = course_fee_map.get(course.id, 0.0)
            if total > 0:
                course_wise_income.append({"name": course.name, "code": course.code, "total": total})
        unassigned_total = course_fee_map.get(None, 0.0)
        if unassigned_total > 0:
            course_wise_income.append({"name": "Unassigned", "code": "-", "total": unassigned_total})

        daily_query = fee_q.filter(
            FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
        )
        daily_total_count = daily_query.count()
        daily_agg = daily_query.with_entities(
            db.func.sum(FeeRecord.amount_paid), db.func.sum(FeeRecord.gst_amount)
        ).one()
        daily_total_amount = float(daily_agg[0] or 0.0)
        daily_total_gst = float(daily_agg[1] or 0.0)
        daily_per_page = DAILY_PAGE_SIZE
        daily_pages = max(1, (daily_total_count + daily_per_page - 1) // daily_per_page)
        try:
            daily_page = int(request.args.get('page', 1))
        except (TypeError, ValueError):
            daily_page = 1
        daily_page = min(max(daily_page, 1), daily_pages)
        daily_collections = daily_query.options(
            joinedload(FeeRecord.student), joinedload(FeeRecord.company)
        ).order_by(
            FeeRecord.payment_date.desc(), FeeRecord.id.desc()
        ).offset((daily_page - 1) * daily_per_page).limit(daily_per_page).all()

# ---- Overall tab: monthly P&L + funding series ----
    elif tab == 'overall':
        fee_monthly_query = db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'),
            db.func.sum(FeeRecord.amount_paid).label('total')
        ).filter(db.extract('year', FeeRecord.payment_date) == filter_year)
        fee_monthly_query = filter_by_company_methods(fee_monthly_query, FeeRecord.payment_method, selected_company_id)
        fee_monthly_rows = fee_monthly_query.group_by(db.extract('month', FeeRecord.payment_date)).all()
        fee_monthly_map = {int(r.m): float(r.total) for r in fee_monthly_rows}

        exp_monthly_query = db.session.query(
            db.extract('month', Expense.expense_date).label('m'),
            db.func.sum(Expense.amount).label('total')
        ).filter(db.extract('year', Expense.expense_date) == filter_year)
        exp_monthly_query = filter_by_company_methods(exp_monthly_query, Expense.payment_method, selected_company_id)
        exp_monthly_rows = exp_monthly_query.group_by(db.extract('month', Expense.expense_date)).all()
        exp_monthly_map = {int(r.m): float(r.total) for r in exp_monthly_rows}

        funding_monthly_query = db.session.query(
            db.extract('month', OwnerFunding.funding_date).label('m'),
            db.func.sum(OwnerFunding.amount).label('total')
        ).filter(db.extract('year', OwnerFunding.funding_date) == filter_year)
        funding_monthly_query = filter_by_company_methods(funding_monthly_query, OwnerFunding.method, selected_company_id)
        funding_monthly_rows = funding_monthly_query.group_by(db.extract('month', OwnerFunding.funding_date)).all()
        funding_monthly_map = {int(r.m): float(r.total) for r in funding_monthly_rows}

        pl_monthly = []
        for m in range(1, 13):
            inc = fee_monthly_map.get(m, 0.0)
            exp = exp_monthly_map.get(m, 0.0)
            fund = funding_monthly_map.get(m, 0.0)
            pl_monthly.append({"month": months_names[m-1], "income": inc, "expense": exp, "funding": fund, "net": inc + fund - exp})
        funding_monthly = [funding_monthly_map.get(m, 0.0) for m in range(1, 13)]
        no_overall_data = not pl_monthly or all(not (p['income'] or p['funding'] or p['expense']) for p in pl_monthly)

    # ---- Per-company income & tax breakdown (Income and Overall tabs) ----
    if tab in ('income', 'overall'):
        company_pl = []
        comp_inc_query = db.session.query(
            FeeRecord.company_id,
            db.func.sum(FeeRecord.amount_paid).label('inc'),
            db.func.sum(FeeRecord.taxable_amount).label('tax'),
            db.func.sum(FeeRecord.gst_amount).label('gst')
        ).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date)
        comp_inc_query = filter_by_company_methods(comp_inc_query, FeeRecord.payment_method, selected_company_id)
        comp_inc_rows = comp_inc_query.group_by(FeeRecord.company_id).all()
        comp_inc_map = {r.company_id: {'inc': float(r.inc or 0), 'tax': float(r.tax or 0), 'gst': float(r.gst or 0)} for r in comp_inc_rows}
        for c in companies:
            if selected_company_id and c.id != selected_company_id:
                continue
            cdata = comp_inc_map.get(c.id, {'inc': 0.0, 'tax': 0.0, 'gst': 0.0})
            company_pl.append({
                'company': c,
                'income': cdata['inc'],
                'taxable': cdata['tax'],
                'gst': cdata['gst'],
            })

    # ---- Payment methods tab: distribution chart + per-method report ----
    if tab == 'payment_methods':
        pm_base = filter_by_company_methods(
            FeeRecord.query.filter(
                FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
            ),
            FeeRecord.payment_method, selected_company_id)

        payment_methods = pm_base.with_entities(
            FeeRecord.payment_method, db.func.sum(FeeRecord.amount_paid)
        ).group_by(FeeRecord.payment_method).all()
        payment_labels = [p[0] for p in payment_methods]
        payment_data = [float(p[1]) for p in payment_methods]
        payment_colors = [METHOD_COLORS.get(classify_method(p[0]), '#FFC107') for p in payment_methods]

        payment_methods_report, total_collected_period = payment_method_period_breakdown(
            start_date, end_date, selected_company_id, detail_limit=PM_DETAIL_LIMIT
        )

        no_payment_data = total_collected_period <= 0

    # ---- Smart insight callouts (per tab) ----
    insights = {}

    income_month_totals = [(tax_monthly[m] if m < len(tax_monthly) else 0.0) + (gst_monthly[m] if m < len(gst_monthly) else 0.0) for m in range(12)]
    data_months = [i for i, v in enumerate(income_month_totals) if v > 0]
    if data_months:
        best_i = max(data_months, key=lambda i: income_month_totals[i])
        year_inc = sum(income_month_totals)
        pct = (income_month_totals[best_i] / year_inc * 100) if year_inc > 0 else 0
        income_ins = [{'icon': 'bi-trophy', 'text': f'Best month: {months_names[best_i]} — ₹{income_month_totals[best_i]:,.2f} ({pct:.0f}% of {filter_year} income)'}]
        if len(data_months) > 1:
            worst_i = min(data_months, key=lambda i: income_month_totals[i])
            if worst_i != best_i:
                income_ins.append({'icon': 'bi-graph-down-arrow', 'text': f'Quietest month: {months_names[worst_i]} — ₹{income_month_totals[worst_i]:,.2f}'})
            jumps = []
            prev = None
            for i in data_months:
                if prev is not None:
                    diff = income_month_totals[i] - income_month_totals[prev]
                    if diff > 0:
                        jumps.append((prev, i, diff))
                prev = i
            if jumps:
                p, i, diff = max(jumps, key=lambda g: g[2])
                gr_pct = (diff / income_month_totals[p] * 100) if income_month_totals[p] else 0
                income_ins.append({'icon': 'bi-arrow-up-right', 'text': f'Biggest month-on-month jump: {months_names[p]} → {months_names[i]} (+₹{diff:,.2f}, {gr_pct:.0f}%)'})
        insights['income'] = income_ins
    if filter_year == today.year and (today.month - 1) not in data_months:
        insights.setdefault('income', []).append({'icon': 'bi-exclamation-triangle', 'text': f'No income recorded yet this month ({today.strftime("%b")})'})

    fee_month_totals = [m['total'] for m in fees_monthly]
    fee_data_months = [i for i, v in enumerate(fee_month_totals) if v > 0]
    fees_ins = []
    if fee_data_months:
        best_fi = max(fee_data_months, key=lambda i: fee_month_totals[i])
        fees_ins.append({'icon': 'bi-trophy', 'text': f'Top collection month: {months_names[best_fi]} — ₹{fee_month_totals[best_fi]:,.2f}'})
    if course_wise_income:
        top_course = max(course_wise_income, key=lambda c: c['total'])
        fees_ins.append({'icon': 'bi-mortarboard', 'text': f'Top course: {top_course["name"]} — ₹{top_course["total"]:,.2f}'})
    if filter_year == today.year and (today.month - 1) not in fee_data_months:
        fees_ins.append({'icon': 'bi-exclamation-triangle', 'text': f'No fees collected yet this month ({today.strftime("%b")})'})
    insights['fees'] = fees_ins

    exp_month_totals = [m['total'] for m in monthly_expense]
    exp_data_months = [i for i, v in enumerate(exp_month_totals) if v > 0]
    exp_ins = []
    if category_wise_expense:
        top_cat = max(category_wise_expense, key=lambda c: c['total'])
        exp_ins.append({'icon': 'bi-receipt-cutoff', 'text': f'Biggest spend category: {top_cat["name"]} — ₹{top_cat["total"]:,.2f} ({top_cat["count"]} entries)'})
    if exp_data_months:
        best_ei = max(exp_data_months, key=lambda i: exp_month_totals[i])
        exp_ins.append({'icon': 'bi-fire', 'text': f'Highest spend month: {months_names[best_ei]} — ₹{exp_month_totals[best_ei]:,.2f}'})
    insights['expense'] = exp_ins

    pl_active = [p for p in pl_monthly if p['income'] or p['funding'] or p['expense']]
    overall_ins = []
    if pl_active:
        best_p = max(pl_active, key=lambda p: p['net'])
        if best_p['net'] > 0:
            overall_ins.append({'icon': 'bi-graph-up-arrow', 'text': f'Most profitable month: {best_p["month"]} — +₹{best_p["net"]:,.2f}'})
        worst_p = min(pl_active, key=lambda p: p['net'])
        overall_ins.append({'icon': 'bi-flag', 'text': f'Weakest month: {worst_p["month"]} — ₹{worst_p["net"]:,.2f}'})
    if net_balance < 0 and total_expense_filtered > total_income_filtered + total_funding_filtered:
        overall_ins.append({'icon': 'bi-lightbulb', 'text': f'Expenses (₹{total_expense_filtered:,.2f}) exceed income + capital for the period — review cost drivers.'})
    insights['overall'] = overall_ins

    pm_ins = []
    if payment_methods_report:
        top_pm = max(payment_methods_report.items(), key=lambda kv: kv[1]['total'])
        if top_pm[1]['total'] > 0:
            pm_ins.append({'icon': 'bi-credit-card', 'text': f'Most-used method: {top_pm[0]} — ₹{top_pm[1]["total"]:,.2f} ({top_pm[1]["count"]} payments)'})
    insights['payment'] = pm_ins

    return render_template('reports.html', tab=tab, today=today, filter_mode=filter_mode,
        filter_month=filter_month, filter_year=filter_year,
        start_date_str=start_date_str or start_date.strftime('%Y-%m-%d'),
        end_date_str=end_date_str or end_date.strftime('%Y-%m-%d'),
        active_quick=quick, companies=companies, selected_company_id=selected_company_id,
        selected_company_name=selected_company_name,
        range_note=range_note,
        daily_page=daily_page, daily_pages=daily_pages, daily_total_count=daily_total_count,
        daily_total_amount=float(daily_total_amount), daily_total_gst=float(daily_total_gst),
        total_income=float(total_income),
        tax_monthly=tax_monthly, gst_monthly=gst_monthly,
        fees_monthly=fees_monthly, course_wise_income=course_wise_income, daily_collections=daily_collections,
        payment_labels=payment_labels, payment_data=payment_data, payment_colors=payment_colors,
        monthly_expense=monthly_expense, category_wise_expense=category_wise_expense,
        expense_by_type=expense_by_type, expense_by_account=expense_by_account,
        total_income_filtered=float(total_income_filtered), total_expense_filtered=float(total_expense_filtered),
        total_gst_filtered=float(total_gst_filtered), total_taxable_filtered=float(total_taxable_filtered),
        total_funding_filtered=float(total_funding_filtered), funding_monthly=funding_monthly,
        net_balance=net_balance, pl_monthly=pl_monthly, company_pl=company_pl,
        payment_methods_report=payment_methods_report, total_collected_period=float(total_collected_period),
        insights=insights,
        no_income_data=no_income_data, no_fees_data=no_fees_data, no_expense_data=no_expense_data,
        no_overall_data=no_overall_data, no_payment_data=no_payment_data,
        selected_company_has_accounts=_company_has_accounts(selected_company_id),
        prev_income=prev_income, prev_taxable=prev_taxable, prev_gst=prev_gst,
        prev_expense=prev_expense, prev_funding=prev_funding, prev_label=prev_label)

@reports_bp.route('/reports/pdf')
@login_required
@admin_required
def report_pdf():
    from fpdf import FPDF
    today = date.today()
    tab = request.args.get('tab', 'income')
    if tab not in REPORT_TABS:
        tab = 'income'
    filter_mode = request.args.get('filter_mode', 'monthly')
    if filter_mode not in ('monthly', 'yearly', 'custom'):
        filter_mode = 'monthly'
    filter_month = request.args.get('month', type=int) or today.month
    if not 1 <= filter_month <= 12:
        filter_month = today.month
    filter_year = request.args.get('year', type=int) or today.year
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    quick = request.args.get('quick', '').strip().lower()
    selected_company_id = request.args.get('company_id', type=int)

    company_obj = Company.query.get(selected_company_id) if selected_company_id else None

    start_date, end_date, filter_mode, start_date_str, end_date_str, _range_note = resolve_date_range(
        today, filter_mode, filter_month, filter_year, start_date_str, end_date_str, quick)

    period_label = f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}"
    company_label = f"  |  Company: {company_obj.name}" if company_obj else "  |  Company: All"

    class ReportPDF(FPDF):
        def header(self):
            self.set_font('DejaVu', 'B', 16)
            self.set_text_color(47, 72, 88)
            self.cell(0, 10, 'Guha Academy - Computer Institute', align='C', new_x="LMARGIN", new_y="NEXT")
            self.set_font('DejaVu', '', 9)
            self.set_text_color(100, 100, 100)
            titles = {'income': 'Income Report', 'fees': 'Student Fees Report', 'expense': 'Expense Report', 'overall': 'Overall Report', 'payment_methods': 'Payment Methods Report'}
            self.cell(0, 6, f'{titles.get(tab, "Report")}  |  Period: {period_label}{company_label}', align='C', new_x="LMARGIN", new_y="NEXT")
            self.ln(4)
            self.set_draw_color(217, 93, 57)
            self.set_line_width(0.5)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(6)

        def footer(self):
            self.set_y(-15)
            self.set_font('DejaVu', 'I', 7)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, f'Generated: {today.strftime("%d %b %Y %I:%M %p")}  |  Page {self.page_no()}/{{nb}}', align='C')

        def section_title(self, title):
            self.set_font('DejaVu', 'B', 12)
            self.set_text_color(47, 72, 88)
            self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

        def kpi_box(self, label, value, color=(107, 142, 35)):
            self.set_font('DejaVu', 'B', 12)
            self.set_text_color(*color)
            self.cell(60, 7, value, align='C')
            self.set_font('DejaVu', '', 7)
            self.set_text_color(100, 100, 100)
            self.cell(0, 7, label, align='C', new_x="LMARGIN", new_y="NEXT")
            self.ln(1)

        def table_header(self, cols, widths):
            self.set_font('DejaVu', 'B', 8)
            self.set_fill_color(47, 72, 88)
            self.set_text_color(255, 255, 255)
            for i, col in enumerate(cols):
                self.cell(widths[i], 6, col, border=1, align='C', fill=True)
            self.ln()

        def table_row(self, cols, widths, aligns=None):
            self.set_font('DejaVu', '', 8)
            self.set_text_color(50, 50, 50)
            for i, col in enumerate(cols):
                a = aligns[i] if aligns else 'C'
                self.cell(widths[i], 5, str(col), border=1, align=a)
            self.ln()

    pdf = ReportPDF()
    font_dir = current_app.root_path + '/static/fonts'
    pdf.add_font('DejaVu', '', font_dir + '/DejaVuSans.ttf')
    pdf.add_font('DejaVu', 'B', font_dir + '/DejaVuSans-Bold.ttf')
    pdf.add_font('DejaVu', 'I', font_dir + '/DejaVuSans-Oblique.ttf')
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    if tab == 'income':
        tot_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.amount_paid)), FeeRecord.payment_method, selected_company_id)
        gst_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.gst_amount)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        tax_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.taxable_amount)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        
        total_income = tot_q.scalar() or 0.0
        gst_tot = gst_q.scalar() or 0.0
        tax_tot = tax_q.scalar() or 0.0

        inc_q = filter_by_company_methods(db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')
        ).filter(db.extract('year', FeeRecord.payment_date) == filter_year), FeeRecord.payment_method, selected_company_id)
        income_rows = inc_q.group_by(db.extract('month', FeeRecord.payment_date)).all()
        income_map = {int(r.m): float(r.total) for r in income_rows}
        income_monthly = [income_map.get(m, 0.0) for m in range(1, 13)]
        
        pdf.section_title('Income Summary')
        pdf.kpi_box('Total Income (All Time)', f'₹{total_income:,.2f}', (107, 142, 35))
        pdf.kpi_box(f'Period Taxable Income', f'₹{tax_tot:,.2f}', (47, 72, 88))
        pdf.kpi_box(f'Period GST Collected', f'₹{gst_tot:,.2f}', (70, 130, 180))
        pdf.ln(4)
        pdf.section_title(f'Monthly Income - {filter_year}')
        pdf.table_header(['Month', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], [20] + [14]*12)
        pdf.table_row(['Income (₹)'] + [f'{v:,.2f}' for v in income_monthly], [20] + [14]*12, ['L'] + ['R']*12)

    elif tab == 'fees':
        fees_q = filter_by_company_methods(db.session.query(
            db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')
        ).filter(db.extract('year', FeeRecord.payment_date) == filter_year), FeeRecord.payment_method, selected_company_id)
        fees_rows = fees_q.group_by(db.extract('month', FeeRecord.payment_date)).all()
        fees_map = {int(r.m): float(r.total) for r in fees_rows}
        fees_monthly = [fees_map.get(m, 0.0) for m in range(1, 13)]
        months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        pdf.section_title('Monthly Fees Collection')
        pdf.table_header(['Month'] + months_names, [20] + [14]*12)
        pdf.table_row(['Amount (₹)'] + [f'{v:,.2f}' for v in fees_monthly], [20] + [14]*12, ['L'] + ['R']*12)
        pdf.ln(3)

        course_fee_map = course_wise_income_summary(start_date, end_date, selected_company_id)
        course_wise = [(course.name, course_fee_map.get(course.id, 0.0)) for course in Course.query.all() if course_fee_map.get(course.id, 0.0) > 0]
        unassigned_total = course_fee_map.get(None, 0.0)
        if unassigned_total > 0:
            course_wise.append(('Unassigned', unassigned_total))
        if course_wise:
            pdf.section_title('Course-wise Income')
            pdf.table_header(['Course', 'Amount (₹)'], [140, 50])
            for name, total in course_wise:
                pdf.table_row([name, f'{total:,.2f}'], [140, 50], ['L', 'R'])
        pdf.ln(3)

        daily_q = filter_by_company_methods(
            FeeRecord.query.filter(
                FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
            ),
            FeeRecord.payment_method, selected_company_id)
        daily = daily_q.order_by(FeeRecord.payment_date.desc()).all()
        if daily:
            pdf.section_title('Daily Collections (with Company & GST)')
            pdf.table_header(['Date', 'Student', 'Company', 'Total', 'GST', 'Method'], [24, 40, 48, 25, 20, 33])
            for r in daily:
                c_name = (r.company.name if r.company else 'Unassigned')[:24]
                pdf.table_row([r.payment_date.strftime('%d %b %Y'), r.student.name[:18], c_name, f'{r.amount_paid:,.2f}', f'{r.gst_amount:,.2f}', r.payment_method], [24, 40, 48, 25, 20, 33], ['L', 'L', 'L', 'R', 'R', 'C'])

    elif tab == 'expense':
        expense_cats = ExpenseCategory.query.all()
        months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        exp_q = db.session.query(
            db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')
        ).filter(db.extract('year', Expense.expense_date) == filter_year)
        exp_q = filter_by_company_methods(exp_q, Expense.payment_method, selected_company_id)
        exp_rows = exp_q.group_by(db.extract('month', Expense.expense_date)).all()
        exp_map = {int(r.m): float(r.total) for r in exp_rows}
        monthly_exp = [exp_map.get(m, 0.0) for m in range(1, 13)]
        pdf.section_title('Monthly Expense')
        pdf.table_header(['Month'] + months_names, [20] + [14]*12)
        pdf.table_row(['Amount (₹)'] + [f'{v:,.2f}' for v in monthly_exp], [20] + [14]*12, ['L'] + ['R']*12)
        pdf.ln(3)
        cat_exp_q = db.session.query(
            Expense.category_id, db.func.sum(Expense.amount).label('total')
        ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        cat_exp_q = filter_by_company_methods(cat_exp_q, Expense.payment_method, selected_company_id)
        cat_exp_rows = cat_exp_q.group_by(Expense.category_id).all()
        cat_exp_map = {r.category_id: float(r.total) for r in cat_exp_rows}
        cat_wise = [(cat.name, cat_exp_map.get(cat.id, 0.0)) for cat in expense_cats if cat_exp_map.get(cat.id, 0.0) > 0]
        if cat_wise:
            pdf.section_title('Category-wise Expense')
            pdf.table_header(['Category', 'Amount (₹)'], [140, 50])
            for name, total in cat_wise:
                pdf.table_row([name, f'{total:,.2f}'], [140, 50], ['L', 'R'])
        pdf.ln(3)
        pdf.section_title(f'Expense Summary - {period_label}')
        pdf.table_header(['Category', 'Count', 'Total (₹)'], [100, 30, 60])
        summary_q = db.session.query(
            Expense.category_id, db.func.count(Expense.id).label('cnt'), db.func.sum(Expense.amount).label('total')
        ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        summary_q = filter_by_company_methods(summary_q, Expense.payment_method, selected_company_id)
        summary_rows = summary_q.group_by(Expense.category_id).all()
        summary_map = {r.category_id: {'total': float(r.total), 'count': r.cnt} for r in summary_rows}
        for cat in expense_cats:
            s = summary_map.get(cat.id, {'total': 0.0, 'count': 0})
            pdf.table_row([cat.name, str(s['count']), f'{s["total"]:,.2f}'], [100, 30, 60], ['L', 'C', 'R'])
        pdf.ln(3)

        acct_exp_q = db.session.query(
            Expense.payment_method, db.func.count(Expense.id).label('cnt'), db.func.sum(Expense.amount).label('total')
        ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        acct_exp_q = filter_by_company_methods(acct_exp_q, Expense.payment_method, selected_company_id)
        acct_exp_rows = acct_exp_q.group_by(Expense.payment_method).all()
        type_map = {}
        account_map = {}
        for method, cnt, total in acct_exp_rows:
            canonical = classify_method(method)
            amt = float(total)
            d_a = account_map.setdefault(canonical, {'total': 0.0, 'count': 0})
            d_a['total'] += amt
            d_a['count'] += cnt
            atype = METHOD_TYPE.get(canonical, 'Other')
            d_t = type_map.setdefault(atype, {'total': 0.0, 'count': 0})
            d_t['total'] += amt
            d_t['count'] += cnt
        type_order = ['Cash', 'UPI', 'Bank', 'Card', 'Other']
        pdf.section_title('Expense by Account Type')
        pdf.table_header(['Account Type', 'Count', 'Total (₹)'], [110, 30, 50])
        for k in type_order:
            if k in type_map:
                d = type_map[k]
                pdf.table_row([k, str(d['count']), f"{d['total']:,.2f}"], [110, 30, 50], ['L', 'C', 'R'])
        for k, d in type_map.items():
            if k not in type_order:
                pdf.table_row([k, str(d['count']), f"{d['total']:,.2f}"], [110, 30, 50], ['L', 'C', 'R'])
        pdf.ln(3)
        pdf.section_title('Expense by Source Account')
        pdf.table_header(['Account', 'Count', 'Total (₹)'], [110, 30, 50])
        account_order = list(PAYMENT_METHODS) + ['Others']
        for k in account_order:
            if k in account_map:
                d = account_map[k]
                pdf.table_row([k, str(d['count']), f"{d['total']:,.2f}"], [110, 30, 50], ['L', 'C', 'R'])
        for k, d in account_map.items():
            if k not in account_order:
                pdf.table_row([k, str(d['count']), f"{d['total']:,.2f}"], [110, 30, 50], ['L', 'C', 'R'])
        pdf.ln(3)

    elif tab == 'overall':
        inc_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        gst_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.gst_amount)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        
        total_income = inc_q.scalar() or 0.0
        total_gst = gst_q.scalar() or 0.0
        
        total_exp_q = db.session.query(db.func.sum(Expense.amount)).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        total_exp_q = filter_by_company_methods(total_exp_q, Expense.payment_method, selected_company_id)
        total_expense = total_exp_q.scalar() or 0.0
        
        total_fund_q = db.session.query(db.func.sum(OwnerFunding.amount)).filter(OwnerFunding.funding_date >= start_date, OwnerFunding.funding_date <= end_date)
        total_fund_q = filter_by_company_methods(total_fund_q, OwnerFunding.method, selected_company_id)
        total_funding = total_fund_q.scalar() or 0.0
        
        net = float(total_income) + float(total_funding) - float(total_expense)
        
        pdf.section_title('Profit & Loss Summary')
        pdf.kpi_box('Total Income', f'₹{float(total_income):,.2f}', (107, 142, 35))
        pdf.kpi_box('GST Collected', f'₹{float(total_gst):,.2f}', (70, 130, 180))
        pdf.kpi_box('Total Expense', f'₹{float(total_expense):,.2f}', (192, 57, 43))
        pdf.ln(3)
        pdf.kpi_box('Net Balance', f"{'+' if net >= 0 else ''}₹{net:,.2f}", (47, 72, 88) if net >= 0 else (192, 57, 43))
        pdf.ln(4)

        months_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        pdf.section_title(f'Monthly P&L - {filter_year}')
        pdf.table_header(['Month', 'Income', 'Funding', 'Expense', 'Net', 'Status'], [30, 40, 40, 40, 40, 30])
        inc_m_q = filter_by_company_methods(db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year), FeeRecord.payment_method, selected_company_id)
        inc_rows = inc_m_q.group_by(db.extract('month', FeeRecord.payment_date)).all()
        inc_map = {int(r.m): float(r.total) for r in inc_rows}
        
        exp_m_q = db.session.query(db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')).filter(db.extract('year', Expense.expense_date) == filter_year)
        exp_m_q = filter_by_company_methods(exp_m_q, Expense.payment_method, selected_company_id)
        exp_rows_ov = exp_m_q.group_by(db.extract('month', Expense.expense_date)).all()
        exp_map_ov = {int(r.m): float(r.total) for r in exp_rows_ov}
        
        fund_m_q = db.session.query(db.extract('month', OwnerFunding.funding_date).label('m'), db.func.sum(OwnerFunding.amount).label('total')).filter(db.extract('year', OwnerFunding.funding_date) == filter_year)
        fund_m_q = filter_by_company_methods(fund_m_q, OwnerFunding.method, selected_company_id)
        fund_rows_ov = fund_m_q.group_by(db.extract('month', OwnerFunding.funding_date)).all()
        fund_map_ov = {int(r.m): float(r.total) for r in fund_rows_ov}
        for m in range(1, 13):
            inc = inc_map.get(m, 0.0)
            exp = exp_map_ov.get(m, 0.0)
            fund = fund_map_ov.get(m, 0.0)
            n = inc + fund - exp
            status = 'Profit' if n > 0 else ('Loss' if n < 0 else 'Breakeven')
            pdf.table_row([months_names[m-1], f'{inc:,.2f}', f'{fund:,.2f}', f'{exp:,.2f}', f"{'+' if n >= 0 else ''}{n:,.2f}", status], [30, 40, 40, 40, 40, 30], ['C', 'R', 'R', 'R', 'R', 'C'])

    elif tab == 'payment_methods':
        report_pm, total_period = payment_method_period_breakdown(
            start_date, end_date, selected_company_id, detail_limit=PM_EXPORT_DETAIL_LIMIT)
        pdf.section_title('Payment Methods Report')
        pdf.kpi_box('Total Collected', f'₹{total_period:,.2f}', (47, 72, 88))
        pdf.ln(4)
        for label in PAYMENT_METHODS + ['Others']:
            d = report_pm.get(label)
            if not d or not d['records']:
                continue
            pdf.section_title(f'{label} - ₹{d["total"]:,.2f}')
            if d['truncated']:
                pdf.set_font('DejaVu', 'I', 7)
                pdf.set_text_color(150, 150, 150)
                pdf.cell(0, 5, f'Showing most recent {len(d["records"])} of {d["count"]} payments', new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)
            pdf.table_header(['Date', 'Student', 'Amount', 'Remarks'], [30, 55, 35, 70])
            for r in d['records']:
                pdf.table_row([r.payment_date.strftime('%d %b %Y'), r.student.name[:20], f'{r.amount_paid:,.2f}', (r.remarks or '')[:30]], [30, 55, 35, 70], ['L', 'L', 'R', 'L'])
            pdf.ln(2)

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    filenames = {'income': 'Income_Report', 'fees': 'Student_Fees_Report', 'expense': 'Expense_Report', 'overall': 'Overall_Report', 'payment_methods': 'Payment_Methods_Report'}
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'{filenames.get(tab, "Report")}_{filter_year}_{filter_month}.pdf')

@reports_bp.route('/reports/excel')
@login_required
@admin_required
def report_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    today = date.today()
    tab = request.args.get('tab', 'income')
    if tab not in REPORT_TABS:
        tab = 'income'
    filter_mode = request.args.get('filter_mode', 'monthly')
    if filter_mode not in ('monthly', 'yearly', 'custom'):
        filter_mode = 'monthly'
    filter_month = request.args.get('month', type=int) or today.month
    if not 1 <= filter_month <= 12:
        filter_month = today.month
    filter_year = request.args.get('year', type=int) or today.year
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    quick = request.args.get('quick', '').strip().lower()
    selected_company_id = request.args.get('company_id', type=int)

    start_date, end_date, filter_mode, start_date_str, end_date_str, _range_note = resolve_date_range(
        today, filter_mode, filter_month, filter_year, start_date_str, end_date_str, quick)

    wb = Workbook()
    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='2F4858', end_color='2F4858', fill_type='solid')
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

    def write_sheet(ws, title, headers, rows):
        ws.title = title
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center')
            c.border = thin_border
        for r, row in enumerate(rows, 2):
            for col, val in enumerate(row, 1):
                c = ws.cell(row=r, column=col, value=val)
                c.border = thin_border
                c.alignment = Alignment(horizontal='right' if isinstance(val, (int, float)) else 'left')
        for col in ws.columns:
            max_len = max((len(str(c.value or '')) for c in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 40)

    if tab == 'income':
        inc_q = filter_by_company_methods(db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year), FeeRecord.payment_method, selected_company_id)
        tot_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.amount_paid)), FeeRecord.payment_method, selected_company_id)
        gst_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.gst_amount)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        tax_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.taxable_amount)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        
        inc_rows = inc_q.group_by(db.extract('month', FeeRecord.payment_date)).all()
        inc_map = {int(r.m): float(r.total) for r in inc_rows}
        income_monthly = [inc_map.get(m, 0.0) for m in range(1, 13)]
        total_all_time = tot_q.scalar() or 0
        gst_period = gst_q.scalar() or 0
        tax_period = tax_q.scalar() or 0

        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        if filter_year < today.year:
            elapsed_months = 12
        elif filter_year > today.year:
            elapsed_months = 1
        else:
            elapsed_months = max(1, min(12, today.month))
        ws = wb.active
        write_sheet(ws, 'Monthly Income', ['Month'] + months, [['Income (₹)'] + income_monthly])
        ws2 = wb.create_sheet('Summary')
        write_sheet(ws2, 'Summary', ['Metric', 'Value'], [
            ['Total Income (All Time)', total_all_time],
            [f'Period Taxable Income', tax_period],
            [f'Period GST Collected', gst_period],
            [f'Total ({filter_year})', sum(income_monthly)],
            [f'Months elapsed in {filter_year}', elapsed_months],
            [f'Monthly Avg ({filter_year})', sum(income_monthly) / elapsed_months]
        ])

    elif tab == 'fees':
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        fees_q = filter_by_company_methods(db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year), FeeRecord.payment_method, selected_company_id)
        fees_rows = fees_q.group_by(db.extract('month', FeeRecord.payment_date)).all()
        fees_map = {int(r.m): float(r.total) for r in fees_rows}
        fees_monthly = [fees_map.get(m, 0.0) for m in range(1, 13)]
        ws = wb.active
        write_sheet(ws, 'Monthly Fees', ['Month'] + months, [['Collection (₹)'] + fees_monthly])
        
        rows = []
        course_fee_map = course_wise_income_summary(start_date, end_date, selected_company_id)
        for course in Course.query.all():
            total = course_fee_map.get(course.id, 0.0)
            if total > 0:
                rows.append([course.name, course.code, total])
        unassigned_total = course_fee_map.get(None, 0.0)
        if unassigned_total > 0:
            rows.append(['Unassigned', '-', unassigned_total])
        if rows:
            ws2 = wb.create_sheet('Course-wise')
            write_sheet(ws2, 'Course-wise', ['Course', 'Code', 'Collected (₹)'], rows)

        daily_q = filter_by_company_methods(FeeRecord.query.filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        daily = daily_q.order_by(FeeRecord.payment_date.desc()).all()
        if daily:
            ws3 = wb.create_sheet('Daily Collections')
            write_sheet(ws3, 'Daily Collections', ['Date', 'Student', 'Company', 'Taxable (₹)', 'GST (₹)', 'Total Paid (₹)', 'Method', 'Remarks'], [
                [r.payment_date.strftime('%d-%b-%Y'), r.student.name, r.company.name if r.company else 'Unassigned', r.taxable_amount, r.gst_amount, r.amount_paid, r.payment_method, r.remarks or ''] for r in daily
            ])

    elif tab == 'expense':
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        exp_q = db.session.query(db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')).filter(db.extract('year', Expense.expense_date) == filter_year)
        exp_q = filter_by_company_methods(exp_q, Expense.payment_method, selected_company_id)
        exp_rows = exp_q.group_by(db.extract('month', Expense.expense_date)).all()
        exp_map = {int(r.m): float(r.total) for r in exp_rows}
        monthly_exp = [exp_map.get(m, 0.0) for m in range(1, 13)]
        ws = wb.active
        write_sheet(ws, 'Monthly Expense', ['Month'] + months, [['Expense (₹)'] + monthly_exp])
        rows = []
        cat_exp_q = db.session.query(Expense.category_id, db.func.sum(Expense.amount).label('total')).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        cat_exp_q = filter_by_company_methods(cat_exp_q, Expense.payment_method, selected_company_id)
        cat_exp_rows = cat_exp_q.group_by(Expense.category_id).all()
        cat_exp_map = {r.category_id: float(r.total) for r in cat_exp_rows}
        for cat in ExpenseCategory.query.all():
            total = cat_exp_map.get(cat.id, 0.0)
            rows.append([cat.name, total])
        ws2 = wb.create_sheet('Category-wise')
        write_sheet(ws2, 'Category-wise', ['Category', 'Total (₹)'], rows)
        recent_q = Expense.query.filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        recent_q = filter_by_company_methods(recent_q, Expense.payment_method, selected_company_id)
        recent = recent_q.order_by(Expense.expense_date.desc()).limit(50).all()
        if recent:
            ws3 = wb.create_sheet('Recent Expenses')
            write_sheet(ws3, 'Recent Expenses', ['Date', 'Category', 'Description', 'Amount'], [[r.expense_date.strftime('%d-%b-%Y'), r.category.name, r.description[:60], r.amount] for r in recent])

        acct_exp_q = db.session.query(
            Expense.payment_method, db.func.count(Expense.id).label('cnt'), db.func.sum(Expense.amount).label('total')
        ).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        acct_exp_q = filter_by_company_methods(acct_exp_q, Expense.payment_method, selected_company_id)
        acct_exp_rows = acct_exp_q.group_by(Expense.payment_method).all()
        type_map = {}
        account_map = {}
        for method, cnt, total in acct_exp_rows:
            canonical = classify_method(method)
            amt = float(total)
            d_a = account_map.setdefault(canonical, {'total': 0.0, 'count': 0})
            d_a['total'] += amt
            d_a['count'] += cnt
            atype = METHOD_TYPE.get(canonical, 'Other')
            d_t = type_map.setdefault(atype, {'total': 0.0, 'count': 0})
            d_t['total'] += amt
            d_t['count'] += cnt
        type_order = ['Cash', 'UPI', 'Bank', 'Card', 'Other']
        type_rows = []
        for k in type_order:
            if k in type_map:
                d = type_map[k]
                type_rows.append([k, d['count'], round(d['total'], 2)])
        for k, d in type_map.items():
            if k not in type_order:
                type_rows.append([k, d['count'], round(d['total'], 2)])
        if type_rows:
            ws4 = wb.create_sheet('By Account Type')
            write_sheet(ws4, 'By Account Type', ['Account Type', 'Count', 'Total (₹)'], type_rows)
        account_order = list(PAYMENT_METHODS) + ['Others']
        account_rows = []
        for k in account_order:
            if k in account_map:
                d = account_map[k]
                account_rows.append([k, d['count'], round(d['total'], 2)])
        for k, d in account_map.items():
            if k not in account_order:
                account_rows.append([k, d['count'], round(d['total'], 2)])
        if account_rows:
            ws5 = wb.create_sheet('By Source Account')
            write_sheet(ws5, 'By Source Account', ['Account', 'Count', 'Total (₹)'], account_rows)

    elif tab == 'overall':
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        ws = wb.active
        tot_inc_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.amount_paid)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)
        gst_q = filter_by_company_methods(db.session.query(db.func.sum(FeeRecord.gst_amount)).filter(FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date), FeeRecord.payment_method, selected_company_id)

        total_inc = tot_inc_q.scalar() or 0.0
        total_gst = gst_q.scalar() or 0.0
        
        total_exp_q = db.session.query(db.func.sum(Expense.amount)).filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
        total_exp_q = filter_by_company_methods(total_exp_q, Expense.payment_method, selected_company_id)
        total_exp = total_exp_q.scalar() or 0.0
        
        total_fund_q = db.session.query(db.func.sum(OwnerFunding.amount)).filter(OwnerFunding.funding_date >= start_date, OwnerFunding.funding_date <= end_date)
        total_fund_q = filter_by_company_methods(total_fund_q, OwnerFunding.method, selected_company_id)
        total_fund = total_fund_q.scalar() or 0.0
        
        write_sheet(ws, 'P&L Summary', ['Metric', 'Value'], [
            ['Total Income', float(total_inc)],
            ['GST Collected', float(total_gst)],
            ['Capital Injection', float(total_fund)],
            ['Total Expense', float(total_exp)],
            ['Net Balance', float(total_inc) + float(total_fund) - float(total_exp)]
        ])
        
        rows = []
        inc_m_q = filter_by_company_methods(db.session.query(db.extract('month', FeeRecord.payment_date).label('m'), db.func.sum(FeeRecord.amount_paid).label('total')).filter(db.extract('year', FeeRecord.payment_date) == filter_year), FeeRecord.payment_method, selected_company_id)
        inc_rows_ov = inc_m_q.group_by(db.extract('month', FeeRecord.payment_date)).all()
        inc_map_ov = {int(r.m): float(r.total) for r in inc_rows_ov}
        
        exp_m_q = db.session.query(db.extract('month', Expense.expense_date).label('m'), db.func.sum(Expense.amount).label('total')).filter(db.extract('year', Expense.expense_date) == filter_year)
        exp_m_q = filter_by_company_methods(exp_m_q, Expense.payment_method, selected_company_id)
        exp_rows_ov = exp_m_q.group_by(db.extract('month', Expense.expense_date)).all()
        exp_map_ov = {int(r.m): float(r.total) for r in exp_rows_ov}
        
        fund_m_q = db.session.query(db.extract('month', OwnerFunding.funding_date).label('m'), db.func.sum(OwnerFunding.amount).label('total')).filter(db.extract('year', OwnerFunding.funding_date) == filter_year)
        fund_m_q = filter_by_company_methods(fund_m_q, OwnerFunding.method, selected_company_id)
        fund_rows_ov = fund_m_q.group_by(db.extract('month', OwnerFunding.funding_date)).all()
        fund_map_ov = {int(r.m): float(r.total) for r in fund_rows_ov}
        for m in range(1, 13):
            inc = inc_map_ov.get(m, 0.0)
            exp = exp_map_ov.get(m, 0.0)
            fund = fund_map_ov.get(m, 0.0)
            rows.append([months[m-1], inc, fund, exp, inc + fund - exp])
        ws2 = wb.create_sheet('Monthly P&L')
        write_sheet(ws2, 'Monthly P&L', ['Month', 'Income', 'Capital Injection', 'Expense', 'Net'], rows)

    elif tab == 'payment_methods':
        export_method = request.args.get('method', '').strip()
        if export_method:
            base_all = filter_by_company_methods(
                FeeRecord.query.filter(
                    FeeRecord.payment_date >= start_date, FeeRecord.payment_date <= end_date
                ),
                FeeRecord.payment_method, selected_company_id)
            all_records = base_all.options(
                joinedload(FeeRecord.student), joinedload(FeeRecord.company)
            ).order_by(FeeRecord.payment_date.desc(), FeeRecord.id.desc()).all()
            records = [r for r in all_records if classify_method(r.payment_method) == export_method]
            if records:
                dest = Workbook()
                dst_ws = dest.active
                write_sheet(dst_ws, export_method, ['Date', 'Student', 'Company', 'Amount', 'GST', 'Method', 'Remarks'], [
                    [r.payment_date.strftime('%d-%b-%Y'), r.student.name,
                     r.company.name if r.company else 'Unassigned', r.amount_paid,
                     r.gst_amount, r.payment_method, (r.remarks or '')] for r in records
                ])
                total_cell = dst_ws.cell(row=dst_ws.max_row + 2, column=1, value='Total')
                total_cell.font = Font(bold=True)
                dst_ws.cell(row=dst_ws.max_row, column=4, value=float(sum(r.amount_paid for r in records)))
                buf = BytesIO()
                dest.save(buf)
                buf.seek(0)
                safe_name = export_method.replace(' ', '_')
                return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'{safe_name}_Payments_{filter_year}_{filter_month}.xlsx')

        ws = wb.active
        ws.title = 'Summary'
        report_pm, total_period = payment_method_period_breakdown(
            start_date, end_date, selected_company_id, detail_limit=PM_EXPORT_DETAIL_LIMIT)
        summary_rows = []
        for label in PAYMENT_METHODS + ['Others']:
            d = report_pm.get(label)
            if not d or not d['records']:
                continue
            summary_rows.append([label, d['total']])
            ws2 = wb.create_sheet(label[:20])
            rows = [[r.payment_date.strftime('%d-%b-%Y'), r.student.name, r.company.name if r.company else 'Unassigned', r.amount_paid, (r.remarks or '')] for r in d['records']]
            write_sheet(ws2, label, ['Date', 'Student', 'Company', 'Amount', 'Remarks'], rows)
            if d['truncated']:
                note = ws2.cell(row=len(rows) + 2, column=1,
                                value=f'Showing most recent {len(d["records"])} of {d["count"]} payments')
                note.font = Font(italic=True, size=9)
        write_sheet(ws, 'Payment Summary', ['Method', 'Total (₹)'], summary_rows)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filenames = {'income': 'Income_Report', 'fees': 'Student_Fees_Report', 'expense': 'Expense_Report', 'overall': 'Overall_Report', 'payment_methods': 'Payment_Methods_Report'}
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'{filenames.get(tab, "Report")}_{filter_year}_{filter_month}.xlsx')
