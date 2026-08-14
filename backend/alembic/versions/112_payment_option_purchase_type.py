"""Add 'member_payment_option_purchase' to payment_transaction_type_enum.

Revision ID: 112
Revises: 111
Create Date: 2026-08-14

Introduces the generic ``PaymentTransactionType`` used by the
unified ``POST /api/checkout`` endpoint (B4B). A single
PaymentOption can grant any combination of experiences —
classifying its ledger row by "primary" grant would embed an
incorrect assumption. Legacy compat wrappers keep their kind-
specific transaction types
(``member_pathway_purchase`` / ``member_series_pass_purchase``)
for historical reporting continuity.
"""

from alembic import op


revision = "112"
down_revision = "111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL: ALTER TYPE ... ADD VALUE cannot run inside a
    # transaction block. AUTOCOMMIT is the simplest reliable path.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE payment_transaction_type_enum "
            "ADD VALUE IF NOT EXISTS 'member_payment_option_purchase'"
        )


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum.
    pass
