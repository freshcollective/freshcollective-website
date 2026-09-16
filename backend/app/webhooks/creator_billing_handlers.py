"""Stripe webhook handlers for Creator / Pro monthly subscription
billing.

Strictly isolated from member finite-plan handlers
(``app/webhooks/finite_plan_handlers.py``). Every entry point in
this module gates on ``metadata.purchase_type == 'creator_subscription'``
via :func:`stripe_creator_billing.is_creator_subscription`. If the
metadata is absent or wrong, the handler no-ops silently — the
finite-plan branch of the dispatcher will pick up the event.

Design invariants (from the workstream's technical amendments):

* **No activation on checkout.session.completed**. That handler only
  links the Customer + Subscription id onto a placeholder
  ``CreatorSubscription`` row with ``status=past_due`` (the row is
  created here but not yet commercially active). Activation
  (``status=active``) happens on ``invoice.paid`` for the initial
  invoice, when Stripe confirms the recurring charge was actually
  collected.

* **Order-independent + idempotent**. Every handler claims the event
  via :func:`stripe_event_dedup.claim_event` before mutating state.
  Duplicate deliveries no-op. Out-of-order deliveries (invoice.paid
  arriving before subscription.updated, for example) reconcile the
  row to the newest data — we always trust the latest Stripe payload.

* **Invoice event routing**. Stripe's Invoice object exposes
  ``subscription`` (an id string), not metadata. We retrieve the
  Subscription with :func:`stripe_creator_billing.retrieve_subscription`
  and read metadata from there before deciding this is a
  creator-billing event.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import stripe
from sqlalchemy.orm import Session

from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.user import User
from app.services import stripe_creator_billing as scb
from app.webhooks.stripe_event_dedup import (
    claim_event,
    hash_payload,
    mark_processed,
)


logger = logging.getLogger(__name__)


# FC's own grace window after a failed creator invoice. Not Stripe's
# retry cadence (which is Stripe Dashboard-configured and dynamic).
_GRACE_WINDOW = timedelta(days=7)


# ---------------------------------------------------------------------------
# checkout.session.completed — link only, DO NOT activate
# ---------------------------------------------------------------------------


def handle_checkout_completed_creator_subscription(
    session: dict, db: Session, *, event_id: str, event_type: str,
) -> None:
    """Called from the outer webhook dispatcher when
    ``session.metadata.purchase_type == 'creator_subscription'``.

    Creates a placeholder CreatorSubscription row keyed to the
    ``stripe_subscription_id`` from the completed session, with
    ``status='past_due'`` (Stripe's ``incomplete`` maps here — see
    ``map_stripe_status``). We do NOT set ``status='active'`` until
    the first ``invoice.paid`` event arrives.

    Rationale (workstream amendment A): a completed checkout session
    means "user filled in card details", not "Stripe collected the
    money". Restricting activation to ``invoice.paid`` guarantees we
    never grant commercial capability without a real successful
    charge.
    """
    if not claim_event(
        db, event_id=event_id, event_type=event_type,
        payload_sha256=hash_payload(session),
    ):
        return

    metadata = session.get("metadata") or {}
    creator_user_id = metadata.get("creator_user_id")
    creator_plan_slug = metadata.get("creator_plan_slug")
    stripe_subscription_id = session.get("subscription")
    stripe_customer_id = session.get("customer")
    if not (creator_user_id and creator_plan_slug and stripe_subscription_id
            and stripe_customer_id):
        logger.error(
            "creator_billing_webhook: incomplete session metadata — "
            "session=%s creator=%s plan=%s sub=%s cust=%s",
            session.get("id"), creator_user_id, creator_plan_slug,
            stripe_subscription_id, stripe_customer_id,
        )
        return

    user = db.query(User).filter(User.id == creator_user_id).first()
    plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.slug == creator_plan_slug, CreatorPlan.is_active.is_(True))
        .first()
    )
    if user is None or plan is None:
        logger.error(
            "creator_billing_webhook: user or plan missing — session=%s "
            "creator=%s plan=%s",
            session.get("id"), creator_user_id, creator_plan_slug,
        )
        return

    # Idempotent upsert of the CreatorSubscription row keyed by
    # stripe_subscription_id. If invoice.paid arrived first (unlikely
    # but possible under redelivery), the row already exists with
    # active status — leave it.
    existing = (
        db.query(CreatorSubscription)
        .filter(CreatorSubscription.stripe_subscription_id == stripe_subscription_id)
        .first()
    )
    now = datetime.utcnow()
    if existing is None:
        db.add(CreatorSubscription(
            id=f"csub_{stripe_subscription_id[-16:]}",
            user_id=user.id,
            creator_plan_id=plan.id,
            # NOT ``active`` — we link but do not activate until
            # invoice.paid confirms the initial charge.
            status=CreatorSubscriptionStatus.past_due,
            starts_at=now,
            source="stripe_paid",
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
        ))
        db.commit()
        logger.info(
            "creator_billing_webhook: linked session=%s creator=%s plan=%s "
            "sub=%s cust=%s (awaiting invoice.paid to activate)",
            session.get("id"), creator_user_id, creator_plan_slug,
            stripe_subscription_id, stripe_customer_id,
        )

    mark_processed(db, event_id)


# ---------------------------------------------------------------------------
# invoice.paid — the true "activate / renew / recover" signal
# ---------------------------------------------------------------------------


def handle_invoice_paid(
    invoice: dict, db: Session, *, event_id: str, event_type: str,
) -> bool:
    """Try to handle ``invoice.paid`` as a creator-subscription event.

    Returns True if this event was a creator-subscription invoice and
    was handled here. Returns False if it wasn't ours (member
    finite-plan or other) — the outer dispatcher then routes to the
    finite-plan handler.

    Behaviour:
      * Retrieve the underlying Stripe Subscription and gate on
        creator-subscription metadata.
      * Idempotency: claim event via ``stripe_webhook_events``.
      * Look up the local ``CreatorSubscription`` by
        ``stripe_subscription_id`` (created by the link step above).
      * Set ``status=active`` (activation for the first invoice, or
        recovery from ``past_due`` on subsequent invoices).
      * Clear ``grace_expires_at`` (any prior grace is resolved).
      * Update ``current_period_end`` from the Subscription.
    """
    subscription_id = invoice.get("subscription")
    if not subscription_id:
        return False

    try:
        subscription = scb.retrieve_subscription(subscription_id)
    except stripe.error.StripeError:
        logger.exception(
            "creator_billing_webhook: failed to retrieve subscription %s "
            "for invoice %s", subscription_id, invoice.get("id"),
        )
        return False

    if not scb.is_creator_subscription(subscription):
        return False

    if not claim_event(
        db, event_id=event_id, event_type=event_type,
        payload_sha256=hash_payload(invoice),
    ):
        # Duplicate — but if it was our event, we still "handled" it.
        return True

    sub_row = (
        db.query(CreatorSubscription)
        .filter(CreatorSubscription.stripe_subscription_id == subscription_id)
        .with_for_update()
        .first()
    )
    if sub_row is None:
        # invoice.paid arrived BEFORE checkout.session.completed — rare
        # but possible under redelivery. Create the row now from what
        # we have, then let session.completed become a no-op via the
        # dedup table.
        metadata = subscription.get("metadata") or {}
        creator_user_id = metadata.get("creator_user_id")
        creator_plan_slug = metadata.get("creator_plan_slug")
        if not (creator_user_id and creator_plan_slug):
            logger.error(
                "creator_billing_webhook: invoice.paid without a linked "
                "CreatorSubscription AND without metadata to reconstruct "
                "one — subscription=%s invoice=%s",
                subscription_id, invoice.get("id"),
            )
            return True
        plan = (
            db.query(CreatorPlan)
            .filter(CreatorPlan.slug == creator_plan_slug)
            .first()
        )
        user = db.query(User).filter(User.id == creator_user_id).first()
        if plan is None or user is None:
            logger.error(
                "creator_billing_webhook: invoice.paid — plan/user missing "
                "for subscription=%s", subscription_id,
            )
            return True
        sub_row = CreatorSubscription(
            id=f"csub_{subscription_id[-16:]}",
            user_id=user.id,
            creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.past_due,   # about to flip below
            starts_at=datetime.utcnow(),
            source="stripe_paid",
            stripe_subscription_id=subscription_id,
            stripe_customer_id=subscription.get("customer"),
        )
        db.add(sub_row)
        db.flush()

    # Flip to active (or keep active). Clear grace, refresh period end.
    was_past_due = sub_row.status == CreatorSubscriptionStatus.past_due
    sub_row.status = CreatorSubscriptionStatus.active
    sub_row.grace_expires_at = None
    sub_row.current_period_end = scb.period_end_from_stripe(subscription)
    sub_row.cancel_at_period_end = bool(subscription.get("cancel_at_period_end", False))
    db.commit()

    logger.info(
        "creator_billing_webhook: invoice.paid handled — subscription=%s "
        "creator=%s status=active was_past_due=%s period_end=%s",
        subscription_id, sub_row.user_id, was_past_due,
        sub_row.current_period_end,
    )
    mark_processed(db, event_id)
    return True


# ---------------------------------------------------------------------------
# invoice.payment_failed — start FC grace
# ---------------------------------------------------------------------------


def handle_invoice_payment_failed(
    invoice: dict, db: Session, *, event_id: str, event_type: str,
) -> bool:
    """Failed invoice → set ``status='past_due'`` +
    ``grace_expires_at = now + 7 days``.

    Returns True if handled here (creator-billing), False otherwise.
    Existing member access is unaffected. The grace-expiry cron
    (``scripts/creator_subscription_grace_reconcile.py``) flips to
    ``unpaid`` after the window elapses.
    """
    subscription_id = invoice.get("subscription")
    if not subscription_id:
        return False
    try:
        subscription = scb.retrieve_subscription(subscription_id)
    except stripe.error.StripeError:
        logger.exception(
            "creator_billing_webhook: retrieve failed for sub=%s",
            subscription_id,
        )
        return False
    if not scb.is_creator_subscription(subscription):
        return False

    if not claim_event(
        db, event_id=event_id, event_type=event_type,
        payload_sha256=hash_payload(invoice),
    ):
        return True

    sub_row = (
        db.query(CreatorSubscription)
        .filter(CreatorSubscription.stripe_subscription_id == subscription_id)
        .with_for_update()
        .first()
    )
    if sub_row is None:
        logger.warning(
            "creator_billing_webhook: invoice.payment_failed for unknown "
            "subscription=%s — ignoring",
            subscription_id,
        )
        return True

    now = datetime.utcnow()
    # Only start a new grace window if not already in one. Repeated
    # invoice failures within a single grace period do not extend it —
    # the window runs from the FIRST failure.
    if sub_row.grace_expires_at is None:
        sub_row.grace_expires_at = now + _GRACE_WINDOW
    sub_row.status = CreatorSubscriptionStatus.past_due
    db.commit()
    logger.info(
        "creator_billing_webhook: invoice.payment_failed — sub=%s "
        "grace_expires_at=%s",
        subscription_id, sub_row.grace_expires_at,
    )
    mark_processed(db, event_id)
    return True


# ---------------------------------------------------------------------------
# customer.subscription.updated — reflect period_end / cancel_flag / plan
# ---------------------------------------------------------------------------


def handle_subscription_updated(
    subscription: dict, db: Session, *, event_id: str, event_type: str,
) -> bool:
    """Reflect Stripe subscription state onto the local row.

    Confirmed plan changes (upgrade committed on Stripe side) update
    ``creator_plan_id``. Cancellation-scheduled and period-end
    refreshes are also reflected here. Grace clearing happens on
    ``invoice.paid``, not here.
    """
    if not scb.is_creator_subscription(subscription):
        return False
    if not claim_event(
        db, event_id=event_id, event_type=event_type,
        payload_sha256=hash_payload(subscription),
    ):
        return True

    sub_row = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.stripe_subscription_id == subscription["id"],
        )
        .with_for_update()
        .first()
    )
    if sub_row is None:
        logger.warning(
            "creator_billing_webhook: subscription.updated for unknown "
            "sub=%s — ignoring",
            subscription["id"],
        )
        return True

    # Refresh lifecycle fields from the latest Stripe payload.
    sub_row.current_period_end = scb.period_end_from_stripe(subscription)
    sub_row.cancel_at_period_end = bool(subscription.get("cancel_at_period_end", False))

    # Plan change (upgrade confirmed). Read the CURRENT price on the
    # subscription and map back to a slug via the metadata (Stripe
    # merges metadata on modify, so ``creator_plan_slug`` is now the
    # target). Only update if the new slug resolves to an active
    # CreatorPlan; otherwise leave the row unchanged and log — this
    # keeps a broken metadata mutation from silently rebinding the
    # local plan_id.
    metadata = subscription.get("metadata") or {}
    new_slug = metadata.get("creator_plan_slug")
    if new_slug and (sub_row.plan is None or sub_row.plan.slug != new_slug):
        target_plan = (
            db.query(CreatorPlan)
            .filter(CreatorPlan.slug == new_slug, CreatorPlan.is_active.is_(True))
            .first()
        )
        if target_plan is not None:
            sub_row.creator_plan_id = target_plan.id
            logger.info(
                "creator_billing_webhook: plan change confirmed — sub=%s "
                "new_slug=%s",
                subscription["id"], new_slug,
            )

    # Reflect Stripe status changes — Stripe → FC mapping. Never
    # downgrade an ``active`` row via subscription.updated alone;
    # invoice events are the source of truth for active vs past_due.
    stripe_status = subscription.get("status")
    if stripe_status == "canceled":
        # ``customer.subscription.deleted`` also fires; treat this as
        # a defensive noop and let deleted handle it.
        pass
    db.commit()
    mark_processed(db, event_id)
    return True


# ---------------------------------------------------------------------------
# customer.subscription.deleted — final cancellation
# ---------------------------------------------------------------------------


def handle_subscription_deleted(
    subscription: dict, db: Session, *, event_id: str, event_type: str,
) -> bool:
    """Stripe subscription ended (either creator-initiated cancel_at_period_end
    reached term, or Stripe abandoned recovery after unpaid retries).

    Local effect: ``status='cancelled'``, clear ``grace_expires_at``.
    Do NOT auto-reassign to Community — creator sees the "not
    configured" warning card and can start a new subscription.
    Existing members / finite plans untouched.
    """
    if not scb.is_creator_subscription(subscription):
        return False
    if not claim_event(
        db, event_id=event_id, event_type=event_type,
        payload_sha256=hash_payload(subscription),
    ):
        return True

    sub_row = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.stripe_subscription_id == subscription["id"],
        )
        .with_for_update()
        .first()
    )
    if sub_row is None:
        logger.warning(
            "creator_billing_webhook: subscription.deleted for unknown "
            "sub=%s — ignoring",
            subscription["id"],
        )
        return True

    sub_row.status = CreatorSubscriptionStatus.cancelled
    sub_row.grace_expires_at = None
    sub_row.ends_at = datetime.utcnow()
    db.commit()
    logger.info(
        "creator_billing_webhook: subscription.deleted — sub=%s status=cancelled",
        subscription["id"],
    )
    mark_processed(db, event_id)
    return True
