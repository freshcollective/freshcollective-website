"""Stripe integration for Creator / Pro monthly subscription billing.

Strictly separated from the member finite-plan Stripe integration
(``app/services/finite_plan_orchestration.py``): different metadata
discriminator (``purchase_type='creator_subscription'``), different
webhook handler module (``app/webhooks/creator_billing_handlers.py``),
different DB rows (``creator_subscriptions`` vs ``purchase_plans``).

Design constraints (see the workstream's audit + amendments):

* **Env-var pricing** — ``STRIPE_PRICE_ID_CREATOR`` and
  ``STRIPE_PRICE_ID_PRO`` are the recurring monthly Prices set up in
  the live Stripe Dashboard. When either is missing / empty, the
  service raises so the caller can 503 rather than pretending to
  work.
* **Card-only checkout** — the MVP restricts payment methods to card
  so that ``invoice.paid`` is the reliable "actually paid" signal.
  Do not add BNPL / bank-debit here without revisiting the
  activation invariant.
* **No activation on session.completed** — this module never mutates
  the ``creator_subscriptions`` row on
  ``checkout.session.completed``. The webhook handler links the
  Customer + Subscription only; activation happens on
  ``invoice.paid`` for the initial invoice.
* **Upgrade uses pending_update** — ``upgrade_subscription`` calls
  ``Subscription.modify(payment_behavior='pending_if_incomplete')``
  so an upgrade whose prorated payment fails does NOT get us stuck
  with the higher tier's fee locally.
* **Downgrade uses SubscriptionSchedule** — a genuine deferred
  Stripe object. Not a ``proration_behavior='none'`` sleight of hand.

No DB writes happen here — every function returns the raw Stripe
resource. Callers own the DB commit boundary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import stripe
from sqlalchemy.orm import Session

from app.core.config import settings
from app.creator.plan_config import get_plan_capability
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.user import User


logger = logging.getLogger(__name__)


# Metadata key + values every creator-subscription Stripe object
# carries. The webhook uses these to isolate creator-billing events
# from member finite-plan events, which use ``purchase_type='finite_plan_setup'``.
METADATA_PURCHASE_TYPE_KEY = "purchase_type"
METADATA_PURCHASE_TYPE_VALUE = "creator_subscription"


class StripeCreatorBillingConfigError(RuntimeError):
    """Raised when the required Stripe Price IDs are not configured.

    Callers translate this to HTTP 503. Never leaks the actual env-var
    values into user-facing responses.
    """


class PlanNotSubscribableError(RuntimeError):
    """Attempt to start Stripe checkout for a plan whose capability
    forbids it (Community, Founding Creator, Organisation). Callers
    translate to HTTP 403."""


# ---------------------------------------------------------------------------
# Price ID resolution
# ---------------------------------------------------------------------------


def resolve_price_id(plan_slug: str) -> str:
    """Return the Stripe Price ID for ``plan_slug`` from env config.

    Raises ``StripeCreatorBillingConfigError`` when the plan is
    subscribable but its Price ID env var is unset. Non-subscribable
    plans (Community, Founding Creator, Organisation) raise
    ``PlanNotSubscribableError`` — the caller should never reach here
    for those, but this second layer defends against a mis-routed
    request.
    """
    capability = get_plan_capability(plan_slug)
    if capability is None:
        raise PlanNotSubscribableError(f"Unknown plan slug {plan_slug!r}.")
    if not capability.is_purchasable:
        raise PlanNotSubscribableError(
            f"Plan {plan_slug!r} is not purchasable via Stripe checkout."
        )
    if plan_slug == "creator":
        price_id = settings.stripe_price_id_creator
    elif plan_slug == "pro":
        price_id = settings.stripe_price_id_pro
    else:
        # Adding a new purchasable tier requires an engineering deploy
        # that (a) adds an env var, (b) extends this resolver, (c)
        # updates the admin CRUD allowlist. Deliberate — silent
        # fallback would be a misconfiguration hazard.
        raise StripeCreatorBillingConfigError(
            f"No Stripe Price env var wired for plan {plan_slug!r}."
        )
    if not price_id:
        raise StripeCreatorBillingConfigError(
            f"Stripe Price ID for plan {plan_slug!r} is not configured. "
            "Set the corresponding env var in the Render Dashboard "
            "before enabling subscription checkout."
        )
    return price_id


# ---------------------------------------------------------------------------
# Stripe Customer resolution
# ---------------------------------------------------------------------------


def find_or_create_customer(user: User, db: Session) -> str:
    """Return a Stripe Customer id for ``user``.

    Reuse strategy: look for the most recent CreatorSubscription (any
    status) with a populated ``stripe_customer_id``. Members and
    creators can share the same underlying Customer if the same user
    happens to be both, but that's fine — Stripe treats them
    identically. If nothing exists, create a fresh Customer with
    metadata that lets the webhook trust the linkage.
    """
    stripe.api_key = settings.stripe_secret_key
    prior = (
        db.query(CreatorSubscription.stripe_customer_id)
        .filter(
            CreatorSubscription.user_id == user.id,
            CreatorSubscription.stripe_customer_id.is_not(None),
        )
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )
    if prior and prior[0]:
        return prior[0]
    customer = stripe.Customer.create(
        email=user.email,
        name=user.name or user.email,
        metadata={
            "fc_user_id": user.id,
            METADATA_PURCHASE_TYPE_KEY: METADATA_PURCHASE_TYPE_VALUE,
        },
    )
    return customer.id


# ---------------------------------------------------------------------------
# Checkout Session — mode='subscription'
# ---------------------------------------------------------------------------


def create_checkout_session(
    *,
    user: User,
    plan: CreatorPlan,
    success_url: str,
    cancel_url: str,
    db: Session,
) -> stripe.checkout.Session:
    """Create a Stripe Checkout Session for a creator to subscribe
    to ``plan``. Card-only per the workstream invariant.

    The returned session's ``url`` is what the frontend redirects
    the browser to. Metadata is duplicated on both the Session AND
    the resulting Subscription so the webhook can trust either
    surface.
    """
    stripe.api_key = settings.stripe_secret_key
    price_id = resolve_price_id(plan.slug)
    customer_id = find_or_create_customer(user, db)
    metadata = _billing_metadata(user_id=user.id, plan_slug=plan.slug)
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        # Card-only — see the module docstring. Adding another PM
        # requires re-verifying that ``invoice.paid`` still fires
        # synchronously enough for our activation semantics.
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        # Metadata on the Session — surfaces on the
        # ``checkout.session.completed`` event.
        metadata=metadata,
        # Metadata on the resulting Subscription — surfaces on every
        # ``customer.subscription.*`` and (indirectly, via
        # subscription lookup) on ``invoice.*`` events.
        subscription_data={"metadata": metadata},
        # Stripe automatic tax config left OFF for MVP — Fresh
        # Collective's GST treatment is a Lindsey decision (see the
        # workstream's "GST / TAX — HOLD POINT" section). When she
        # confirms, add ``automatic_tax={'enabled': True}`` here and
        # populate ``tax_id_collection`` if required.
    )
    return session


# ---------------------------------------------------------------------------
# Customer Portal
# ---------------------------------------------------------------------------


def create_portal_session(
    *,
    customer_id: str,
    return_url: str,
) -> stripe.billing_portal.Session:
    """Return a one-shot Stripe Customer Portal session URL for the
    creator to manage payment method / view invoices / cancel."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )


