"""Regression tests for the production 500 on the capital-injection page.

Render runs Postgres without AUTO_MIGRATE, so the boot self-heal chain must add
owner_funding.reference / investment_type to a legacy database (restored from a
pre-batch-2 backup) before the ORM queries them. These tests simulate exactly
that scenario.
"""
from sqlalchemy import inspect, text

from app.extensions import db


def _legacy_owner_funding_table():
    db.session.execute(text('DROP TABLE IF EXISTS "owner_funding"'))
    db.session.execute(text(
        '''
        CREATE TABLE "owner_funding" (
            id INTEGER NOT NULL PRIMARY KEY,
            amount FLOAT NOT NULL,
            funding_date DATE DEFAULT (CURRENT_DATE) NOT NULL,
            method VARCHAR(50) DEFAULT 'Cash' NOT NULL,
            purpose TEXT,
            created_by INTEGER,
            created_at DATETIME
        )
        '''
    ))
    db.session.execute(text(
        '''
        INSERT INTO "owner_funding"
            (amount, funding_date, method, purpose, created_by, created_at)
        VALUES
            (50000.0, '2026-09-01', 'Bank Transfer', 'Legacy injection', 1, '2026-09-01 10:00:00')
        '''
    ))
    db.session.commit()


def test_funding_migration_repairs_legacy_database(app, client):
    # Simulate a Postgres database created before funding batch 2: the new
    # columns simply do not exist, which made GET /funding 500 in production.
    with app.app_context():
        _legacy_owner_funding_table()
        cols = {c['name'] for c in inspect(db.engine).get_columns('owner_funding')}
        assert 'reference' not in cols
        assert 'investment_type' not in cols

        from app.services.db_migration import migrate_funding_batch2_columns
        migrate_funding_batch2_columns()

        cols = {c['name'] for c in inspect(db.engine).get_columns('owner_funding')}
        assert 'reference' in cols
        assert 'investment_type' in cols

        # Legacy row is untouched; inserts after the migration carry the
        # investment_type default and allow a reference.
        row = db.session.execute(
            text('SELECT reference, investment_type FROM "owner_funding" LIMIT 1')
        ).fetchone()
        assert row.reference is None
        assert row.investment_type is None

        db.session.execute(text(
            '''
            INSERT INTO "owner_funding"
                (amount, funding_date, method, purpose, reference, investment_type, created_by)
            VALUES
                (25000.0, '2026-09-19', 'Cash', 'New injection', 'UTR123', 'Director Loan', 1)
            '''
        ))
        db.session.commit()

        # Idempotent: the boot self-heal runs on every startup.
        migrate_funding_batch2_columns()

    # The capital-injection page used to 500 here on the legacy schema.
    resp = client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    assert resp.status_code == 302
    page = client.get('/funding')
    assert page.status_code == 200