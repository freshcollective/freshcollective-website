"""What Fresh Collective is still owed back from a creator, and why.

Revision ID: 143
Revises: 142
Create Date: 2026-09-29

A refund or a dispute on a Connect-routed purchase means FC has to get the
creator's share back. Stripe will reverse a transfer only as far as the
creator's balance allows, so "we asked" and "we got it" are different facts
and the ledger needs to hold both.

The payout-status decision recorded here
----------------------------------------
``payout_status`` keeps meaning exactly what it has always meant: the state
of FC's **manual** payout bookkeeping. It is not reused for Connect.

The tempting move — ``sent`` ⇒ ``payout_status = 'paid'`` — was rejected.
``paid`` in this ledger means "a ``CreatorPayoutBatch`` recorded a manual
disbursement", and it travels with ``payout_reference`` and
``payout_batch_id``; ``CreatorPayoutBatchItem`` is documented as the
authoritative payout history. A ``paid`` row with no batch would break that.
Worse, it would be untrue in a second way: a completed transfer puts money in
the creator's Stripe *balance*, which is not the same as Stripe having paid
their bank.

So Connect rows take ``payout_status = 'not_applicable'`` — literally true,
the manual payout process does not apply to them — and
``connect_transfer_status`` remains the only authority on whether FC has sent
the creator their funds. Consequences, all of them the ones we want: manual
payout batches already exclude them by ``payout_model``; the admin
paid/payable aggregates and the creator's pending-payout estimate exclude
them, because FC does not owe that money by hand; and the refund gate now
reads ``connect_transfer_status`` directly instead of inferring from payout
vocabulary that was never about Connect.

The backfill below moves any existing Connect row to ``not_applicable``. In
production there are none — no creator has been enabled — so it is a no-op
there and correct everywhere else.

Recovery, as distinct from reversal
-----------------------------------
``connect_transfer_status`` describes the transfer: ``sent``,
``partially_reversed``, ``reversed``. ``connect_recovery_state`` describes
FC's position: whether money is still owed back and could not be taken.
Keeping them apart is what lets a row say "we reversed what we could, and
this much is still outstanding" instead of collapsing to a status that
implies either success or nothing.

``connect_dispute_opened_at`` exists so a disputed charge does not quietly
keep paying its creator. A transfer that has not been sent when a dispute
opens stays owed but is held out of the sweeper's queue until the dispute
closes — reported, never silently stalled.
"""

from alembic import op
import sqlalchemy as sa

revision = "143"
down_revision = "142"
branch_labels = None
depends_on = None


RECOVERY_STATES = ("none", "required", "recovered", "unrecoverable")


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column(
            "connect_recovery_state", sa.String(20),
            nullable=False, server_default="none",
        ),
    )
    # How much of the reversal target Stripe would not give back. The
    # number an admin needs, and the reason "we tried" is not recorded as
    # "we recovered".
    op.add_column(
        "payment_transactions",
        sa.Column(
            "connect_unrecovered_amount_cents", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("reversal_attempted_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column(
            "reversal_attempt_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("reversal_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column(
            "connect_dispute_opened_at", sa.DateTime(timezone=False), nullable=True,
        ),
    )

    # The payout-status decision, applied to any row already routed through
    # Connect. None exist in production; this keeps every environment
    # consistent with the rule above.
    op.execute(
        """
        UPDATE payment_transactions
        SET payout_status = 'not_applicable'
        WHERE payout_model = 'connect'
          AND payout_status = 'pending'
        """
    )

    # Finding what is still owed back, and what is held by a dispute.
    op.create_index(
        "ix_payment_transactions_connect_recovery",
        "payment_transactions", ["connect_recovery_state", "created_at"],
    )

    rendered = ", ".join(f"'{s}'" for s in RECOVERY_STATES)
    op.create_check_constraint(
        "ck_payment_transactions_connect_recovery_state",
        "payment_transactions",
        f"connect_recovery_state IN ({rendered})",
    )
    op.create_check_constraint(
        "ck_payment_transactions_unrecovered_non_negative",
        "payment_transactions",
        "connect_unrecovered_amount_cents >= 0",
    )
    # Only a Connect row can owe anything back. A manual row carrying
    # recovery state would be a row two systems disagree about, exactly as
    # with the transfer columns in 142.
    op.create_check_constraint(
        "ck_payment_transactions_recovery_requires_connect",
        "payment_transactions",
        "payout_model = 'connect' OR ("
        "connect_recovery_state = 'none' "
        "AND connect_unrecovered_amount_cents = 0 "
        "AND connect_dispute_opened_at IS NULL)",
    )


def downgrade() -> None:
    for name in (
        "ck_payment_transactions_recovery_requires_connect",
        "ck_payment_transactions_unrecovered_non_negative",
        "ck_payment_transactions_connect_recovery_state",
    ):
        op.drop_constraint(name, "payment_transactions", type_="check")
    op.drop_index(
        "ix_payment_transactions_connect_recovery",
        table_name="payment_transactions",
    )
    for column in (
        "connect_dispute_opened_at",
        "reversal_last_error",
        "reversal_attempt_count",
        "reversal_attempted_at",
        "connect_unrecovered_amount_cents",
        "connect_recovery_state",
    ):
        op.drop_column("payment_transactions", column)
