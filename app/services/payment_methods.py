# Single source of truth for payment methods across the whole app.
# All dropdowns, reports, account bucketing and Tally/Zoho exports must
# derive from these constants so a given string lands in the same bucket
# everywhere.

PAYMENT_METHODS = [
    'Cash',
    'UPI - Guha India',
    'UPI - Ejaj Sir',
    'UPI',
    'Bank Transfer',
    'Card',
]

DEFAULT_PAYMENT_METHOD = 'Cash'

# Human-friendly labels shown in dropdowns.
METHOD_LABELS = {
    'Cash': 'Cash Handover',
    'UPI - Guha India': 'UPI - Guha India',
    'UPI - Ejaj Sir': 'UPI - Ejaj Sir',
    'UPI': 'UPI / Digital Wallet',
    'Bank Transfer': 'Direct Bank Wire',
    'Card': 'Credit/Debit Card',
}

# Accounts seeded on startup when the account table is empty. The account
# names are exactly the canonical PAYMENT_METHODS plus the Others fallback.
DEFAULT_ACCOUNTS = [
    ('Cash', 'Cash'),
    ('UPI - Guha India', 'UPI'),
    ('UPI - Ejaj Sir', 'UPI'),
    ('UPI', 'UPI'),
    ('Bank Transfer', 'Bank'),
    ('Card', 'Card'),
    ('Others', 'Other'),
]

# Ledger name used by the Tally export for each method. Cash stays Cash,
# everything else is booked through the bank.
TALLY_ACCOUNT_FOR_METHOD = {m: ('Cash' if m == 'Cash' else 'Bank') for m in PAYMENT_METHODS}


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
