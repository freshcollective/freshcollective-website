"""Add index on payment_transactions.provider_checkout_session_id for webhook lookups

Revision ID: 039
Revises: 038
Create Date: 2026-06-06
"""
from alembic import op

revision = '039'
down_revision = '038'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payment_transactions_provider_checkout_session_id "
        "ON payment_transactions (provider_checkout_session_id)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_payment_transactions_provider_checkout_session_id"
    )
