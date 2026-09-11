"""Add refund-state columns to ``payment_transactions``.

Revision ID: 126
Revises: 125
Create Date: 2026-09-11

Motivation
----------
The ``PaymentTransactionStatus`` enum has always carried ``refunded``
and ``partially_refunded`` values, but nothing wrote them. Stripe
refund webhooks were also unhandled — a real refund would leave the
ledger showing ``status='succeeded'`` and continue counting the
refunded amount in Gross Sales / Total Revenue.

The refund-sync work needs two additive columns so a single ledger
row can express the truthful state after one or more partial refunds
plus a final full refund. Stripe's ``charge.amount_refunded`` is the
cumulative refunded amount on the charge; the handler stamps that
value straight into ``refunded_amount_cents`` — no running-sum
bookkeeping on our side.

Columns added
-------------

``refunded_amount_cents INTEGER NOT NULL DEFAULT 0``
    Cumulative amount refunded on this transaction, in cents. Zero
    for anything that has never been refunded (historical rows and
    all new pending / succeeded rows).

``last_refunded_at TIMESTAMP NULL``
    Stamped when a refund event updates this row. Monotonic — the
    handler refuses to move this backwards on out-of-order events.

Both fields are populated by the refund handler. Nothing in
application code reads them prior to the handler being wired.

Historical rows
---------------
Every existing row initialises to ``refunded_amount_cents=0``,
``last_refunded_at=NULL`` — the correct truth on the day the
migration runs. Known exception: the one historical Stripe refund
that has already happened in production (Awaken $1 test purchase)
is reconciled post-deploy by resending the original
``charge.refunded`` event through the newly-live handler. No
special-case application logic or in-migration reconciliation.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "126"
down_revision = "125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column(
            "refunded_amount_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("last_refunded_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_transactions", "last_refunded_at")
    op.drop_column("payment_transactions", "refunded_amount_cents")
