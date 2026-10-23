"""Becoming the owner of an Offering.

Two ways in, one set of rules.

    free     →  ``acquire_free``          (no Stripe, no ledger row)
    paid     →  ``POST /api/checkout/offering``  →  Stripe  →  webhook

Both ask :func:`check_acquirable` first, and both end at the same
place: one ``OfferingEntitlement`` row, plus membership of the
Collective. The free path writes that row itself; the paid path hands
the work to ``purchase_fulfilment.apply_intent`` through the shared
grant machinery, so there is exactly one implementation of "what
owning this means".

Why free does not go through checkout
-------------------------------------

``orchestrate_free_checkout`` exists and handles zero-price Payment
Options for Pathways and Series. Offerings deliberately do not use it,
for three reasons:

  * It writes a ``PaymentTransaction``. A free download is not a
    payment, and a zero-value row for every acquisition would put
    thousands of non-transactions into the creator's Payments received
    ledger and the platform's financial reporting.
  * It would need a Payment Option, a schedule and a grant provisioned
    for every free Offering — commerce rows that never charge anything,
    and a second place for "is this free?" to be answered.
  * ``OfferingEntitlement`` already models a free acquisition
    first-class: ``source='free'``, ``payment_transaction_id`` nullable.
    Writing a transaction to satisfy a code path would contradict the
    schema's own design.

So free acquisition is its own short, auditable function, and the
entitlement row — identical in shape to the one a purchase produces —
is the single record of ownership either way.

Idempotency
-----------

Three layers, deliberately:

  1. ``check_acquirable`` reports ``already_owned`` so the UI can say
     "It's already in Your Collection" instead of acquiring twice.
  2. :func:`acquire_free` re-reads before inserting and returns the
     existing row if it finds one.
  3. ``ux_offering_entitlements_active`` — a partial unique index over
     ``(user_id, offering_id) WHERE status='active'`` — makes a second
     active row impossible regardless of what the application does.

Layer 3 is the guarantee; 1 and 2 are what make the common case a
pleasant no-op rather than a 500. If two requests from the same person
genuinely interleave between 2 and 3, the loser's insert raises and the
**route** recovers: it rolls back and calls ``acquire_free`` again, at
which point layer 2 sees the winner. The recovery is in the route
because the route owns the transaction, and deciding what survives a
rollback is not a service's business.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
    OfferingStatus,
)
from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus
from app.models.user import User
from app.services import membership_grant as _membership_grant
from app.services import offering_pilot as _pilot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Refusal reasons — stable codes, member-facing prose
# ---------------------------------------------------------------------------

#: Why acquisition is not available. The code is for the client and the
#: tests; the message is what a person reads. Kept together so the two
#: cannot drift, and kept as data so the detail endpoint can report the
#: reason without a second copy of the rule.
REASON_NOT_PUBLISHED = "not_published"
REASON_RETIRED = "retired"
REASON_NO_FILES = "no_files"
REASON_PLAN_FORBIDS_PAID = "plan_forbids_paid"
REASON_PRICING_UNSET = "pricing_unset"
REASON_WRONG_PRICING = "wrong_pricing"
REASON_NOT_SELLABLE = "not_sellable"
#: The Collective is outside the Offerings pilot. Member-facing prose is
#: deliberately the same as "not available yet" — a visitor must not
#: learn that a feature exists which their Collective is excluded from.
REASON_OUTSIDE_PILOT = "outside_pilot"
#: Not a refusal in the usual sense — the member has it already, and the
#: right response is a way in rather than an error. Carried as a reason
#: code so the client can tell this 409 from the others.
REASON_ALREADY_OWNED = "already_owned"

_MESSAGES: dict[str, str] = {
    REASON_NOT_PUBLISHED: "This Offering isn't available yet.",
    REASON_OUTSIDE_PILOT: "This Offering isn't available yet.",
    REASON_RETIRED: (
        "This Offering is no longer available. People who already have "
        "it keep their files."
    ),
    REASON_NO_FILES: (
        "This Offering's files are being updated. Please check back "
        "shortly."
    ),
    REASON_PLAN_FORBIDS_PAID: (
        "This Offering isn't available for purchase at the moment."
    ),
    REASON_PRICING_UNSET: "This Offering isn't available yet.",
    REASON_WRONG_PRICING: "This Offering has a price and can't be claimed for free.",
    REASON_NOT_SELLABLE: (
        "This Offering isn't available for purchase at the moment."
    ),
}


class AcquisitionRefused(Exception):
    """Acquisition cannot proceed. Carries a code and prose."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        self.message = message or _MESSAGES.get(
            reason, "This Offering isn't available."
        )
        super().__init__(self.message)


