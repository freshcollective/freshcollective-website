"""Create ``refund_operations`` — durable audit + state machine for
creator/admin-initiated Stripe refunds.

Revision ID: 128
Revises: 127
Create Date: 2026-09-12

Motivation
----------
Refunds today land in the ledger via the ``charge.refunded`` webhook,
regardless of who clicked. Once creators can initiate refunds from
Creator Studio, we need durable per-attempt records that survive
process crashes, network races, and webhook re-orderings:

* who initiated the refund + why (reason / note);
* what amount was requested;
* which Stripe Refund object it corresponds to (once known);
* whether Stripe accepted, refused, or is still deciding;
* whether the confirming ``charge.refunded`` webhook has arrived;
* whether a stranded operation was reconciled by pulling state
  directly from Stripe.

Multiple partial refunds can happen per PaymentTransaction (1:N), so
these facts cannot live as columns on PaymentTransaction — they need
their own row per attempt.

State machine (see ``services.refund_reconciliation`` for the code):

    in_flight ──→ accepted          (Stripe .create returned Refund)
              ├──→ webhook_confirmed (metadata-first correlator on the
                                      race where webhook arrives before
                                      API persists ``accepted``)
              ├──→ refused           (Stripe 4xx)
              └──→ failed            (Stripe 5xx unrecoverable)
    accepted  ──→ webhook_confirmed  (webhook correlator OR retrieve
                                       reconciliation)
              └──→ failed             (retrieve reconciliation found
                                       refund failed / canceled)

Active states blocking a new refund: ``in_flight``, ``accepted``.
Terminal states: ``webhook_confirmed``, ``refused``, ``failed``.

Idempotency key: derived from ``id`` — ``refop:{id}:v1``. Stripe
caches this for 24h so replay is safe within that window. Beyond
24h the Phase B reconciliation path uses ``Refund.list`` +
``metadata.refund_operation_id`` search.

Columns
-------
See the model docstring for full semantics.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "128"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refund_operations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "payment_transaction_id",
            sa.String(),
            sa.ForeignKey("payment_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("requested_amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "expected_cumulative_refunded_amount_cents",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "stripe_identifier_kind",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "stripe_identifier_value",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column("stripe_refund_id", sa.String(length=200), nullable=True),
        sa.Column(
            "terminal_status",
            sa.String(length=24),
            nullable=False,
            server_default="in_flight",
        ),
        sa.Column("api_error_message", sa.Text(), nullable=True),
        sa.Column("payout_advisory", sa.String(length=60), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "confirming_webhook_event_id",
            sa.String(),
            sa.ForeignKey("webhook_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_refund_operations_payment_transaction_id",
        "refund_operations",
        ["payment_transaction_id"],
    )
    op.create_index(
        "ix_refund_operations_stripe_refund_id",
        "refund_operations",
        ["stripe_refund_id"],
    )
    # Composite index supports the in-flight check:
    #   WHERE payment_transaction_id = ? AND terminal_status IN (...)
    op.create_index(
        "ix_refund_operations_active_check",
        "refund_operations",
        ["payment_transaction_id", "terminal_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_refund_operations_active_check", table_name="refund_operations")
    op.drop_index("ix_refund_operations_stripe_refund_id", table_name="refund_operations")
    op.drop_index("ix_refund_operations_payment_transaction_id", table_name="refund_operations")
    op.drop_table("refund_operations")
