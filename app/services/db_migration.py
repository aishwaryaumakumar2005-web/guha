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
    """Add indexes for frequently-filtered directory and finance columns."""
    for table, col, extra in [
        ('fee_record', 'payment_method', 'idx_fee_payment_method'),
        ('fee_record', 'company_id', 'idx_fee_company'),
        ('expense', 'payment_method', 'idx_expense_payment_method'),
        ('owner_funding', 'method', 'idx_funding_method'),
        ('payroll_record', 'payment_method', 'idx_payroll_payment_method'),
        ('student', 'status', 'idx_student_status'),
        ('student', 'name', 'idx_student_name'),
        ('student', 'phone', 'idx_student_phone'),
        ('student_courses', 'status', 'idx_student_courses_status'),
        ('student_courses', 'course_id', 'idx_student_courses_course'),
    ]:
        if _table_exists(table) and _has_column(table, col):
            try:
                db.session.execute(text('CREATE INDEX IF NOT EXISTS %s ON "%s" ("%s")' % (extra, table, col)))
                db.session.commit()
            except Exception:
                db.session.rollback()


def migrate_course_lifecycle_columns():
    """Add additive course lifecycle fields for legacy databases."""
    if not _table_exists('course'):
        return
    for column, sql_type, default in [
        ('status', 'VARCHAR(20)', "'Active'"),
        ('start_date', 'DATE', None),
        ('end_date', 'DATE', None),
    ]:
        if not _has_column('course', column):
            try:
                suffix = f' DEFAULT {default}' if default else ''
                db.session.execute(text(f'ALTER TABLE "course" ADD COLUMN "{column}" {sql_type}{suffix}'))
                db.session.commit()
            except Exception:
                db.session.rollback()


def migrate_attendance_provenance_column():
    """Widen attendance.marked_by for tutor IDs and audit sources."""
    if not _table_exists('attendance'):
        return
    try:
        if db.engine.dialect.name == 'postgresql':
            db.session.execute(text('ALTER TABLE "attendance" ALTER COLUMN "marked_by" TYPE VARCHAR(50)'))
        elif db.engine.dialect.name == 'mysql':
            db.session.execute(text('ALTER TABLE attendance MODIFY marked_by VARCHAR(50)'))
        else:
            # SQLite does not enforce VARCHAR lengths; no rebuild is needed.
            return
        db.session.commit()
    except Exception:
        db.session.rollback()


