"""
Creator plan activation — the single domain service every activation
path calls.

Callers today:
  * ``admin.routes.grant_creator_plan_access`` — admin UI grants (a
    thin wrapper after the Stage 3 refactor).
  * ``purchases.claim.claim_intent`` — Stripe-driven activation via
    a paid PurchaseIntent.

Deliberately knows *nothing* about ``PurchaseIntent`` — the caller
translates the purchase-shape into an :class:`ActivationSource`.

Responsibilities:
  1. Resolve the target :class:`CreatorPlan` by slug.
  2. Create or reactivate a :class:`CreatorSubscription` for the user.
  3. Ensure ``user.role='creator'`` (via
     :func:`app.admin.service.promote_to_creator`) and reconcile
     World Builders auto-role membership (via the existing
     ``creator_eligibility`` reconciler).
  4. Record a :class:`CreatorPlanGrant` audit row through the shared
     ``record_grant_event`` primitive.
  5. Send an in-app notification to the creator.

Idempotency:
  * A repeat call while the user already has an active subscription
    for *this same plan* is a no-op — the existing subscription is
    returned unchanged. Role and eligibility reconciliation are
    still invoked defensively (both are idempotent).
  * A repeat call when the user has an active subscription for a
    *different* plan raises :class:`ActivationConflictError`. Higher
    layers translate that into an HTTP 409.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.admin.service import promote_to_creator, record_grant_event
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.user import User
from app.services.notification_service import create_notification

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CreatorPlanActivationError(RuntimeError):
    """Base class for user-facing activation failures. Route handlers
    translate concrete subclasses into HTTP responses."""


class UnknownCreatorPlanError(CreatorPlanActivationError):
    """Requested plan slug is not present or not active."""


class ActivationConflictError(CreatorPlanActivationError):
    """User already has an active subscription for a *different* plan.
    Callers must resolve the conflict before retrying."""


# ---------------------------------------------------------------------------
# Activation source — the caller-provided description of *why* we're
# activating. Distinguishes admin-granted from Stripe-purchased flows
# without letting either path smuggle in the other's assumptions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationSource:
    """Immutable description of the origin of an activation.

    ``source='manual_grant'`` — admin UI path. ``reason`` is required
    (the enumeration lives in ``admin/schemas.py::PLAN_GRANT_REASONS``);
    ``actor_user_id`` is the admin who granted.

    ``source='stripe_paid'`` — Stripe-driven activation via a paid
    PurchaseIntent. ``stripe_subscription_id`` and
    ``stripe_customer_id`` should be present; ``reason`` and
    ``actor_user_id`` are unused.
    """
    source: Literal["manual_grant", "stripe_paid"]
    reason: str | None = None
    note: str | None = None
    actor_user_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_customer_id: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


# ---------------------------------------------------------------------------
# Result — small helper so callers can react to reactivation without
# re-inspecting the row.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationResult:
    subscription: CreatorSubscription
    was_reactivated: bool
    was_noop: bool
    # R2B — populated when this call produced a genuine activation
    # transition (``was_noop=False``) and the ``creator.plan_activated``
    # event was emitted. Callers commit and then pass this to
    # ``schedule_routing_if_needed`` so routing runs against a committed
    # event. Remains ``None`` on the idempotent no-op path.
    activation_event: "CommunicationEvent | None" = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


_ACTIVE_STATUSES = (
    CreatorSubscriptionStatus.active,
    CreatorSubscriptionStatus.trialing,
    CreatorSubscriptionStatus.past_due,
)


def activate_creator_plan(
    db: Session,
    user: User,
    plan_slug: str,
    activation: ActivationSource,
) -> ActivationResult:
    """Activate ``plan_slug`` for ``user``. Idempotent.

    The transaction is not committed here — the caller owns commit /
    rollback boundaries (mirrors the pattern used throughout this
    codebase for services called from webhooks + routes).
    """
    plan = _load_plan_or_raise(db, plan_slug)
    starts_at = activation.starts_at or datetime.utcnow()
    ends_at = activation.ends_at

    # ── Idempotency + conflict check ──────────────────────────────
    existing_active = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == user.id,
            CreatorSubscription.status.in_([s.value for s in _ACTIVE_STATUSES]),
        )
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )
    if existing_active:
        if existing_active.creator_plan_id == plan.id:
            # Already active on this exact plan — safe no-op. Still
            # promote_to_creator + reconcile defensively so a repeat
            # activation heals any drift (role got reset elsewhere,
            # World Builders membership was removed by hand, etc.).
            promote_to_creator(user, db)
            db.flush()
            return ActivationResult(
                subscription=existing_active,
                was_reactivated=False,
                was_noop=True,
                activation_event=None,
            )
        raise ActivationConflictError(
            f"User already has an active subscription for plan "
            f"'{existing_active.plan.slug if existing_active.plan else existing_active.creator_plan_id}'; "
            f"cannot activate '{plan_slug}' without cancelling the "
            "existing subscription first."
        )

    # ── Create or reactivate ──────────────────────────────────────
    subscription, was_reactivated = _create_or_reactivate(
        db, user.id, plan.id, starts_at, ends_at, activation,
    )
    db.flush()

    # ── Promote role + reconcile eligibility (World Builders) ─────
    promote_to_creator(user, db)

    # ── Audit ─────────────────────────────────────────────────────
    # The ck_creator_plan_grants_action CHECK allows only
    # ``granted | extended | revoked``. Both first-grant and
    # reactivation are recorded as ``granted`` — the reactivation
    # signal is carried on the returned ActivationResult and can be
    # reconstructed from the row-history if ever needed.
    record_grant_event(
        db,
        subscription=subscription,
        action="granted",
        reason=activation.reason,
        note=activation.note,
        actor_user_id=activation.actor_user_id,
    )

    # ── Notify creator (best-effort; failure never blocks activation) ─
    try:
        _notify_creator(db, user=user, subscription=subscription, plan=plan,
                        source=activation.source, reason=activation.reason,
                        ends_at=ends_at)
    except Exception:  # pragma: no cover — logged, not raised
        logger.exception(
            "creator plan activation: notification failed for user=%s plan=%s",
            user.id, plan_slug,
        )

    db.flush()

    # ── R2B — emit creator.plan_activated (transactional lifecycle) ──
    # Only reached on genuine inactive→active transitions (the no-op
    # branch returned earlier). Emit failure is logged but never blocks
    # the activation itself.
    activation_event = _emit_plan_activated_event(
        db,
        user=user,
        subscription=subscription,
        plan=plan,
        starts_at=starts_at,
        was_reactivated=was_reactivated,
    )

    return ActivationResult(
        subscription=subscription,
        was_reactivated=was_reactivated,
        was_noop=False,
        activation_event=activation_event,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_plan_or_raise(db: Session, plan_slug: str) -> CreatorPlan:
    plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.slug == plan_slug, CreatorPlan.is_active.is_(True))
        .first()
    )
    if plan is None:
        raise UnknownCreatorPlanError(
            f"CreatorPlan '{plan_slug}' is not present or not active."
        )
    return plan


def _create_or_reactivate(
    db: Session,
    user_id: str,
    plan_id: str,
    starts_at: datetime,
    ends_at: datetime | None,
    activation: ActivationSource,
) -> tuple[CreatorSubscription, bool]:
    """Reactivate the most-recent prior subscription of the same
    source when it exists; otherwise INSERT a new row.

    Mirrors the semantics of the pre-existing admin grant flow (only
    ``source='manual_grant'`` rows were reactivated there) but applies
    the same rule symmetrically to ``source='stripe_paid'`` so a
    creator who cancels and later re-subscribes reuses their prior
    row and their grant history stays a single per-user thread.
    """
    now = datetime.utcnow()
    existing_inactive = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == user_id,
            CreatorSubscription.source == activation.source,
        )
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )
    if existing_inactive is not None:
        sub = existing_inactive
        sub.creator_plan_id = plan_id
        sub.status = CreatorSubscriptionStatus.active
        sub.starts_at = starts_at
        sub.ends_at = ends_at
        sub.source = activation.source
        sub.grant_reason = activation.reason
        sub.granted_by_user_id = activation.actor_user_id
        sub.grant_note = activation.note
        sub.stripe_subscription_id = activation.stripe_subscription_id
        sub.stripe_customer_id = activation.stripe_customer_id
        sub.revoked_at = None
        sub.revoked_by_user_id = None
        sub.revoked_reason = None
        sub.updated_at = now
        return sub, True

    sub = CreatorSubscription(
        id=str(uuid4()),
        user_id=user_id,
        creator_plan_id=plan_id,
        status=CreatorSubscriptionStatus.active,
        starts_at=starts_at,
        ends_at=ends_at,
        source=activation.source,
        grant_reason=activation.reason,
        granted_by_user_id=activation.actor_user_id,
        grant_note=activation.note,
        stripe_subscription_id=activation.stripe_subscription_id,
        stripe_customer_id=activation.stripe_customer_id,
    )
    db.add(sub)
    return sub, False


_STRIPE_PAID_MESSAGE = (
    "Your {plan_name} plan is active on Fresh Collective. "
    "Welcome — your Creator Studio is ready for you."
)


def _notify_creator(
    db: Session,
    *,
    user: User,
    subscription: CreatorSubscription,
    plan: CreatorPlan,
    source: str,
    reason: str | None,
    ends_at: datetime | None,
) -> None:
    """Send an in-app notification appropriate to the activation
    source. Reuses ``create_notification`` — no new notification
    type is added in Stage 3 for admin grants (that path continues
    to send ``creator_plan_granted_by_platform`` as before)."""
    if source == "stripe_paid":
        title = f"Welcome — {plan.name} plan is active"
        message = _STRIPE_PAID_MESSAGE.format(plan_name=plan.name)
        notification_type = "creator_plan_granted_by_stripe"
    else:
        # Preserve the existing wording used by the admin grant flow
        # so no regression in creator inboxes.
        from app.admin.routes import _PLAN_REASON_LABELS  # local import avoids cycle
        reason_label = _PLAN_REASON_LABELS.get(reason or "", reason or "")
        if ends_at is not None:
            message = (
                f"Fresh Collective granted you access to the {plan.name} "
                f"plan until {ends_at.strftime('%d %b %Y')}. "
                f"Reason: {reason_label}."
            )
        else:
            message = (
                f"Fresh Collective granted you ongoing access to the "
                f"{plan.name} plan. Reason: {reason_label}."
            )
        title = f"Plan access granted — {plan.name}"
        notification_type = "creator_plan_granted_by_platform"

    create_notification(
        db=db,
        recipient_id=user.id,
        notification_type=notification_type,
        title=title,
        message=message,
        url=None,
    )


# ---------------------------------------------------------------------------
# R2B — creator.plan_activated emit
# ---------------------------------------------------------------------------


def _emit_plan_activated_event(
    db: Session,
    *,
    user: User,
    subscription: CreatorSubscription,
    plan: CreatorPlan,
    starts_at: datetime,
    was_reactivated: bool,
) -> "CommunicationEvent | None":
    """Emit the ``creator.plan_activated`` communication event.

    Dedupe key is ``creator-plan-activated:{subscription.id}:{starts_at}``.
    ``subscription.starts_at`` is reset only when
    ``_create_or_reactivate`` writes a new activation window, so this
    key uniquely identifies a genuine activation episode:

    * initial activation → new key
    * Stripe/webhook replay of same activation → already-active no-op
      returns before this function is called
    * ordinary continuous renewal → this function isn't invoked
      (renewals don't call ``activate_creator_plan``)
    * cancellation → later reactivation → fresh ``starts_at`` → new key

    Returns the event on success, or ``None`` if the emit deduped or
    a soft failure was swallowed. Never raises — comms failure must
    not block a paid activation from persisting.
    """
    # Local imports keep the plan_activation module free of comms
    # dependencies at collection time (mirrors the pattern in
    # rollout.py).
    from app.comms import Source, emit as comms_emit
    from app.core.config import settings

    first_name = ""
    if user.name:
        first_name = user.name.strip().split(" ", 1)[0]

    # State-aware destination — matches the Stripe-paid claim's
    # ``purchases/routes.py::_resolve_next_url`` so a fresh Creator
    # lands on the short welcome page (which leads into Build Your
    # Collective) and an already-onboarded Creator opens Creator
    # Studio directly. Sourced from the persisted
    # ``user.creator_onboarded_at`` — not from ``was_reactivated``,
    # which measures Stripe lifecycle, not onboarding progress. A
    # revoked-then-regranted Creator who had previously completed the
    # welcome still gets the "Open Creator Studio" variant; a
    # never-onboarded first-time Creator (via either manual grant or
    # Stripe) gets the "Set up your Collective" variant.
    is_fresh_creator = user.creator_onboarded_at is None
    origin = settings.frontend_origin.rstrip("/")
    next_url = (
        f"{origin}/creator-onboarding"
        if is_fresh_creator
        else f"{origin}/creator-studio"
    )
    # No dedupe_key on the emit itself. Duplicate suppression is
    # provided by ``activate_creator_plan``'s idempotent no-op branch:
    # a replay against an already-active subscription returns
    # ``was_noop=True`` and this helper is never invoked. Using an
    # ``emit()`` dedupe_key would additionally force ``begin_nested``
    # here, which conflicts with sessions that just ran an interior
    # ``db.commit()`` earlier in the same request (e.g. the in-app
    # notification write inside ``_notify_creator``).
    try:
        event = comms_emit(
            db,
            event_type="creator.plan_activated",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=user.id,
            subject_type="creator_subscription",
            subject_id=subscription.id,
            context={
                "plan_slug":            plan.slug,
                "source":               subscription.source,
                # Persisted purely for observability — reconstructing
                # "which activation episode did this fire for" from
                # the event alone would otherwise require joining
                # against ``creator_subscriptions``.
                "activation_starts_at": starts_at.isoformat(),
            },
            payload={
                "first_name":       first_name,
                "plan_name":        plan.name,
                "was_reactivated":  was_reactivated,
                "is_fresh_creator": is_fresh_creator,
                "next_url":         next_url,
            },
        )
    except Exception:  # pragma: no cover — logged, not raised
        logger.exception(
            "creator plan activation: creator.plan_activated emit "
            "failed for user=%s plan=%s subscription=%s",
            user.id, plan.slug, subscription.id,
        )
        return None
    return event
