"""
PurchaseIntent — Fresh Collective domain model for a purchase in flight.

This is a *Fresh Collective* concept, not Stripe's `PaymentIntent`. Stripe's
PaymentIntent represents a specific card authorisation attempt; our
`PurchaseIntent` represents a customer's *intent to purchase something on
Fresh Collective*, from the moment we begin the journey (before the Stripe
Checkout Session exists) through to the moment access is granted (or the
intent expires / is cancelled / is refunded).

Motivation: some Fresh Collective purchases must be able to occur *before*
the buyer has an account (e.g. a new visitor buying a Creator plan or a
paid Collective membership). `PaymentTransaction` (the ledger) requires a
`payer_user_id`; it is not a suitable carrier for pre-account state. This
model sits upstream and holds the journey together across:

    - Creator subscription purchase before account creation
    - Existing Member purchasing a Creator plan
    - Paid Collective membership
    - Paid Pathway
    - Paid Gathering

Stage 1 (this file) creates the stable core only. Consumption, claim-token
API, webhook activation, entitlement grants and Creator role changes are
deliberately *not* implemented here — they belong to later stages.

Design notes:

  * `kind` uses *stable internal* values (`creator_subscription`,
    `collective_membership`, `pathway`, `gathering`). Public plan display
    names such as "Creator Portfolio" or "Ecosystem" are never persisted
    as kinds — the stable plan slug (`pro`) is stored in `plan_slug`
    instead.
  * `status` is deliberately minimal. Expiry of the *claim token*
    (`claim_token_expires_at`) is separate from the *intent status*: a
    paid but unclaimed intent must not silently become forfeited — it
    remains `paid` and the claim window closing is a support-recoverable
    situation, not a status transition.
  * Claim tokens follow the `PasswordReset` pattern: raw token is
    generated at Session-creation time, only the SHA-256 hash is stored,
    and the raw token appears in the Stripe success URL.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PurchaseIntentKind(str, enum.Enum):
    """What is being purchased. Uses stable internal identifiers only.

    Public plan display names (e.g. "Creator", "Creator Portfolio",
    "Ecosystem") are *not* kinds — they are one specific plan under
    ``creator_subscription`` and are identified by ``plan_slug``.
    """
    creator_subscription = "creator_subscription"
    collective_membership = "collective_membership"
    pathway = "pathway"
    gathering = "gathering"


class PurchaseIntentStatus(str, enum.Enum):
    """Minimal, honest lifecycle.

    ``pending``   — intent created, awaiting payment confirmation.
    ``paid``      — Stripe (or equivalent) has confirmed the payment.
                    The buyer's access is still to be granted; the
                    intent is *not* consumed yet.
    ``consumed``  — access has been granted / entitlement issued. The
                    intent has done its job and will not be re-used.
    ``cancelled`` — the buyer or an operator abandoned the intent
                    before payment.
    ``expired``   — an unpaid intent whose Checkout Session was
                    invalidated (Stripe fires ``checkout.session.expired``)
                    or which timed out server-side. NOTE: this is
                    distinct from ``claim_token_expires_at`` on a
                    *paid* intent — a paid but unclaimed purchase
                    stays ``paid`` and remains support-recoverable.
    ``refunded``  — payment was reversed (Stripe refund). Any granted
                    access should be revoked by consumption handlers.
    """
    pending = "pending"
    paid = "paid"
    consumed = "consumed"
    cancelled = "cancelled"
    expired = "expired"
    refunded = "refunded"


class PurchaseIntent(Base):
    """A purchase journey, held together from selection through to
    entitlement grant.

    Fields marked "nullable until priced" or "nullable until provider
    identifies" are set by service code as the journey progresses —
    Stage 1 only creates the schema; the transitions themselves land in
    later stages.
    """

    __tablename__ = "purchase_intents"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    kind: Mapped[PurchaseIntentKind] = mapped_column(
        SAEnum(
            PurchaseIntentKind,
            name="purchase_intent_kind_enum",
            create_type=True,
        ),
        nullable=False,
    )
    status: Mapped[PurchaseIntentStatus] = mapped_column(
        SAEnum(
            PurchaseIntentStatus,
            name="purchase_intent_status_enum",
            create_type=True,
        ),
        nullable=False,
        default=PurchaseIntentStatus.pending,
        server_default="pending",
    )

    # ── Parties ────────────────────────────────────────────────────────
    # payer_user_id is nullable so that a brand-new visitor can begin an
    # intent before they have an account. It is populated at Session
    # creation time when the visitor is already logged in, or at
    # consumption time when a new account is created against the
    # intent's claim token.
    payer_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # created_by_user_id records who initiated the intent. Almost always
    # equal to payer_user_id for logged-in flows, but stays populated
    # even if the eventual payer differs (rare). Nullable for anonymous
    # flows.
    created_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Subject of the purchase ────────────────────────────────────────
    # Exactly which of these are populated depends on ``kind``.
    # Kind → required field mapping is enforced in service code, not by
    # a database CHECK, so future kinds can be added without a fragile
    # migration.
    plan_slug: Mapped[str | None] = mapped_column(String(32), nullable=True)
    space_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True
    )
    pathway_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("pathways.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    payment_option_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("payment_options.id", ondelete="SET NULL"), nullable=True
    )

    # ── Pricing snapshot (nullable until priced) ───────────────────────
    # Snapshotted at Session-creation time so the amount agreed with
    # the buyer cannot drift if a plan price or fee changes mid-flight.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    gross_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_fee_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Provider (Stripe today; column left open for the future) ───────
    provider: Mapped[str] = mapped_column(
        String(16), nullable=False, default="stripe", server_default="stripe"
    )
    # ``provider_checkout_session_id`` is our idempotency anchor for
    # webhook processing — mirrors the pattern already used on
    # ``payment_transactions``.
    provider_checkout_session_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    provider_customer_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )

    # ── Claim token (raw token never stored) ───────────────────────────
    # Generated *before* Stripe Checkout Session creation so it can be
    # baked into the success URL. Storage follows the PasswordReset
    # pattern: only the SHA-256 hash is persisted.
    claim_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    claim_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    # ── Consumption tracking ───────────────────────────────────────────
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    consumed_by_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Audit ──────────────────────────────────────────────────────────
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
        # Idempotency anchor: at most one intent per Stripe Session.
        # Partial index so many rows can share NULL before a Session is
        # created (matches the existing convention on
        # ``payment_transactions.provider_checkout_session_id``).
        Index(
            "ix_purchase_intents_provider_checkout_session_id",
            "provider_checkout_session_id",
            unique=True,
            postgresql_where=(
                "provider_checkout_session_id IS NOT NULL"
            ),
        ),
        # Claim-token lookup + guarantee no two intents share a hash.
        Index(
            "ix_purchase_intents_claim_token_hash",
            "claim_token_hash",
            unique=True,
            postgresql_where=("claim_token_hash IS NOT NULL"),
        ),
        # Reconciler / expiry-sweeper query shape.
        Index("ix_purchase_intents_status_created_at", "status", "created_at"),
    )
