"""A creator's Stripe Connect account, and FC's picture of its readiness.

One row per creator per Stripe mode. The grain is the creator ``User``
because that is already how payouts are scoped — ``CreatorPayoutBatch``
keys on ``(creator_user_id, currency)`` explicitly "because a creator's
future Stripe Connect account is per-User".

Mode is part of the key, not a detail. FC runs test and live keys in
different environments against the same database shape, and a test-mode
``acct_…`` used under a live key would be a silent failure at the worst
possible moment. ``UNIQUE(creator_user_id, stripe_mode)`` lets both exist
and keeps them apart.

Nothing here is authoritative. Stripe owns this state; these columns are
a projection of it, written by the sync path so FC can render a page and
make a routing decision without a network call. When they disagree with
Stripe, Stripe is right.

Why raw statuses rather than two booleans
-----------------------------------------
``transfers_status`` and ``payouts_status`` store Stripe's own values —
``active | pending | restricted | unsupported`` — alongside their
``status_details`` codes. A boolean cannot tell "restricted, the creator
should provide more information" from "unsupported, nothing they do will
help", and those are different screens and different decisions. The
booleans remain as derived conveniences for the one hot path that only
needs a yes/no, guarded by CHECK constraints so they cannot drift from
the status they summarise.

The two capabilities are separate on purpose
--------------------------------------------
Verified against a real account: ``stripe_transfers`` needs identity and
ToS acceptance, while ``payouts`` needs those *plus* an external account.
So an account can be transfer-ready with no bank account attached, and FC
would move real money into a balance that cannot leave. That is the
``transfers_only`` state, and it is why ``connect_payouts_enabled_at``
carries a CHECK requiring ``payouts_enabled`` — the gate is enforced in
the schema, not only in the code that sets it.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OnboardingState(str, enum.Enum):
    """FC's single derived answer to "where is this creator up to?".

    Derived from Stripe's fields by
    ``app.services.connect_account_state.project``; never set by hand.
    """

    #: No Stripe account exists yet — nothing has been created.
    not_started = "not_started"
    #: An account exists but the creator has not finished submitting.
    onboarding = "onboarding"
    #: Stripe is checking what was submitted. Ask the creator for nothing.
    verifying = "verifying"
    #: The creator submitted, and Stripe has come back wanting more.
    action_required = "action_required"
    #: Transfers are live but payouts are not — usually no bank account.
    transfers_only = "transfers_only"
    #: Both capabilities active. The only state in which Connect routing
    #: may be enabled for this creator.
    ready = "ready"
    #: Blocked in a way the creator cannot resolve themselves; Stripe
    #: must be contacted. Also the conservative fallback.
    restricted = "restricted"
    #: The creator's country, entity type or business cannot receive
    #: transfers at all. Terminal — never invite a retry.
    unsupported = "unsupported"
    #: The account has been closed.
    closed = "closed"


class CapabilityStatus(str, enum.Enum):
    """Stripe's own capability status values, read from the v2 API.

    Note the absence of ``rejected``: rejection surfaces as
    ``restricted`` with a ``restricted_other`` detail code and a
    ``contact_stripe`` resolution.
    """

    active = "active"
    pending = "pending"
    restricted = "restricted"
    unsupported = "unsupported"


class SyncSource(str, enum.Enum):
    """Where the last projection came from, for diagnosing a stale row."""

    webhook = "webhook"
    onboarding_return = "onboarding_return"
    manual = "manual"


_ONBOARDING_STATES = tuple(s.value for s in OnboardingState)
_CAPABILITY_STATUSES = tuple(s.value for s in CapabilityStatus)
_SYNC_SOURCES = tuple(s.value for s in SyncSource)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


class CreatorStripeAccount(Base):
    __tablename__ = "creator_stripe_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # csa_<uuid>

    creator_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    #: 'test' | 'live' — mirrors ``PaymentTransaction.stripe_mode``.
    stripe_mode: Mapped[str] = mapped_column(String(10), nullable=False)

    #: Null between creating this row and a successful v2 account create.
    stripe_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    onboarding_state: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default=OnboardingState.not_started.value,
        server_default=OnboardingState.not_started.value,
    )

    # --- capability state, as Stripe reports it -----------------------------
    transfers_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transfers_status_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    payouts_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payouts_status_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: Derived from ``transfers_status``. This is the flag the money path
    #: consults — confirmed by Stripe refusing a transfer with
    #: ``insufficient_capabilities_for_transfer`` and naming exactly
    #: ``configurations.recipient.capabilities.stripe_balance.stripe_transfers``.
    transfers_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    #: Derived from ``payouts_status``. Money can leave the connected
    #: balance for the creator's bank only when this is true.
    payouts_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )

    # --- requirements -------------------------------------------------------
    #: v1-only. Separates "has not finished onboarding" from "finished,
    #: and Stripe has since asked for more".
    details_submitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    #: Requirement *entries*, not field names. Each carries
    #: ``description``, ``awaiting_action_from``, ``restricts_capabilities``
    #: and ``errors``. ``awaiting_action_from`` is the only thing that
    #: distinguishes ``action_required`` from ``verifying`` — a non-empty
    #: list of due fields cannot, because it does not say who must act.
    currently_due_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    requirements_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    # --- v1-only facts about getting money to the bank ----------------------
    #: Absent from the v2 account object entirely; read from v1.
    external_account_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    #: ``settings.payouts.schedule``. Present from account creation —
    #: Stripe pays out automatically and FC creates no payouts. Stored so
    #: the UI can say "paid out daily, two days after each sale" without
    #: a Stripe round trip.
    payout_interval: Mapped[str | None] = mapped_column(String(10), nullable=True)
    payout_delay_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Defaults true. Stripe will attempt to recover a negative balance
    #: from the creator's bank account without FC asking — which matters
    #: for the refund and dispute work in a later phase.
    debit_negative_balances: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # --- how the account was configured ------------------------------------
    dashboard: Mapped[str | None] = mapped_column(String(10), nullable=True)
    fees_collector: Mapped[str | None] = mapped_column(String(30), nullable=True)
    losses_collector: Mapped[str | None] = mapped_column(String(30), nullable=True)
    #: Observed as ``"stripe"``, set by Stripe rather than by FC — it
    #: follows from ``dashboard: "express"``. Recorded so that if FC ever
    #: takes on collecting requirements itself, the change is visible
    #: rather than inferred from a wall of 403s.
    requirements_collector: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # --- the routing gate ---------------------------------------------------
    #: Non-null means new purchases for this creator route through
    #: Connect. Deliberately separate from the capability flags: Stripe
    #: saying "ready" must never by itself start moving money. A CHECK
    #: below refuses to let this be set without ``payouts_enabled``.
    connect_payouts_enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    # --- diagnostics --------------------------------------------------------
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    last_sync_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Answers "did they ever actually start?" without guessing. Account
    #: links expire five minutes after creation, so a creator who never
    #: returns is common and worth telling apart from one who never began.
    last_account_link_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    account_link_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "creator_user_id", "stripe_mode",
            name="uq_creator_stripe_accounts_creator_mode",
        ),
        CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_creator_stripe_accounts_mode",
        ),
        CheckConstraint(
            _in_list("onboarding_state", _ONBOARDING_STATES),
            name="ck_creator_stripe_accounts_onboarding_state",
        ),
        CheckConstraint(
            "transfers_status IS NULL OR "
            + _in_list("transfers_status", _CAPABILITY_STATUSES),
            name="ck_creator_stripe_accounts_transfers_status",
        ),
        CheckConstraint(
            "payouts_status IS NULL OR "
            + _in_list("payouts_status", _CAPABILITY_STATUSES),
            name="ck_creator_stripe_accounts_payouts_status",
        ),
        CheckConstraint(
            "last_sync_source IS NULL OR "
            + _in_list("last_sync_source", _SYNC_SOURCES),
            name="ck_creator_stripe_accounts_sync_source",
        ),
        # The derived booleans cannot drift from the status they
        # summarise. Without this a bad write could leave
        # ``transfers_enabled`` true against a restricted capability, and
        # the money path reads the boolean.
        CheckConstraint(
            "transfers_enabled = (transfers_status = 'active')",
            name="ck_creator_stripe_accounts_transfers_enabled_matches",
        ),
        CheckConstraint(
            "payouts_enabled = (payouts_status = 'active')",
            name="ck_creator_stripe_accounts_payouts_enabled_matches",
        ),
        # The Phase 2 gate, in the schema. Transfers being live is not
        # enough: without payouts the money arrives somewhere it cannot
        # leave, so routing must not be switchable on that alone.
        CheckConstraint(
            "connect_payouts_enabled_at IS NULL OR "
            "(payouts_enabled AND stripe_account_id IS NOT NULL)",
            name="ck_creator_stripe_accounts_routing_requires_payouts",
        ),
        # A Stripe account id belongs to exactly one row. Partial so the
        # pre-create state (many rows with NULL) stays legal.
        Index(
            "uq_creator_stripe_accounts_account_id",
            "stripe_account_id",
            unique=True,
            postgresql_where=sa_text("stripe_account_id IS NOT NULL"),
        ),
        # Operational lookups: "who is stuck?" per environment.
        Index(
            "ix_creator_stripe_accounts_mode_state",
            "stripe_mode", "onboarding_state",
        ),
    )