@dataclass(frozen=True)
class Acquirability:
    """Whether this viewer could acquire this Offering right now."""

    #: None when acquisition is available.
    refusal: str | None = None
    #: They already own it — not a refusal. The action becomes "open it".
    already_owned: bool = False
    #: Count of files they would receive. Zero means ``REASON_NO_FILES``.
    approved_files: int = 0

    @property
    def can_acquire(self) -> bool:
        return self.refusal is None and not self.already_owned

    @property
    def message(self) -> str | None:
        return _MESSAGES.get(self.refusal) if self.refusal else None


@dataclass(frozen=True)
class AcquisitionOutcome:
    """What :func:`acquire_free` did."""

    entitlement: OfferingEntitlement
    #: False when they already owned it and nothing was created.
    created: bool
    #: True when this acquisition also made them a member.
    joined_collective: bool
    #: True only when the membership was created FOR THE FIRST TIME —
    #: False for a reactivation and False for somebody who was already
    #: a member. The route turns this into the Collective's welcome, so
    #: it has to tell those apart; ``joined_collective`` cannot, because
    #: it answers the different question the response body asks ("are
    #: they in the Collective now because of this?").
    membership_first_time: bool = False


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def already_owns(db: Session, *, user_id: str, offering_id: str) -> bool:
    return (
        db.query(OfferingEntitlement.id)
        .filter(
            OfferingEntitlement.user_id == user_id,
            OfferingEntitlement.offering_id == offering_id,
            OfferingEntitlement.status
            == OfferingEntitlementStatus.active.value,
        )
        .first()
    ) is not None


def approved_file_count(db: Session, offering_id: str) -> int:
    """How many files a new owner would actually be able to download.

    The same predicate the member detail page and download
    authorisation use: current (not superseded) **and** passed. A
    pending or quarantined file is not counted, because counting it
    would let somebody acquire an Offering whose every download then
    refuses them.
    """
    return (
        db.query(OfferingFile.id)
        .filter(
            OfferingFile.offering_id == offering_id,
            OfferingFile.superseded_at.is_(None),
            OfferingFile.validation_status == FVS.passed.value,
        )
        .count()
    )


def is_member(db: Session, *, user_id: str, space_id: str) -> bool:
    """Active membership only. Used for the transparency notice, so a
    paused or removed row correctly reads as "not a member" and the
    person is told they will be joining."""
    return (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    ) is not None


