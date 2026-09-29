"""Record which payout model each purchase uses, and the transfer it owes.

Revision ID: 142
Revises: 141
Create Date: 2026-09-29

Storage and bookkeeping only. **No money moves differently.** Nothing in
this revision sends a Stripe Transfer, and no row is created with
``payout_model = 'connect'`` unless a creator has been individually and
deliberately enabled — which no creator has been, because
``creator_stripe_accounts.connect_payouts_enabled_at`` is NULL for
everyone.

This is the deliberate seam in the Connect work: it makes the routing
decision observable in the ledger *before* a single cent moves differently.
If the decision comes out wrong for any creator, that is discoverable with
a query rather than from a transfer.

The mechanism this supports
---------------------------
Fresh Collective uses **separate charges and transfers**, not destination
charges. The charge stays on the platform account exactly as today — no
Checkout Session parameter changes anywhere — and the creator's share is
sent afterwards as a ``/v1/transfers`` transfer. That choice follows from
the fee rule:

    creator proceeds = gross - FC platform fee - actual Stripe processing fee

Stripe bills the processing fee to Fresh Collective as the platform
merchant, and its exact amount only exists once the charge has a balance
transaction. ``application_fee_amount`` must be fixed at Session creation,
so a destination charge cannot express that number without estimating it —
and the estimate error would *be* the whole fee for a Founding Creator on
0%.

Transfer status
---------------
``connect_transfer_status`` distinguishes *applicable* from *due*. A
Connect row is created ``awaiting_payment``: a transfer will be owed, but
not until the money arrives. Fulfilment moves it to ``pending``, which is
the only state the future sweeper acts on — so abandoned and still-open
Checkout Sessions never enter its queue, and no row has to pretend a
transfer will never apply to it. The CHECK constraints make the
relationship exact in both directions:

    manual / not_applicable  ⇔  not_applicable
    connect                  ⇔  anything but not_applicable

Why the snapshot
----------------
``payout_model`` and ``connect_destination_account_id`` are decided once,
when the transaction is created, and never re-derived. A creator who
finishes onboarding — or loses a capability — while a buyer is away at
Stripe must not change how that purchase pays out. Same discipline as
``snapshot_grants_json`` and ``discount_snapshot_json`` on this table, and
``platform_fee_basis_points`` on ``purchase_plans``.

What is deliberately NOT changed
--------------------------------
``net_creator_amount_cents`` keeps meaning ``gross - platform_fee``. The
processing fee is not subtracted from it, because ``CreatorPayoutBatch``
sums that column across all history and the refund invariant
``refunded_platform_fee + refunded_creator == refunded_amount`` holds only
while the gross splits in two. The Connect figure lives in the new
``transfer_amount_cents``.

Backfill
--------
``not_applicable`` where ``payout_status = 'not_applicable'`` — those are
platform-owned Collectives, where no creator share exists. Everything else
becomes ``manual``, which is what every historical row already is in
practice. Adding NOT NULL columns with a server default does not rewrite
the table on PostgreSQL 11+, so the only row-touching work is that one
targeted UPDATE.
"""

from alembic import op
import sqlalchemy as sa

revision = "142"
down_revision = "141"
branch_labels = None
depends_on = None