# ---------------------------------------------------------------------------
# Upgrade — immediate, prorated, payment-safe
# ---------------------------------------------------------------------------


def upgrade_subscription(
    *,
    subscription_id: str,
    target_plan_slug: str,
) -> stripe.Subscription:
    """Immediate prorated upgrade (Creator → Pro).

    Uses ``payment_behavior='pending_if_incomplete'`` so an upgrade
    whose prorated payment fails does not silently succeed on
    Stripe's side. The webhook (``customer.subscription.updated``)
    then reflects the actual post-payment state — pending upgrades
    do not flip the local ``creator_plan_id`` until the invoice
    resolves paid. See the workstream's technical amendment C.
    """
    stripe.api_key = settings.stripe_secret_key
    target_price_id = resolve_price_id(target_plan_slug)
    sub = stripe.Subscription.retrieve(subscription_id)
    if not sub["items"]["data"]:
        raise RuntimeError(
            f"Stripe subscription {subscription_id!r} has no items — cannot upgrade."
        )
    item_id = sub["items"]["data"][0]["id"]
    updated = stripe.Subscription.modify(
        subscription_id,
        items=[{"id": item_id, "price": target_price_id}],
        proration_behavior="create_prorations",
        payment_behavior="pending_if_incomplete",
        # Refresh metadata so future events reflect the new plan slug
        # even if we haven't yet processed the update-confirmed event.
        metadata=_metadata_from_existing(sub) | {"creator_plan_slug": target_plan_slug},
    )
    return updated