def migrate_exam_status_column():
    """Add the non-destructive exam lifecycle status."""
    if not _table_exists('exam') or _has_column('exam', 'status'):
        return
    try:
        db.session.execute(text("ALTER TABLE \"exam\" ADD COLUMN \"status\" VARCHAR(20) DEFAULT 'Active'"))
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
    Works on SQLite and PostgreSQL. NOTE: PostgreSQL has no DATETIME type,
    so timestamp columns use TIMESTAMP there (DATETIME on SQLite). A previous
    version used DATETIME unconditionally, which failed silently on Postgres
    and left enquiry.last_contacted_at / enquiry.updated_at missing.
    """
    ts_type = 'TIMESTAMP' if db.engine.dialect.name == 'postgresql' else 'DATETIME'
    additions = [
        ('course', 'capacity', 'INTEGER'),
        ('student', 'date_of_birth', 'DATE'),
        ('enquiry', 'last_contacted_at', ts_type),
        ('enquiry', 'converted_student_id', 'INTEGER'),
        ('enquiry', 'updated_at', ts_type),
    ]
    for table, column, col_type in additions:
        if _table_exists(table) and not _has_column(table, column):
            try:
                db.session.execute(text('ALTER TABLE "%s" ADD COLUMN "%s" %s' % (table, column, col_type)))
                db.session.commit()
            except Exception as e:
                # Never swallow DDL failures silently: a failed column add
                # leaves the app selecting a non-existent column (500s).
                db.session.rollback()
                print(f"Migration migrate_schema_additions: FAILED to add {table}.{column}: {e}", flush=True)


def migrate_exam_window_columns():
    """Add exam.available_from / exam.available_until (nullable) on existing DBs.

    The ORM maps these columns, so a database created before they existed (e.g. a
    Postgres/Neon DB restored from an old backup) 500s on every exam query until
    the columns are added. Idempotent and additive-only: skips columns that
    already exist, works on SQLite and PostgreSQL, and logs loudly on failure.
    """
    if not _table_exists('exam'):
        return
    for column, col_type in [('available_from', 'DATE'), ('available_until', 'DATE')]:
        if not _has_column('exam', column):
            try:
                db.session.execute(text('ALTER TABLE "exam" ADD COLUMN "%s" %s' % (column, col_type)))
                db.session.commit()
                print(f"Migration migrate_exam_window_columns: added exam.{column}", flush=True)
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_exam_window_columns: FAILED to add exam.{column}: {e}", flush=True)


def migrate_leave_action_columns():
    """Add leave_request.approved_by / actioned_at / remarks (all nullable).

    The ORM maps these columns, so a database created before they existed (e.g. a
    Postgres/Neon DB restored from an old backup) 500s on every leave_request
    query until the columns are added. Idempotent and additive-only: skips columns
    that already exist, works on SQLite and PostgreSQL, and logs loudly on failure.
    """
    if not _table_exists('leave_request'):
        return
    ts_type = 'TIMESTAMP' if db.engine.dialect.name == 'postgresql' else 'DATETIME'
    for column, col_type in [('approved_by', 'INTEGER'), ('actioned_at', ts_type), ('remarks', 'TEXT')]:
        if not _has_column('leave_request', column):
            try:
                db.session.execute(text('ALTER TABLE "leave_request" ADD COLUMN "%s" %s' % (column, col_type)))
                db.session.commit()
                print(f"Migration migrate_leave_action_columns: added leave_request.{column}", flush=True)
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_leave_action_columns: FAILED to add leave_request.{column}: {e}", flush=True)


def migrate_leave_type_column():
    """Add leave_request.leave_type (nullable) on existing DBs.

    The ORM maps this column, so databases created before leave types existed
    (e.g. a Postgres/Neon DB restored from an old backup) 500 on every
    leave_request query until it is added. Idempotent and additive-only: skips
    the column when it already exists, works on SQLite and PostgreSQL, and
    logs loudly on failure. Legacy rows keep a NULL value, which the app
    renders as the default leave type.
    """
    if not _table_exists('leave_request'):
        return
    if not _has_column('leave_request', 'leave_type'):
        try:
            db.session.execute(text('ALTER TABLE "leave_request" ADD COLUMN "leave_type" VARCHAR(20)'))
            db.session.commit()
            print("Migration migrate_leave_type_column: added leave_request.leave_type", flush=True)
        except Exception as e:
            db.session.rollback()
            print(f"Migration migrate_leave_type_column: FAILED to add leave_request.leave_type: {e}", flush=True)


def migrate_fee_created_by_column():
    """Add fee_record.created_by (nullable) on existing DBs.

    The ORM maps this column, so databases created before it existed (e.g. a
    Postgres/Neon DB restored from an old backup) 500 on every fee query
    until it is added. Idempotent and additive-only: skips the column when it
    already exists, works on SQLite and PostgreSQL, and logs loudly on
    failure. Legacy rows keep NULL (collector unknown).
    """
    if not _table_exists('fee_record'):
        return
    if not _has_column('fee_record', 'created_by'):
        try:
            db.session.execute(text('ALTER TABLE "fee_record" ADD COLUMN "created_by" INTEGER'))
            db.session.commit()
            print("Migration migrate_fee_created_by_column: added fee_record.created_by", flush=True)
        except Exception as e:
            db.session.rollback()
            print(f"Migration migrate_fee_created_by_column: FAILED to add fee_record.created_by: {e}", flush=True)


def migrate_fee_concession_column():
    """Add fee_record.concession (nullable float) on existing DBs.

    Same self-heal rationale as the other fee_record columns: the ORM maps
    it, so legacy databases 500 on fee queries until it exists. Idempotent
    and additive-only. Legacy rows keep NULL, read as 0 (no waiver).
    """
    if not _table_exists('fee_record'):
        return
    if not _has_column('fee_record', 'concession'):
        try:
            db.session.execute(text('ALTER TABLE "fee_record" ADD COLUMN "concession" FLOAT'))
            db.session.commit()
            print("Migration migrate_fee_concession_column: added fee_record.concession", flush=True)
        except Exception as e:
            db.session.rollback()
            print(f"Migration migrate_fee_concession_column: FAILED to add fee_record.concession: {e}", flush=True)


def migrate_fee_audit_columns():
    """Add immutable financial-transaction void/audit fields."""
    if not _table_exists('fee_record'):
        return
    ts_type = 'TIMESTAMP' if db.engine.dialect.name == 'postgresql' else 'DATETIME'
    for column, col_type in [
        ('status', "VARCHAR(20) DEFAULT 'Active'"),
        ('voided_at', ts_type),
        ('voided_by', 'INTEGER'),
        ('void_reason', 'VARCHAR(300)'),
    ]:
        if not _has_column('fee_record', column):
            try:
                db.session.execute(text('ALTER TABLE "fee_record" ADD COLUMN "%s" %s' % (column, col_type)))
                db.session.commit()
                print(f"Migration migrate_fee_audit_columns: added fee_record.{column}", flush=True)
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_fee_audit_columns: FAILED to add fee_record.{column}: {e}", flush=True)
    try:
        db.session.execute(text("UPDATE fee_record SET status = 'Active' WHERE status IS NULL"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration migrate_fee_audit_columns: FAILED to backfill status: {e}", flush=True)


def migrate_payroll_commission_breakdown_column():
    """Add payroll_record.commission_breakdown (nullable JSON text).

    E1: per-student commission detail. The ORM maps it, so legacy databases
    need the column before payroll pages or that column's ORM mapper touches
    the table. Idempotent and additive-only; legacy rows keep NULL (= no
    breakdown captured at processing time, rendered as absent).
    """
    if not _table_exists('payroll_record'):
        return
    if not _has_column('payroll_record', 'commission_breakdown'):
        try:
            db.session.execute(text('ALTER TABLE "payroll_record" ADD COLUMN "commission_breakdown" TEXT'))
            db.session.commit()
            print("Migration migrate_payroll_commission_breakdown_column: added payroll_record.commission_breakdown", flush=True)
        except Exception as e:
            db.session.rollback()
            print(f"Migration migrate_payroll_commission_breakdown_column: FAILED to add column: {e}", flush=True)


def migrate_agreed_dues_columns():
    """Add agreed_fee / agreed_gst / agreed_company_id to student_courses.

    W2: dues are agreed at enrollment; catalog edits affect new enrollments
    only. Idempotent and additive-only. After adding, backfills every NULL
    row from the live course row — freezing today's prices as the baseline,
    so deploying changes no visible dues. Legacy BOOLEAN arrives as 0/1 on
    SQLite, True/False on Postgres; readers must use IS NULL checks, never
    truthiness, to distinguish "no snapshot" from "GST-exempt".
    """
    if not _table_exists('student_courses'):
        return
    for column, col_type in [('agreed_fee', 'FLOAT'),
                             ('agreed_gst', 'BOOLEAN'),
                             ('agreed_company_id', 'INTEGER')]:
        if not _has_column('student_courses', column):
            try:
                db.session.execute(text('ALTER TABLE "student_courses" ADD COLUMN "%s" %s' % (column, col_type)))
                db.session.commit()
                print(f"Migration migrate_agreed_dues_columns: added student_courses.{column}", flush=True)
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_agreed_dues_columns: FAILED to add student_courses.{column}: {e}", flush=True)
                return
    try:
        db.session.execute(text(
            'UPDATE "student_courses" SET "agreed_fee" = '
            '(SELECT "fees" FROM "course" WHERE "course"."id" = "student_courses"."course_id"), '
            '"agreed_gst" = (SELECT "gst_applicable" FROM "course" WHERE "course"."id" = "student_courses"."course_id"), '
            '"agreed_company_id" = (SELECT "company_id" FROM "course" WHERE "course"."id" = "student_courses"."course_id") '
            'WHERE "agreed_fee" IS NULL'
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration migrate_agreed_dues_columns: FAILED to backfill: {e}", flush=True)


def migrate_expense_student_id():
    """Add student_id to expense (W3 refund link).

    Nullable FK ON DELETE SET NULL; index added inline with the existing
    __table_args__ pattern. Backfill is not needed: only new refund expenses
    use this column. Idempotent.
    """
    if not _table_exists('expense'):
        return
    if not _has_column('expense', 'student_id'):
        try:
            db.session.execute(text('ALTER TABLE "expense" ADD COLUMN "student_id" INTEGER'))
            db.session.commit()
            print("Migration migrate_expense_student_id: added expense.student_id", flush=True)
        except Exception as e:
            db.session.rollback()
            print(f"Migration migrate_expense_student_id: FAILED: {e}", flush=True)


def migrate_expense_enhancements():
    """Add expense enhancement columns (company attribution, payment ref,
    receipt attachment) and expense_category budget/archive flags.

    All columns are nullable or defaulted, so existing rows need no backfill.
    Index for the company filter added inline. Idempotent, SQLite-safe.
    """
    if _table_exists('expense'):
        blob = 'BYTEA' if db.engine.dialect.name == 'postgresql' else 'BLOB'
        timestamp_type = 'TIMESTAMP' if db.engine.dialect.name == 'postgresql' else 'DATETIME'
        for col, ctype in [
            ('company_id', 'INTEGER'),
            ('payment_ref', 'VARCHAR(100)'),
            ('attachment_data', blob),
            ('attachment_mime', 'VARCHAR(50)'),
            ('attachment_name', 'VARCHAR(255)'),
            ('status', "VARCHAR(20) DEFAULT 'Active'"),
            ('voided_at', timestamp_type),
            ('voided_by', 'INTEGER'),
            ('void_reason', 'VARCHAR(300)'),
        ]:
            if not _has_column('expense', col):
                try:
                    db.session.execute(text('ALTER TABLE "expense" ADD COLUMN "%s" %s' % (col, ctype)))
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"Migration migrate_expense_enhancements: ADD expense.{col} FAILED: {e}", flush=True)
        _ensure_column_index('expense', 'company_id')
        try:
            db.session.execute(text('UPDATE "expense" SET "status" = \'Active\' WHERE "status" IS NULL'))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Migration migrate_expense_enhancements: status backfill FAILED: {e}", flush=True)
    if _table_exists('expense_category'):
        if not _has_column('expense_category', 'budget_limit'):
            try:
                db.session.execute(text('ALTER TABLE "expense_category" ADD COLUMN "budget_limit" FLOAT'))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_expense_enhancements: ADD expense_category.budget_limit FAILED: {e}", flush=True)
        if not _has_column('expense_category', 'is_active'):
            default = 'TRUE' if db.engine.dialect.name == 'postgresql' else '1'
            try:
                db.session.execute(text('ALTER TABLE "expense_category" ADD COLUMN "is_active" BOOLEAN DEFAULT %s' % default))
                db.session.commit()
                # SQLite keeps NULL for legacy rows after ADD COLUMN DEFAULT;
                # normalize them so archiving logic sees a real boolean.
                db.session.execute(text('UPDATE "expense_category" SET "is_active" = %s WHERE "is_active" IS NULL' % default))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_expense_enhancements: ADD expense_category.is_active FAILED: {e}", flush=True)


def migrate_lifecycle_ack_table():
    """Create the lifecycle_ack table on legacy databases.

    The ORM maps it (fresh databases get it from db.create_all()), so an older
    database would otherwise 500 on every lifecycle page that queries ack
    state. Idempotent and additive-only: skips when the table already exists,
    works on SQLite and PostgreSQL, and logs loudly on failure.
    """
    if _table_exists('lifecycle_ack'):
        return
    try:
        ts = 'TIMESTAMP' if db.engine.dialect.name == 'postgresql' else 'DATETIME'
        db.session.execute(text(f"""
            CREATE TABLE lifecycle_ack (
                id INTEGER NOT NULL PRIMARY KEY,
                student_id INTEGER NOT NULL UNIQUE,
                acknowledged_on {ts},
                acknowledged_by VARCHAR(100),
                note VARCHAR(500),
                FOREIGN KEY(student_id) REFERENCES student (id) ON DELETE CASCADE
            )
        """))
        db.session.commit()
        print('Migration migrate_lifecycle_ack_table: created lifecycle_ack', flush=True)
    except Exception as e:
        db.session.rollback()
        print(f'Migration migrate_lifecycle_ack_table: FAILED: {e}', flush=True)


def migrate_enquiry_course_nullable():
    """Make enquiry.course_id nullable with ON DELETE SET NULL.

    Legacy databases defined the column NOT NULL with ON DELETE CASCADE, so
    deleting a course silently destroyed every lead that pointed at it. New
    models use SET NULL; this rebuilds the table in place on SQLite (which
    cannot alter a column constraint) and drops NOT NULL elsewhere. Existing
    rows are preserved. Idempotent: only runs while NOT NULL is present.
    """
    if not _table_exists('enquiry') or not _has_column('enquiry', 'course_id'):
        return
    if db.engine.dialect.name != 'sqlite':
        try:
            db.session.execute(text('ALTER TABLE enquiry ALTER COLUMN course_id DROP NOT NULL'))
            db.session.commit()
        except Exception:
            db.session.rollback()
        return

    info = {r[1]: r for r in db.session.execute(text('PRAGMA table_info(enquiry)')).fetchall()}
    # PRAGMA table_info row: (cid, name, type, notnull, dflt_value, pk)
    if not info.get('course_id') or not bool(info['course_id'][3]):
        return

    existing = list(info.keys())
    wanted = ['id', 'student_name', 'email', 'phone', 'course_id', 'source', 'status',
              'notes', 'follow_up_date', 'last_contacted_at', 'converted_student_id',
              'created_at', 'updated_at']
    select_expr = ', '.join(c if c in existing else 'NULL' for c in wanted)
    try:
        db.session.execute(text('''
            CREATE TABLE enquiry_new (
                id INTEGER NOT NULL PRIMARY KEY,
                student_name VARCHAR(100) NOT NULL,
                email VARCHAR(100),
                phone VARCHAR(20) NOT NULL,
                course_id INTEGER,
                source VARCHAR(50),
                status VARCHAR(20),
                notes TEXT,
                follow_up_date DATE,
                last_contacted_at DATETIME,
                converted_student_id INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(course_id) REFERENCES course (id) ON DELETE SET NULL,
                FOREIGN KEY(converted_student_id) REFERENCES student (id) ON DELETE SET NULL
            )
        '''))
        db.session.execute(text('INSERT INTO enquiry_new (%s) SELECT %s FROM enquiry'
                                % (', '.join(wanted), select_expr)))
        db.session.execute(text('DROP TABLE enquiry'))
        db.session.execute(text('ALTER TABLE enquiry_new RENAME TO enquiry'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_enquiry_status ON enquiry(status)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_enquiry_course ON enquiry(course_id)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_enquiry_followup ON enquiry(follow_up_date)'))
        # Backfill "last activity" from creation so staleness still works.
        db.session.execute(text('UPDATE enquiry SET updated_at = COALESCE(updated_at, created_at) '
                                'WHERE updated_at IS NULL'))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def migrate_funding_batch2_columns():
    """Add owner_funding.reference and owner_funding.investment_type.

    Batch 2 (funding enhancement): a tracking/UTR reference and the
    Capital-vs-Director-Loan classification. The ORM maps them, so legacy
    databases 500 on funding queries until the columns exist. Idempotent and
    additive-only; legacy rows keep NULL reference and read 'Capital'.
    """
    if not _table_exists('owner_funding'):
        return
    adds = [('reference', 'VARCHAR(100)'), ('investment_type', 'VARCHAR(20)')]
    for column, col_type in adds:
        if not _has_column('owner_funding', column):
            try:
                db.session.execute(text('ALTER TABLE "owner_funding" ADD COLUMN "%s" %s' % (column, col_type)))
                db.session.commit()
                print(f"Migration migrate_funding_batch2_columns: added owner_funding.{column}", flush=True)
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_funding_batch2_columns: FAILED to add owner_funding.{column}: {e}", flush=True)


def migrate_task_priority_and_category():
    """Ensure priority and category columns exist on the task table."""
    if not _table_exists('task'):
        return
    adds = [('priority', "VARCHAR(20) DEFAULT 'Medium'"), ('category', "VARCHAR(50) DEFAULT 'General'")]
    for column, col_type in adds:
        if not _has_column('task', column):
            try:
                db.session.execute(text('ALTER TABLE "task" ADD COLUMN "%s" %s' % (column, col_type)))
                db.session.commit()
                print(f"Migration migrate_task_priority_and_category: added task.{column}", flush=True)
            except Exception as e:
                db.session.rollback()
                print(f"Migration migrate_task_priority_and_category: FAILED to add task.{column}: {e}", flush=True)


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
