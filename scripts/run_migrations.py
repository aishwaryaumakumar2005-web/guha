#!/usr/bin/env python3
"""
One-off migration runner for Guha Academy app.

Usage:
  python scripts/run_migrations.py        # dry-run (no changes)
  python scripts/run_migrations.py --apply -y   # apply without confirmation
"""
import os
import sys
import argparse


def main():
    parser = argparse.ArgumentParser(description='Run one-off schema/data migrations')
    parser.add_argument('--apply', action='store_true', help='Apply migrations (default: dry-run)')
    parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    if not args.apply:
        print('Dry run: no changes will be applied. Pass --apply to run migrations.')

    if args.apply and not args.yes:
        resp = input('Confirm applying migrations to the configured database? [y/N]: ').strip().lower()
        if resp not in ('y', 'yes'):
            print('Aborted by user.')
            sys.exit(0)

    # Ensure the guarded auto-migrate path is enabled when creating the app
    os.environ['AUTO_MIGRATE'] = 'true'

    try:
        # Import app factory and DB
        from app import create_app, db
    except Exception as e:
        print('Failed to import app/create_app:', e)
        sys.exit(2)

    app = create_app()

    with app.app_context():
        try:
            print('Running db.create_all() ...')
            if args.apply:
                db.create_all()
            else:
                print('Would run: db.create_all()')

            # Run migration helpers from app.services.db_migration
            try:
                from app.services import db_migration
            except Exception:
                db_migration = None

            for fn in ('migrate_renames', 'migrate_company_names', 'migrate_photos_to_db', 'migrate_schema_additions'):
                if db_migration and hasattr(db_migration, fn):
                    print(f"Preparing to run {fn}()")
                    if args.apply:
                        try:
                            res = getattr(db_migration, fn)()
                            if res is not None:
                                print(f"{fn} returned: {res}")
                        except Exception as e:
                            print(f"{fn} failed:", e)
                            db.session.rollback()
                    else:
                        print(f"[dry-run] Would invoke {fn}()")

            print('Migration run complete.')
        except Exception as e:
            print('Migration runner failed:', e)
            sys.exit(3)


if __name__ == '__main__':
    main()
