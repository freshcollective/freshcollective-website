"""Add stripe_mode to payment_transactions

Revision ID: 056
Revises: 055
Create Date: 2026-06-19

Records whether each transaction was processed against Stripe test or live keys.
All existing rows are backfilled as 'test' — they were all created while
STRIPE_SECRET_KEY was a sk_test_* key. New transactions record the mode at
creation time via the checkout route.

This column is used by the admin revenue dashboard to separate test sandbox
figures from real revenue so the two are never mixed after go-live.
"""

from alembic import op
import sqlalchemy as sa

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add with server_default so the NOT NULL constraint is satisfied immediately
    # for all existing rows (they are all test-mode transactions).
    op.add_column(
        "payment_transactions",
        sa.Column(
            "stripe_mode",
            sa.String(10),
            nullable=False,
            server_default="test",
        ),
    )
    # Drop the server default after backfill — new rows must be explicit.
    op.alter_column("payment_transactions", "stripe_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("payment_transactions", "stripe_mode")
