from app.extensions import db
from app.models import Account, FeeRecord, Expense, OwnerFunding, Company
from .payment_methods import DEFAULT_ACCOUNTS, classify_method


def normalize_method(method):
    return (method or '').strip().lower()


def ensure_default_companies():
    c1 = Company.query.filter_by(code='COMP-GST').first()
    if not c1:
        c1 = Company(
            name='Guha Tech Solutions (GST)',
            code='COMP-GST',
            is_gst_registered=True,
            gstin='33ABCDE1234F1Z5',
            address='123 Tech Park, Anna Salai, Chennai, TN',
            phone='9876543210',
            email='billing@guhatech.com',
            invoice_prefix='GTS-GST/'
        )
        db.session.add(c1)
    
    c2 = Company.query.filter_by(code='COMP-NGST').first()
    if not c2:
        c2 = Company(
            name='Guha Tech Institute (Non-GST)',
            code='COMP-NGST',
            is_gst_registered=False,
            gstin=None,
            address='456 Academy Road, Anna Salai, Chennai, TN',
            phone='9876543211',
            email='info@guhainstitute.com',
            invoice_prefix='GTS-NGST/'
        )
        db.session.add(c2)
    db.session.commit()
    return c1, c2


def ensure_default_accounts():
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
            for acc in Account.query.filter(Account.company_id.is_(None)).all():
                acc.company_id = c1.id if 'Bank' in acc.name or 'Card' in acc.name else c2.id
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
    ).group_by(FeeRecord.payment_method).all()
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


def compute_account_summary():
    """Per-account balance cards. Balances are derived live from source records."""
    ensure_default_accounts()
    raw = _raw_balances()
    accounts = Account.query.order_by(Account.id).all()

    # Distribute each observed method into its matching account, folding
    # unmatched methods into the generic 'Others' account.
    assigned = {acc.name: {'income': 0.0, 'expense': 0.0, 'count': 0} for acc in accounts}
    used_methods = set()

    for method, b in raw.items():
        aname = classify_method(method)
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
            'company_id': acc.company_id,
            'company_name': acc.company.name if acc.company else 'Unassigned',
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
        return classify_method(method)

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
