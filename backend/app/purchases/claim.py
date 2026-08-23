"""
PurchaseIntent claim orchestrator.

Kind-agnostic. This module owns exactly two questions:

  1. Is this PurchaseIntent in a state that permits activation, and is
     the supplied user allowed to claim it?
  2. Which per-kind domain service does the actual work?

It does NOT contain any creator-plan specifics — those live in
``app.creator.plan_activation``. When future intent kinds (paid
Pathway, paid Gathering, paid Collective membership) arrive, each
adds its own dispatch branch here and its own domain service
elsewhere. ``PurchaseIntent`` remains the central source of truth
for every purchase journey.

Callers today:
  * ``webhooks.routes`` — auto-claims for a known payer.
  * ``purchases.routes`` — logged-in visitor claim, new-user claim.

Public API:
  * :func:`claim_intent` — validates + dispatches + marks consumed.
  * :func:`fetch_intent_by_raw_token` — token lookup + hash check.
  * Errors: :class:`InvalidClaimTokenError`, :class:`ClaimTokenExpiredError`,
    :class:`IntentNotPaidError`,
    :class:`IntentAlreadyConsumedByOtherUserError`,
    :class:`IntentEmailMismatchError`,
    :class:`UnsupportedIntentKindError`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.creator.plan_activation import (
    ActivationSource,
    activate_creator_plan,
)
from app.models.purchase_intent import (
    PurchaseIntent,
    PurchaseIntentKind,
    PurchaseIntentStatus,
)
from app.models.user import User
from app.purchases.service import hash_claim_token

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors — every path that touches an intent raises exactly one of these
# ---------------------------------------------------------------------------


class ClaimError(RuntimeError):
    """Base class for all claim failures. Route handlers translate
    concrete subclasses into HTTP responses."""


class InvalidClaimTokenError(ClaimError):
    """Token did not match any PurchaseIntent."""


class ClaimTokenExpiredError(ClaimError):
    """The intent's claim token has passed its expiry timestamp. Per
    the Stage 1 brief a *paid* intent whose claim token elapses is
    not silently forfeited — the intent stays ``paid`` — but the
    frontend must show a "contact support" state rather than allow
    claim through the elapsed token."""


class IntentNotPaidError(ClaimError):
    """Intent has not yet been marked paid by the webhook. Frontend
    should poll / render a 'waiting for payment' state."""


class IntentAlreadyConsumedByOtherUserError(ClaimError):
    """Intent is consumed and bound to a different user."""


class IntentEmailMismatchError(ClaimError):
    """Intent's claim_email doesn't match the supplied user's email.
    Prevents someone with the token from binding a purchase to the
    wrong account."""


class UnsupportedIntentKindError(ClaimError):
    """Intent kind isn't wired for claim in this stage (e.g. paid
    Pathway / Gathering / Collective membership will land in Stage 5)."""


# ---------------------------------------------------------------------------
# Token lookup
# ---------------------------------------------------------------------------


def fetch_intent_by_raw_token(
    db: Session, raw_token: str, *, for_update: bool = False,
) -> PurchaseIntent:
    """Hash the caller-supplied raw token and return the matching
    PurchaseIntent, or raise :class:`InvalidClaimTokenError`.

    Set ``for_update=True`` when the caller intends to mutate the
    intent — takes a row-level SELECT ... FOR UPDATE, matching the
    idempotency pattern used by ``webhooks/routes.py``.
    """
    if not raw_token:
        raise InvalidClaimTokenError("Empty claim token.")
    q = db.query(PurchaseIntent).filter(
        PurchaseIntent.claim_token_hash == hash_claim_token(raw_token)
    )
    if for_update:
        q = q.with_for_update()
    intent = q.one_or_none()
    if intent is None:
        raise InvalidClaimTokenError("Unknown claim token.")
    return intent


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimResult:
    """Return shape for :func:`claim_intent`.

    ``intent`` is the (now-consumed) PurchaseIntent. ``activation_event``
    is populated when the claim produced a genuine
    ``creator.plan_activated`` event that the caller should route
    after committing — ``None`` when the claim was an idempotent
    replay against a subscription that was already active, or when
    the intent kind doesn't map to a plan activation.
    """
    intent: PurchaseIntent
    activation_event: "CommunicationEvent | None" = None


def claim_intent(db: Session, intent: PurchaseIntent, user: User) -> ClaimResult:
    """Activate the intent for the supplied user. Idempotent.

    Pre-conditions:
      * ``intent.status == 'paid'`` (or already ``'consumed'`` by
        this same user, in which case the call is a no-op).
      * If ``intent.claim_email`` is set, it must match ``user.email``
        case-insensitively.

    On success ``intent.status`` transitions to ``'consumed'`` with
    ``consumed_at`` and ``consumed_by_user_id`` set.

    Does *not* commit — the caller owns the transaction boundary.

    R2B: returns :class:`ClaimResult` so the caller can schedule
    routing of the comms event after committing. Historical callers
    that ignored the return value continue to work — the intent
    still transitions atomically.
    """
    # ── Idempotency ───────────────────────────────────────────────
    if intent.status == PurchaseIntentStatus.consumed:
        if intent.consumed_by_user_id == user.id:
            return ClaimResult(intent=intent)  # no-op
        raise IntentAlreadyConsumedByOtherUserError(
            f"Intent {intent.id} has already been claimed by another account."
        )

    # ── State + auth checks ───────────────────────────────────────
    if intent.status != PurchaseIntentStatus.paid:
        raise IntentNotPaidError(
            f"Intent {intent.id} is in status '{intent.status.value}'; "
            "claim requires 'paid'."
        )

    if intent.claim_email:
        supplied = (user.email or "").strip().lower()
        expected = intent.claim_email.strip().lower()
        if supplied != expected:
            raise IntentEmailMismatchError(
                "The supplied account email does not match the email "
                "used at Stripe Checkout for this purchase."
            )

    # ── Dispatch to per-kind domain service ───────────────────────
    activation_event = None
    if intent.kind == PurchaseIntentKind.creator_subscription:
        if not intent.plan_slug:
            raise UnsupportedIntentKindError(
                f"Intent {intent.id} kind='creator_subscription' but has "
                "no plan_slug — cannot activate."
            )
        activation_result = activate_creator_plan(
            db,
            user,
            intent.plan_slug,
            ActivationSource(
                source="stripe_paid",
                stripe_subscription_id=intent.provider_subscription_id,
                stripe_customer_id=intent.provider_customer_id,
            ),
        )
        activation_event = activation_result.activation_event
    else:
        # Stage 3 wires only creator_subscription. Others raise so
        # webhook/route callers can return a clear error instead of
        # silently marking the intent consumed.
        raise UnsupportedIntentKindError(
            f"Intent kind '{intent.kind.value}' is not claimable yet."
        )

    # ── Mark consumed ─────────────────────────────────────────────
    intent.status = PurchaseIntentStatus.consumed
    intent.consumed_at = datetime.utcnow()
    intent.consumed_by_user_id = user.id
    db.flush()

    logger.info(
        "PurchaseIntent claimed intent=%s kind=%s user=%s",
        intent.id, intent.kind.value, user.id,
    )
    return ClaimResult(intent=intent, activation_event=activation_event)


# ---------------------------------------------------------------------------
# Public safe-summary shape (used by GET /api/purchases/by-token)
# ---------------------------------------------------------------------------


def is_claim_token_expired(intent: PurchaseIntent) -> bool:
    """Returns True when the claim window has closed. Does NOT touch
    intent.status — a paid but token-elapsed intent stays paid, per
    Stage 1's separate-concerns invariant."""
    if intent.claim_token_expires_at is None:
        return False
    return intent.claim_token_expires_at < datetime.utcnow()
