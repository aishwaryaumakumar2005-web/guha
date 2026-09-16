# -*- coding: utf-8 -*-
"""
RESEARCH ONLY - renders the /reports route for several filter combinations,
saves the FULL rendered HTML for inspection, and prints a structured audit
of form-field reflection, table data, and chart JSON.

Does NOT modify any source files or the database.
"""
import os
import re
import sys
import json
import traceback
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask_login import login_user

from app import create_app
from app.extensions import db
from app.models import User
from app.routes.reports import reports as reports_handler

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

TODAY = date.today()
OUT_DIR = PROJECT_ROOT
MAIN_HTML = os.path.join(OUT_DIR, "temp_rendered.html")
ALL_HTML = os.path.join(OUT_DIR, "temp_rendered_all.html")

app = create_app()


def resolve_user():
    with app.app_context():
        u = User.query.filter_by(role="Admin").order_by(User.id).first()
        if u:
            return u
        u = User.query.order_by(User.id).first()
        if u:
            return u
        # transient fallback - no DB write
        return User(
            id=1, username="research_admin", password_hash="x",
            role="Admin", name="Research User", email="research@guha.test",
        )


import app.routes.reports as reports_module
from flask import render_template as real_render_template

_captured_ctx = {}


def _capturing_render(template_name, **ctx):
    _captured_ctx[template_name] = ctx
    return real_render_template(template_name, **ctx)


def call_reports(params, user):
    """Invoke the reports view inside a request context, capturing the template
    context the route passes to reports.html and rendering the full HTML."""
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    _captured_ctx.clear()
    orig = reports_module.render_template
    reports_module.render_template = _capturing_render
    try:
        with app.test_request_context(path="/reports", query_string=qs):
            login_user(user)
            html = reports_handler()
        ctx = _captured_ctx.get("reports.html")
        if ctx is None:
            raise RuntimeError("route did not render reports.html (redirect/404?)")
        return ctx, html
    finally:
        reports_module.render_template = orig


# ---------------------------------------------------------------- snapshot
def snapshot(ctx):
    return {
        "input.resolved": {
            "tab": ctx["tab"],
            "filter_mode": ctx["filter_mode"],
            "filter_month": ctx["filter_month"],
            "filter_year": ctx["filter_year"],
            "start_date": ctx["start_date_str"],
            "end_date": ctx["end_date_str"],
            "active_quick": ctx.get("active_quick"),
            "selected_company_id": ctx.get("selected_company_id"),
            "companies": [{"id": c.id, "name": c.name, "code": c.code} for c in ctx["companies"]],
        },
        "kpis": {
            "total_income_all_time": round(ctx["total_income"], 2),
            "total_income_period": round(ctx["total_income_filtered"], 2),
            "total_taxable_period": round(ctx["total_taxable_filtered"], 2),
            "total_gst_period": round(ctx["total_gst_filtered"], 2),
            "total_expense_period": round(ctx["total_expense_filtered"], 2),
            "total_funding_period": round(ctx["total_funding_filtered"], 2),
            "net_balance": round(ctx["net_balance"], 2),
            "total_collected_period": round(ctx["total_collected_period"], 2),
        },
        "income_monthly": [round(x, 2) for x in ctx["income_monthly"]],
        "fees_monthly": [round(f["total"], 2) for f in ctx["fees_monthly"]],
        "monthly_expense": [round(e["total"], 2) for e in ctx["monthly_expense"]],
        "funding_monthly": [round(x, 2) for x in ctx["funding_monthly"]],
        "pl_monthly": [
            {"m": p["month"], "income": round(p["income"], 2), "expense": round(p["expense"], 2),
             "funding": round(p["funding"], 2), "net": round(p["net"], 2)}
            for p in ctx["pl_monthly"]
        ],
        "course_wise_income": [
            {"name": c["name"], "code": c["code"], "total": round(c["total"], 2)}
            for c in ctx["course_wise_income"]
        ],
        "category_wise_expense": [
            {"name": c["name"], "total": round(c["total"], 2), "count": c["count"]}
            for c in ctx["category_wise_expense"]
        ],
        "expense_by_type": [
            {"type": t["type"], "total": round(t["total"], 2), "count": t["count"]}
            for t in ctx["expense_by_type"]
        ],
        "expense_by_account": [
            {"account": a["account"], "total": round(a["total"], 2), "count": a["count"]}
            for a in ctx["expense_by_account"]
        ],
        "expense_summary": [
            {"name": s["name"], "total": round(s["total"], 2), "count": s["count"]}
            for s in ctx["expense_summary"]
        ],
        "daily_collections": {
            "count": len(ctx["daily_collections"]),
            "total": round(sum(r.amount_paid for r in ctx["daily_collections"]), 2),
        },
        "recent_expenses": {
            "count": len(ctx["recent_expenses"]),
            "amounts": [round(e.amount, 2) for e in ctx["recent_expenses"]],
        },
        "payment_labels": ctx["payment_labels"],
        "payment_data": [float(x) for x in ctx["payment_data"]],
        "daily_labels": ctx["daily_labels"],
        "daily_amounts": [float(x) for x in ctx["daily_amounts"]],
        "company_pl": [
            {"company": c["company"].name,
             "income": round(c["income"], 2), "taxable": round(c["taxable"], 2),
             "gst": round(c["gst"], 2)}
            for c in ctx["company_pl"]
        ],
        "payment_methods_report": {
            m: {"total": round(d["total"], 2), "records": len(d["records"])}
            for m, d in ctx["payment_methods_report"].items()
        },
        "account_balances_rendered": bool(ctx.get("account_balances")),
    }


