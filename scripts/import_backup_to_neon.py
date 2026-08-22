import os
import re
import sqlite3
import sys
import time
from argparse import ArgumentParser

from sqlalchemy.exc import IntegrityError

# Ensure project root is importable
_here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _here not in sys.path:
    sys.path.insert(0, _here)

from app import create_app
from app.extensions import db


def read_database_url_from_render_yaml(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return None
    m = re.search(r"DATABASE_URL\s*:\s*\"?(?P<url>[^\n\"]+)\"?", text)
    return m.group('url').strip() if m else None


def get_sqlite_tables(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row[0] for row in cur.fetchall()]
    return tables


def get_table_columns(conn, table):
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{table}")')
    cols = [row[1] for row in cur.fetchall()]
    return cols


def import_backup(sqlite_path, drop_and_create=True, render_yaml='render.yaml'):
    if not os.path.exists(sqlite_path):
        print('Backup file not found:', sqlite_path)
        return 2

    # If DATABASE_URL not set, attempt to read from render.yaml
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        db_url = read_database_url_from_render_yaml(os.path.join(os.path.dirname(_here), render_yaml))
        if db_url:
            os.environ['DATABASE_URL'] = db_url

    # Create Flask app (will configure SQLALCHEMY_DATABASE_URI from env)
    app = create_app()

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    with app.app_context():
        if drop_and_create:
            print('Dropping and recreating all tables in destination DB...')
            try:
                db.drop_all()
            except Exception as e:
                print('Warning: drop_all failed:', e)
            db.create_all()

        tables = get_sqlite_tables(sqlite_conn)
        print(f'Found {len(tables)} tables in sqlite backup')

        remaining = list(tables)
        attempts = 0
        max_attempts = max(5, len(remaining) * 2)

        while remaining and attempts < max_attempts:
            attempts += 1
            progressed = False
            for table in remaining[:]:
                try:
                    cols = get_table_columns(sqlite_conn, table)
                    if not cols:
                        remaining.remove(table)
                        progressed = True
                        continue
                    cur = sqlite_conn.cursor()
                    cur.execute(f'SELECT * FROM "{table}"')
                    rows = cur.fetchall()
                    if not rows:
                        remaining.remove(table)
                        progressed = True
                        continue
                    # inspect target table column types to coerce values if needed
                    try:
                        from sqlalchemy import inspect
                        inspector = inspect(db.engine)
                        target_cols_info = {c['name']: c for c in inspector.get_columns(table)}
                    except Exception:
                        target_cols_info = {}

                    col_list = ','.join([f'"{c}"' for c in cols])
                    param_list = ','.join([f':{c}' for c in cols])
                    insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({param_list})'
                    inserted = 0
                    for r in rows:
                        params = {}
                        for c in cols:
                            v = r[c]
                            # coerce booleans stored as 0/1 in sqlite to proper bool for Postgres
                            tc = target_cols_info.get(c)
                            if tc is not None:
                                tstr = str(tc.get('type')).lower() if tc.get('type') is not None else ''
                                if 'boolean' in tstr:
                                    if v in (0, '0'):
                                        v = False
                                    elif v in (1, '1'):
                                        v = True
                                    else:
                                        # keep None or already boolean
                                        v = bool(v) if v not in (None, '') else None
                                # coerce empty string to None for numeric targets
                                if ('integer' in tstr or 'numeric' in tstr or 'float' in tstr) and v == '':
                                    v = None
                            params[c] = v
                        try:
                            db.session.execute(db.text(insert_sql), params)
                            inserted += 1
                        except IntegrityError as ie:
                            db.session.rollback()
                            # defer; likely FK violation or duplicate
                            raise
                    db.session.commit()
                    print(f'Inserted {inserted} rows into {table}')
                    remaining.remove(table)
                    progressed = True
                except IntegrityError:
                    # will retry later
                    pass
                except Exception as e:
                    print(f'Error importing table {table}:', e)
                    db.session.rollback()
                    # skip this table for now
            if not progressed:
                print('No progress on this pass; possible unresolved FK dependencies. Retrying...')
                time.sleep(1)

        if remaining:
            print('Failed to import tables:', remaining)
            return 3

        # Reset sequences for Postgres if applicable
        if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            from sqlalchemy import text
            # common tables to reset as in app.__init__
            seq_tables = [t.name for t in db.metadata.sorted_tables]
            for tbl in seq_tables:
                try:
                    max_id = db.session.execute(db.text(f'SELECT MAX(id) FROM "{tbl}"')).scalar() or 0
                    seq_name = f"{tbl}_id_seq"
                    db.session.execute(text(f'ALTER SEQUENCE {seq_name} RESTART WITH {int(max_id) + 1}'))
                except Exception:
                    db.session.rollback()
            db.session.commit()

    sqlite_conn.close()
    print('Import completed successfully')
    return 0


def main():
    p = ArgumentParser()
    p.add_argument('--backup', '-b', default='backups/institute_backup_20260818_131625.db')
    p.add_argument('--drop', dest='drop', action='store_true', help='Drop and recreate tables before import')
    p.add_argument('--no-drop', dest='drop', action='store_false')
    p.set_defaults(drop=True)
    args = p.parse_args()
    sys.exit(import_backup(args.backup, drop_and_create=args.drop))


if __name__ == '__main__':
    main()
