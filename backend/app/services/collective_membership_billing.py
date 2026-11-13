"""Opening a paid Collective membership — the Stripe side.

What this module does, and what it refuses to do
------------------------------------------------
It prices a Collective's membership from the Collective's own settings,
mints a recurring Stripe Price for it, writes a ``pending``
``CollectiveMembership`` row, and opens a ``mode='subscription'``
Checkout Session. It grants nothing. Membership arrives only when a
verified invoice reaches
``collective_membership_lifecycle.activate_from_first_invoice``.

The row is written **before** Stripe is called, for the reason
``PurchasePlan`` does the same: a Stripe failure must not leave a
Session that nothing owns. A ``pending`` row is harmless — no access
check reads this table — and the partial unique index makes a
double-clicked Join collide in the database rather than relying on this
code noticing.

Pricing is the server's
-----------------------
Nothing in the request names a price. The amount comes from
``Space.pricing_amount_cents`` and the interval from
``Space.pricing_type``, both read here and then **frozen onto the row**.
After that the agreement never consults the Collective again, so a
creator re-pricing tomorrow re-prices nobody who already subscribed.

Why not ``stripe_creator_billing``
----------------------------------
Its ``resolve_price_id`` reads an env var per platform plan slug, which
cannot express a price each creator sets, and its
``find_or_create_customer`` looks for a prior ``CreatorSubscription`` —
useless for a member who has never been a creator. The reusable
precedent is ``stripe_finite_plan``, which already mints a Price from a
creator-set amount. Creator subscription behaviour is untouched.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus, LIVE_STATUSES,
)
from app.models.platform import Space
from app.models.user import User
from app.services import membership_pricing_terms as terms
from app.services.checkout_orchestration import (
    NO_ACTIVE_CREATOR_PLAN_DETAIL, PLAN_FORBIDS_PAID_OFFERS_DETAIL,
    FeeContext, NoActiveCreatorPlanError, resolve_fee_context,
)
from app.services.connect_payout_model import resolve_payout_model

logger = logging.getLogger(__name__)

#: The Stripe metadata discriminator. Every Stripe object this module
#: creates carries it, and the webhook routes on it — so a membership
#: subscription is never mistaken for a creator plan
#: (``creator_subscription``) or a finite instalment agreement
#: (``finite_plan_setup``).
METADATA_PURCHASE_TYPE = "collective_membership"


class MembershipBillingUnavailable(RuntimeError):
    """Stripe is not configured on this deployment."""


@dataclass(frozen=True)
class CheckoutOutcome:
    subscription: CollectiveMembership
    checkout_url: str
    #: True when an existing live Session was handed back rather than a
    #: new one opened.
    reused: bool = False


def _idem(subscription_id: str, op: str, *, version: str = "v1") -> str:
    """Stable per-agreement-per-operation idempotency key.

    Same shape and the same reasoning as ``stripe_finite_plan._idem``:
    Stripe caches both successes and 4xx against a key for 24h, so the
    version suffix is how a changed payload gets retried without
    disturbing sibling operations that already succeeded.
    """
    return f"cmem:{subscription_id}:{op}:{version}"


def _bind_key() -> None:
    if not settings.stripe_secret_key:
        raise MembershipBillingUnavailable(
            "Stripe is not configured — cannot open membership checkout."
        )
    stripe.api_key = settings.stripe_secret_key


# ---------------------------------------------------------------------------
# Stripe Customer identity
# ---------------------------------------------------------------------------


def resolve_customer_id(db: Session, *, user: User) -> str:
    """A Stripe Customer for this member, reused where one is known.

    **One Customer per person, not per Collective.** Charges for every
    Collective land on Fresh Collective's own Stripe account — the
    platform is the merchant of record and the creator is paid by a
    separate transfer — so there is one account for a Customer to live
    on, and splitting a person across several would multiply payment
    methods they would each have to enter again.

    Separation between Collectives is carried by the *subscription*, not
    the Customer: one ``CollectiveMembership`` row per agreement, each
    with its own Stripe subscription id, each independently cancellable.
    Nothing about one Collective's agreement is legible from another's.

    Lookup order, widest reuse first:

    1. a membership agreement this member already holds, any status;
    2. a ``CreatorSubscription`` of theirs, if they are also a creator —
       Stripe treats the two identically and a person with one card
       should not acquire two Customers;
    3. otherwise create one, stamped with ``user_id`` so the webhook can
       trust the linkage.
    """
    _bind_key()

    prior = (
        db.query(CollectiveMembership.stripe_customer_id)
        .filter(
            CollectiveMembership.user_id == user.id,
            CollectiveMembership.stripe_customer_id.is_not(None),
        )
        .order_by(CollectiveMembership.created_at.desc())
        .first()
    )
    if prior and prior[0]:
        return prior[0]

    # Reading the creator table, never writing it. This is the one place
    # the two subscription systems touch, and it is a read.
    from app.models.creator_billing import CreatorSubscription

    as_creator = (
        db.query(CreatorSubscription.stripe_customer_id)
        .filter(
            CreatorSubscription.user_id == user.id,
            CreatorSubscription.stripe_customer_id.is_not(None),
        )
        .order_by(CreatorSubscription.created_at.desc())
        .first()
    )
    if as_creator and as_creator[0]:
        return as_creator[0]

    customer = stripe.Customer.create(
        email=user.email,
        name=getattr(user, "name", None) or None,
        metadata={
            "fc_user_id": user.id,
            "fc_customer_for": "collective_membership",
        },
        idempotency_key=f"cmem:customer:{user.id}:v1",
    )
    logger.info(
        "collective membership: created Stripe Customer for user=%s", user.id,
    )
    return customer.id


# ---------------------------------------------------------------------------
# Opening a subscription
# ---------------------------------------------------------------------------


def find_live_subscription(
    db: Session, *, user_id: str, space_id: str,
) -> CollectiveMembership | None:
    """This member's current agreement with this Collective, if any."""
    return (
        db.query(CollectiveMembership)
        .filter(
            CollectiveMembership.user_id == user_id,
            CollectiveMembership.space_id == space_id,
            CollectiveMembership.status.in_(sorted(LIVE_STATUSES)),
        )
        .order_by(CollectiveMembership.created_at.desc())
        .first()
    )


