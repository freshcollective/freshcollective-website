"""FIP2 — finite payment plan Stripe object ids + installment_number + invoice unique.

Revision ID: 118
Revises: 117
Create Date: 2026-08-14

Adds the fields FIP2's real Stripe SubscriptionSchedule flow needs:

* ``purchase_plans.snapshot_grants_json`` — JSON blob of the
  resolved ``FulfilmentIntent`` at plan creation. Locks in "what
  the member was promised" so a later Creator edit to the Payment
  Option's grants cannot silently alter an in-flight plan.
* ``purchase_plans.stripe_product_id`` — Stripe Product id created
  once per plan (used as the parent of the recurring Price).
* ``purchase_plans.stripe_price_id`` — Stripe Price id created
  from the schedule's per-instalment amount + cadence. This is
  what the SubscriptionSchedule phases point at.
* ``payment_transactions.installment_number`` — 1-based ordinal
  for per-invoice rows belonging to a plan. Populated by the
  ``invoice.payment_succeeded`` handler as ``plan.installments_paid
  + 1``. Nullable so legacy pay-in-full rows leave it NULL.
* ``ux_payment_transactions_provider_invoice_id`` — partial unique
  on ``provider_invoice_id`` (WHERE NOT NULL). Belt-and-braces on
  top of the FIP1 webhook idempotency table: even a bug that
  bypasses the helper cannot produce two ledger rows for the
  same Stripe invoice.

All columns nullable / additive. No historical rewrite.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "118"
down_revision = "117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_plans",
        sa.Column(
            "snapshot_grants_json", postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("stripe_product_id", sa.String(200), nullable=True),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("stripe_price_id", sa.String(200), nullable=True),
    )

    op.add_column(
        "payment_transactions",
        sa.Column("installment_number", sa.Integer, nullable=True),
    )

    # Partial unique — one PaymentTransaction per Stripe invoice.
    # Historical rows carry NULL invoice ids (pay-in-full uses
    # provider_checkout_session_id / provider_payment_intent_id
    # instead) and coexist under the WHERE clause.
    op.execute(
        "CREATE UNIQUE INDEX ux_payment_transactions_provider_invoice_id "
        "ON payment_transactions (provider_invoice_id) "
        "WHERE provider_invoice_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_payment_transactions_provider_invoice_id")
    op.drop_column("payment_transactions", "installment_number")
    op.drop_column("purchase_plans", "stripe_price_id")
    op.drop_column("purchase_plans", "stripe_product_id")
    op.drop_column("purchase_plans", "snapshot_grants_json")