# ---------------------------------------------------------------------------
# Downgrade — Subscription Schedule at period end
# ---------------------------------------------------------------------------


def schedule_downgrade(
    *,
    subscription_id: str,
    target_plan_slug: str,
) -> stripe.SubscriptionSchedule:
    """Schedule a Pro → Creator downgrade to take effect at
    ``subscription.current_period_end``.

    Uses ``stripe.SubscriptionSchedule.create(from_subscription=…)``
    followed by ``.modify(phases=[current, next-tier])``. This is
    the only Stripe primitive that genuinely defers a Price change
    to a specific date; ``Subscription.modify`` with
    ``proration_behavior='none'`` still switches the price
    immediately, which is not what we want.

    Returns the created SubscriptionSchedule so the caller can
    persist its ``id`` on ``CreatorSubscription.stripe_subscription_schedule_id``.
    """
    stripe.api_key = settings.stripe_secret_key
    target_price_id = resolve_price_id(target_plan_slug)
    sub = stripe.Subscription.retrieve(subscription_id)
    current_price_id = sub["items"]["data"][0]["price"]["id"]
    current_period_end = sub["current_period_end"]

    schedule = stripe.SubscriptionSchedule.create(
        from_subscription=subscription_id,
    )
    # Two-phase: current tier through period end, target tier from
    # then on. Stripe requires phases with explicit ``start_date``
    # values in this shape.
    updated_schedule = stripe.SubscriptionSchedule.modify(
        schedule.id,
        end_behavior="release",  # after the target phase completes, Stripe releases
        phases=[
            {
                "items": [{"price": current_price_id, "quantity": 1}],
                "start_date": sub["current_period_start"],
                "end_date": current_period_end,
                "metadata": _metadata_from_existing(sub),
            },
            {
                "items": [{"price": target_price_id, "quantity": 1}],
                "start_date": current_period_end,
                "metadata": _metadata_from_existing(sub)
                | {"creator_plan_slug": target_plan_slug},
            },
        ],
    )
    return updated_schedule


def cancel_schedule(schedule_id: str) -> stripe.SubscriptionSchedule:
    """Cancel a pending downgrade Schedule (creator changed their mind)."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.SubscriptionSchedule.release(schedule_id)


# ---------------------------------------------------------------------------
# Cancellation — cancel_at_period_end
# ---------------------------------------------------------------------------


def cancel_at_period_end(subscription_id: str) -> stripe.Subscription:
    """Flip ``cancel_at_period_end=True`` on the Stripe subscription.

    Creator retains commercial capability through
    ``current_period_end``. At period end, Stripe fires
    ``customer.subscription.deleted`` and our webhook flips local
    ``status='cancelled'``.
    """
    stripe.api_key = settings.stripe_secret_key
    return stripe.Subscription.modify(
        subscription_id,
        cancel_at_period_end=True,
    )


def reactivate(subscription_id: str) -> stripe.Subscription:
    """Undo a pending cancellation before it takes effect."""
    stripe.api_key = settings.stripe_secret_key
    return stripe.Subscription.modify(
        subscription_id,
        cancel_at_period_end=False,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _billing_metadata(*, user_id: str, plan_slug: str) -> dict[str, str]:
    return {
        METADATA_PURCHASE_TYPE_KEY: METADATA_PURCHASE_TYPE_VALUE,
        "creator_user_id": user_id,
        "creator_plan_slug": plan_slug,
    }


def _metadata_from_existing(sub) -> dict[str, str]:
    """Preserve creator identity metadata across ``Subscription.modify``
    calls. Stripe merges metadata; we still send the full triplet so
    a subsequent webhook that only saw one previous event still
    resolves correctly."""
    md = dict(sub.get("metadata", {}) or {})
    md.setdefault(METADATA_PURCHASE_TYPE_KEY, METADATA_PURCHASE_TYPE_VALUE)
    return md


# ---------------------------------------------------------------------------
# Subscription state helpers (webhook side, read-only Stripe lookups)
# ---------------------------------------------------------------------------


def retrieve_subscription(subscription_id: str) -> stripe.Subscription:
    """Read-side helper — the invoice webhook resolves the subscription
    to check metadata + confirm active status before mutating FC state.
    """
    stripe.api_key = settings.stripe_secret_key
    return stripe.Subscription.retrieve(subscription_id)


@dataclass(frozen=True)
class CreatorInvoiceSummary:
    """One row for the Creator Studio Billing History list. Everything
    is safe to render — no card details, no PII beyond the amount +
    date, and the hosted URLs are Stripe's own tokenised links."""
    id: str
    number: str | None
    created_at: datetime
    period_start: datetime | None
    period_end: datetime | None
    amount_paid_cents: int
    amount_due_cents: int
    currency: str
    status: str          # paid | open | draft | uncollectible | void
    hosted_invoice_url: str | None
    invoice_pdf: str | None
    description: str | None