def _freeze_fee_context(db: Session, space: Space) -> FeeContext:
    try:
        fee = resolve_fee_context(space, db)
    except NoActiveCreatorPlanError as exc:
        raise HTTPException(
            status_code=409, detail=NO_ACTIVE_CREATOR_PLAN_DETAIL,
        ) from exc
    if not fee.permits_paid_offers:
        # The same gate every other paid door runs. A creator who has
        # downgraded cannot keep selling through a door nobody closed.
        raise HTTPException(
            status_code=403, detail=PLAN_FORBIDS_PAID_OFFERS_DETAIL,
        )
    return fee


def open_membership_checkout(
    db: Session, *,
    space: Space,
    member: User,
    success_url: str,
    cancel_url: str,
    now: datetime,
) -> CheckoutOutcome:
    """Price the membership, record the agreement, open Stripe Checkout.

    Caller is responsible for eligibility — see
    ``collective_membership_eligibility``. This function assumes the
    member may join and concerns itself only with money.
    """
    agreed = terms.resolve(space)

    existing = find_live_subscription(
        db, user_id=member.id, space_id=space.id,
    )
    if existing is not None:
        reuse = _reuse_if_still_valid(existing, agreed=agreed)
        if reuse is not None:
            logger.info(
                "collective membership: reusing live Session=%s sub=%s "
                "user=%s space=%s",
                existing.stripe_checkout_session_id, existing.id,
                member.id, space.id,
            )
            return CheckoutOutcome(
                subscription=existing, checkout_url=reuse, reused=True,
            )
        # Priced differently, or the page is gone. Supersede rather than
        # hand back an agreement the member is no longer being quoted —
        # the Stage 4A lesson, applied before it can bite again.
        _supersede(db, existing, now=now, reason="superseded_by_new_quote")

    fee = _freeze_fee_context(db, space)
    payout = resolve_payout_model(
        db,
        creator_user_id=fee.creator_id,
        is_platform_owned=fee.is_platform_owned,
    )

    row = CollectiveMembership(
        id=f"cmem_{uuid.uuid4().hex[:24]}",
        user_id=member.id,
        space_id=space.id,
        status=CollectiveMembershipStatus.pending.value,
        interval=agreed.interval,
        interval_count=agreed.interval_count,
        amount_cents=agreed.amount_cents,
        currency=agreed.currency,
        creator_user_id=fee.creator_id,
        platform_fee_basis_points=fee.fee_bps,
        payout_model=payout.payout_model,
        connect_destination_account_id=payout.destination_account_id,
        creator_plan_id=fee.creator_plan_id,
        stripe_mode=settings.stripe_mode,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    # Flushed, not committed: the unique index decides here whether this
    # member already has a live agreement, and a concurrent duplicate
    # fails now rather than after Stripe has been told about it.
    db.flush()

    try:
        product_id, price_id = _create_price(row, space=space)
        row.stripe_product_id = product_id
        row.stripe_price_id = price_id
        row.stripe_customer_id = resolve_customer_id(db, user=member)
        session = _create_session(
            row, space=space, member=member,
            success_url=success_url, cancel_url=cancel_url,
        )
    except Exception:
        # The agreement is left ``pending`` with no Session. It grants
        # nothing, blocks nothing a retry needs — the retry supersedes
        # it — and leaves a row an operator can see.
        logger.exception(
            "collective membership: Stripe failed opening checkout "
            "sub=%s user=%s space=%s", row.id, member.id, space.id,
        )
        raise

    row.stripe_checkout_session_id = session.id
    row.updated_at = now
    logger.info(
        "collective membership: opened checkout sub=%s session=%s "
        "user=%s space=%s %s %d %s",
        row.id, session.id, member.id, space.id,
        agreed.interval, agreed.amount_cents, agreed.currency,
    )
    return CheckoutOutcome(
        subscription=row, checkout_url=session.url, reused=False,
    )


def _reuse_if_still_valid(
    existing: CollectiveMembership, *, agreed: terms.AgreedTerms,
) -> str | None:
    """The live Session to send the member back to, or ``None``.

    Reuse protects against a second payment page for one purchase. It is
    only safe when the page is for *the same agreement*: Stage 4A was
    exactly this check missing a price comparison, and a member being
    handed back a page priced before the creator changed it.

    Every term is compared, not just the amount — an interval or a
    currency change is as much a different agreement as a different
    number.
    """
    if existing.status != CollectiveMembershipStatus.pending.value:
        # ``active`` or ``past_due`` is not a checkout to resume; the
        # caller refuses the duplicate instead.
        return None
    if not existing.stripe_checkout_session_id:
        return None
    if (
        existing.amount_cents != agreed.amount_cents
        or existing.currency != agreed.currency
        or existing.interval != agreed.interval
        or existing.interval_count != agreed.interval_count
    ):
        return None
    state = _inspect_session(existing.stripe_checkout_session_id)
    if state is None or state.get("status") != "open":
        return None
    return state.get("url") or None


def _inspect_session(session_id: str) -> dict[str, Any] | None:
    _bind_key()
    try:
        sess = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError:                   # pragma: no cover - network
        # Unreadable is treated as unusable: superseding opens a fresh
        # page, which is safe, where reusing an unknown one is not.
        return None
    return {"status": getattr(sess, "status", None),
            "url": getattr(sess, "url", None)}


def _supersede(
    db: Session, row: CollectiveMembership, *, now: datetime, reason: str,
) -> None:
    """Close a superseded pending agreement and expire its page.

    Expiring at Stripe is belt and braces — activation refuses any
    invoice whose agreement is no longer ``pending`` — but it stops a
    member who kept the old tab from reaching a page that would charge
    them for a quote they have replaced.
    """
    if row.stripe_checkout_session_id:
        try:
            _bind_key()
            stripe.checkout.Session.expire(row.stripe_checkout_session_id)
        except Exception:                        # pragma: no cover - network
            logger.warning(
                "collective membership: could not expire Session=%s for "
                "superseded sub=%s", row.stripe_checkout_session_id, row.id,
            )
    row.status = CollectiveMembershipStatus.failed.value
    row.cancelled_at = now
    row.cancelled_reason = reason[:250]
    row.ended_at = now
    row.updated_at = now
    db.flush()
    logger.info(
        "collective membership: superseded sub=%s (%s)", row.id, reason,
    )


def _create_price(
    row: CollectiveMembership, *, space: Space,
) -> tuple[str, str]:
    """A Product and a recurring Price for this agreement.

    One Price per agreement rather than one per Collective. A shared
    Price would have to be found, validated and re-minted whenever the
    creator changed the amount, and an agreement pointing at a Price
    somebody else edited is exactly the staleness this stage is
    avoiding. Stripe charges nothing for the objects.
    """
    _bind_key()
    product = stripe.Product.create(
        name=f"{space.name} membership",
        description=(
            f"Ongoing membership of {space.name} on Fresh Collective."
        ),
        metadata={
            "purchase_type": METADATA_PURCHASE_TYPE,
            "collective_membership_id": row.id,
            "space_id": space.id,
        },
        idempotency_key=_idem(row.id, "product"),
    )
    price = stripe.Price.create(
        product=product.id,
        currency=row.currency.lower(),
        unit_amount=row.amount_cents,
        recurring={
            "interval": row.interval,
            "interval_count": row.interval_count,
        },
        metadata={
            "purchase_type": METADATA_PURCHASE_TYPE,
            "collective_membership_id": row.id,
        },
        idempotency_key=_idem(row.id, "price"),
    )
    return product.id, price.id


def _create_session(
    row: CollectiveMembership, *,
    space: Space,
    member: User,
    success_url: str,
    cancel_url: str,
) -> Any:
    """The Stripe-hosted subscription checkout.

    ``metadata`` is carried on both the Session and the Subscription it
    creates: the Session's is what ``checkout.session.completed`` sees,
    and ``subscription_data.metadata`` is what every future invoice
    event sees. Without the second, a renewal arrives with no way to tell
    which system owns it.
    """
    _bind_key()
    meta = {
        "purchase_type": METADATA_PURCHASE_TYPE,
        "collective_membership_id": row.id,
        "space_id": space.id,
        "member_user_id": member.id,
    }
    return stripe.checkout.Session.create(
        mode="subscription",
        customer=row.stripe_customer_id,
        line_items=[{"price": row.stripe_price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=meta,
        subscription_data={"metadata": meta},
        idempotency_key=_idem(row.id, "session"),
    )
