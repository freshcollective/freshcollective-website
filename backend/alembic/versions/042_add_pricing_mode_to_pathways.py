"""Add pricing_mode to pathways; fix calculated_total_cents on existing payment options

Revision ID: 042
Revises: 041
Create Date: 2026-06-09

Changes:
  pathways.pricing_mode — 'legacy' (default) or 'payment_options'
    'legacy'          → uses pathway.price_cents as before (all existing pathways)
    'payment_options' → member must select a published PaymentOption at checkout

  payment_options.calculated_total_cents — backfill for rows where
    total_sessions and price_per_session_cents are set but calculated_total_cents is NULL
"""

from alembic import op

revision = '042'
down_revision = '041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add pricing_mode column — defaults to 'legacy' for all existing pathways
    op.execute("""
        ALTER TABLE pathways
            ADD COLUMN IF NOT EXISTS pricing_mode VARCHAR(20) NOT NULL DEFAULT 'legacy'
    """)

    # Backfill calculated_total_cents on existing payment options
    # where both inputs are present but the total was never computed
    op.execute("""
        UPDATE payment_options
        SET calculated_total_cents = total_sessions * price_per_session_cents
        WHERE total_sessions IS NOT NULL
          AND price_per_session_cents IS NOT NULL
          AND calculated_total_cents IS NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE pathways DROP COLUMN IF EXISTS pricing_mode")
