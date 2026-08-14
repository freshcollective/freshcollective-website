"""FIP1 — link PaymentTransaction, AccessPass, PathwayEntitlement to PurchasePlan.

Revision ID: 116
Revises: 115
Create Date: 2026-08-14

Adds a nullable ``purchase_plan_id`` FK to the three tables that
represent "something Fresh Collective did as a consequence of a
purchase":

* ``payment_transactions.purchase_plan_id`` — set on every per-
  invoice PaymentTransaction that belongs to a plan (populated by
  FIP3 when the invoice.payment_succeeded handler lands). Legacy
  pay-in-full transactions leave it NULL.

* ``access_passes.purchase_plan_id`` — set when the AccessPass was
  granted by a plan-derived first payment. Legacy AccessPasses
  granted by pay-in-full leave it NULL.

* ``pathway_entitlements.purchase_plan_id`` — same rationale for
  Pathway grants.

All three columns are nullable, indexed, and set to NULL on plan
deletion (``ondelete='SET NULL'``) so a plan row can be soft-deleted
without cascading through the historical ledger. Existing rows are
not backfilled — legacy pay-in-full purchases have no plan and never
will.

No historical data is rewritten. No existing behaviour changes.
FIP1 has no code path that writes to these columns yet — the
column is added ahead of FIP2/FIP3 so those phases don't need
their own schema migration to attach the linkage.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column(
            "purchase_plan_id",
            sa.String,
            sa.ForeignKey("purchase_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_payment_transactions_purchase_plan_id",
        "payment_transactions", ["purchase_plan_id"],
    )

    op.add_column(
        "access_passes",
        sa.Column(
            "purchase_plan_id",
            sa.String,
            sa.ForeignKey("purchase_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_access_passes_purchase_plan_id",
        "access_passes", ["purchase_plan_id"],
    )

    op.add_column(
        "pathway_entitlements",
        sa.Column(
            "purchase_plan_id",
            sa.String,
            sa.ForeignKey("purchase_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_pathway_entitlements_purchase_plan_id",
        "pathway_entitlements", ["purchase_plan_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pathway_entitlements_purchase_plan_id",
        table_name="pathway_entitlements",
    )
    op.drop_column("pathway_entitlements", "purchase_plan_id")

    op.drop_index(
        "ix_access_passes_purchase_plan_id",
        table_name="access_passes",
    )
    op.drop_column("access_passes", "purchase_plan_id")

    op.drop_index(
        "ix_payment_transactions_purchase_plan_id",
        table_name="payment_transactions",
    )
    op.drop_column("payment_transactions", "purchase_plan_id")