def will_join_collective(db: Session, *, user: User | None, space: Space) -> bool:
    """Whether acquiring would change this person's membership.

    Drives the notice on the detail page ("you'll also become a member
    of …"). Answered from the same facts
    ``membership_grant.ensure_membership_for_purchase`` uses, so the
    page does not promise something fulfilment would skip:

      * a Collective that computes its own membership
        (``auto_grant_role`` — World Builders and friends) joins nobody;
      * an already-active member joins nothing;
      * anyone else — including an anonymous visitor who has not signed
        in yet — would be joined.
    """
    if space.auto_grant_role is not None:
        return False
    if user is None:
        return True
    return not is_member(db, user_id=user.id, space_id=space.id)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def check_acquirable(
    db: Session, *,
    offering: Offering,
    space: Space,
    user: User | None,
    for_pricing: str | None = None,
) -> Acquirability:
    """Can this be acquired? Report, don't raise.

    Used by the detail endpoint to decide what the page offers.
    :func:`guard_acquirable` is the raising wrapper the write paths use.

    ``for_pricing`` pins the expected pricing kind — ``'free'`` from the
    free-acquisition endpoint, ``'one_time'`` from checkout. A mismatch
    is refused rather than silently redirected: a member who pressed
    "Get this Offering" on a page that said Free must not be charged
    because the price changed thirty seconds ago, and the reverse would
    hand away a paid file.
    """
    # ── Ownership is answered first, ahead of every gate ──────────
    #
    # Somebody who already owns this Offering is not asking to acquire
    # anything, so none of the refusals below apply to them — and
    # ``already_owned`` is deliberately not a refusal. Putting this
    # first is what lets the detail page keep working for an owner
    # whose Collective has left the pilot: the page reads this result,
    # and an owner must see their downloads rather than "not available
    # yet".
    #
    # It cannot become a way to acquire twice. ``already_owned`` carries
    # no permission — ``guard_acquirable`` raises only on ``refusal`` —
    # and every write path checks ownership explicitly before it gets
    # here: the Offering checkout wrapper and
    # ``guard_option_purchase`` both 409 on ``already_owned``, and
    # ``acquire_free`` returns the existing row without creating one.
    if user is not None and already_owns(
        db, user_id=user.id, offering_id=offering.id,
    ):
        return Acquirability(
            already_owned=True,
            approved_files=approved_file_count(db, offering.id),
        )

    # ── Pilot scope — for everybody who does NOT already own it ────
    #
    # New activity in a Collective outside the pilot is refused. This is
    # checked here as well as at the routes because this one function is
    # what all three write paths guard with: the free endpoint, the
    # Offering checkout wrapper and the unified checkout's
    # ``guard_option_purchase``. One rule, three doors.
    if not _pilot.offerings_available_for(space):
        return Acquirability(refusal=REASON_OUTSIDE_PILOT)

    if offering.status == OfferingStatus.retired.value:
        return Acquirability(refusal=REASON_RETIRED)
    if offering.status != OfferingStatus.published.value:
        return Acquirability(refusal=REASON_NOT_PUBLISHED)

    if offering.pricing_kind is None:
        return Acquirability(refusal=REASON_PRICING_UNSET)
    if for_pricing is not None and offering.pricing_kind != for_pricing:
        return Acquirability(refusal=REASON_WRONG_PRICING)

    # Nothing to download means nothing to acquire. Checked here rather
    # than only at publish time because a file can be quarantined by an
    # operator, or superseded by a replacement that is still being
    # validated, long after the Offering went live.
    files = approved_file_count(db, offering.id)
    if files == 0:
        return Acquirability(refusal=REASON_NO_FILES, approved_files=0)

    if offering.pricing_kind == OfferingPricingKind.one_time.value:
        refusal = _paid_refusal(db, offering=offering, space=space)
        if refusal is not None:
            return Acquirability(refusal=refusal, approved_files=files)

    return Acquirability(approved_files=files)


