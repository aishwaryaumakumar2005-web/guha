import json
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


def migrate_renames():
    """Rename old account names to their new canonical names in all persisted data.

    Idempotent: safe to run on every startup. Covers account rows, payment-method
    columns on fee/expense/payroll/funding records, and JSON inside audit_log.
    """
    for old, new in RENAMES.items():
        # account table (name is unique; drop the newly-created duplicate first so
        # the old row can be renamed into place without a uniqueness conflict)
        old_row = db.session.execute(db.text("SELECT id FROM account WHERE name = :n"), {'n': old}).fetchone()
        new_row = db.session.execute(db.text("SELECT id FROM account WHERE name = :n"), {'n': new}).fetchone()
        if old_row:
            if new_row:
                db.session.execute(db.text("DELETE FROM account WHERE id = :id"), {'id': new_row.id})
            db.session.execute(db.text("UPDATE account SET name = :new WHERE name = :old"), {'new': new, 'old': old})

        # payment-method columns
        for table, col in [('fee_record', 'payment_method'),
                           ('expense', 'payment_method'),
                           ('payroll_record', 'payment_method'),
                           ('owner_funding', 'method')]:
            try:
                db.session.execute(db.text("UPDATE [%s] SET [%s] = :new WHERE [%s] = :old" % (table, col, col)),
                                   {'new': new, 'old': old})
            except Exception:
                db.session.rollback()

        # audit_log JSON
        try:
            rows = db.session.execute(
                db.text("SELECT id, changes FROM audit_log WHERE changes LIKE :pat"),
                {'pat': '%' + old + '%'}
            ).fetchall()
            for rid, changes in rows:
                updated = _rename_json(changes)
                if updated != changes:
                    db.session.execute(db.text("UPDATE audit_log SET changes = :c WHERE id = :id"),
                                       {'c': updated, 'id': rid})
        except Exception:
            db.session.rollback()

    db.session.commit()
