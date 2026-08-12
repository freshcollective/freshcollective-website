"""Add 'member_series_pass_purchase' to payment_transaction_type_enum.

Revision ID: 107
Revises: 106
Create Date: 2026-08-11

Introduces a distinct PaymentTransactionType for Gathering Series pass
purchases, so ledger rows can be told apart from single-Gathering ticket
purchases (``gathering_ticket_purchase``) and Pathway purchases
(``member_pathway_purchase``).
"""

from alembic import op


revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE payment_transaction_type_enum "
            "ADD VALUE IF NOT EXISTS 'member_series_pass_purchase'"
        )


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum.
    pass