def _paid_refusal(
    db: Session, *, offering: Offering, space: Space,
) -> str | None:
    """Paid-only gates, in the order a creator would hit them.

    Plan eligibility is resolved against the **Collective's owner**, not
    the buyer — the same rule ``offering_readiness`` and
    ``guard_member_allowance`` use. A creator who downgrades to a plan
    without paid selling stops making new sales; every existing
    purchaser keeps their files, every entitlement stays active, and
    nothing is deleted. This function is the "stops making new sales"
    half, and it sits in backend authorisation rather than in the UI so
    hiding the button is a courtesy rather than the control.
    """
    from app.creator.plan_guards import is_platform_owner, resolve_creator_plan
    from app.services import offering_commerce

    owner = (
        db.query(User).filter(User.id == space.creator_id).first()
        if space.creator_id else None
    )
    if owner is not None and not is_platform_owner(owner):
        plan = resolve_creator_plan(owner, db)
        if plan is None or not plan.paid_offers_enabled:
            return REASON_PLAN_FORBIDS_PAID

    # The commerce rows must actually be able to take a payment. A
    # published Offering whose option was archived — or never
    # provisioned, for a row predating this phase — would otherwise
    # send the buyer to a checkout that 400s.
    option = offering_commerce.find_option(db, offering)
    if option is None:
        return REASON_NOT_SELLABLE
    schedule = offering_commerce.pay_in_full_schedule(db, option)
    rows = offering_commerce.CommerceRows(option, schedule)
    if not rows.sellable:
        return REASON_NOT_SELLABLE
    if (schedule.total_amount_cents or 0) != int(offering.price_cents or 0):
        # The projection is stale. Refusing is the conservative answer:
        # charging either figure would be charging a price the Offering
        # page did not state.
        logger.error(
            "offering_acquisition: price mismatch offering=%s (%s) "
            "schedule=%s (%s) — refusing purchase",
            offering.id, offering.price_cents,
            schedule.id, schedule.total_amount_cents,
        )
        return REASON_NOT_SELLABLE
    return None


def guard_acquirable(
    db: Session, *,
    offering: Offering,
    space: Space,
    user: User,
    for_pricing: str,
) -> Acquirability:
    """:func:`check_acquirable`, raising :class:`AcquisitionRefused`.

    ``already_owned`` is returned rather than raised — the caller
    decides whether that is an error (it is not) or a no-op (it is).
    """
    result = check_acquirable(
        db, offering=offering, space=space, user=user,
        for_pricing=for_pricing,
    )
    if result.refusal is not None:
        raise AcquisitionRefused(result.refusal)
    return result


def guard_option_purchase(
    db: Session, *, payment_option, user: User,
) -> None:
    """Apply the Offering rules to a purchase arriving by Payment Option.

    ``POST /api/checkout/offering`` resolves the Offering from its slugs
    and checks everything before delegating. This is the same check at
    the **other** entrance: ``POST /api/checkout`` takes a Payment
    Option id directly, and its own guards are option-shaped — they know
    about duplicate access passes and unfulfillable grant kinds, not
    about retired Offerings, quarantined files or a creator who has
    since downgraded.

    Nothing exposes an Offering's Payment Option id — the member payload
    is asserted not to, in
    ``test_offering_creator_studio::test_the_payload_never_names_the_commerce_rows``
    — so this is defence in depth rather than a reachable hole. It costs
    one query on a path that already makes several, and it means the
    rules live at the boundary rather than in whichever door happened to
    be used.

    A no-op for every non-Offering option, so Pathway and Gathering
    checkout are untouched.
    """
    from app.services.purchase_fulfilment import OFFERING_ATTACHES_KIND

    if payment_option.attaches_to_kind != OFFERING_ATTACHES_KIND:
        return

    offering = (
        db.query(Offering)
        .filter(Offering.id == payment_option.attaches_to_id)
        .first()
    )
    if offering is None:
        raise AcquisitionRefused(
            REASON_NOT_SELLABLE,
            "This Offering isn't available for purchase at the moment.",
        )
    space = db.query(Space).filter(Space.id == offering.space_id).first()
    if space is None:
        raise AcquisitionRefused(REASON_NOT_SELLABLE)

    if already_owns(db, user_id=user.id, offering_id=offering.id):
        raise AcquisitionRefused(
            REASON_ALREADY_OWNED,
            "This Offering is already in Your Collection.",
        )
    guard_acquirable(
        db, offering=offering, space=space, user=user,
        for_pricing=OfferingPricingKind.one_time.value,
    )


# ---------------------------------------------------------------------------
# The free path
# ---------------------------------------------------------------------------


