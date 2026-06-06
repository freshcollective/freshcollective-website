"""Add partial unique index on payment_transactions.provider_checkout_session_id

Prevents duplicate PaymentTransaction rows being created for the same Stripe
Checkout Session. NULLs are excluded so manual/admin transactions (which have
NULL for this field) are unaffected.

Revision ID: 040
Revises: 039
Create Date: 2026-06-06
"""
from alembic import op

revision = '040'
down_revision = '039'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uix_payment_txn_checkout_session_id "
        "ON payment_transactions (provider_checkout_session_id) "
        "WHERE provider_checkout_session_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uix_payment_txn_checkout_session_id")
