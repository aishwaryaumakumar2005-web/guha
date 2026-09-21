from app.extensions import db
from app.models import Account, FeeRecord, Expense, OwnerFunding, Company
from .payment_methods import DEFAULT_ACCOUNTS, METHOD_TYPE, classify_method, ACCOUNT_TYPE_ICONS
import re


def agreed_enrollment_items_bulk(student_ids):
    """Batched agreed_enrollment_items: {student_id: [items]} in two queries.

    For list pages (dues matrix, reminder batches) that previously loaded
    student.courses eagerly; the single-student variant would pay N+1.
    """
    from app.models import student_courses, Course
    student_ids = list(student_ids)
    if not student_ids:
        return {}
    rows = db.session.query(student_courses).filter(
        student_courses.c.student_id.in_(student_ids)).all()
    if not rows:
        return {}
    assoc = {}
    for row in rows:
        assoc.setdefault(row.student_id, {})[row.course_id] = row
    courses = Course.query.filter(Course.id.in_([r.course_id for r in rows])).all()
    by_course = {c.id: c for c in courses}
    out = {}
    for sid, by in assoc.items():
        items = []
        for cid, snap in by.items():
            course = by_course.get(cid)
            if course is None:
                continue
            fee = course.fees
            gst = course.gst_applicable
            company_id = course.company_id
            if snap is not None:
                if snap.agreed_fee is not None:
                    fee = snap.agreed_fee
                if snap.agreed_gst is not None:
                    gst = snap.agreed_gst
                if snap.agreed_company_id is not None:
                    company_id = snap.agreed_company_id
            items.append({
                'course_id': course.id,
                'course': course,
                'fee': fee,
                'gst_applicable': bool(gst),
                'company_id': company_id,
            })
        out[sid] = items
    return out


def agreed_enrollment_items(student_id):
    """Per-course dues basis for a student: agreed snapshot first, live course row as fallback.

    Returns a list of dicts: course_id, course (live row, for names/codes),
    fee, gst_applicable, company_id. NULL snapshot fields (pre-W2 rows whose
    backfill was skipped, or rows stamped before a column existed) fall back
    to the live course row per-field — never all-or-nothing, so a partial
    snapshot still freezes what it captured. NOTE: `is None` checks, not
    truthiness: agreed_gst=False and agreed_fee=0.0 are real snapshots.
    """
    return agreed_enrollment_items_bulk([student_id]).get(student_id, [])


def snapshot_company_id(item, gst_company_id, nongst_company_id):
    """Attribute an agreed enrollment item to a billing company.

    Mirrors the booking fallback for rows whose snapshot has no company:
    GST-applicable items bill through the GST entity, others through the
    non-GST one.
    """
    if item['company_id']:
        return item['company_id']
    return gst_company_id if item['gst_applicable'] else nongst_company_id


def student_refunded_total(student_id):
    """Total amount refunded to a student through Expenses linked to them (W3).

    A refund is defined as any Expense carrying student_id; non-refund
    expenses never set it.
    """
    from app.models import Expense
    total = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0)).filter(
        Expense.student_id == student_id).scalar()
    return round(total or 0.0, 2)


def student_refunded_totals_bulk(student_ids):
    """Batched student_refunded_total: {student_id: total} in one query."""
    from app.models import Expense
    student_ids = list(student_ids)
    if not student_ids:
        return {}
    rows = db.session.query(Expense.student_id, db.func.sum(Expense.amount)).filter(
        Expense.student_id.in_(student_ids)
    ).group_by(Expense.student_id).all()
    return {sid: round(total or 0.0, 2) for sid, total in rows}


