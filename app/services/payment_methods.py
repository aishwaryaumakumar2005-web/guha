# Single source of truth for payment methods across the whole app.
# All dropdowns, reports, account bucketing and Tally/Zoho exports must
# derive from these constants so a given string lands in the same bucket
# everywhere.

PAYMENT_METHODS = [
    'Cash',
    'Current Account',
    'Savings Account',
    'UPI',
    'Bank Transfer',
    'Card',
]

DEFAULT_PAYMENT_METHOD = 'Cash'

# Human-friendly labels shown in dropdowns.
METHOD_LABELS = {
    'Cash': 'Cash Handover',
    'Current Account': 'Current Account',
    'Savings Account': 'Savings Account',
    'UPI': 'UPI / Digital Wallet',
    'Bank Transfer': 'Direct Bank Wire',
    'Card': 'Credit/Debit Card',
}

# Accounts seeded on startup when the account table is empty. The account
# names are exactly the canonical PAYMENT_METHODS plus the Others fallback.
DEFAULT_ACCOUNTS = [
    ('Cash', 'Cash'),
    ('Current Account', 'UPI'),
    ('Savings Account', 'UPI'),
    ('UPI', 'UPI'),
    ('Bank Transfer', 'Bank'),
    ('Card', 'Card'),
    ('Others', 'Other'),
]

# Ledger name used by the Tally export for each method. Cash stays Cash,
# everything else is booked through the bank.
TALLY_ACCOUNT_FOR_METHOD = {m: ('Cash' if m == 'Cash' else 'Bank') for m in PAYMENT_METHODS}

# Grouping (order) used to render every payment-mode dropdown into optgroups.
METHOD_GROUPS = [
    ('Cash', ['Cash']),
    ('UPI Accounts', ['Current Account', 'Savings Account', 'UPI']),
    ('Bank', ['Bank Transfer']),
    ('Cards', ['Card']),
]

# Bootstrap icon name per account type (shared by dropdowns, cards, reports).
ACCOUNT_TYPE_ICONS = {
    'Cash': 'cash',
    'UPI': 'phone',
    'Bank': 'bank',
    'Card': 'credit-card',
    'Other': 'wallet-fill',
}

# Consistent, accent-safe colors per canonical method. Used by Reports and
# Accounts so a given method always renders the same color across the app.
METHOD_COLORS = {
    'Cash': '#00BFA6',
    'Current Account': '#29B6F6',
    'Savings Account': '#F06292',
    'UPI': '#7986CB',
    'Bank Transfer': '#FFA726',
    'Card': '#AB47BC',
    'Others': '#FFC107',
}

# Map canonical method -> account type (drives icon/color in UI).
METHOD_TYPE = {
    'Cash': 'Cash',
    'Current Account': 'UPI',
    'Savings Account': 'UPI',
    'UPI': 'UPI',
    'Bank Transfer': 'Bank',
    'Card': 'Card',
    'Others': 'Other',
}


def method_icon(method):
    """Bootstrap icon name for a canonical method (falls back to Other)."""
    return ACCOUNT_TYPE_ICONS.get(METHOD_TYPE.get(method, 'Other'), 'wallet-fill')


def normalize_method(method):
    return (method or '').strip().lower()


def classify_method(method):
    """Map a raw payment-method string to its canonical account name.

    Exact match wins, then a conservative substring match (generic 'UPI'
    is excluded from substring matching so the specific UPI variants do
    not fold into it). Anything unknown rolls into 'Others'.
    """
    key = normalize_method(method)
    if not key:
        return 'Others'
    for m in PAYMENT_METHODS:
        if normalize_method(m) == key:
            return m
    for m in PAYMENT_METHODS:
        if m == 'UPI':
            continue
        mn = normalize_method(m)
        if mn in key or key in mn:
            return m
    return 'Others'
