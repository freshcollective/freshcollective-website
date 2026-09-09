"""Phase 1 — pay-in-full grants snapshot on PaymentTransaction.

Revision ID: 123
Revises: 122
Create Date: 2026-09-09

Symmetric with ``purchase_plans.snapshot_grants_json`` (added by
migration 118). Locks in "what the member was promised at checkout"
for pay-in-full purchases so a Creator edit to the Payment Option's
grants between the buyer clicking Pay and Stripe firing
``checkout.session.completed`` cannot silently alter the fulfilment
that lands.

Column is nullable and additive:

* new pay-in-full checkouts populate the column via
  ``orchestrate_paid_checkout``;
* the webhook prefers the snapshot when present and falls back to
  ``resolve_intent_for_option`` (live DB read) when NULL — the
  historical behaviour for every ledger row that predates this
  migration. No backfill needed.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "123"
down_revision = "122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column(
            "snapshot_grants_json", postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_transactions", "snapshot_grants_json")
