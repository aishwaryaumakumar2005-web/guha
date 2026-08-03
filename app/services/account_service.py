from app.extensions import db
from app.models import Account, FeeRecord, Expense, OwnerFunding


# Default accounts seeded on startup when the account table is empty.
DEFAULT_ACCOUNTS = [
    ('Cash', 'Cash'),
    ('UPI - Guha India', 'UPI'),
    ('UPI - Ejaj Sir', 'UPI'),
    ('UPI', 'UPI'),
    ('Bank Transfer', 'Bank'),
    ('Card', 'Card'),
    ('Others', 'Other'),
]


def normalize_method(method):
    return (method or '').strip().lower()


def ensure_default_accounts():
    if db.session.query(Account).first():
        return
    db.session.add_all(
        Account(name=name, account_type=atype, opening_balance=0.0)
        for name, atype in DEFAULT_ACCOUNTS
    )
    db.session.commit()


def account_for_payment_method(payment_method):
    """Resolve a payment-method string to an Account (substring match)."""
    key = normalize_method(payment_method)
    if not key:
        return None
    accounts = Account.query.filter_by(is_active=True).all()
    for acc in accounts:
        if normalize_method(acc.name) == key:
            return acc
    for acc in accounts:
        aname = normalize_method(acc.name)
        if aname in ('others', 'upi'):
            continue
        if key.startswith(aname) or aname in key:
            return acc
    return Account.query.filter_by(name='Others', is_active=True).first()


def _raw_balances():
    """Compute live income/expense totals keyed by normalized payment method."""
    fees = db.session.query(
        FeeRecord.payment_method, db.func.sum(FeeRecord.amount_paid)
    ).group_by(FeeRecord.payment_method).all()
    exp = db.session.query(
        Expense.payment_method, db.func.sum(Expense.amount)
    ).group_by(Expense.payment_method).all()
    fund = db.session.query(
        OwnerFunding.method, db.func.sum(OwnerFunding.amount)
    ).group_by(OwnerFunding.method).all()

    balances = {}
    fees_total = fees + fund
    for method, total in fees_total:
        k = normalize_method(method)
        if k:
            bucket = balances.setdefault(k, {'income': 0.0, 'expense': 0.0, 'count': 0})
            bucket['income'] += float(total or 0)
            bucket['count'] += 1
    for method, total in exp:
        k = normalize_method(method)
        if k:
            bucket = balances.setdefault(k, {'income': 0.0, 'expense': 0.0, 'count': 0})
            bucket['expense'] += float(total or 0)
            bucket['count'] += 1
    return balances


def compute_account_summary():
    """Per-account balance cards. Balances are derived live from source records."""
    ensure_default_accounts()
    raw = _raw_balances()
    accounts = Account.query.order_by(Account.id).all()

    # Distribute each observed method into its matching account, folding
    # unmatched methods into the generic 'Others' account.
    assigned = {acc.name: {'income': 0.0, 'expense': 0.0, 'count': 0} for acc in accounts}
    used_methods = set()

    def match_account(method):
        if not method:
            return 'Others'
        for acc in accounts:
            if normalize_method(acc.name) == method:
                return acc.name
        for acc in accounts:
            aname = normalize_method(acc.name)
            if aname in ('others', 'upi'):
                continue
            if method.startswith(aname) or aname in method:
                return acc.name
        return 'Others'

    for method, b in raw.items():
        aname = match_account(method)
        used_methods.add(aname)
        assigned[aname]['income'] += b['income']
        assigned[aname]['expense'] += b['expense']
        assigned[aname]['count'] += b.get('count', 1)

    summary = []
    for acc in accounts:
        b = assigned[acc.name]
        income = b['income']
        expense = b['expense']
        summary.append({
            'id': acc.id,
            'name': acc.name,
            'account_type': acc.account_type,
            'opening_balance': round(acc.opening_balance, 2),
            'income': round(income, 2),
            'expense': round(expense, 2),
            'balance': round(acc.opening_balance + income - expense, 2),
            'txn_count': b.get('count', 0),
            'is_active': acc.is_active,
        })
    summary.sort(key=lambda r: (not r['is_active'], r['name'] in ('Others', 'UPI'), r['name']))
    return summary


def matching_methods(account_name):
    """All distinct payment_method values (normalized) that roll into `account_name`."""
    ensure_default_accounts()
    accounts = Account.query.order_by(Account.id).all()

    def match_account(method):
        if not method:
            return 'Others'
        for acc in accounts:
            if normalize_method(acc.name) == method:
                return acc.name
        for acc in accounts:
            aname = normalize_method(acc.name)
            if aname in ('others', 'upi'):
                continue
            if method.startswith(aname) or aname in method:
                return acc.name
        return 'Others'

    observed = set()
    for (m,) in db.session.query(FeeRecord.payment_method).all():
        if m:
            observed.add(normalize_method(m))
    for (m,) in db.session.query(Expense.payment_method).all():
        if m:
            observed.add(normalize_method(m))
    for (m,) in db.session.query(OwnerFunding.method).all():
        if m:
            observed.add(normalize_method(m))
    target = normalize_method(account_name)
    return [m for m in observed if match_account(m) == target or (not target and match_account(m) == 'Others')]


def account_breakdown(account_name):
    """Ledger rows (income + expense + funding) for one account."""
    methods = matching_methods(account_name)
    if not methods:
        return {'income': [], 'expenses': [], 'funding': []}

    fee_q = FeeRecord.query
    exp_q = Expense.query
    fund_q = OwnerFunding.query
    ors_fee = db.or_(*(db.func.lower(db.func.coalesce(FeeRecord.payment_method, '')) == m for m in methods))
    ors_exp = db.or_(*(db.func.lower(db.func.coalesce(Expense.payment_method, '')) == m for m in methods))
    ors_fund = db.or_(*(db.func.lower(db.func.coalesce(OwnerFunding.method, '')) == m for m in methods))

    fees = fee_q.filter(ors_fee).order_by(FeeRecord.payment_date.desc()).all()
    exp = exp_q.filter(ors_exp).order_by(Expense.expense_date.desc()).all()
    fund = fund_q.filter(ors_fund).order_by(OwnerFunding.funding_date.desc()).all()
    return {'income': fees, 'expenses': exp, 'funding': fund}