PAYOUT_MODELS = ("manual", "connect", "not_applicable")
TRANSFER_STATUSES = (
    "not_applicable", "awaiting_payment", "pending", "sent", "failed",
    "reversed", "partially_reversed",
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column(
            "payout_model", sa.String(20),
            nullable=False, server_default="manual",
        ),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("connect_destination_account_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("transfer_amount_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("provider_transfer_id", sa.String(200), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column(
            "connect_transfer_status", sa.String(20),
            nullable=False, server_default="not_applicable",
        ),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("transfer_attempted_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("transfer_sent_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column(
            "transfer_attempt_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("transfer_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column(
            "reversed_transfer_amount_cents", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )

    # Platform-owned Collectives never owed a creator anything, and
    # ``payout_status`` already records exactly that.
    op.execute(
        """
        UPDATE payment_transactions
        SET payout_model = 'not_applicable'
        WHERE payout_status = 'not_applicable'
        """
    )

    # The future sweeper's query: owed-and-unsent transfers, oldest first.
    op.create_index(
        "ix_payment_transactions_connect_transfer",
        "payment_transactions", ["connect_transfer_status", "created_at"],
    )
    # One transfer per transaction, even under webhook re-delivery. Mirrors
    # the existing partial unique index on provider_checkout_session_id.
    op.create_index(
        "uq_payment_transactions_provider_transfer_id",
        "payment_transactions", ["provider_transfer_id"],
        unique=True,
        postgresql_where=sa.text("provider_transfer_id IS NOT NULL"),
    )

    op.create_check_constraint(
        "ck_payment_transactions_payout_model",
        "payment_transactions",
        _in_list("payout_model", PAYOUT_MODELS),
    )
    op.create_check_constraint(
        "ck_payment_transactions_connect_transfer_status",
        "payment_transactions",
        _in_list("connect_transfer_status", TRANSFER_STATUSES),
    )
    # A Connect row must name the account it owes. This is what turns the
    # snapshot from a convention into a guarantee.
    op.create_check_constraint(
        "ck_payment_transactions_connect_has_destination",
        "payment_transactions",
        "payout_model <> 'connect' OR connect_destination_account_id IS NOT NULL",
    )
    # And nothing else may carry Connect state: a manual row holding a
    # transfer id or a transfer status is a row two systems disagree about.
    op.create_check_constraint(
        "ck_payment_transactions_non_connect_has_no_transfer",
        "payment_transactions",
        "payout_model = 'connect' OR ("
        "connect_destination_account_id IS NULL "
        "AND provider_transfer_id IS NULL "
        "AND transfer_amount_cents IS NULL "
        "AND connect_transfer_status = 'not_applicable' "
        "AND reversed_transfer_amount_cents = 0)",
    )
    # The other half: a Connect row always owes a transfer eventually, so
    # ``not_applicable`` is wrong for it even before the payment succeeds.
    # ``awaiting_payment`` carries "applicable but not due yet", which is
    # what keeps abandoned Checkout Sessions out of the sweeper's queue
    # without claiming a transfer will never apply.
    op.create_check_constraint(
        "ck_payment_transactions_connect_transfer_applies",
        "payment_transactions",
        "payout_model <> 'connect' OR connect_transfer_status <> 'not_applicable'",
    )
    op.create_check_constraint(
        "ck_payment_transactions_transfer_amount_non_negative",
        "payment_transactions",
        "transfer_amount_cents IS NULL OR transfer_amount_cents >= 0",
    )
    op.create_check_constraint(
        "ck_payment_transactions_reversed_amount_non_negative",
        "payment_transactions",
        "reversed_transfer_amount_cents >= 0",
    )


def downgrade() -> None:
    for name in (
        "ck_payment_transactions_reversed_amount_non_negative",
        "ck_payment_transactions_transfer_amount_non_negative",
        "ck_payment_transactions_connect_transfer_applies",
        "ck_payment_transactions_non_connect_has_no_transfer",
        "ck_payment_transactions_connect_has_destination",
        "ck_payment_transactions_connect_transfer_status",
        "ck_payment_transactions_payout_model",
    ):
        op.drop_constraint(name, "payment_transactions", type_="check")

    op.drop_index(
        "uq_payment_transactions_provider_transfer_id",
        table_name="payment_transactions",
    )
    op.drop_index(
        "ix_payment_transactions_connect_transfer",
        table_name="payment_transactions",
    )

    for column in (
        "reversed_transfer_amount_cents",
        "transfer_last_error",
        "transfer_attempt_count",
        "transfer_sent_at",
        "transfer_attempted_at",
        "connect_transfer_status",
        "provider_transfer_id",
        "transfer_amount_cents",
        "connect_destination_account_id",
        "payout_model",
    ):
        op.drop_column("payment_transactions", column)
