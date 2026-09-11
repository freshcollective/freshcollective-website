"""Create ``creator_payout_batches`` + ``creator_payout_batch_items``
+ ``payment_transactions.payout_batch_id`` FK.

Revision ID: 129
Revises: 128
Create Date: 2026-09-12

Motivation
----------
External creators cannot safely be paid while every PaymentTransaction
row stays ``payout_status='pending'`` forever. This introduces the
minimum bookkeeping needed to record manual bank/SEPA payouts, without
building full Stripe Connect payout automation.

Two tables:

* ``creator_payout_batches`` — one row per admin-recorded payout.
  Scoped by ``(creator_user_id, currency)`` — cross-Collective, since
  a creator's future Stripe Connect account will be per-User, not
  per-Space, and a real-world bank transfer is per-recipient.
  Total amount + transaction count are snapshotted at creation and
  IMMUTABLE — the batch represents "what Fresh Collective recorded
  as paid", a historical fact.

* ``creator_payout_batch_items`` — immutable join rows recording
  which PaymentTransactions were paid in which batch, at what
  creator-amount at payout time. NEVER deleted or reassigned. If a
  batch is corrected/cancelled with revert_transactions=True, the
  PaymentTransaction may revert to ``payout_status='pending'``, but
  the BatchItem row stays. Same transaction paid later in Batch B
  gets a NEW BatchItem — historical membership of Batch A is
  queryable forever.

Additional column on ``payment_transactions``:

* ``payout_batch_id`` — convenience pointer to the CURRENT (most
  recent uncancelled) batch. Nullable, cleared by batch cancellation.
  NOT the authoritative history — that lives on BatchItem.

Cancellation semantics
----------------------
Batch cancellation is a correction of Fresh Collective's internal
record. It does NOT reverse the bank transfer. Cancelled rows are
kept in the batches table with ``cancelled_at`` / ``cancelled_by_user_id``
/ ``cancellation_reason`` audit fields. UI must warn admins
explicitly that this only fixes the FC record.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PGEnum


revision = "129"
down_revision = "128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Named ENUM so the value set is explicit at the DB level.
    op.execute(
        "CREATE TYPE creator_payout_batch_status_enum AS ENUM "
        "('paid', 'cancelled')"
    )

    op.create_table(
        "creator_payout_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "creator_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        # IMMUTABLE snapshots — do not recompute on refund events.
        sa.Column("total_amount_cents", sa.Integer(), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            PGEnum(
                "paid", "cancelled",
                name="creator_payout_batch_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="paid",
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Admin-recorded date/time of the actual bank transfer.
        sa.Column("paid_at", sa.DateTime(timezone=False), nullable=False),
        # Audit-only cancellation trail — never mutates historical
        # total_amount_cents / transaction_count / paid_at fields.
        sa.Column("cancelled_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "cancelled_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_creator_payout_batches_creator",
        "creator_payout_batches",
        ["creator_user_id"],
    )
    op.create_index(
        "ix_creator_payout_batches_creator_currency_status",
        "creator_payout_batches",
        ["creator_user_id", "currency", "status"],
    )

    op.create_table(
        "creator_payout_batch_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "payout_batch_id",
            sa.String(),
            sa.ForeignKey("creator_payout_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_transaction_id",
            sa.String(),
            sa.ForeignKey("payment_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "creator_amount_cents_at_payout", sa.Integer(), nullable=False,
        ),
        sa.Column(
            "refunded_creator_amount_cents_at_payout",
            sa.Integer(), nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "payout_batch_id", "payment_transaction_id",
            name="uq_payout_batch_item_batch_txn",
        ),
    )
    op.create_index(
        "ix_creator_payout_batch_items_batch",
        "creator_payout_batch_items",
        ["payout_batch_id"],
    )
    op.create_index(
        "ix_creator_payout_batch_items_txn",
        "creator_payout_batch_items",
        ["payment_transaction_id"],
    )

    # Convenience pointer on PaymentTransaction — see the model
    # docstring. Nullable; ON DELETE SET NULL protects the child row
    # if a batch is ever deleted (which we don't do, but the safety
    # net matters).
    op.add_column(
        "payment_transactions",
        sa.Column(
            "payout_batch_id",
            sa.String(),
            sa.ForeignKey("creator_payout_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_payment_transactions_payout_batch_id",
        "payment_transactions",
        ["payout_batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_transactions_payout_batch_id",
        table_name="payment_transactions",
    )
    op.drop_column("payment_transactions", "payout_batch_id")
    op.drop_index(
        "ix_creator_payout_batch_items_txn",
        table_name="creator_payout_batch_items",
    )
    op.drop_index(
        "ix_creator_payout_batch_items_batch",
        table_name="creator_payout_batch_items",
    )
    op.drop_table("creator_payout_batch_items")
    op.drop_index(
        "ix_creator_payout_batches_creator_currency_status",
        table_name="creator_payout_batches",
    )
    op.drop_index(
        "ix_creator_payout_batches_creator",
        table_name="creator_payout_batches",
    )
    op.drop_table("creator_payout_batches")
    op.execute("DROP TYPE creator_payout_batch_status_enum")
