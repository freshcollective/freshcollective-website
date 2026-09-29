"""
SQLAlchemy model for the payment transaction ledger.

This table is the internal source of truth for all payment activity:
  - Creator billing: creator → Fresh Collective (subscription payments)
  - Member payments: member → creator (pathway/collective purchases)

Stripe integration is intentionally deferred. All provider_* columns are
present but always NULL until Stripe is integrated.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentTransactionType(str, enum.Enum):
    creator_subscription_payment = "creator_subscription_payment"
    member_pathway_purchase = "member_pathway_purchase"
    member_collective_purchase = "member_collective_purchase"
    member_pathway_subscription = "member_pathway_subscription"
    member_collective_subscription = "member_collective_subscription"
    # Standalone Gathering ticket: one-time purchase of a single event, without
    # buying the Collective. Named "gathering" (not "member") because non-members
    # can also purchase — Stage 1 audit § "Payment transaction type".
    gathering_ticket_purchase = "gathering_ticket_purchase"
    # Gathering Series pass: pay-in-full for a bounded Series (e.g. EMBODY term).
    # Distinct from Pathway/Collective purchase so the ledger reflects the
    # commerce product actually sold.
    member_series_pass_purchase = "member_series_pass_purchase"
    # Generic Payment Option purchase — used by the unified
    # ``POST /api/checkout`` endpoint (B4B). A single PaymentOption
    # can grant any combination of Pathways / Gathering Series /
    # (eventually) Gatherings, so classifying the ledger row by
    # "primary" grant would embed an incorrect assumption. The
    # experiences actually granted live on the option's grants +
    # the downstream AccessPass / PathwayEntitlement rows the
    # webhook writes. Legacy compat wrappers keep their kind-
    # specific transaction types.
    member_payment_option_purchase = "member_payment_option_purchase"
    refund = "refund"
    adjustment = "adjustment"


class PaymentTransactionStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    partially_refunded = "partially_refunded"
    disputed = "disputed"
    cancelled = "cancelled"


class PaymentProvider(str, enum.Enum):
    manual = "manual"
    stripe = "stripe"


class PaymentFulfilmentStatus(str, enum.Enum):
    """Orthogonal to ``PaymentTransactionStatus``.

    ``PaymentTransactionStatus`` records the *payment lifecycle*
    (pending → succeeded / failed / refunded …).
    ``PaymentFulfilmentStatus`` records what happened to the
    downstream access grants once the payment was known to
    succeed. The two axes are deliberately separate: Stripe may
    successfully collect money even when Fresh Collective cannot
    (yet) fulfil the promised access — that state must not be
    invisible.

    States
    ------
    pending
        No fulfilment attempt has committed yet. Applies to every
        row while its payment is still pending, and to rows where
        the previous webhook attempt raised (transaction rolled
        back) so Stripe should retry.

    applied
        The shared fulfilment service ran to completion and
        committed every entitlement / AccessPass / booking the
        purchase promised. Terminal for the happy path.

    blocked
        Payment succeeded, but the shared fulfilment service
        refused to write (e.g. a referenced Pathway or Series row
        does not exist, or the resolver reported a fatal error).
        Marked so operational tooling can surface it; the state is
        recoverable — a subsequent webhook re-delivery (or a
        manual replay after the underlying data is fixed) will
        retry fulfilment.
    """

    pending = "pending"
    applied = "applied"
    blocked = "blocked"


class PayoutStatus(str, enum.Enum):
    not_applicable = "not_applicable"  # creator subscription payments, failed/cancelled
    pending = "pending"                # succeeded member purchase, not yet paid out
    paid = "paid"                      # TODO: set when Stripe Connect transfer confirmed
    held = "held"                      # TODO: set when payout is on hold (dispute, etc.)
    cancelled = "cancelled"            # TODO: set if payout is cancelled


class PayoutModel(str, enum.Enum):
    """How a transaction's creator share reaches the creator.

    Decided once, when the transaction is created, and never re-derived.
    A creator who completes Stripe onboarding (or loses a capability)
    while a checkout is in flight must not change how that purchase pays
    out — the row records the promise made at the time.
    """

    #: Fresh Collective holds the creator's share and pays it out through
    #: ``CreatorPayoutBatch``. Every historical row, and every creator who
    #: has not been individually enabled for Connect routing.
    manual = "manual"
    #: The creator's share is owed to their own Stripe account as a
    #: ``/v1/transfers`` transfer. Only set when the creator is fully
    #: payout-ready *and* deliberately enabled.
    connect = "connect"
    #: No creator share exists — a platform-owned Collective, where the
    #: money stays with Fresh Collective.
    not_applicable = "not_applicable"


class ConnectTransferStatus(str, enum.Enum):
    """State of the transfer that carries a Connect row's creator share.

    The distinction that shapes this enum: *applicable* and *due* are not
    the same thing. A Connect row always owes a transfer eventually, so it
    is never ``not_applicable`` — but it is not owed one until the money
    actually arrives. Hence ``awaiting_payment``, which keeps abandoned and
    still-open Checkout Sessions out of the sweeper's queue without
    pretending a transfer will never apply to them.

    The relationship to ``payout_model`` is exact, and the ledger's CHECK
    constraints enforce it in both directions:

        manual / not_applicable  ⇔  not_applicable
        connect                  ⇔  anything but not_applicable
    """

    #: No transfer will ever be owed — the row is not Connect-routed.
    not_applicable = "not_applicable"
    #: Connect-routed, but the payment has not succeeded. A transfer is
    #: applicable and simply not due yet. The sweeper ignores these.
    awaiting_payment = "awaiting_payment"
    #: The money arrived and the creator's share is owed and unsent. This
    #: is the only state the sweeper acts on.
    pending = "pending"
    sent = "sent"
    #: A genuine dead end, not a retryable hiccup. A transfer that failed
    #: for a reason worth retrying — an insufficient platform balance, for
    #: instance, which is a normal outcome while a charge settles — stays
    #: ``pending`` and records the error instead, so the sweeper keeps it.
    failed = "failed"
    reversed = "reversed"
    partially_reversed = "partially_reversed"


class PaymentTransaction(Base):
    """
    Ledger row for a single payment event.

    Calculation rules:
      Member payments:
        platform_fee_cents        = gross_amount_cents * platform_fee_basis_points / 10000
        net_creator_amount_cents  = gross_amount_cents - platform_fee_cents
        net_platform_amount_cents = platform_fee_cents
        processing_fee_cents      = NULL (Stripe not connected)

      Creator billing:
        platform_fee_basis_points = 0
        platform_fee_cents        = 0
        net_platform_amount_cents = gross_amount_cents
        net_creator_amount_cents  = NULL

    Connect routing (migration 142) does NOT change any of the above.
    ``net_creator_amount_cents`` keeps meaning the creator's share of the
    gross — ``gross - platform_fee`` — and the Stripe processing fee is
    still never subtracted from it. Two things depend on that identity and
    would break if it moved: ``CreatorPayoutBatch`` sums this column across
    every historical row, and the refund invariant
    ``refunded_platform_fee_cents + refunded_creator_amount_cents ==
    refunded_amount_cents`` holds precisely because the gross splits in two.

    The Connect number lives separately, in ``transfer_amount_cents``:

        transfer_amount_cents = net_creator_amount_cents - processing_fee_cents

    Stripe charges the processing fee to Fresh Collective as the platform
    merchant; FC accounts for that cost by retaining it before transferring
    the creator's share, which is why the deduction appears here and not in
    the gross split. ``processing_fee_cents`` continues to be populated
    exactly as before — it simply stops being informational once a row is
    Connect-routed.
    """

    __tablename__ = "payment_transactions"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    transaction_type: Mapped[PaymentTransactionType] = mapped_column(
        SAEnum(
            PaymentTransactionType,
            name="payment_transaction_type_enum",
            create_type=True,
        ),
        nullable=False,
    )
    status: Mapped[PaymentTransactionStatus] = mapped_column(
        SAEnum(
            PaymentTransactionStatus,
            name="payment_transaction_status_enum",
            create_type=True,
        ),
        nullable=False,
        default=PaymentTransactionStatus.pending,
        server_default="pending",
    )
    payment_provider: Mapped[PaymentProvider] = mapped_column(
        SAEnum(
            PaymentProvider,
            name="payment_provider_enum",
            create_type=True,
        ),
        nullable=False,
        default=PaymentProvider.manual,
        server_default="manual",
    )
    # Fulfilment lifecycle — orthogonal to ``status`` above. See the
    # ``PaymentFulfilmentStatus`` docstring for state semantics.
    # Migration 111 adds the column and backfills every historical
    # row to ``applied``; new rows default to ``pending``.
    fulfilment_status: Mapped[PaymentFulfilmentStatus] = mapped_column(
        SAEnum(
            PaymentFulfilmentStatus,
            name="payment_fulfilment_status_enum",
            create_type=True,
        ),
        nullable=False,
        default=PaymentFulfilmentStatus.pending,
        server_default="pending",
    )

    # Parties
    payer_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    creator_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Resource references (all nullable — not all transactions have all of these)
    space_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entitlement_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("pathway_entitlements.id", ondelete="SET NULL"),
        nullable=True,
    )
    creator_plan_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("creator_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    creator_subscription_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("creator_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Money (all stored as integer cents)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="AUD", server_default="AUD"
    )
    gross_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    platform_fee_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    processing_fee_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True
        # TODO: Stripe webhook — populate from Stripe charge.balance_transaction when live
    )
    net_creator_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_platform_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # TODO: Stripe webhook — populate these from webhook events when Stripe is integrated
    provider_checkout_session_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    provider_payment_intent_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    provider_charge_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_invoice_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    # Stripe Checkout hosted URL — stored so a repeat checkout attempt by the
    # same user (with an unexpired hold) can safely be redirected back to the
    # original Session URL rather than creating a new Session and dangling
    # capacity holds. Only populated for Stripe-hosted checkout flows.
    provider_checkout_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Payment option selected at checkout (null for legacy single-price pathway purchases)
    payment_option_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("payment_options.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Payment schedule selected at checkout (null when no schedules on the option)
    payment_option_schedule_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("payment_option_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Finite Payment Plan parent (FIP1, migration 116). Non-null on
    # per-invoice PaymentTransaction rows written by the future
    # ``invoice.payment_succeeded`` handler; NULL on legacy pay-in-
    # full transactions. ``SET NULL`` on plan deletion so historical
    # ledger rows are preserved.
    purchase_plan_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("purchase_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 1-based ordinal for per-invoice transactions belonging to a
    # plan (FIP2, migration 118). Populated by the
    # ``invoice.payment_succeeded`` handler as ``plan.installments_paid
    # + 1``. Enables reporting to say "Payment 3 of 10" without
    # relying on created_at ordering. NULL on pay-in-full rows.
    installment_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # Grants snapshot for pay-in-full purchases (Phase 1, migration
    # 123). JSON-serialised ``FulfilmentIntent`` captured at
    # checkout-session creation. Prevents a Creator edit to the
    # Payment Option's grants between "buyer clicked Pay" and Stripe
    # firing ``checkout.session.completed`` from silently altering
    # what the purchase grants. Nullable so historical ledger rows
    # (pre-migration and future free/legacy paths) fall back to the
    # live-DB resolver in the webhook. Symmetric with
    # ``PurchasePlan.snapshot_grants_json`` — same JSON shape, same
    # ``services.purchase_fulfilment.serialise_intent`` helper.
    snapshot_grants_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )


    # The discount as it stood at purchase, or NULL when none applied.
    # Same stance as ``snapshot_grants_json`` above: a historical
    # purchase must not change because a Creator later edited or
    # disabled the code, so the transaction reads its own copy and never
    # the live ``discount_codes`` row. Some older rows legitimately have
    # neither snapshot — absence means "not recorded", not "no discount".
    discount_snapshot_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Refund state (migration 126). Populated by the
    # ``charge.refunded`` webhook handler with Stripe's cumulative
    # ``charge.amount_refunded`` value — the handler enforces
    # monotonicity so an out-of-order older event cannot regress
    # these fields. ``status`` becomes ``refunded`` (fully) or
    # ``partially_refunded`` when this column is set.
    refunded_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    last_refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    # Fee-split reversal columns (migration 127). Cumulative reversed
    # portions of ``platform_fee_cents`` and ``net_creator_amount_cents``.
    # Maintained by the ``charge.refunded`` handler using
    # ``services.refund_reversal.compute_cumulative_reversal_targets``.
    # Invariant enforced on every write:
    #
    #   refunded_platform_fee_cents + refunded_creator_amount_cents
    #       == refunded_amount_cents
    #
    # (subject to deterministic cent rounding, with a full-refund
    # short-circuit that forces the columns to their exact originals).
    # Zero for rows that have never been refunded.
    refunded_platform_fee_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    refunded_creator_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    # 'test' when created against sk_test_* Stripe keys, 'live' when against sk_live_*.
    # Used to separate sandbox figures from real revenue in dashboards.
    stripe_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="test", server_default="test"
    )

    # Payout tracking — populated by admin when transfer is processed.
    # For manual payouts (migration 129), the CreatorPayoutBatch flow
    # transitions ``pending → paid`` atomically alongside setting
    # ``payout_batch_id``. ``payout_marked_at`` and ``payout_reference``
    # are denormalised convenience copies of the batch's ``paid_at`` and
    # ``reference`` for legacy readers and quick per-row inspection.
    # The authoritative payout history lives on ``CreatorPayoutBatchItem``.
    payout_status: Mapped[PayoutStatus] = mapped_column(
        SAEnum(PayoutStatus, name="payout_status_enum", create_type=False),
        nullable=False,
        default=PayoutStatus.pending,
        server_default="pending",
    )
    payout_marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    payout_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Convenience pointer to the current (most recent uncancelled) batch
    # this transaction is part of. Nullable — cleared by batch
    # cancellation with revert_transactions=True. Not the authoritative
    # history: CreatorPayoutBatchItem is never deleted, so a query on
    # that table gives the full membership trail.
    payout_batch_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("creator_payout_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Connect routing (migration 142) ------------------------------------
    # Snapshotted at creation. Nothing downstream re-reads the creator's
    # current Connect state, because the answer must not change once a
    # buyer has been sent to Stripe.
    payout_model: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default=PayoutModel.manual.value, server_default="manual",
    )
    #: The ``acct_…`` this row's share is owed to, as it stood at checkout.
    #: A creator who later swaps accounts must not retarget an old sale.
    connect_destination_account_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    #: What was (or will be) transferred. For Connect rows this is the
    #: creator's authoritative entitlement, and it is deliberately NOT the
    #: same number as ``net_creator_amount_cents`` — see the class
    #: docstring's calculation rules.
    transfer_amount_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    provider_transfer_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
    )
    connect_transfer_status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default=ConnectTransferStatus.not_applicable.value,
        server_default="not_applicable",
    )
    transfer_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    transfer_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    transfer_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    transfer_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Cumulative, maintained the same monotonic way as
    #: ``refunded_amount_cents``. Zero for rows never reversed.
    reversed_transfer_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_payment_transactions_status", "status"),
        Index("ix_payment_transactions_transaction_type", "transaction_type"),
        Index("ix_payment_transactions_created_at", "created_at"),
        # The future sweeper's query: owed-and-unsent transfers, oldest
        # first.
        Index(
            "ix_payment_transactions_connect_transfer",
            "connect_transfer_status", "created_at",
        ),
        # One transfer per transaction, even under webhook re-delivery.
        # Mirrors the partial unique index on
        # ``provider_checkout_session_id``.
        Index(
            "uq_payment_transactions_provider_transfer_id",
            "provider_transfer_id",
            unique=True,
            postgresql_where=sa_text("provider_transfer_id IS NOT NULL"),
        ),
        CheckConstraint(
            "payout_model IN ('manual', 'connect', 'not_applicable')",
            name="ck_payment_transactions_payout_model",
        ),
        CheckConstraint(
            "connect_transfer_status IN ('not_applicable', 'awaiting_payment', "
            "'pending', 'sent', 'failed', 'reversed', 'partially_reversed')",
            name="ck_payment_transactions_connect_transfer_status",
        ),
        # A Connect row must name the account it owes. This is what makes
        # the snapshot a guarantee rather than a convention.
        CheckConstraint(
            "payout_model <> 'connect' OR connect_destination_account_id IS NOT NULL",
            name="ck_payment_transactions_connect_has_destination",
        ),
        # And nothing else may carry Connect state. A manual row with a
        # transfer id or a transfer status would be a row two systems
        # disagree about.
        CheckConstraint(
            "payout_model = 'connect' OR ("
            "connect_destination_account_id IS NULL "
            "AND provider_transfer_id IS NULL "
            "AND transfer_amount_cents IS NULL "
            "AND connect_transfer_status = 'not_applicable' "
            "AND reversed_transfer_amount_cents = 0)",
            name="ck_payment_transactions_non_connect_has_no_transfer",
        ),
        # The other half of the relationship above: a Connect row always
        # owes a transfer eventually, so ``not_applicable`` is wrong for it
        # even before the payment succeeds.
        CheckConstraint(
            "payout_model <> 'connect' OR connect_transfer_status <> 'not_applicable'",
            name="ck_payment_transactions_connect_transfer_applies",
        ),
        CheckConstraint(
            "transfer_amount_cents IS NULL OR transfer_amount_cents >= 0",
            name="ck_payment_transactions_transfer_amount_non_negative",
        ),
        CheckConstraint(
            "reversed_transfer_amount_cents >= 0",
            name="ck_payment_transactions_reversed_amount_non_negative",
        ),
    )
