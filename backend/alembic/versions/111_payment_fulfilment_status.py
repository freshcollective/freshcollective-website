"""PaymentTransaction: add ``fulfilment_status`` column.

Revision ID: 111
Revises: 110
Create Date: 2026-08-14

Adds a dedicated fulfilment lifecycle to ``PaymentTransaction`` so
"payment succeeded but Fresh Collective could not fulfil the
promised access" is a visible, first-class state instead of a
silent partial-write in the webhook.

Enum values (see ``PaymentFulfilmentStatus`` in
``app/models/payment.py``):

    pending    — no fulfilment write has committed yet
    applied    — every promised grant was written
    blocked    — payment succeeded, fulfilment refused to write

Backfill
--------
Historical rows are marked ``applied``. The pre-hardening webhook
committed the txn as ``succeeded`` even when the fulfilment
fanout errored partway, so there is no reliable way to
retroactively distinguish "fully applied" from "partially
applied" for any given historical row. Marking them all
``applied`` matches the pre-hardening operational assumption
(txn.status='succeeded' meant "we're done with it") and prevents
existing rows from suddenly appearing in an "unhandled"
operational bucket after this migration lands. From this point
onwards, new rows go through the resolve → validate → apply flow
which either commits ``applied`` atomically with the writes or
commits ``blocked`` when validation rejects the bundle before any
writes happen.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE payment_fulfilment_status_enum "
        "AS ENUM ('pending', 'applied', 'blocked')"
    )
    op.add_column(
        "payment_transactions",
        sa.Column(
            "fulfilment_status",
            sa.Enum(
                "pending", "applied", "blocked",
                name="payment_fulfilment_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
    )
    # Backfill: historical rows are treated as already-applied.
    # See migration docstring for the rationale.
    op.execute(
        "UPDATE payment_transactions SET fulfilment_status = 'applied'"
    )


def downgrade() -> None:
    op.drop_column("payment_transactions", "fulfilment_status")
    op.execute("DROP TYPE payment_fulfilment_status_enum")
