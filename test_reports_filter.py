"""
Standalone test script for Reports & Analytics page filter logic.
Tests the /reports route handler directly with ALL combinations of filter parameters.
"""

import os, sys
from datetime import date, datetime, timedelta
from unittest.mock import patch

os.environ['FLASK_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['GEMINI_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''
os.environ['CRON_SECRET'] = 'test'

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import init_db as _init_db_mod
import app as _app_mod
import app.routes.dashboard as _dash_mod
from app import create_app
from app.extensions import db
from app.models import (
    User, Course, Student, Tutor, Company, FeeRecord, Expense,
    ExpenseCategory, OwnerFunding, Account
)
from app.services.account_service import ensure_default_companies, ensure_default_accounts
from werkzeug.security import generate_password_hash
from flask import request
from flask_login import login_user


def build_app():
    _app_mod._sidebar_cache = {"data": None, "time": 0}
    _dash_mod._stats_cache = {"data": None, "time": 0}
    _orig_seed = _init_db_mod.seed_if_empty
    _init_db_mod.seed_if_empty = lambda: None
    flask_app = create_app()
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    _init_db_mod.seed_if_empty = _orig_seed
    return flask_app


def seed_test_data():
    """Create controlled test data for deterministic filter testing.
    
    Companies and accounts are already created by ensure_default_accounts()
    during app factory. We reuse them and add test-specific data on top.
    """
    admin = User(
        username='admin', password_hash=generate_password_hash('pass'),
        role='Admin', name='Admin User', email='admin@test.local'
    )
    db.session.add(admin)
    db.session.flush()

    # Use the companies created by ensure_default_companies()
    c1 = Company.query.filter_by(code='COMP-GST').first()
    c2 = Company.query.filter_by(code='COMP-NGST').first()
    if not c1:
        c1 = Company(name='Default GST', code='COMP-GST', is_gst_registered=True, is_active=True)
        db.session.add(c1)
        db.session.flush()
    if not c2:
        c2 = Company(name='Default NonGST', code='COMP-NGST', is_gst_registered=False, is_active=True)
        db.session.add(c2)
        db.session.flush()

    cat_rent = ExpenseCategory(name='Rent')
    cat_salary = ExpenseCategory(name='Salary')
    db.session.add_all([cat_rent, cat_salary])
    db.session.flush()

    s1 = Student(name='Student A', email='a@test.com', phone='1111111111', status='Active', roll_no='STU1001')
    s2 = Student(name='Student B', email='b@test.com', phone='2222222222', status='Active', roll_no='STU1002')
    s3 = Student(name='Student C', email='c@test.com', phone='3333333333', status='Active', roll_no='STU1003')
    db.session.add_all([s1, s2, s3])
    db.session.flush()

    crs_gst = Course(name='GST Course', code='GC', fees=10000, gst_applicable=True,
                     duration_weeks=8, company_id=c1.id)
    crs_ngst = Course(name='NonGST Course', code='NG', fees=8000, gst_applicable=False,
                      duration_weeks=4, company_id=c2.id)
    db.session.add_all([crs_gst, crs_ngst])
    db.session.flush()

    s1.courses.append(crs_gst)
    s2.courses.append(crs_ngst)
    s3.courses.append(crs_gst)
    db.session.flush()

    # --- Fee Records ---
    fees_data = [
        # (student, company, date, amount, method, has_gst)
        # Jun 2026 - Company 1 (GST)
        (s1, c1, date(2026, 6, 5),  11800.0, 'Cash', True),
        (s3, c1, date(2026, 6, 12), 11800.0, 'Bank Transfer', True),
        (s1, c1, date(2026, 6, 20),  5900.0, 'UPI', True),
        # Jun 2026 - Company 2 (NonGST)
        (s2, c2, date(2026, 6, 8),   8000.0, 'Cash', False),
        (s2, c2, date(2026, 6, 15),  4000.0, 'UPI', False),
        # Jul 2026 - Company 1
        (s1, c1, date(2026, 7, 3),  11800.0, 'Cash', True),
        # Jul 2026 - Company 2
        (s2, c2, date(2026, 7, 10),  8000.0, 'Card', False),
        # Aug 2026 - Company 1
        (s3, c1, date(2026, 8, 1),  11800.0, 'Bank Transfer', True),
        # May 2026 - Company 2
        (s2, c2, date(2026, 5, 14),  8000.0, 'Cash', False),
        # Oct 2025 - Company 1 (for all-time totals)
        (s1, c1, date(2025, 10, 10), 11800.0, 'Cash', True),
    ]
    for stu, comp, pdate, amt, method, has_gst in fees_data:
        taxable = round(amt / 1.18, 2) if has_gst else amt
        gst = round(amt - taxable, 2) if has_gst else 0.0
        fr = FeeRecord(
            student_id=stu.id, company_id=comp.id,
            amount_paid=amt, taxable_amount=taxable, gst_amount=gst,
            payment_date=pdate, payment_method=method,
            receipt_number=f'{comp.code}-{pdate.strftime("%Y%m")}',
            remarks=f'test fee {comp.code}'
        )
        db.session.add(fr)

    # --- Expenses ---
    exp_data = [
        # Jun 2026
        (cat_rent, 15000, 'Jun rent', date(2026, 6, 1), 'Cash'),
        (cat_salary, 25000, 'Jun salary', date(2026, 6, 5), 'Bank Transfer'),
        (cat_rent, 3000, 'Jun utilities', date(2026, 6, 10), 'UPI'),
        # Jul 2026
        (cat_rent, 15000, 'Jul rent', date(2026, 7, 1), 'Cash'),
        # May 2026
        (cat_salary, 25000, 'May salary', date(2026, 5, 5), 'Bank Transfer'),
    ]
    for cat, amt, desc, edate, method in exp_data:
        db.session.add(Expense(
            category_id=cat.id, amount=amt, description=desc,
            expense_date=edate, payment_method=method, created_by=admin.id
        ))

    # --- Owner Funding ---
    db.session.add(OwnerFunding(amount=50000, funding_date=date(2026, 6, 1),
                                method='Cash', purpose='Working capital', created_by=admin.id))
    db.session.add(OwnerFunding(amount=30000, funding_date=date(2026, 7, 15),
                                method='Bank Transfer', purpose='Expansion', created_by=admin.id))

    db.session.commit()
    return admin, c1, c2


def call_reports_route(app, admin_user, params):
    """Call the reports() view function with the given query params and capture template kwargs."""
    captured = {}

    def fake_render_template(template_name, **kwargs):
        captured.update(kwargs)
        return ''

    qs = '&'.join(f'{k}={v}' for k, v in params.items() if v is not None)
    url = '/reports' + ('?' + qs if qs else '')

    with app.test_request_context(url):
        login_user(admin_user)
        with patch('app.routes.reports.render_template', side_effect=fake_render_template):
            from app.routes.reports import reports
            reports()
    return captured


def print_section(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def print_result(label, val, indent=2):
    sp = ' ' * indent
    if isinstance(val, float):
        print(f"{sp}{label}: {val:,.2f}")
    elif isinstance(val, list) and len(val) == 12:
        names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        if isinstance(val[0], dict) and 'total' in val[0]:
            print(f"{sp}{label}:")
            for i, v in enumerate(val):
                print(f"{sp}  {names[i]}: {v['total']:,.2f}")
        else:
            print(f"{sp}{label}:")
            for i, v in enumerate(val):
                print(f"{sp}  {names[i]}: {v:,.2f}")
    else:
        print(f"{sp}{label}: {val}")


def print_company_pl(company_pl):
    print("  company_pl breakdown:")
    for item in company_pl:
        c = item['company']
        print(f"    Company {c.id} ({c.name}): "
              f"income={item['income']:,.2f}  taxable={item['taxable']:,.2f}  gst={item['gst']:,.2f}")


def print_filter_vars(ctx):
    print(f"  Filter vars -> selected_company_id={ctx.get('selected_company_id')}  "
          f"filter_month={ctx.get('filter_month')}  filter_year={ctx.get('filter_year')}  "
          f"filter_mode={ctx.get('filter_mode')}")
    print(f"  start_date_str={ctx.get('start_date_str')}  end_date_str={ctx.get('end_date_str')}")


FILTER_COMBOS = [
    ("All Companies, Monthly, Jun 2026", {
        'filter_mode': 'monthly', 'month': 6, 'year': 2026, 'company_id': None
    }),
    ("Company 2 only, Monthly, Jun 2026", {
        'filter_mode': 'monthly', 'month': 6, 'year': 2026, 'company_id': 2
    }),
    ("Company 1 only, Monthly, Jun 2026", {
        'filter_mode': 'monthly', 'month': 6, 'year': 2026, 'company_id': 1
    }),
    ("All Companies, Monthly, Sep 2026 (no data)", {
        'filter_mode': 'monthly', 'month': 9, 'year': 2026, 'company_id': None
    }),
    ("All Companies, Yearly, 2026", {
        'filter_mode': 'yearly', 'month': 1, 'year': 2026, 'company_id': None
    }),
    ("Company 2, Yearly, 2026", {
        'filter_mode': 'yearly', 'month': 1, 'year': 2026, 'company_id': 2
    }),
    ("Custom range: 2026-06-01 to 2026-06-30", {
        'filter_mode': 'custom', 'start_date': '2026-06-01', 'end_date': '2026-06-30',
        'company_id': None
    }),
    ("All Companies, Quarterly, Q2 2026 (month=4)", {
        'filter_mode': 'quarterly', 'month': 4, 'year': 2026, 'company_id': None
    }),
]


def main():
    print("Building Flask app with in-memory DB...")
    app = build_app()
    with app.app_context():
        db.create_all()
        print("Seeding controlled test data...")
        admin, c1, c2 = seed_test_data()
        print(f"Seeded: Company 1 id={c1.id} name='{c1.name}', Company 2 id={c2.id} name='{c2.name}'")

        companies = Company.query.filter_by(is_active=True).all()
        fee_count = FeeRecord.query.count()
        exp_count = Expense.query.count()
        fund_count = OwnerFunding.query.count()
        print(f"Fee records: {fee_count}, Expenses: {exp_count}, Owner Fundings: {fund_count}")
        for comp in companies:
            fc = FeeRecord.query.filter_by(company_id=comp.id).count()
            print(f"  Company {comp.id} ({comp.name}): {fc} fee records")

        for combo_name, params in FILTER_COMBOS:
            print_section(combo_name)
            print(f"  Input params: {params}")

            ctx = call_reports_route(app, admin, params)

            print_filter_vars(ctx)

            print(f"\n  --- KPI Values ---")
            print_result("total_income (all-time)", ctx.get('total_income', 0))
            print_result("total_income_filtered (period)", ctx.get('total_income_filtered', 0))
            print_result("total_taxable_filtered", ctx.get('total_taxable_filtered', 0))
            print_result("total_gst_filtered", ctx.get('total_gst_filtered', 0))
            print_result("total_expense_filtered", ctx.get('total_expense_filtered', 0))
            print_result("total_funding_filtered", ctx.get('total_funding_filtered', 0))
            print_result("net_balance", ctx.get('net_balance', 0))
            print_result("total_collected_period", ctx.get('total_collected_period', 0))

            print(f"\n  --- Company P&L Breakdown ---")
            company_pl = ctx.get('company_pl', [])
            if company_pl:
                print_company_pl(company_pl)
            else:
                print("    (empty)")

            print(f"\n  --- Monthly Income (12-month array for {ctx.get('filter_year', '?')}) ---")
            print_result("income_monthly", ctx.get('income_monthly', []))

            print(f"\n  --- Monthly Expenses (12-month array for {ctx.get('filter_year', '?')}) ---")
            print_result("monthly_expense", ctx.get('monthly_expense', []))

            print(f"\n  --- Monthly Funding (12-month array) ---")
            print_result("funding_monthly", ctx.get('funding_monthly', []))

            print(f"\n  --- Course-wise Income (period) ---")
            course_wise = ctx.get('course_wise_income', [])
            if course_wise:
                for cw in course_wise:
                    print(f"    {cw['name']} ({cw['code']}): {cw['total']:,.2f}")
            else:
                print("    (empty)")

            print(f"\n  --- Expense Summary (period by category) ---")
            exp_sum = ctx.get('expense_summary', [])
            for es in exp_sum:
                if es['total'] > 0:
                    print(f"    {es['name']}: total={es['total']:,.2f}  count={es['count']}")

            print(f"\n  --- Quick sanity checks ---")
            inc_m = ctx.get('income_monthly', [])
            exp_m = ctx.get('monthly_expense', [])
            total_m = sum(inc_m) if isinstance(inc_m[0], (int, float)) else sum(x['total'] for x in inc_m)
            total_me = sum(exp_m) if isinstance(exp_m[0], (int, float)) else sum(x['total'] for x in exp_m)
            print(f"    Sum of monthly income array: {total_m:,.2f}")
            print(f"    Sum of monthly expense array: {total_me:,.2f}")
            nb = ctx.get('net_balance', 0)
            inc_f = ctx.get('total_income_filtered', 0)
            fund_f = ctx.get('total_funding_filtered', 0)
            exp_f = ctx.get('total_expense_filtered', 0)
            check = round(float(inc_f) + float(fund_f) - float(exp_f), 2)
            print(f"    net_balance ({nb:,.2f}) == income+funding-expense ({check:,.2f}) ? {'PASS' if abs(nb - check) < 0.01 else 'FAIL'}")

    print_section("ALL COMBINATIONS TESTED")


if __name__ == '__main__':
    main()