def student_outstanding_bulk(student_ids):
    """{student_id: outstanding_balance} mirroring the fees-page balance rule:
    due (agreed GST-inclusive fees) - paid - concessions + refunds.

    One pass per aggregate for the whole picker, so the expenses page can show
    live payment impact without N+1 single-student totals.
    """
    from app.models import FeeRecord, Expense
    from app.helpers import get_gst_rates
    student_ids = list(student_ids)
    if not student_ids:
        return {}
    cgst_pct, sgst_pct = get_gst_rates()
    total_gst_pct = cgst_pct + sgst_pct
    paid_rows = db.session.query(
        FeeRecord.student_id, db.func.sum(FeeRecord.amount_paid)
    ).filter(FeeRecord.student_id.in_(student_ids), FeeRecord.status != 'Voided').group_by(FeeRecord.student_id).all()
    paid_map = {sid: round(float(total or 0), 2) for sid, total in paid_rows}
    conc_rows = db.session.query(
        FeeRecord.student_id, db.func.sum(db.func.coalesce(FeeRecord.concession, 0))
    ).filter(FeeRecord.student_id.in_(student_ids), FeeRecord.status != 'Voided').group_by(FeeRecord.student_id).all()
    conc_map = {sid: round(float(total or 0), 2) for sid, total in conc_rows}
    refunded_map = student_refunded_totals_bulk(student_ids)
    items_map = agreed_enrollment_items_bulk(student_ids)
    out = {}
    for sid in student_ids:
        items = items_map.get(sid, [])
        total_taxable = round(sum(it['fee'] for it in items), 2)
        gst_amount = round(sum(
            round(it['fee'] * total_gst_pct / 100, 2) for it in items if it['gst_applicable']
        ), 2)
        total_fee = round(total_taxable + gst_amount, 2)
        balance = round(
            total_fee - paid_map.get(sid, 0.0) - conc_map.get(sid, 0.0)
            + refunded_map.get(sid, 0.0), 2)
        out[sid] = balance
    return out


def company_bill_name(company):
    """Name as shown on bills — strips the trailing '(GST)' / '(NON GST)' bracket."""
    if not company or not company.name:
        return company.name if company else ''
    return re.sub(r'\s*\([^)]*\)\s*$', '', company.name).strip() or company.name


def normalize_method(method):
    return (method or '').strip().lower()


def ensure_default_companies():
    created = False
    c1 = Company.query.filter_by(code='COMP-GST').first()
    if not c1:
        c1 = Company(
            name='GUHA INDUSTRIAL SOLUTIONS (GST)',
            code='COMP-GST',
            is_gst_registered=True,
            gstin='33ABAFG1922E1Z2',
            address='1st floor, KKG Complex, SPT Mani Nagar, Gandhi Nagar Post, Arch Gate, Neyveli, Tamilnadu 607308, India',
            phone='8248779596',
            email='md@guhaindia.in',
            invoice_prefix='GTS-GST/'
        )
        db.session.add(c1)
        created = True

    c2 = Company.query.filter_by(code='COMP-NGST').first()
    if not c2:
        c2 = Company(
            name='YAZH ACADEMY (NON GST)',
            code='COMP-NGST',
            is_gst_registered=False,
            gstin=None,
            address='1st floor, KKG Complex, SPT Mani Nagar, Gandhi Nagar Post, Arch Gate, Neyveli, Tamilnadu 607308, India',
            phone='8248779596',
            email='md@guhaindia.in',
            invoice_prefix='GTS-NGST/'
        )
        db.session.add(c2)
        created = True
    # Same no-op rule as ensure_default_accounts: never open a write
    # transaction when there was nothing to seed.
    if created:
        db.session.commit()
    return c1, c2


def ensure_default_accounts():
    try:
        from .db_migration import migrate_renames
        migrate_renames()
    except Exception:
        db.session.rollback()
    try:
        ensure_default_companies()
        c1 = Company.query.filter_by(code='COMP-GST').first()
        c2 = Company.query.filter_by(code='COMP-NGST').first()
        
        if not db.session.query(Account).first():
            db.session.add_all(
                Account(name=name, account_type=atype, opening_balance=0.0, company_id=c1.id if 'Bank' in name or 'Card' in name else c2.id)
                for name, atype in DEFAULT_ACCOUNTS
            )
            db.session.commit()
        else:
            updated = False
            for acc in Account.query.filter(Account.company_id.is_(None)).all():
                acc.company_id = c1.id if 'Bank' in acc.name or 'Card' in acc.name else c2.id
                updated = True
            # A no-op ensure must not open a write transaction on every page
            # view — commit only when something actually changed.
            if updated:
                db.session.commit()
    except Exception:
        db.session.rollback()



def account_for_payment_method(payment_method):
    """Resolve a payment-method string to an Account via the shared classifier."""
    name = classify_method(payment_method)
    return Account.query.filter_by(name=name, is_active=True).first()