def acquire_free(
    db: Session, *,
    offering: Offering,
    space: Space,
    user: User,
    now: datetime | None = None,
) -> AcquisitionOutcome:
    """Give this member the Offering. Free only, idempotent, atomic.

    Does **not** commit — the caller owns the transaction, so the
    entitlement and the membership land together or not at all. That
    atomicity is the point: a member who owns a file but was never
    joined, or was joined without receiving the file, are both states
    somebody then has to repair by hand.

    Re-running is safe and returns ``created=False``.
    """
    now = now or datetime.utcnow()
    guard_acquirable(
        db, offering=offering, space=space, user=user,
        for_pricing=OfferingPricingKind.free.value,
    )

    existing = (
        db.query(OfferingEntitlement)
        .filter(
            OfferingEntitlement.user_id == user.id,
            OfferingEntitlement.offering_id == offering.id,
            OfferingEntitlement.status
            == OfferingEntitlementStatus.active.value,
        )
        .first()
    )
    if existing is not None:
        # Already theirs. Membership is still ensured — somebody who
        # acquired and then left should be back in the Collective if
        # they press the button again, and the helper's own rules decide
        # whether that is appropriate.
        outcome = _membership_grant.ensure_membership_for_purchase(
            db, user_id=user.id, space_id=space.id, now=now,
        )
        return AcquisitionOutcome(
            entitlement=existing, created=False,
            joined_collective=outcome.changed,
            membership_first_time=outcome.created,
        )

    ent = OfferingEntitlement(
        id=str(uuid4()),
        user_id=user.id,
        offering_id=offering.id,
        space_id=space.id,
        source=OfferingEntitlementSource.free.value,
        status=OfferingEntitlementStatus.active.value,
        # No payment, so no ledger row to point at. The column is
        # nullable precisely for this.
        payment_transaction_id=None,
        acquired_at=now,
        created_at=now,
        updated_at=now,
    )
    # No savepoint, and no ``try`` around this: if the partial unique
    # index refuses the row, the ``IntegrityError`` is allowed to reach
    # the caller.
    #
    # That is deliberate, and it is where the recovery belongs. This
    # function does not own the transaction — the route does — so it is
    # not this function's business to decide what survives a rollback.
    # The route catches the error, rolls back the request's transaction
    # and calls this function once more; the read above then finds the
    # winning row and returns ``created=False``. One retry, and the
    # recovery lives with the transaction it is recovering.
    db.add(ent)
    db.flush()

    # Automatic Collective membership — a firm product decision, and the
    # same helper every paid path uses. It declines to overturn a
    # ``paused`` row, an invited row or a Collective that manages its own
    # membership, which is how "join automatically" coexists with access
    # controls the platform set deliberately.
    membership = _membership_grant.ensure_membership_for_purchase(
        db, user_id=user.id, space_id=space.id, now=now,
    )

    logger.info(
        "offering_acquisition: free acquisition entitlement=%s user=%s "
        "offering=%s space=%s joined=%s",
        ent.id, user.id, offering.id, space.id, membership.changed,
    )
    return AcquisitionOutcome(
        entitlement=ent, created=True,
        joined_collective=membership.changed,
        membership_first_time=membership.created,
    )


__all__ = [
    "Acquirability",
    "AcquisitionOutcome",
    "AcquisitionRefused",
    "REASON_ALREADY_OWNED",
    "REASON_NOT_PUBLISHED",
    "REASON_OUTSIDE_PILOT",
    "REASON_NOT_SELLABLE",
    "REASON_NO_FILES",
    "REASON_PLAN_FORBIDS_PAID",
    "REASON_PRICING_UNSET",
    "REASON_RETIRED",
    "REASON_WRONG_PRICING",
    "acquire_free",
    "already_owns",
    "approved_file_count",
    "check_acquirable",
    "guard_acquirable",
    "guard_option_purchase",
    "is_member",
    "will_join_collective",
]
