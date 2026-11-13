"""Turning a verified payment into membership — and stopping one safely.

Activation is the only thing that grants
-----------------------------------------
Membership arrives here and nowhere else. Not from the Join click, not
from the Stripe return URL, not from a ``pending`` row, not from a
completed Checkout Session — a Session completing means a card was
captured, and Stripe will tell us separately whether it could be
charged. Only ``invoice.payment_succeeded``, verified against the
agreement it names, calls
``membership_grant.ensure_membership_for_purchase``.

Payment does not overrule eligibility
-------------------------------------
``ensure_membership_for_purchase`` already refuses to restore a
membership that a creator removed or an admin revoked, and logs an ERROR
when it does, precisely because somebody has then paid and not become a
member. That property is relied on rather than re-implemented: this
module records the money either way and reports what happened, so the
case is visible for cancellation or refund instead of either being
silently admitted or silently dropped.

Renewals
--------
Stage 5A.2. The transaction shape here is deliberately the one a renewal
needs — keyed on the invoice id, carrying the billing period, fee
snapshot and payout routing — so that stage adds a caller rather than a
second ledger path.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider, PaymentTransaction,
    PaymentTransactionStatus, PaymentTransactionType,
)
from app.services import membership_grant

logger = logging.getLogger(__name__)


class AmountMismatch(RuntimeError):
    """A verified invoice did not match the agreement it named.

    Raised rather than tolerated. A mismatch means either the wrong
    agreement was resolved or the Price was edited underneath it, and
    recording it as though it were correct would put a wrong figure in
    the creator's earnings.
    """


@dataclass(frozen=True)
class ActivationOutcome:
    subscription: CollectiveMembership
    transaction: PaymentTransaction | None
    #: ``True`` when this call did the work; ``False`` when a replay
    #: found it already done.
    applied: bool
    #: What happened to the membership row — ``created``,
    #: ``reactivated``, or a ``skipped_reason`` from
    #: ``membership_grant``.
    membership: str
    #: Set when money was taken but membership could not be granted.
    #: The caller surfaces it; nothing here refunds or cancels.
    needs_attention: str | None = None


def _payout_fields(sub: CollectiveMembership) -> dict:
    """Routing plus manual-payout status for a succeeded payment.

    Delegates to ``finite_plan_lifecycle.plan_payout_fields`` rather
    than restating it. That function reads only ``payout_model`` and
    ``connect_destination_account_id``, both of which this model carries
    by the same names, so it applies unchanged — and one implementation
    cannot drift from the ledger's CHECK constraints the way a second
    copy would.

    It was a second copy, briefly, and it was wrong: it set
    ``connect_transfer_status`` to ``not_applicable`` on a Connect row,
    which ``ck_payment_transactions_connect_transfer_applies`` refuses.
    A Connect payment is ``awaiting_payment`` until fulfilment moves it
    on. Reusing the original is how that stays true.
    """
    from app.services.finite_plan_lifecycle import plan_payout_fields

    return plan_payout_fields(sub)


def record_membership_payment(
    db: Session, *,
    subscription: CollectiveMembership,
    invoice_id: str,
    invoice_amount_cents: int,
    invoice_currency: str,
    stripe_subscription_id: str | None,
    charge_id: str | None,
    payment_intent_id: str | None,
    period_start: datetime | None,
    period_end: datetime | None,
    now: datetime,
) -> PaymentTransaction | None:
    """One ledger row per paid invoice, or ``None`` if already recorded.

    ``provider_invoice_id`` is the natural key. A replayed webhook finds
    the existing row and writes nothing — the same protection the
    instalment ledger uses, and the reason a renewal cannot be
    double-counted.
    """
    existing = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.provider_invoice_id == invoice_id)
        .first()
    )
    if existing is not None:
        logger.info(
            "collective membership: invoice %s already recorded as txn %s",
            invoice_id, existing.id,
        )
        return None

    expected = subscription.amount_cents
    if invoice_amount_cents != expected:
        raise AmountMismatch(
            f"collective membership {subscription.id}: invoice {invoice_id} "
            f"amount {invoice_amount_cents} does not match the agreed "
            f"{expected}"
        )
    if (invoice_currency or "").upper() != subscription.currency.upper():
        raise AmountMismatch(
            f"collective membership {subscription.id}: invoice {invoice_id} "
            f"currency {invoice_currency!r} does not match the agreed "
            f"{subscription.currency!r}"
        )

    gross = invoice_amount_cents
    platform_fee = round(gross * subscription.platform_fee_basis_points / 10000)
    txn = PaymentTransaction(
        id=str(uuid.uuid4()),
        transaction_type=PaymentTransactionType.member_collective_subscription,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        fulfilment_status=PaymentFulfilmentStatus.applied,
        payer_user_id=subscription.user_id,
        creator_user_id=subscription.creator_user_id,
        space_id=subscription.space_id,
        creator_plan_id=subscription.creator_plan_id,
        currency=subscription.currency,
        gross_amount_cents=gross,
        platform_fee_basis_points=subscription.platform_fee_basis_points,
        platform_fee_cents=platform_fee,
        net_platform_amount_cents=platform_fee,
        net_creator_amount_cents=gross - platform_fee,
        provider_invoice_id=invoice_id,
        provider_subscription_id=stripe_subscription_id,
        provider_charge_id=charge_id,
        provider_payment_intent_id=payment_intent_id,
        billing_period_start=period_start,
        billing_period_end=period_end,
        created_at=now,
        updated_at=now,
        **_payout_fields(subscription),
    )
    db.add(txn)
    db.flush()
    logger.info(
        "collective membership: recorded txn=%s invoice=%s sub=%s "
        "gross=%d fee=%d net=%d",
        txn.id, invoice_id, subscription.id, gross, platform_fee,
        gross - platform_fee,
    )
    return txn


def activate_from_first_invoice(
    db: Session, *,
    subscription: CollectiveMembership,
    invoice_id: str,
    invoice_amount_cents: int,
    invoice_currency: str,
    stripe_subscription_id: str | None,
    charge_id: str | None,
    payment_intent_id: str | None,
    period_start: datetime | None,
    period_end: datetime | None,
    now: datetime,
) -> ActivationOutcome:
    """Record the first payment and make the buyer a member.

    Replay-safe in both halves: the ledger is keyed on the invoice, and
    an agreement already ``active`` short-circuits. Does not commit —
    the webhook owns the transaction, so the money and the membership
    land together or not at all.
    """
    already_active = (
        subscription.status == CollectiveMembershipStatus.active.value
    )

    txn = record_membership_payment(
        db,
        subscription=subscription,
        invoice_id=invoice_id,
        invoice_amount_cents=invoice_amount_cents,
        invoice_currency=invoice_currency,
        stripe_subscription_id=stripe_subscription_id,
        charge_id=charge_id,
        payment_intent_id=payment_intent_id,
        period_start=period_start,
        period_end=period_end,
        now=now,
    )

    if already_active and txn is None:
        return ActivationOutcome(
            subscription=subscription, transaction=None, applied=False,
            membership="already_active",
        )

    if stripe_subscription_id and not subscription.stripe_subscription_id:
        subscription.stripe_subscription_id = stripe_subscription_id
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end

    # Stage 5A.2 — a payment arriving against a problem clears it. The
    # same path serves the first invoice, a renewal and a recovery,
    # which is deliberate: all three are "money arrived for this
    # agreement", and three code paths would eventually disagree about
    # what that means.
    recovered = recover_payment_problem(
        db, subscription=subscription, now=now,
    )
    if not already_active and not recovered:
        subscription.status = CollectiveMembershipStatus.active.value
    if subscription.activated_at is None:
        subscription.activated_at = now
    subscription.updated_at = now

    outcome = membership_grant.ensure_membership_for_purchase(
        db,
        user_id=subscription.user_id,
        space_id=subscription.space_id,
        now=now,
    )
    if outcome.created:
        membership = "created"
    elif outcome.reactivated:
        membership = "reactivated"
    else:
        membership = outcome.skipped_reason or "unchanged"

    # Stage 5A.2 — the one case the shared grant deliberately will not
    # handle. ``ensure_membership_for_purchase`` skips a ``paused`` row
    # with ``status_paused`` because four other purchase paths share it
    # and any of them unpausing a membership would reverse pauses that
    # had nothing to do with that purchase. A membership payment for
    # *this* Collective is the one thing that should, so it is done
    # here and only here. A ``removed`` row is still refused above.
    if membership == "status_paused":
        from app.services import collective_membership_access as _access

        membership = _access.reactivate_paused_membership(
            db, subscription=subscription, now=now,
        )

    # Money taken, membership withheld. ``ensure_membership_for_purchase``
    # refuses to overturn a creator's removal or an admin's revocation,
    # which is correct — and leaves a payment that needs a human. Named
    # here so the webhook can log it loudly rather than returning
    # success for something that is not.
    needs_attention = None
    if membership not in (
        "created", "reactivated", "already_active", "unpaused",
    ):
        needs_attention = membership
        logger.error(
            "collective membership: PAID BUT NOT A MEMBER sub=%s user=%s "
            "space=%s invoice=%s reason=%s — needs cancellation or refund",
            subscription.id, subscription.user_id, subscription.space_id,
            invoice_id, membership,
        )

    db.flush()

    # The message, last and never load-bearing. ``_safe_emit`` swallows
    # its own failures: the payment and the membership are the facts of
    # record, and a comms problem must not roll them back or leave
    # Stripe retrying something already handled.
    if txn is not None and needs_attention is None:
        from app.services import collective_membership_emit as _emit

        if membership in ("created", "reactivated"):
            _emit.emit_membership_purchased(db, subscription=subscription)
        elif membership == "unpaused":
            _emit.emit_membership_reactivated(db, subscription=subscription)
        else:
            # Already a member, money arrived: a renewal. Keyed on the
            # invoice, so a replay sends nothing.
            _emit.emit_membership_renewed(
                db, subscription=subscription, invoice_id=invoice_id,
            )

    return ActivationOutcome(
        subscription=subscription, transaction=txn,
        applied=txn is not None, membership=membership,
        needs_attention=needs_attention,
    )


# ---------------------------------------------------------------------------
# Stopping one — §16's authorised mechanism
# ---------------------------------------------------------------------------


def cancel_subscription_now(
    db: Session, *,
    subscription: CollectiveMembership,
    reason: str,
    now: datetime,
    actor_user_id: str | None = None,
) -> CollectiveMembership:
    """Stop billing immediately. Provider first, then local state.

    Stage 5A.1 introduces recurring subscriptions, so it must also
    introduce a reliable way to stop one — before any exist, not after.
    Member self-service and cancel-at-period-end are Stage 5A.2/5A.3;
    this is the operator's lever and the one the three immediate-ending
    paths (a member leaving, a creator removing, a ban) will call.

    **Provider first**, like ``cancel_plan_by_admin``: a transient Stripe
    error propagates with local state untouched, so a retry is clean.
    Marking it cancelled locally while Stripe kept billing is the one
    outcome worth ordering against.

    Idempotent — Stripe accepts a cancel on an already-cancelled
    subscription, and a second call here preserves the original audit.

    Deliberately **does not** touch ``SpaceMembership``. Cancelling the
    money and ending the belonging are different decisions with
    different rules, and Stage 5A.2 owns the second.
    """
    import stripe

    from app.core.config import settings

    if subscription.stripe_subscription_id:
        stripe.api_key = settings.stripe_secret_key
        try:
            stripe.Subscription.delete(subscription.stripe_subscription_id)
        except stripe.InvalidRequestError as exc:
            # Already gone at Stripe is success, not failure. Anything
            # else is a real error and propagates.
            if "No such subscription" not in str(exc):
                raise
            logger.info(
                "collective membership: Stripe subscription %s already "
                "absent for sub=%s",
                subscription.stripe_subscription_id, subscription.id,
            )

    if subscription.status != CollectiveMembershipStatus.cancelled.value:
        subscription.status = CollectiveMembershipStatus.cancelled.value
        subscription.cancelled_at = now
        subscription.cancelled_reason = reason[:250]
        subscription.ended_at = now
        subscription.cancel_at_period_end = False
        subscription.updated_at = now
        logger.info(
            "collective membership: cancelled sub=%s user=%s space=%s "
            "reason=%r actor=%s",
            subscription.id, subscription.user_id, subscription.space_id,
            reason, actor_user_id or "-",
        )
    db.flush()
    return subscription


# ---------------------------------------------------------------------------
# Stage 5A.2 — the rest of the lifecycle
# ---------------------------------------------------------------------------

#: Fresh Collective's own grace window after a failed renewal.
#:
#: Seven days, matching ``creator_billing_handlers._GRACE_WINDOW``
#: exactly. Reused rather than chosen afresh because a member whose card
#: fails should get the same consideration whichever subscription it
#: was, and two numbers would eventually drift apart with nobody
#: noticing.
#:
#: Note what this window is *not*: it is not Stripe's retry schedule.
#: Stripe retries on its own cadence and may still be trying when this
#: expires. Expiry here pauses **access**; it does not tell Stripe to
#: stop, which is why ``end_subscription`` cancels at the provider when
#: grace runs out rather than assuming silence means stopped.
GRACE_WINDOW = timedelta(days=7)


def begin_payment_problem(
    db: Session, *,
    subscription: CollectiveMembership,
    invoice_id: str | None,
    now: datetime,
) -> CollectiveMembership:
    """A renewal failed. Start the clock; leave access alone.

    Access continues through the window — a card expiring is not a
    reason to shut somebody out of their community the same afternoon.
    ``SpaceMembership`` is deliberately untouched here.

    Idempotent: a second failed invoice inside an open window does not
    restart it, so repeated retries cannot extend grace indefinitely.
    """
    if subscription.status not in (
        CollectiveMembershipStatus.active.value,
        CollectiveMembershipStatus.past_due.value,
    ):
        logger.info(
            "collective membership: ignoring payment failure for %s "
            "agreement sub=%s", subscription.status, subscription.id,
        )
        return subscription

    opened_window = (
        subscription.status != CollectiveMembershipStatus.past_due.value
    )
    if opened_window:
        subscription.status = CollectiveMembershipStatus.past_due.value
        subscription.payment_problem_started_at = now
        subscription.grace_expires_at = now + GRACE_WINDOW
        logger.warning(
            "collective membership: payment problem sub=%s user=%s space=%s "
            "grace until %s", subscription.id, subscription.user_id,
            subscription.space_id, subscription.grace_expires_at,
        )
    if invoice_id:
        subscription.last_failed_invoice_id = invoice_id
    subscription.updated_at = now
    db.flush()

    if opened_window:
        from app.services import collective_membership_emit as _emit

        _emit.emit_membership_payment_failed(db, subscription=subscription)
    return subscription


def recover_payment_problem(
    db: Session, *, subscription: CollectiveMembership, now: datetime,
) -> bool:
    """A retry succeeded. Clear the problem and the clock.

    Returns True when there was a problem to clear. Does not grant
    membership — the caller's activation path does that, so recovery and
    first payment take the same route to access.
    """
    if subscription.status != CollectiveMembershipStatus.past_due.value:
        return False
    subscription.status = CollectiveMembershipStatus.active.value
    subscription.payment_problem_started_at = None
    subscription.grace_expires_at = None
    subscription.last_failed_invoice_id = None
    subscription.updated_at = now
    logger.info(
        "collective membership: recovered sub=%s user=%s space=%s",
        subscription.id, subscription.user_id, subscription.space_id,
    )
    db.flush()
    return True


def schedule_cancellation(
    db: Session, *,
    subscription: CollectiveMembership,
    now: datetime,
    actor_user_id: str | None = None,
) -> CollectiveMembership:
    """Stop renewing; keep the paid period.

    The member keeps what they paid for and is not charged again. Access
    ends when the period does, not today — which is why this does not
    touch ``SpaceMembership`` and ``end_subscription`` does.

    Provider first, and idempotent at both ends: Stripe accepts a
    repeated ``cancel_at_period_end``, and a second call here preserves
    the original ``cancelled_at``.
    """
    import stripe

    from app.core.config import settings

    if subscription.status not in (
        CollectiveMembershipStatus.active.value,
        CollectiveMembershipStatus.past_due.value,
        CollectiveMembershipStatus.cancel_scheduled.value,
    ):
        raise ValueError(
            f"cannot schedule cancellation of a {subscription.status} "
            f"agreement ({subscription.id})"
        )

    if subscription.stripe_subscription_id:
        stripe.api_key = settings.stripe_secret_key
        stripe.Subscription.modify(
            subscription.stripe_subscription_id, cancel_at_period_end=True,
        )

    newly_scheduled = (
        subscription.status
        != CollectiveMembershipStatus.cancel_scheduled.value
    )
    if newly_scheduled:
        subscription.status = (
            CollectiveMembershipStatus.cancel_scheduled.value
        )
        subscription.cancelled_at = now
        subscription.cancelled_reason = "member_cancelled_renewal"
        logger.info(
            "collective membership: renewal cancelled sub=%s user=%s "
            "space=%s access until %s by %s",
            subscription.id, subscription.user_id, subscription.space_id,
            subscription.current_period_end, actor_user_id or "member",
        )
    subscription.cancel_at_period_end = True
    subscription.updated_at = now
    db.flush()

    if newly_scheduled:
        from app.services import collective_membership_emit as _emit

        _emit.emit_membership_cancellation_scheduled(
            db, subscription=subscription,
        )
    return subscription


def resume_cancelled_renewal(
    db: Session, *, subscription: CollectiveMembership, now: datetime,
) -> CollectiveMembership:
    """Undo a scheduled cancellation while the period is still running.

    Reactivates the *existing* Stripe subscription rather than opening a
    new agreement — the member's terms, price and period are all still
    valid, and a new subscription would re-price them at today's list.
    """
    import stripe

    from app.core.config import settings

    if subscription.status != CollectiveMembershipStatus.cancel_scheduled.value:
        raise ValueError(
            f"nothing to resume on a {subscription.status} agreement "
            f"({subscription.id})"
        )
    if subscription.stripe_subscription_id:
        stripe.api_key = settings.stripe_secret_key
        stripe.Subscription.modify(
            subscription.stripe_subscription_id, cancel_at_period_end=False,
        )
    subscription.status = CollectiveMembershipStatus.active.value
    subscription.cancel_at_period_end = False
    subscription.cancelled_at = None
    subscription.cancelled_reason = None
    subscription.updated_at = now
    logger.info(
        "collective membership: renewal resumed sub=%s user=%s space=%s",
        subscription.id, subscription.user_id, subscription.space_id,
    )
    db.flush()
    return subscription


# ---------------------------------------------------------------------------
# Stopping the money when the membership ends — §7, §8, §9, §10
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CancellationSweep:
    """What happened when a membership ended."""

    cancelled: int = 0
    #: Agreements Stripe would not cancel. Non-zero means somebody has
    #: left and **billing may still be running** — the caller flags the
    #: membership and the reconciler retries.
    failed: int = 0


def cancel_live_subscriptions_for_member(
    db: Session, *,
    user_id: str,
    space_id: str,
    reason: str,
    now: datetime,
    actor_user_id: str | None = None,
) -> CancellationSweep:
    """Stop future charges for one member in one Collective.

    Called from ``membership_removal.end_membership`` — the single point
    every ending passes through, whether the member left, a creator
    removed them, or they were banned. Hooking there rather than in each
    route is what stops a fourth path being added later that forgets.

    **Never raises.** A member must be able to leave even when Stripe is
    unreachable; blocking the departure to protect the billing would get
    the priority backwards. But a failure is not swallowed either:

    * the agreement is left **live locally**, because it is still live
      at Stripe and the row should say so — marking it cancelled would
      be the local-field lie §7 warns about;
    * an ERROR is logged naming the member, the Collective and the
      agreement;
    * the count comes back so the caller can set
      ``SpaceMembership.payment_action_required``, which is the durable
      operator signal;
    * ``reconcile_collective_memberships`` finds live agreements whose
      membership has ended and retries.

    Scoped to one member and one Collective. Another Collective's
    agreement, and anybody else's, are outside the query.
    """
    live = (
        db.query(CollectiveMembership)
        .filter(
            CollectiveMembership.user_id == user_id,
            CollectiveMembership.space_id == space_id,
            CollectiveMembership.status.in_(sorted(_CANCELLABLE_STATUSES)),
        )
        .all()
    )
    cancelled = failed = 0
    for sub in live:
        try:
            cancel_subscription_now(
                db, subscription=sub, reason=reason, now=now,
                actor_user_id=actor_user_id,
            )
            cancelled += 1
        except Exception:
            failed += 1
            logger.exception(
                "collective membership: COULD NOT STOP BILLING for sub=%s "
                "user=%s space=%s — the member's membership is ending and "
                "Stripe may still charge them. Left live locally for the "
                "reconciler to retry.",
                sub.id, user_id, space_id,
            )
    if cancelled or failed:
        logger.info(
            "collective membership: departure sweep user=%s space=%s "
            "cancelled=%d failed=%d reason=%r",
            user_id, space_id, cancelled, failed, reason,
        )
    return CancellationSweep(cancelled=cancelled, failed=failed)


#: Agreements worth cancelling when a membership ends: anything that
#: could still take money. ``cancel_scheduled`` is included — the member
#: stopped the renewal but the current period is still live at Stripe,
#: and leaving outright should end it now rather than let it run.
_CANCELLABLE_STATUSES: frozenset[str] = frozenset({
    CollectiveMembershipStatus.pending.value,
    CollectiveMembershipStatus.active.value,
    CollectiveMembershipStatus.past_due.value,
    CollectiveMembershipStatus.cancel_scheduled.value,
})
