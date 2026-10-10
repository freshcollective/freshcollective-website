"""Releasing an abandoned payment-plan checkout.

A finite payment plan is written to the database *before* Stripe is
contacted: ``start_finite_plan_setup`` inserts the plan in
``pending_setup`` and commits, then opens the Checkout Session. That
order is deliberate — the webhook must be able to find the plan the
instant setup completes — but it means an abandoned or failed checkout
leaves a real row behind, and Rule D in
:mod:`app.services.checkout_orchestration` treats that row as an
agreement in progress. The member is then locked out of *every* payment
method on that Payment Option, including paying in full, until someone
intervenes by hand.

This module is the narrow way out. It moves one abandoned plan to
``cancelled`` and does **nothing else**.

That restraint is the point. ``finite_plan_lifecycle.cancel_plan_by_admin``
is the right tool for cancelling a real agreement: it revokes grant
records, suspends plan-owned access, releases future plan-dependent
bookings and emails the member. Every one of those is wrong for a
checkout that was never completed — there is nothing to revoke, and a
member who abandoned a payment page should certainly not receive an
"access paused" email. Worse, reusing it here would put booking and
access mutation on the *checkout* path, where a bug could revoke
something a member legitimately holds. So this function cannot reach
any of it: it writes four columns on one row.

What keeps it safe is the precondition, not the caller. ``releasable``
refuses any plan that could represent something real — anything past
``pending_setup``, anything with an instalment paid, anything carrying a
Stripe subscription or subscription schedule. A caller that gets a
``PlanNotReleasable`` should refuse the checkout rather than work around
it.

The remaining question is a late webhook: what if the member completes
the superseded Session after we have cancelled its plan? Nothing
happens, and that is by existing design —
``handle_finite_plan_setup_completed`` short-circuits unless the plan is
still ``pending_setup``, so no SubscriptionSchedule is created and no
money moves. Cancelling the plan is therefore sufficient to neutralise
the Session, with expiring it at Stripe being belt and braces rather
than the actual guarantee.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus

logger = logging.getLogger(__name__)

__all__ = [
    "PlanNotReleasable",
    "RELEASE_SUPERSEDED",
    "RELEASE_SESSION_EXPIRED",
    "releasable",
    "assert_releasable",
    "release_abandoned_setup",
]

#: Audit reasons. Stored on ``cancelled_reason`` so the history says
#: which mechanism released the plan, not merely that it was cancelled.
RELEASE_SUPERSEDED = "superseded_by_new_checkout"
RELEASE_SESSION_EXPIRED = "checkout_session_expired"


class PlanNotReleasable(RuntimeError):
    """This plan might represent something real — refuse to release it."""


def releasable(plan: PurchasePlan) -> str | None:
    """Why this plan must not be released, or ``None`` if it may be.

    Returns a human-readable reason rather than a bool so callers can
    log and surface exactly which invariant held.
    """
    if plan.status is not PurchasePlanStatus.pending_setup:
        return f"status is {plan.status.value!r}, not pending_setup"
    if (plan.installments_paid or 0) > 0:
        return f"{plan.installments_paid} instalment(s) already paid"
    if plan.provider_subscription_schedule_id:
        return "a Stripe subscription schedule exists"
    if getattr(plan, "provider_subscription_id", None):
        return "a Stripe subscription exists"
    return None


def assert_releasable(plan: PurchasePlan) -> None:
    reason = releasable(plan)
    if reason is not None:
        raise PlanNotReleasable(f"plan {plan.id}: {reason}")


def release_abandoned_setup(
    db: Session,
    *,
    plan: PurchasePlan,
    reason: str,
    now: datetime,
    actor_user_id: str | None = None,
) -> bool:
    """Move one abandoned ``pending_setup`` plan to ``cancelled``.

    Returns ``True`` when this call performed the transition, ``False``
    when the plan was already ``cancelled`` — so a repeated webhook
    delivery or a racing checkout is a no-op rather than an error, and
    the original audit stamps are preserved.

    Touches ``status``, ``cancelled_at``, ``cancelled_reason`` and
    ``cancelled_by_user_id``. Nothing else, ever. Does not commit: the
    caller owns the transaction, so a checkout that fails later in the
    same request rolls the release back with it.

    ``actor_user_id`` is the operator or member whose action caused the
    release, or ``None`` when Stripe told us the Session expired — there
    is no human to attribute that to, and inventing one would make the
    audit trail lie.
    """
    if plan.status is PurchasePlanStatus.cancelled:
        logger.info(
            "finite plan release: plan=%s already cancelled — no-op (reason=%r)",
            plan.id, reason,
        )
        return False

    assert_releasable(plan)

    plan.status = PurchasePlanStatus.cancelled
    plan.cancelled_at = now
    plan.cancelled_reason = reason[:250]
    plan.cancelled_by_user_id = actor_user_id
    plan.updated_at = now

    logger.info(
        "finite plan release: plan=%s member=%s option=%s schedule=%s "
        "reason=%r actor=%s session=%s",
        plan.id, plan.member_user_id, plan.payment_option_id,
        plan.payment_option_schedule_id, reason, actor_user_id or "-",
        plan.provider_setup_session_id or "-",
    )
    return True
