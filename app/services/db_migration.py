import json
import os
from sqlalchemy import inspect, text
from app.extensions import db

RENAMES = {
    'UPI - Guha India': 'Current Account',
    'UPI - Ejaj Sir': 'Savings Account',
}

_renames_done = False

# Canonical company details, keyed by stable company code. Idempotent and
# safe to apply on every startup; existing rows are updated in place.
COMPANY_RENAMES = {
    'COMP-GST': {
        'name': 'GUHA INDUSTRIAL SOLUTIONS (GST)',
        'address': '1st floor, KKG Complex, SPT Mani Nagar, Gandhi Nagar Post, Arch Gate, Neyveli, Tamilnadu 607308, India',
        'gstin': '33ABAFG1922E1Z2',
        'phone': '8248779596',
        'email': 'md@guhaindia.in',
    },
    'COMP-NGST': {
        'name': 'YAZH ACADEMY (NON GST)',
        'address': '1st floor, KKG Complex, SPT Mani Nagar, Gandhi Nagar Post, Arch Gate, Neyveli, Tamilnadu 607308, India',
        'gstin': None,
        'phone': '8248779596',
        'email': 'md@guhaindia.in',
    },
}

_company_renames_done = False


def _renamed(value):
    if not value:
        return value
    for old, new in RENAMES.items():
        if value == old:
            return new
    return value


def _rename_json(changes, mapping=None):
    """Rewrite JSON stored in audit_log.changes so old names become new."""
    if not changes:
        return changes
    try:
        obj = json.loads(changes)
    except (ValueError, TypeError):
        return changes
    mapping = mapping if mapping is not None else RENAMES
    changed = False

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if isinstance(v, str) and v in mapping:
                    node[k] = mapping[v]
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


def _has_index(table, column):
    """Return True if an index covering `column` exists on `table` (SQLite + Postgres)."""
    try:
        insp = inspect(db.engine)
        for idx in insp.get_indexes(table):
            if column in (idx.get('column_names') or []):
                return True
        return False
    except Exception:
        return True


def _ensure_column_index(table, column):
    """Create a plain index on a column if it doesn't already exist (idempotent)."""
    if not _table_exists(table):
        return
    if _has_column(table, column) and not _has_index(table, column):
        try:
            db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_%s_%s ON "%s" ("%s")' % (table, column, table, column)))
            db.session.commit()
        except Exception:
            db.session.rollback()


def migrate_indexes():
    """Add indexes for frequently-filtered columns used by finance/account pages."""
    for table, col, extra in [
        ('fee_record', 'payment_method', 'idx_fee_payment_method'),
        ('expense', 'payment_method', 'idx_expense_payment_method'),
        ('owner_funding', 'method', 'idx_funding_method'),
        ('payroll_record', 'payment_method', 'idx_payroll_payment_method'),
    ]:
        if _table_exists(table) and _has_column(table, col):
            try:
                db.session.execute(text('CREATE INDEX IF NOT EXISTS %s ON "%s" ("%s")' % (extra, table, col)))
                db.session.commit()
            except Exception:
                db.session.rollback()


def migrate_renames():
    """Rename old account names to their new canonical names in all persisted data.

    Idempotent: safe to run on every startup. Ports to SQLite and PostgreSQL.
    Covers account rows, payment-method columns on fee/expense/payroll/funding
    records, and JSON inside audit_log. Tables/columns that do not exist are
    skipped without rolling back other work.
    """
    global _renames_done
    if _renames_done:
        return
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
    _renames_done = True


def migrate_company_names():
    """Rename the two seeded companies to their canonical names by code.

    Idempotent: safe to run on every startup. Renames existing company rows
    (matched on the stable `code` column) and rewrites old names inside
    audit_log JSON. Works on SQLite and PostgreSQL.
    """
    global _company_renames_done
    if _company_renames_done:
        return
    if not _has_column('company', 'name') or not _has_column('company', 'code'):
        _company_renames_done = True
        return
    old_by_code = {row.code: row.name for row in db.session.execute(
        text("SELECT code, name FROM company WHERE code IN ('COMP-GST', 'COMP-NGST')")
    ).fetchall()}
    for code, details in COMPANY_RENAMES.items():
        old_name = old_by_code.get(code)
        new_name = details['name']
        db.session.execute(
            text("UPDATE company SET name = :new, address = :address, gstin = :gstin, "
                 "phone = :phone, email = :email WHERE code = :code"),
            {'new': new_name, 'address': details['address'], 'gstin': details['gstin'],
             'phone': details['phone'], 'email': details['email'], 'code': code})
        # Rewrite old company names inside audit_log JSON changes
        if old_name and old_name != new_name and _has_column('audit_log', 'changes'):
            rows = db.session.execute(
                text("SELECT id, changes FROM audit_log WHERE changes LIKE :pat"),
                {'pat': '%' + old_name + '%'}
            ).fetchall()
            for rid, changes in rows:
                updated = _rename_json(changes, {old_name: new_name})
                if updated != changes:
                    db.session.execute(text("UPDATE audit_log SET changes = :c WHERE id = :id"),
                                       {'c': updated, 'id': rid})
    db.session.commit()
    _company_renames_done = True


def migrate_schema_additions():
    """Add dashboard-required columns that DB create_all/ALTER cannot add to existing tables.

    Idempotent and safe to run on every startup. Adds:
      - course.capacity      (course seat capacity for utilization card)
      - student.date_of_birth (birthday wishes card)
    Works on SQLite and PostgreSQL.
    """
    additions = [
        ('course', 'capacity', 'INTEGER'),
        ('student', 'date_of_birth', 'DATE'),
    ]
    for table, column, col_type in additions:
        if _table_exists(table) and not _has_column(table, column):
            try:
                db.session.execute(text('ALTER TABLE "%s" ADD COLUMN "%s" %s' % (table, column, col_type)))
                db.session.commit()
            except Exception:
                db.session.rollback()


def migrate_photos_to_db():
    """Copy any file-based photos (photo filename set, photo_data empty) into the DB.

    One-time backfill for photos uploaded before DB storage was introduced. Skips
    rows that already have photo_data, and ignores files that no longer exist.
    """
    from flask import current_app
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    migrated = 0
    for table in ('student', 'tutor'):
        # Ensure the new DB-storage columns exist (create_all does not ALTER existing tables)
        if _has_column(table, 'photo') and not _has_column(table, 'photo_data'):
            bin_type = 'BYTEA' if db.engine.dialect.name == 'postgresql' else 'BLOB'
            db.session.execute(text('ALTER TABLE "%s" ADD COLUMN photo_data %s' % (table, bin_type)))
            db.session.execute(text('ALTER TABLE "%s" ADD COLUMN photo_mime VARCHAR(50)' % table))
            db.session.commit()
        if not _has_column(table, 'photo') or not _has_column(table, 'photo_data'):
            continue
        rows = db.session.execute(
            text('SELECT id, photo FROM "%s" WHERE photo IS NOT NULL AND photo != \'\' AND photo_data IS NULL' % table)
        ).fetchall()
        for rid, filename in rows:
            if not filename:
                continue
            path = os.path.join(upload_dir, filename)
            if not os.path.exists(path):
                continue
            with open(path, 'rb') as fh:
                data = fh.read()
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            mime = f'image/{ext if ext != "jpg" else "jpeg"}'
            db.session.execute(
                text('UPDATE "%s" SET photo_data = :d, photo_mime = :m WHERE id = :id' % table),
                {'d': data, 'm': mime, 'id': rid}
            )
            migrated += 1
    if migrated:
        db.session.commit()
    return migrated