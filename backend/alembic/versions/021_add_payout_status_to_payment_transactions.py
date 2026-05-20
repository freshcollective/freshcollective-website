"""Add payout_status, payout_marked_at, payout_reference to payment_transactions.

Revision ID: 021
Revises: 020
Create Date: 2026-05-20
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create payout_status enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payout_status_enum') THEN
                CREATE TYPE payout_status_enum AS ENUM (
                    'not_applicable',
                    'pending',
                    'paid',
                    'held',
                    'cancelled'
                );
            END IF;
        END$$;
    """)

    # Add payout_status column (default pending; will be backfilled below)
    op.execute("""
        ALTER TABLE payment_transactions
            ADD COLUMN IF NOT EXISTS payout_status payout_status_enum
                NOT NULL DEFAULT 'pending';
    """)

    # Add payout_marked_at (when the payout was marked as paid by admin)
    op.execute("""
        ALTER TABLE payment_transactions
            ADD COLUMN IF NOT EXISTS payout_marked_at TIMESTAMP WITHOUT TIME ZONE;
    """)

    # Add payout_reference (future: Stripe transfer ID or batch reference)
    op.execute("""
        ALTER TABLE payment_transactions
            ADD COLUMN IF NOT EXISTS payout_reference VARCHAR(200);
    """)

    # Backfill: creator_subscription_payment rows → not_applicable
    op.execute("""
        UPDATE payment_transactions
        SET payout_status = 'not_applicable'
        WHERE transaction_type = 'creator_subscription_payment';
    """)

    # Backfill: refund / adjustment rows → not_applicable
    op.execute("""
        UPDATE payment_transactions
        SET payout_status = 'not_applicable'
        WHERE transaction_type IN ('refund', 'adjustment');
    """)

    # Backfill: failed / cancelled / disputed → not_applicable
    op.execute("""
        UPDATE payment_transactions
        SET payout_status = 'not_applicable'
        WHERE status IN ('failed', 'cancelled');
    """)

    # Member purchases that are succeeded → pending (already the column default, but explicit)
    op.execute("""
        UPDATE payment_transactions
        SET payout_status = 'pending'
        WHERE transaction_type IN (
            'member_pathway_purchase',
            'member_collective_purchase',
            'member_pathway_subscription',
            'member_collective_subscription'
        )
        AND status = 'succeeded';
    """)

    # Index for payout reporting queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_payment_transactions_payout_status
            ON payment_transactions (payout_status);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_transactions_payout_status;")
    op.execute("ALTER TABLE payment_transactions DROP COLUMN IF EXISTS payout_reference;")
    op.execute("ALTER TABLE payment_transactions DROP COLUMN IF EXISTS payout_marked_at;")
    op.execute("ALTER TABLE payment_transactions DROP COLUMN IF EXISTS payout_status;")
    op.execute("DROP TYPE IF EXISTS payout_status_enum;")
