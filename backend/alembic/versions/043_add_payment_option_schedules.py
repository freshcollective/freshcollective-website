"""Add payment_option_schedules table and schedule FK on payment_transactions

Revision ID: 043
Revises: 042
Create Date: 2026-06-09
"""
from alembic import op

revision = '043'
down_revision = '042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_option_schedules (
            id VARCHAR NOT NULL PRIMARY KEY,
            payment_option_id VARCHAR NOT NULL
                REFERENCES payment_options(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            schedule_type VARCHAR(30) NOT NULL DEFAULT 'pay_in_full',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            total_amount_cents INTEGER,
            upfront_amount_cents INTEGER,
            installment_amount_cents INTEGER,
            installment_count INTEGER,
            interval VARCHAR(20),
            stripe_interval VARCHAR(20),
            stripe_interval_count INTEGER,
            currency VARCHAR(3) NOT NULL DEFAULT 'AUD',
            buyer_note TEXT,
            internal_note TEXT,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_payment_option_schedules_option_id
            ON payment_option_schedules(payment_option_id)
    """)

    op.execute("""
        ALTER TABLE payment_transactions
            ADD COLUMN IF NOT EXISTS payment_option_schedule_id VARCHAR
            REFERENCES payment_option_schedules(id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_payment_transactions_schedule_id
            ON payment_transactions(payment_option_schedule_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_transactions_schedule_id")
    op.execute(
        "ALTER TABLE payment_transactions "
        "DROP COLUMN IF EXISTS payment_option_schedule_id"
    )
    op.execute("DROP TABLE IF EXISTS payment_option_schedules")