def list_creator_invoices(
    *,
    customer_id: str,
    subscription_id: str | None = None,
    limit: int = 24,
) -> list[CreatorInvoiceSummary]:
    """Return invoices for the creator's Stripe Customer, filtered to
    the given subscription when supplied. Read-only Stripe call — no
    DB mutation. Card / payment-method / private billing data are
    deliberately not surfaced.

    ``subscription_id`` — when passed, only invoices attached to that
    Stripe Subscription are returned. This keeps member finite-plan
    invoices (which live on different subscriptions) out of the
    creator billing history even if the same Customer id happens to
    be reused.
    """
    stripe.api_key = settings.stripe_secret_key
    kwargs: dict = {"customer": customer_id, "limit": limit}
    if subscription_id:
        kwargs["subscription"] = subscription_id
    resp = stripe.Invoice.list(**kwargs)
    out: list[CreatorInvoiceSummary] = []
    for inv in resp.auto_paging_iter() if hasattr(resp, "auto_paging_iter") else resp.get("data", []):
        # ``stripe.Invoice`` behaves as dict; use .get for defensive
        # access against optional fields (period_start etc. are absent
        # on some invoice types).
        data = inv if isinstance(inv, dict) else inv.to_dict()
        created_ts = data.get("created")
        ps = data.get("period_start")
        pe = data.get("period_end")
        out.append(CreatorInvoiceSummary(
            id=data["id"],
            number=data.get("number"),
            created_at=datetime.utcfromtimestamp(created_ts) if created_ts else datetime.utcnow(),
            period_start=datetime.utcfromtimestamp(ps) if ps else None,
            period_end=datetime.utcfromtimestamp(pe) if pe else None,
            amount_paid_cents=int(data.get("amount_paid") or 0),
            amount_due_cents=int(data.get("amount_due") or 0),
            currency=(data.get("currency") or "aud").upper(),
            status=data.get("status") or "unknown",
            hosted_invoice_url=data.get("hosted_invoice_url"),
            invoice_pdf=data.get("invoice_pdf"),
            description=data.get("description"),
        ))
        if len(out) >= limit:
            break
    return out


def is_creator_subscription(sub: dict) -> bool:
    """Metadata gate. Every creator-subscription Stripe object carries
    ``metadata.purchase_type='creator_subscription'``. Member
    finite-plan subs use ``purchase_type='finite_plan_setup'``. If the
    metadata is absent or wrong, this returns False and the webhook
    ignores the event."""
    metadata = sub.get("metadata") or {}
    return metadata.get(METADATA_PURCHASE_TYPE_KEY) == METADATA_PURCHASE_TYPE_VALUE


# Status mapping — Stripe → FC. Kept as a pure function so tests can
# assert every Stripe status maps to a defined FC status.
_STRIPE_TO_FC_STATUS: dict[str, CreatorSubscriptionStatus] = {
    "active":              CreatorSubscriptionStatus.active,
    "trialing":            CreatorSubscriptionStatus.trialing,
    "past_due":            CreatorSubscriptionStatus.past_due,
    "unpaid":              CreatorSubscriptionStatus.unpaid,
    "canceled":            CreatorSubscriptionStatus.cancelled,
    "incomplete":          CreatorSubscriptionStatus.past_due,   # not-yet-paid initial invoice
    "incomplete_expired":  CreatorSubscriptionStatus.cancelled,
    "paused":              CreatorSubscriptionStatus.past_due,   # rare; treat as past_due
}


def map_stripe_status(stripe_status: str) -> CreatorSubscriptionStatus:
    """Return the FC status that corresponds to ``stripe_status``. Raises
    on unknown values so an unexpected Stripe status doesn't silently
    coerce to a wrong state."""
    if stripe_status not in _STRIPE_TO_FC_STATUS:
        raise ValueError(
            f"Unmapped Stripe subscription status: {stripe_status!r}. Add to "
            "``_STRIPE_TO_FC_STATUS`` in ``stripe_creator_billing.py``."
        )
    return _STRIPE_TO_FC_STATUS[stripe_status]


def period_end_from_stripe(subscription: dict) -> datetime | None:
    ts = subscription.get("current_period_end")
    return datetime.utcfromtimestamp(ts) if ts else None