# ------------------------------------------------------------- validations
def _month_selected(html, month):
    return f'<option value="{month}" class="month-option" selected' in html


def _year_selected(html, year):
    return f'<option value="{year}" selected' in html


def _company_selected(html, company_id):
    m = re.search(r'<select name="company_id".*?</select>', html, re.S)
    block = m.group(0) if m else html
    if not company_id:
        # with 'All Companies', no company option should carry `selected`
        return not re.search(r'<option value="\d+" selected>', block)
    return f'<option value="{company_id}" selected>' in block


def extract_charts(html):
    """Return {chart_id: {'labels': [...], 'data': [[...], ...]}} from the inline script."""
    charts = {}
    chunks = re.split(r"chartConfigs\['", html)
    for chunk in chunks[1:]:
        m = re.match(r"(\w+)'\] = \{(.*)", chunk, re.S)
        if not m:
            continue
        cid, body = m.group(1), m.group(2)
        labels = None
        lbl = re.search(r"labels:\s*(\[[^\]]*\])", body)
        if lbl:
            try:
                labels = json.loads(lbl.group(1))
            except ValueError:
                labels = lbl.group(1)
        datasets = []
        for dm in re.finditer(r"data:\s*(\[[^\]]*\])", body):
            try:
                datasets.append(json.loads(dm.group(1)))
            except ValueError:
                datasets.append(dm.group(1))
        charts[cid] = {"labels": labels, "data": datasets}
    return charts


