"""Switching a creator's sales over to Connect, and the acknowledgement first.

Two acts, deliberately separate and deliberately in this order.

The creator acknowledges the fee model. That is theirs to give and it changes
nothing on its own — acknowledging is not enabling, and a creator cannot route
their own money.

Fresh Collective then enables routing. That is an administrative decision, made
once per creator, and it is the only thing in this codebase that causes money
to take a different path. Nothing automatic may do it: not onboarding
completing, not a webhook reporting a capability active, not a sweeper. Stripe
saying an account is ready is an input to the decision, never the decision.

Why acknowledgement is a precondition
-------------------------------------
Connect changes what a creator receives. Today FC absorbs the Stripe processing
fee; once their sales route through Connect that fee comes out of each sale
before FC's own. For a Founding Creator on a 0% platform fee the change is
starkest — they go from receiving the full price to receiving the price less
Stripe's fee — and 0% is exactly the number most likely to have been heard as
"nothing is deducted". Nobody should learn that from a bank statement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.creator_stripe_account import (
    FEE_DISCLOSURE_VERSION,
    CreatorStripeAccount,
    OnboardingState,
)

logger = logging.getLogger(__name__)


class RoutingEnablementError(RuntimeError):
    """Routing cannot be enabled for this creator yet.

    Carries a machine-readable ``reason`` so an admin UI can say which
    condition is missing rather than "not allowed".
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class EnablementReadiness:
    """Whether every condition holds, and which do not."""

    ready: bool
    blockers: list[str]


#: The five conditions. Each is checked independently so an admin sees all of
#: what is missing, not just the first thing to fail.
BLOCKER_NO_ACCOUNT_ROW = "no_account_for_current_mode"
BLOCKER_NO_ACCOUNT_ID = "no_stripe_account_id"
BLOCKER_PAYOUTS_NOT_ACTIVE = "payouts_status_not_active"
BLOCKER_PAYOUTS_NOT_ENABLED = "payouts_not_enabled"
BLOCKER_NOT_ACKNOWLEDGED = "fee_disclosure_not_acknowledged"


def find_account(db: Session, *, creator_user_id: str) -> CreatorStripeAccount | None:
    """The creator's account **for this environment's Stripe mode only**.

    Mode-scoped like every other Connect lookup: enabling routing against a
    live account from a test deployment, or the reverse, would only be
    discovered by a failed transfer.
    """
    return (
        db.query(CreatorStripeAccount)
        .filter(
            CreatorStripeAccount.creator_user_id == creator_user_id,
            CreatorStripeAccount.stripe_mode == settings.stripe_mode,
        )
        .first()
    )


def find_awaiting_enablement(db: Session) -> list[CreatorStripeAccount]:
    """Creators who could be switched over, and have not been.

    **Read-only.** This function exists so an admin is told when a creator
    has finished everything asked of them and is now waiting on a decision
    only Fresh Collective can make. It writes nothing, enables nothing, and
    changes none of the guards below — being on this list is a prompt to a
    person, never a step towards routing.

    Stricter than :func:`assess` on purpose. ``assess`` asks whether the
    *payouts* capability is active, because that is what makes a transfer
    reach a bank. This asks for ``onboarding_state == ready``, which the
    projection only reaches when transfers **and** payouts are both active.
    So an account can satisfy the enable guard without appearing here —
    deliberately: a prompt that fires while a capability is still settling
    would send an admin to press a button they should not yet press. The
    guard is the authority on what is permitted; this is only what is worth
    mentioning.

    Mode-scoped, like every other Connect lookup.

    Uncapped, and that is the point: the result is self-clearing. A row
    leaves this list the moment routing is enabled or readiness lapses, so
    it cannot accumulate into a list worth truncating — and truncating it
    would quietly hide the creator waiting longest.
    """
    return (
        db.query(CreatorStripeAccount)
        .filter(
            CreatorStripeAccount.stripe_mode == settings.stripe_mode,
            CreatorStripeAccount.stripe_account_id.isnot(None),
            CreatorStripeAccount.onboarding_state == OnboardingState.ready.value,
            CreatorStripeAccount.payouts_enabled.is_(True),
            CreatorStripeAccount.fee_disclosure_acknowledged_at.isnot(None),
            CreatorStripeAccount.connect_payouts_enabled_at.is_(None),
        )
        .order_by(CreatorStripeAccount.fee_disclosure_acknowledged_at.asc())
        .all()
    )


def assess(account: CreatorStripeAccount | None) -> EnablementReadiness:
    """Every unmet condition, not just the first."""
    blockers: list[str] = []
    if account is None:
        return EnablementReadiness(ready=False, blockers=[BLOCKER_NO_ACCOUNT_ROW])

    if not account.stripe_account_id:
        blockers.append(BLOCKER_NO_ACCOUNT_ID)
    if account.payouts_status != "active":
        blockers.append(BLOCKER_PAYOUTS_NOT_ACTIVE)
    if not account.payouts_enabled:
        blockers.append(BLOCKER_PAYOUTS_NOT_ENABLED)
    if account.fee_disclosure_acknowledged_at is None:
        blockers.append(BLOCKER_NOT_ACKNOWLEDGED)

    return EnablementReadiness(ready=not blockers, blockers=blockers)