def _raw_balances():
    """Compute live income/expense totals keyed by normalized payment method."""
    fees = db.session.query(
        FeeRecord.payment_method, db.func.sum(FeeRecord.amount_paid), db.func.count(FeeRecord.id)
    ).filter(FeeRecord.status != 'Voided').group_by(FeeRecord.payment_method).all()
    exp = db.session.query(
        Expense.payment_method, db.func.sum(Expense.amount), db.func.count(Expense.id)
    ).group_by(Expense.payment_method).all()
    fund = db.session.query(
        OwnerFunding.method, db.func.sum(OwnerFunding.amount), db.func.count(OwnerFunding.id)
    ).group_by(OwnerFunding.method).all()

    balances = {}
    for method, total, cnt in fees:
        k = normalize_method(method)
        if k:
            bucket = balances.setdefault(k, {'income': 0.0, 'expense': 0.0, 'count': 0})
            bucket['income'] += float(total or 0)
            bucket['count'] += int(cnt or 0)
    for method, total, cnt in fund:
        k = normalize_method(method)
        if k:
            bucket = balances.setdefault(k, {'income': 0.0, 'expense': 0.0, 'count': 0})
            bucket['income'] += float(total or 0)
            bucket['count'] += int(cnt or 0)
    for method, total, cnt in exp:
        k = normalize_method(method)
        if k:
            bucket = balances.setdefault(k, {'income': 0.0, 'expense': 0.0, 'count': 0})
            bucket['expense'] += float(total or 0)
            bucket['count'] += int(cnt or 0)
    return balances


_summary_cache = {"data": None, "time": 0}


def invalidate_account_caches():
    """Drop all cached ledger aggregates.

    Called automatically on every FeeRecord/Expense/OwnerFunding write (see
    register_cache_invalidation) so balances never lie after a booking. The
    TTLs remain as a second layer for multi-worker staleness.
    """
    _summary_cache["data"] = None
    _summary_cache["time"] = 0
    _matching_cache.clear()
    _breakdown_cache.clear()


def _clear_caches_on_write(mapper, connection, target):
    invalidate_account_caches()


_invalidation_registered = False


def register_cache_invalidation():
    """Hook ledger cache drops to ORM writes on accounts and money models.

    Event-driven (not per-route) so every writer is covered: fee/expense/
    funding routes, account edits, payroll confirm/delete, admin bulk import,
    and any future code path. Safe to call multiple times (test app rebuilds).
    """
    global _invalidation_registered
    if _invalidation_registered:
        return
    from sqlalchemy import event as sa_event
    from app.models import Account, FeeRecord, Expense, OwnerFunding
    for cls in (Account, FeeRecord, Expense, OwnerFunding):
        for evt in ('after_insert', 'after_update', 'after_delete'):
            sa_event.listen(cls, evt, _clear_caches_on_write)
    _invalidation_registered = True


def compute_account_summary():
    """Per-account balance cards. Balances are derived live from source records."""
    from time import time
    if time() - _summary_cache["time"] < 30 and _summary_cache["data"]:
        return _summary_cache["data"]
    from sqlalchemy.orm import joinedload
    ensure_default_accounts()
    raw = _raw_balances()
    accounts = Account.query.options(joinedload(Account.company)).order_by(Account.id).all()

    # Distribute each observed method into its matching account, folding
    # unmatched methods into the generic 'Others' account.
    assigned = {acc.name: {'income': 0.0, 'expense': 0.0, 'count': 0} for acc in accounts}
    used_methods = set()

    for method, b in raw.items():
        aname = classify_method(method)
        used_methods.add(aname)
        # setdefault, not [aname]: a renamed or deleted account row must
        # never 500 the ledger — its bucket survives below as an orphan row
        # so no money disappears from the books.
        bucket = assigned.setdefault(aname, {'income': 0.0, 'expense': 0.0, 'count': 0})
        bucket['income'] += b['income']
        bucket['expense'] += b['expense']
        bucket['count'] += b.get('count', 1)

    summary = []
    for acc in accounts:
        b = assigned[acc.name]
        income = b['income']
        expense = b['expense']
        summary.append({
            'id': acc.id,
            'name': acc.name,
            'account_type': acc.account_type,
            'icon': ACCOUNT_TYPE_ICONS.get(acc.account_type, 'wallet-fill'),
            'company_id': acc.company_id,
            'company_name': acc.company.name if acc.company else 'Unassigned',
            'is_gst_registered': bool(acc.company.is_gst_registered) if acc.company else False,
            'opening_balance': round(acc.opening_balance, 2),
            'income': round(income, 2),
            'expense': round(expense, 2),
            'balance': round(acc.opening_balance + income - expense, 2),
            'txn_count': b.get('count', 0),
            'is_active': acc.is_active,
        })
    seen = {acc.name for acc in accounts}
    for aname, b in assigned.items():
        if aname in seen:
            continue
        if not (b['income'] or b['expense'] or b['count']):
            continue
        # Bucket with postings but no account row (renamed/deleted account):
        # surfaced explicitly so the money stays visible instead of 500ing.
        summary.append({
            'id': None,
            'name': aname,
            'account_type': METHOD_TYPE.get(aname, 'Other'),
            'icon': ACCOUNT_TYPE_ICONS.get(METHOD_TYPE.get(aname, 'Other'), 'wallet-fill'),
            'company_id': None,
            'company_name': 'Unassigned',
            'is_gst_registered': False,
            'opening_balance': 0.0,
            'income': round(b['income'], 2),
            'expense': round(b['expense'], 2),
            'balance': round(b['income'] - b['expense'], 2),
            'txn_count': b.get('count', 0),
            'is_active': True,
            'orphan': True,
        })
    summary.sort(key=lambda r: (not r['is_active'], r['name'] in ('Others', 'UPI'), r['name']))
    _summary_cache["data"] = summary
    _summary_cache["time"] = time()
    return summary