def validate(label, snap, html):
    issues = []
    r = snap["input.resolved"]
    k = snap["kpis"]
    fm, fy, fc = r["filter_month"], r["filter_year"], r["selected_company_id"]

    # 1) form field reflection
    if r["filter_mode"] != "quarterly":
        if not _month_selected(html, fm):
            issues.append(f"form: month select does NOT mark option {fm} as selected")
    if not _year_selected(html, fy):
        issues.append(f"form: year select does NOT mark option {fy} as selected")
    if not _company_selected(html, fc):
        issues.append(f"form: company select mismatch (company_id={fc})")

    if fc and fc not in [c["id"] for c in r["companies"]]:
        issues.append(
            f"data: selected_company_id={fc} does not match any active company "
            f"({[c['id'] for c in r['companies']]}) -> all company-filtered queries return nothing"
        )

    # 2) tab / active pane
    if r["tab"] not in ("income", "fees", "expense", "overall", "payment_methods", "staff"):
        issues.append(
            f"tab: '{r['tab']}' is not a known tab (valid: income/fees/expense/overall/"
            f"payment_methods) - no tab pane will be marked active"
        )

    # 3) internal KPI cross-checks (period == the selected month when in monthly mode)
    if r["filter_mode"] == "monthly":
        m_idx = fm - 1
        inc = snap["income_monthly"][m_idx]
        exp = snap["monthly_expense"][m_idx]
        fund = snap["funding_monthly"][m_idx]
        net = snap["pl_monthly"][m_idx]["net"]
        if abs(inc - k["total_income_period"]) > 0.01:
            issues.append(
                f"data: income_monthly[{m_idx}]={inc} != total_income_period="
                f"{k['total_income_period']}")
        if abs(exp - k["total_expense_period"]) > 0.01:
            issues.append(
                f"data: monthly_expense[{m_idx}]={exp} != total_expense_period="
                f"{k['total_expense_period']}")
        if abs(fund - k["total_funding_period"]) > 0.01:
            issues.append(
                f"data: funding_monthly[{m_idx}]={fund} != total_funding_period="
                f"{k['total_funding_period']}")
        if abs(net - k["net_balance"]) > 0.01:
            issues.append(
                f"data: pl_monthly[{m_idx}].net={net} != net_balance="
                f"{k['net_balance']}")

    # 4) table totals
    sum_course = round(sum(c["total"] for c in snap["course_wise_income"]), 2)
    sum_cat = round(sum(c["total"] for c in snap["category_wise_expense"]), 2)
    sum_pm = round(sum(d["total"] for d in snap["payment_methods_report"].values()), 2)
    if sum_course != k["total_income_period"]:
        issues.append(
            f"data: sum(course_wise_income)={sum_course} != total_income_period="
            f"{k['total_income_period']}")
    if sum_cat != k["total_expense_period"]:
        issues.append(
            f"data: sum(category_wise_expense)={sum_cat} != total_expense_period="
            f"{k['total_expense_period']}")
    if sum_pm != k["total_collected_period"]:
        issues.append(
            f"data: sum(payment_methods_report)={sum_pm} != total_collected_period="
            f"{k['total_collected_period']}")
    if snap["daily_collections"]["total"] != k["total_income_period"]:
        issues.append(
            f"data: daily_collections total={snap['daily_collections']['total']} != "
            f"total_income_period={k['total_income_period']}")

    # 5) chart JSON vs context
    charts = extract_charts(html)
    if not charts:
        issues.append("charts: could not extract any chartConfigs from rendered HTML")
    else:
        if "incomeChart" in charts:
            d = charts["incomeChart"]["data"]
            wanted = snap["income_monthly"]
            if not d or d[0] != wanted:
                issues.append(
                    f"charts: incomeChart data mismatch\n  html={d}\n  ctx ={wanted}")
        if "feesMonthlyChart" in charts:
            d = charts["feesMonthlyChart"]["data"]
            wanted = snap["fees_monthly"]
            if not d or d[0] != wanted:
                issues.append(
                    f"charts: feesMonthlyChart data mismatch\n  html={d}\n  ctx ={wanted}")
        if "expenseMonthlyChart" in charts:
            d = charts["expenseMonthlyChart"]["data"]
            wanted = snap["monthly_expense"]
            if not d or d[0] != wanted:
                issues.append(
                    f"charts: expenseMonthlyChart data mismatch\n  html={d}\n  ctx ={wanted}")
        if "plChart" in charts:
            d = charts["plChart"]["data"]
            wanted = [p["income"] for p in snap["pl_monthly"]]
            if not d or d[0] != wanted:
                issues.append(
                    f"charts: plChart dataset[0] (Income) mismatch\n  html={d[0] if d else None}"
                    f"\n  ctx ={wanted}")

    return {"issues": issues, "chart_blocks": {k: v for k, v in charts.items()}}


SCENARIOS = [
    ("no_params", {}),
    ("company_only", {"company_id": 2}),
    ("month_year_only", {"month": 6, "year": 2026}),
    ("overview_main", {"tab": "overview", "filter_mode": "monthly",
                       "month": 6, "year": 2026, "company_id": 2}),
    ("overview_all", {"tab": "overview", "filter_mode": "monthly",
                      "month": 6, "year": 2026}),
    ("overall_main_alt", {"tab": "overall", "filter_mode": "monthly",
                          "month": 6, "year": 2026, "company_id": 2}),
    ("overall_all_alt", {"tab": "overall", "filter_mode": "monthly",
                         "month": 6, "year": 2026}),
]


def main():
    user = resolve_user()
    print(f"Resolved user for login simulation: {user.username} ({user.role})")
    report = {}
    saves = {}

    for label, params in SCENARIOS:
        print(f"\n===== scenario: {label}  params={params}")
        try:
            ctx, html = call_reports(params, user)
            snap = snapshot(ctx)
            val = validate(label, snap, html)
            report[label] = {
                "params": params,
                "snapshot": snap,
                "issues": val["issues"],
                "charts": val["chart_blocks"],
            }
            print(json.dumps(snap, indent=2, default=str))
            print("ISSUES:", json.dumps(val["issues"], indent=2))

            if label == "overview_main":
                with open(MAIN_HTML, "w", encoding="utf-8") as fh:
                    fh.write(html)
                saves["temp_rendered.html"] = MAIN_HTML
            if label == "overview_all":
                with open(ALL_HTML, "w", encoding="utf-8") as fh:
                    fh.write(html)
                saves["temp_rendered_all.html"] = ALL_HTML
        except Exception:
            print("EXCEPTION in scenario:")
            traceback.print_exc()
            report[label] = {"params": params, "error": traceback.format_exc()}

    for key, path in saves.items():
        print(f"SAVED {key} -> {path} ({os.path.getsize(path)} bytes)")

    with open(os.path.join(OUT_DIR, "research_reports_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("\nFull audit written to research_reports_audit.json")


if __name__ == "__main__":
    main()