def acknowledge_fee_disclosure(
    db: Session, *, creator_user_id: str, now: datetime | None = None,
) -> CreatorStripeAccount:
    """Record that the creator has seen how the fees fall.

    Explicitly does **not** enable routing. Acknowledging is a precondition the
    creator controls; the decision to route their money is not theirs and not
    automatic.

    Idempotent in effect: re-acknowledging the same version refreshes the
    timestamp and nothing else.
    """
    now = now or datetime.utcnow()
    account = find_account(db, creator_user_id=creator_user_id)
    if account is None:
        raise RoutingEnablementError(
            BLOCKER_NO_ACCOUNT_ROW,
            "Connect a Stripe account before acknowledging the fee model.",
        )

    account.fee_disclosure_acknowledged_at = now
    account.fee_disclosure_version = FEE_DISCLOSURE_VERSION
    db.commit()

    logger.info(
        "connect: creator=%s acknowledged the fee disclosure (version=%s). "
        "Routing is NOT enabled by this — that remains a separate admin action.",
        creator_user_id, FEE_DISCLOSURE_VERSION,
    )
    return account


def enable_routing(
    db: Session,
    *,
    creator_user_id: str,
    enabled_by_user_id: str,
    now: datetime | None = None,
) -> CreatorStripeAccount:
    """Route this creator's future sales through Connect.

    The only place ``connect_payouts_enabled_at`` is ever assigned. Re-entrant:
    a creator already enabled is returned unchanged rather than re-stamped, so
    the timestamp keeps meaning "when this decision was made".

    Raises :class:`RoutingEnablementError` naming the first unmet condition.
    The schema enforces two of them independently — routing requires
    ``payouts_enabled`` and an acknowledgement — so a future caller that skips
    this function still cannot produce an unsafe row.
    """
    now = now or datetime.utcnow()
    account = find_account(db, creator_user_id=creator_user_id)
    readiness = assess(account)

    if not readiness.ready:
        reason = readiness.blockers[0]
        raise RoutingEnablementError(reason, _explain(reason))

    assert account is not None   # assess() guarantees it

    if account.connect_payouts_enabled_at is not None:
        logger.info(
            "connect: creator=%s already routed through Connect since %s",
            creator_user_id, account.connect_payouts_enabled_at,
        )
        return account

    account.connect_payouts_enabled_at = now
    db.commit()

    # Deliberately loud. This is the moment a creator's money changes path.
    logger.warning(
        "connect: ROUTING ENABLED for creator=%s by=%s at=%s account=%s mode=%s. "
        "Future sales transfer their share to the creator's Stripe account; "
        "purchases already in flight keep the model they were created with.",
        creator_user_id, enabled_by_user_id, now,
        account.stripe_account_id, account.stripe_mode,
    )
    return account


def disable_routing(
    db: Session,
    *,
    creator_user_id: str,
    disabled_by_user_id: str,
) -> CreatorStripeAccount:
    """Stop routing this creator's *future* sales through Connect.

    Does not touch anything already in flight. Every existing purchase and plan
    snapshotted its payout model at creation, and a transfer already owed is
    still owed — reversing that decision retrospectively would leave a creator
    paid by neither route.
    """
    account = find_account(db, creator_user_id=creator_user_id)
    if account is None:
        raise RoutingEnablementError(
            BLOCKER_NO_ACCOUNT_ROW, "No Stripe account for this creator.",
        )

    if account.connect_payouts_enabled_at is None:
        return account

    account.connect_payouts_enabled_at = None
    db.commit()
    logger.warning(
        "connect: routing DISABLED for creator=%s by=%s. Purchases and plans "
        "already created keep their snapshotted payout model.",
        creator_user_id, disabled_by_user_id,
    )
    return account


def _explain(reason: str) -> str:
    return {
        BLOCKER_NO_ACCOUNT_ROW: (
            f"This creator has no {settings.stripe_mode}-mode Stripe account."
        ),
        BLOCKER_NO_ACCOUNT_ID: (
            "This creator's Stripe account has not been created yet."
        ),
        BLOCKER_PAYOUTS_NOT_ACTIVE: (
            "Stripe has not activated payouts for this account. Until it does, "
            "money transferred to them could not reach their bank."
        ),
        BLOCKER_PAYOUTS_NOT_ENABLED: (
            "Payouts are not enabled on this account."
        ),
        BLOCKER_NOT_ACKNOWLEDGED: (
            "This creator has not acknowledged the fee model. Connect changes "
            "what they receive, so they must see that before it applies."
        ),
    }.get(reason, "Connect routing cannot be enabled for this creator yet.")
