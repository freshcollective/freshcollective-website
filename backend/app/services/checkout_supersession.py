"""Letting a member change their mind before they have paid anything.

A member who starts the weekly-payments checkout for a Payment Option
and then decides to pay in full used to be stuck. The plan row written
before Stripe was contacted sat in ``pending_setup`` forever — nothing
expired it — and Rule D in :mod:`app.services.checkout_orchestration`
reads that status as an agreement in progress, for *every* payment
method on the option. The member could still buy a different Payment
Option, which is what made it look so strange: only the one they had
touched was sealed.

This module decides what to do about such a plan when a new checkout
starts. It runs *before* the Rule D guard and, where the plan really is
abandoned, releases it — so the guard then finds nothing and proceeds
unchanged. Rule D itself is untouched, which matters because three
other callers rely on it exactly as it is.

Three verdicts, and the reasoning behind each:

``reused``
    Same payment method, Session still open. The member is retrying —
    they closed the tab, or came back to a stale page. Hand back the
    Session they already have rather than opening a second one. A new
    Session here would be a second payment page for one purchase, which
    is how people end up paying twice.

``superseded``
    Different payment method, or the Session is dead. This is the
    change-of-mind case. The old Session is expired at Stripe where it
    is still open, the plan is released through
    :mod:`app.services.finite_plan_release`, and the new checkout
    proceeds.

``none``
    No ``pending_setup`` plan. Nothing to do.

Anything else refuses, by raising 409. In particular a Session that
completed, a SetupIntent that succeeded, an attached payment method, a
subscription, a paid instalment, or a Stripe read we could not perform:
each means the plan may represent something real, and the member is
better served by a clear refusal than by us guessing. Plans in
``active`` or ``payment_problem`` are not considered here at all — they
fall through to Rule D and stay protected.

Expiring the Session at Stripe is belt and braces, not the guarantee.
The guarantee is that ``handle_finite_plan_setup_completed`` ignores any
Session whose plan is no longer ``pending_setup``, so a member who
somehow completes a superseded page still gets no SubscriptionSchedule
and no charge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.user import User
from app.services import finite_plan_release as release
from app.services.discount_stripe_sessions import (
    StripeStateChanged,
    StripeUnavailable,
    expire_session,
)
from app.services.stripe_finite_plan import inspect_setup_session

logger = logging.getLogger(__name__)

__all__ = ["SupersessionOutcome", "lock_member_option", "resolve_pending_setup"]

_BUSY = (
    "We could not confirm the state of your previous checkout with our "
    "payment provider. Please try again in a moment."
)
_REAL = (
    "You already have a payment plan in progress for this Payment "
    "Option. Contact support if you need to change it."
)


@dataclass(frozen=True)
class SupersessionOutcome:
    kind: Literal["none", "reused", "superseded"]
    plan: PurchasePlan | None = None
    #: Only set when ``kind == 'reused'`` — the live Stripe page to
    #: send the member back to.
    checkout_url: str | None = None


def lock_member_option(db: Session, *, user_id: str, payment_option_id: str) -> None:
    """Serialise checkout starts for one member on one Payment Option.

    Two requests arriving together could otherwise both read "no plan
    in progress" and both create one, leaving the member with two
    agreements for the same thing. The lock is held to the end of the
    transaction, which is released by the commit inside
    ``start_finite_plan_setup`` — precisely when the new plan becomes
    visible to the next waiter, so the second request sees it rather
    than racing it.

    A transaction-scoped advisory lock needs no table and no migration,
    and cannot leak: Postgres drops it at commit or rollback either way.
    Hash collisions between unrelated pairs are possible and harmless —
    the cost is that two unrelated members briefly serialise.
    """
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": f"fc:checkout:{user_id}:{payment_option_id}"},
    )


def _pending_plan(
    db: Session, *, user_id: str, payment_option_id: str,
) -> PurchasePlan | None:
    """The member's in-flight setup for this option, if any.

    Row-locked: the lock above serialises new arrivals, and this stops
    a concurrent release of the same row from interleaving.
    """
    return (
        db.query(PurchasePlan)
        .filter(
            PurchasePlan.member_user_id == user_id,
            PurchasePlan.payment_option_id == payment_option_id,
            PurchasePlan.status == PurchasePlanStatus.pending_setup,
        )
        .order_by(PurchasePlan.created_at.desc())
        .with_for_update()
        .first()
    )


def resolve_pending_setup(
    db: Session,
    *,
    user: User,
    payment_option_id: str,
    requested_schedule_id: str | None,
    now: datetime,
) -> SupersessionOutcome:
    """Decide what to do about an in-flight setup before a new checkout.

    Call inside :func:`lock_member_option`, before
    ``check_same_option_not_active``. Does not commit — the release
    lands with whatever the caller goes on to do, so a checkout that
    fails later rolls the release back with it.
    """
    plan = _pending_plan(
        db, user_id=user.id, payment_option_id=payment_option_id,
    )
    if plan is None:
        return SupersessionOutcome(kind="none")

    # Never release something that might be real. Rule D would refuse
    # these too, but refusing here keeps the reason in the log next to
    # the decision.
    blocked = release.releasable(plan)
    if blocked is not None:
        logger.warning(
            "supersession refused: plan=%s member=%s — %s",
            plan.id, user.id, blocked,
        )
        raise HTTPException(status_code=409, detail=_REAL)

    same_method = (
        requested_schedule_id is not None
        and plan.payment_option_schedule_id == requested_schedule_id
    )

    # The Section C case: we hold no Session id, because Stripe errored
    # or timed out before we recorded one. There is no page the member
    # was ever given, so nothing to protect and nothing to expire. If
    # Stripe did create one, cancelling the plan already neutralises it.
    if not plan.provider_setup_session_id:
        logger.info(
            "supersession: plan=%s has no Session id — releasing as orphaned",
            plan.id,
        )
        release.release_abandoned_setup(
            db, plan=plan, reason=release.RELEASE_SUPERSEDED,
            now=now, actor_user_id=user.id,
        )
        db.flush()
        return SupersessionOutcome(kind="superseded", plan=plan)

    try:
        state = inspect_setup_session(plan.provider_setup_session_id)
    except StripeUnavailable as exc:
        # Refuse rather than assume. Releasing a plan whose Session we
        # could not read risks discarding a live payment arrangement.
        logger.warning(
            "supersession deferred: plan=%s session=%s unreadable: %s",
            plan.id, plan.provider_setup_session_id, exc,
        )
        raise HTTPException(status_code=409, detail=_BUSY) from exc

    if state.usable:
        logger.warning(
            "supersession refused: plan=%s session=%s is usable "
            "(status=%s setup_intent=%s pm=%s sub=%s)",
            plan.id, state.session_id, state.status,
            state.setup_intent_status, state.payment_method_id,
            state.subscription_id,
        )
        raise HTTPException(status_code=409, detail=_REAL)

    # Retrying the same payment method on a page that is still live:
    # send them back to it instead of opening another.
    if same_method and state.status == "open":
        url = _session_url(state.session_id)
        if url:
            logger.info(
                "supersession: reusing live Session=%s for plan=%s member=%s",
                state.session_id, plan.id, user.id,
            )
            return SupersessionOutcome(
                kind="reused", plan=plan, checkout_url=url,
            )
        # No URL to hand back — fall through and supersede instead.

    if state.status == "open":
        try:
            expire_session(state.session_id)
        except StripeStateChanged:
            # Stripe refused because it is no longer open. Re-read
            # rather than assume which way it went.
            try:
                state = inspect_setup_session(state.session_id)
            except StripeUnavailable as exc:
                raise HTTPException(status_code=409, detail=_BUSY) from exc
            if state.usable:
                logger.warning(
                    "supersession refused: plan=%s session=%s became usable",
                    plan.id, state.session_id,
                )
                raise HTTPException(status_code=409, detail=_REAL)
        except StripeUnavailable as exc:
            logger.warning(
                "supersession deferred: plan=%s session=%s expire failed: %s",
                plan.id, state.session_id, exc,
            )
            raise HTTPException(status_code=409, detail=_BUSY) from exc

    release.release_abandoned_setup(
        db, plan=plan, reason=release.RELEASE_SUPERSEDED,
        now=now, actor_user_id=user.id,
    )
    db.flush()
    logger.info(
        "supersession: released plan=%s (session=%s status=%s) for member=%s "
        "switching to schedule=%s",
        plan.id, state.session_id, state.status, user.id, requested_schedule_id,
    )
    return SupersessionOutcome(kind="superseded", plan=plan)


def _session_url(session_id: str) -> str | None:
    """The hosted page for a Session, or ``None`` if Stripe won't say."""
    import stripe
    from app.core.config import settings

    stripe.api_key = settings.stripe_secret_key
    try:
        sess = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError:                   # pragma: no cover - network
        return None
    return getattr(sess, "url", None)