_matching_cache = {}


def matching_methods(account_name):
    """All distinct payment_method values (normalized) that roll into `account_name`."""
    from time import time
    key = normalize_method(account_name) or 'others'
    entry = _matching_cache.get(key)
    if entry and time() - entry['time'] < 60:
        return entry['data']
    ensure_default_accounts()
    accounts = Account.query.order_by(Account.id).all()

    def match_account(method):
        return classify_method(method)

    observed = set()
    for (m,) in db.session.query(FeeRecord.payment_method).distinct().all():
        if m:
            observed.add(normalize_method(m))
    for (m,) in db.session.query(Expense.payment_method).distinct().all():
        if m:
            observed.add(normalize_method(m))
    for (m,) in db.session.query(OwnerFunding.method).distinct().all():
        if m:
            observed.add(normalize_method(m))
    target = normalize_method(account_name)
    result = [m for m in observed
              if normalize_method(match_account(m)) == target
              or (not target and match_account(m) == 'Others')]
    _matching_cache[key] = {'data': result, 'time': time()}
    return result


def account_breakdown(account_name, limit=200):
    """Ledger rows (income + expense + funding) for one account, most recent first."""
    from sqlalchemy.orm import joinedload
    from time import time
    key = normalize_method(account_name) or 'others'
    entry = _breakdown_cache.get(key)
    if entry and time() - entry['time'] < 15:
        return entry['data']
    methods = matching_methods(account_name)
    if not methods:
        return {'income': [], 'expenses': [], 'funding': [],
                'limit': limit, 'totals': {'income': 0, 'expenses': 0, 'funding': 0}}

    fee_q = FeeRecord.query.filter(FeeRecord.status != 'Voided')
    exp_q = Expense.query
    fund_q = OwnerFunding.query
    ors_fee = db.or_(*(db.func.lower(db.func.coalesce(FeeRecord.payment_method, '')) == m for m in methods))
    ors_exp = db.or_(*(db.func.lower(db.func.coalesce(Expense.payment_method, '')) == m for m in methods))
    ors_fund = db.or_(*(db.func.lower(db.func.coalesce(OwnerFunding.method, '')) == m for m in methods))

    fee_base = fee_q.filter(ors_fee)
    exp_base = exp_q.filter(ors_exp)
    fund_base = fund_q.filter(ors_fund)

    fees = fee_base.options(joinedload(FeeRecord.student)).order_by(FeeRecord.payment_date.desc()).limit(limit).all()
    exp = exp_base.options(joinedload(Expense.category), joinedload(Expense.student)).order_by(Expense.expense_date.desc()).limit(limit).all()
    fund = fund_base.order_by(OwnerFunding.funding_date.desc()).limit(limit).all()
    data = {
        'income': fees,
        'expenses': exp,
        'funding': fund,
        'limit': limit,
        'totals': {
            'income': fee_base.order_by(None).count(),
            'expenses': exp_base.order_by(None).count(),
            'funding': fund_base.order_by(None).count(),
        },
    }
    _breakdown_cache[key] = {'data': data, 'time': time()}
    return data


_breakdown_cache = {}
