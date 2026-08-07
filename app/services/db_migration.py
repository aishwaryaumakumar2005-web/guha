import json
from sqlalchemy import inspect, text
from app.extensions import db

RENAMES = {
    'UPI - Guha India': 'Current Account',
    'UPI - Ejaj Sir': 'Savings Account',
}


def _renamed(value):
    if not value:
        return value
    for old, new in RENAMES.items():
        if value == old:
            return new
    return value


def _rename_json(changes):
    """Rewrite JSON stored in audit_log.changes so old account names become new."""
    if not changes:
        return changes
    try:
        obj = json.loads(changes)
    except (ValueError, TypeError):
        return changes
    changed = False

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if isinstance(v, str) and v in RENAMES:
                    node[k] = RENAMES[v]
                    changed = True
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    if changed:
        return json.dumps(obj, ensure_ascii=False)
    return changes


def _has_column(table, column):
    """Return True if `table` exists and has `column` (works on SQLite and Postgres)."""
    try:
        insp = inspect(db.engine)
        if table not in insp.get_table_names():
            return False
        return any(c['name'] == column for c in insp.get_columns(table))
    except Exception:
        return False


def _table_exists(table):
    try:
        return table in inspect(db.engine).get_table_names()
    except Exception:
        return False


def migrate_renames():
    """Rename old account names to their new canonical names in all persisted data.

    Idempotent: safe to run on every startup. Ports to SQLite and PostgreSQL.
    Covers account rows, payment-method columns on fee/expense/payroll/funding
    records, and JSON inside audit_log. Tables/columns that do not exist are
    skipped without rolling back other work.
    """
    for old, new in RENAMES.items():
        # account table (name is unique; drop the newly-created duplicate first so
        # the old row can be renamed into place without a uniqueness conflict)
        old_row = db.session.execute(text("SELECT id FROM account WHERE name = :n"), {'n': old}).fetchone()
        new_row = db.session.execute(text("SELECT id FROM account WHERE name = :n"), {'n': new}).fetchone()
        if old_row:
            if new_row:
                db.session.execute(text("DELETE FROM account WHERE id = :id"), {'id': new_row.id})
            db.session.execute(text("UPDATE account SET name = :new WHERE name = :old"),
                               {'new': new, 'old': old})

        # payment-method columns (skip missing tables/columns silently)
        for table, col in [('fee_record', 'payment_method'),
                           ('expense', 'payment_method'),
                           ('payroll_record', 'payment_method'),
                           ('owner_funding', 'method')]:
            if _has_column(table, col):
                db.session.execute(
                    text('UPDATE "%s" SET "%s" = :new WHERE "%s" = :old' % (table, col, col)),
                    {'new': new, 'old': old})

        # audit_log JSON (skip if table/column missing)
        if _has_column('audit_log', 'changes'):
            rows = db.session.execute(
                text("SELECT id, changes FROM audit_log WHERE changes LIKE :pat"),
                {'pat': '%' + old + '%'}
            ).fetchall()
            for rid, changes in rows:
                updated = _rename_json(changes)
                if updated != changes:
                    db.session.execute(text("UPDATE audit_log SET changes = :c WHERE id = :id"),
                                       {'c': updated, 'id': rid})

    db.session.commit()