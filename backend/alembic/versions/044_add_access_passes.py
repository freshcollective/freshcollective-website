"""Add access_passes and access_pass_events tables

Revision ID: 044
Revises: 043
Create Date: 2026-06-10
"""
from alembic import op

revision = '044'
down_revision = '043'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS access_passes (
            id VARCHAR NOT NULL PRIMARY KEY,
            user_id VARCHAR NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            space_id VARCHAR NOT NULL
                REFERENCES spaces(id) ON DELETE CASCADE,
            payment_transaction_id VARCHAR
                REFERENCES payment_transactions(id) ON DELETE SET NULL,
            payment_option_id VARCHAR
                REFERENCES payment_options(id) ON DELETE SET NULL,
            payment_option_schedule_id VARCHAR
                REFERENCES payment_option_schedules(id) ON DELETE SET NULL,
            pass_type VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            valid_from TIMESTAMP NOT NULL DEFAULT NOW(),
            valid_until TIMESTAMP,
            total_credits INTEGER,
            used_credits INTEGER NOT NULL DEFAULT 0,
            credits_per_week INTEGER,
            eligible_pathway_id VARCHAR
                REFERENCES pathways(id) ON DELETE SET NULL,
            grants_pathway_id VARCHAR
                REFERENCES pathways(id) ON DELETE SET NULL,
            pathway_entitlement_id VARCHAR
                REFERENCES pathway_entitlements(id) ON DELETE SET NULL,
            source VARCHAR(30) NOT NULL DEFAULT 'one_time_purchase',
            notes TEXT,
            granted_by_user_id VARCHAR
                REFERENCES users(id) ON DELETE SET NULL,
            revoked_by_user_id VARCHAR
                REFERENCES users(id) ON DELETE SET NULL,
            revoked_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_access_passes_user_id ON access_passes(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_access_passes_space_id ON access_passes(space_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_access_passes_user_status ON access_passes(user_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_access_passes_txn_id ON access_passes(payment_transaction_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_access_passes_eligible_pathway ON access_passes(eligible_pathway_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS access_pass_events (
            access_pass_id VARCHAR NOT NULL
                REFERENCES access_passes(id) ON DELETE CASCADE,
            event_id VARCHAR NOT NULL
                REFERENCES events(id) ON DELETE CASCADE,
            PRIMARY KEY (access_pass_id, event_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS access_pass_events")
    op.execute("DROP INDEX IF EXISTS ix_access_passes_eligible_pathway")
    op.execute("DROP INDEX IF EXISTS ix_access_passes_txn_id")
    op.execute("DROP INDEX IF EXISTS ix_access_passes_user_status")
    op.execute("DROP INDEX IF EXISTS ix_access_passes_space_id")
    op.execute("DROP INDEX IF EXISTS ix_access_passes_user_id")
    op.execute("DROP TABLE IF EXISTS access_passes")
