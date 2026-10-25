"""Ending a membership — one place, two callers.

The mirror of :mod:`app.services.membership_grant`. That module answers
"did this make me a member?"; this one answers "what happens when the
membership ends?", for the two reasons it can end:

* a creator removes somebody (moderation) — ``creator.routes.remove_member``;
* a member leaves of their own accord — ``spaces.routes.leave_collective``.

Both write ``SpaceMembership.status = removed``, and that single write
is what actually closes the doors: ``services.space_viewer`` requires an
``active`` row, so every area gate, Channel read, member listing and
"included with membership" Pathway re-decides on the next request. There
is no cached membership to invalidate and no page that keeps working
because it was already open.

Why the two callers differ
--------------------------

They differ on exactly one question: **may this operation destroy
something the person paid for?**

A creator removing a member is a moderation act, and the behaviour
below is what ``remove_member`` has always done — revoke every active
entitlement, cancel every pass, cancel future bookings. That is
preserved verbatim; this module did not get to re-decide it.

A member leaving is not moderation, and voluntarily walking out of a
room is not consent to forfeit what you bought on the way in. So
self-departure takes the conservative option on every paid artefact:

    ============================  =============  ==================
    Artefact                      Creator        Self-departure
    ============================  =============  ==================
    SpaceMembership               removed        removed
    PathwayEntitlement (granted)  revoked        revoked
    PathwayEntitlement (bought)   revoked        **preserved**
    AccessPass                    cancelled      **preserved**
    Future EventBooking           cancelled      **preserved**
    OfferingEntitlement           untouched      untouched
    PurchasePlan / Stripe         untouched      untouched
    StepProgress                  untouched      untouched
    ============================  =============  ==================

``manual_grant`` entitlements are revoked in both cases: a creator's
gift to a member is membership-dependent by nature, and no money
changed hands.

What this module deliberately does not do
-----------------------------------------

**It never speaks to Stripe.** Not to cancel a SubscriptionSchedule,
not to refund, not to alter a schedule. ``PurchasePlan`` rows are left
exactly as they are, which is why the self-service caller must refuse
to run at all while one is live — see
:func:`live_payment_plan_count`. Revoking access while a card is still
being charged is the one outcome nobody chose, so the endpoint stops
rather than create it.

Known issue — creator removal can revoke access while billing continues
-----------------------------------------------------------------------

**Deliberately not fixed here; carried as a separate piece of work.**

``creator.routes.remove_member`` has never consulted ``purchase_plans``,
and this module did not change that. So a creator removing a member who
is mid-way through a finite instalment plan revokes their access and
cancels their bookings while the Stripe ``SubscriptionSchedule`` keeps
collecting the remaining instalments. The member pays for access they no
longer have, and nothing in the product tells either party.

Scope of the exposure:

* only ``purchase_plans`` rows in ``LIVE_PLAN_STATUSES`` — a pay-in-full
  purchase has nothing left to collect;
* the member keeps no access in exchange, because moderation removal
  revokes entitlements and cancels passes;
* it predates self-departure and is unaffected by it. The
  member-initiated path refuses outright in this situation (see
  ``spaces.routes.leave_collective``), which is why the two callers
  differ on a payment question at all.

The remedy is not in doubt — ``services.finite_plan_lifecycle``
already has ``cancel_plan_by_admin``, which cancels the schedule
provider-first, revokes the plan's grant records and releases
plan-dependent bookings without issuing a refund. Wiring it into
creator removal is a payment change and needs its own approval, so
``remove_member`` is left as it was rather than quietly acquiring a
Stripe call.

Nor does it record *who* ended the membership. ``SpaceMembership`` has
no column for that, which is the gap
``membership_grant.REACTIVATABLE_SOURCES`` already names: a later
purchase restores a ``removed`` row whose ``source`` the buyer chose,
and it cannot tell a departure from a removal. Closing that needs a
migration and a decision about creator moderation, so it is not taken
here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.offering import OfferingEntitlement, OfferingEntitlementStatus
from app.spaces import retained_reservations as _retained
from app.models.platform import (
    BookingStatus,
    EntitlementSource,
    EntitlementStatus,
    Event,
    EventBooking,
    PathwayEntitlement,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

logger = logging.getLogger(__name__)

#: ``PurchasePlan`` statuses that mean Stripe may still charge this
#: member. ``pending_setup`` / ``active`` / ``payment_problem`` is the
#: set ``checkout_orchestration`` already calls "active-ish" when it
#: refuses a duplicate plan.
#:
#: ``suspended`` is added here and deliberately so. Its own docstring
#: says re-entry to ``active`` is possible "if Stripe collects the
#: outstanding invoice while the SubscriptionSchedule is still
#: provider-live" — so a suspended plan is a schedule that can wake up.
#: For refusing to take somebody's access away, "might still charge" is
#: the question, not "is charging right now".
LIVE_PLAN_STATUSES: tuple[str, ...] = (
    "pending_setup", "active", "payment_problem", "suspended",
)

#: Why a membership ended. Written to
#: ``space_memberships.removal_kind`` (migration 166) and read by
#: ``membership_grant.may_rejoin`` to decide whether somebody may come
#: back. ``source`` says how a membership began; this says how it ended,
#: and only the second question answers "may they return?".
#:
#: Mirrored by a CHECK constraint, so a new removal path that invents a
#: value fails at the database instead of being read as "not voluntary"
#: by accident.
REMOVAL_VOLUNTARY = "voluntary"
REMOVAL_BY_CREATOR = "creator"
REMOVAL_BY_ADMIN = "admin"
REMOVAL_BY_AUTO_ROLE = "auto_role"

REMOVAL_KINDS: tuple[str, ...] = (
    REMOVAL_VOLUNTARY,
    REMOVAL_BY_CREATOR,
    REMOVAL_BY_ADMIN,
    REMOVAL_BY_AUTO_ROLE,
)

#: The creator's choice field. Mirrored by a CHECK constraint.
#:
#: None of these implies a ban. That is the point of keeping them in a
#: separate column from ``rejoin_blocked``: a creator helping somebody
#: leave picks ``member_requested``, a creator barring somebody picks
#: whichever reason fits and *also* decides to block. Reading a ban off
#: the reason would mean "Inappropriate behaviour" silently barring
#: people the creator meant to let back.
REASON_MEMBER_REQUESTED = "member_requested"
REASON_NO_LONGER_REQUIRED = "no_longer_required"
REASON_INAPPROPRIATE_BEHAVIOUR = "inappropriate_behaviour"
REASON_PAYMENT_ISSUES = "payment_issues"
REASON_OTHER = "other"

REMOVAL_REASONS: tuple[str, ...] = (
    REASON_MEMBER_REQUESTED,
    REASON_NO_LONGER_REQUIRED,
    REASON_INAPPROPRIATE_BEHAVIOUR,
    REASON_PAYMENT_ISSUES,
    REASON_OTHER,
)

#: The only reason that may proceed past a live instalment plan. Urgent
#: behaviour removals cannot be made to wait on billing; everything
#: else can and must. See ``RemovalDecision.may_override_live_plan``.
URGENT_REASONS: frozenset[str] = frozenset({REASON_INAPPROPRIATE_BEHAVIOUR})

#: Ledger actions for ``MembershipRestrictionEvent``.
RESTRICTION_BLOCKED = "blocked"
RESTRICTION_UNBLOCKED = "unblocked"


class RemovalDecisionError(ValueError):
    """The removal as described is not a decision the platform allows."""


@dataclass(frozen=True)
class RemovalDecision:
    """What a creator (or the member, or the platform) decided.

    Grouped rather than passed as five loose arguments because the
    fields constrain each other, and the constraints are the product
    rules — so they are checked once, here, instead of at each call
    site:

    * a block needs a written explanation. It is the consequential,
      creator-only decision and the note is the only record of why;
    * a block is a creator's decision. A voluntary departure cannot
      carry one (nobody bans themselves), and the automatic sweep has
      no opinion;
    * the reason never implies the block, in either direction.
    """

    kind: str
    reason: str | None = None
    note: str | None = None
    rejoin_blocked: bool = False

    def __post_init__(self) -> None:
        if self.kind not in REMOVAL_KINDS:
            raise RemovalDecisionError(
                f"removal kind must be one of {REMOVAL_KINDS}, "
                f"got {self.kind!r}",
            )
        if self.reason is not None and self.reason not in REMOVAL_REASONS:
            raise RemovalDecisionError(
                f"removal reason must be one of {REMOVAL_REASONS}, "
                f"got {self.reason!r}",
            )
        if self.rejoin_blocked:
            if self.kind != REMOVAL_BY_CREATOR:
                raise RemovalDecisionError(
                    "only a creator removal may block rejoining",
                )
            if not (self.note or "").strip():
                raise RemovalDecisionError(
                    "blocking rejoining requires a written explanation",
                )

    @property
    def may_override_live_plan(self) -> bool:
        """Whether this removal may proceed while Stripe is still
        collecting instalments.

        True only for an urgent behaviour removal. Everything else is
        refused until the payment arrangement is resolved, because an
        ordinary tidy-up is never worth leaving somebody paying for
        access they no longer have. Safety is: a creator must be able
        to act on behaviour immediately, and billing must not be the
        thing that stops them.
        """
        return self.reason in URGENT_REASONS

#: Entitlement sources that represent a creator's gift rather than a
#: purchase. Revoked on self-departure; everything else is kept.
GRANTED_SOURCES: frozenset[EntitlementSource] = frozenset({
    EntitlementSource.manual_grant,
})

#: Roles that make somebody a caretaker of the Collective rather than a
#: member of it. They do not leave through the member-facing door —
#: stepping back from running a place is a different operation, with
#: different consequences for the place.
CARETAKER_ROLES: frozenset[SpaceRole] = frozenset({
    SpaceRole.creator, SpaceRole.moderator,
})


@dataclass(frozen=True)
class RemovalOutcome:
    """What the operation actually changed."""

    entitlements_revoked: int = 0
    passes_cancelled: int = 0
    bookings_cancelled: int = 0


@dataclass(frozen=True)
class DepartureConsequences:
    """What leaving would mean for one member of one Collective.

    Built so the confirmation dialog can state consequences instead of
    guessing at them. Every count is scoped to this Collective except
    ``offerings_retained``, which is the reassurance and is therefore
    also scoped here — "what you keep from *this* place".
    """

    #: Blocks departure outright. See ``LIVE_PLAN_STATUSES``.
    live_payment_plans: int = 0
    #: Paid passes that survive but whose Collective doorway closes.
    active_passes: int = 0
    #: Unused credits on those passes, when any are credit-based.
    unused_credits: int = 0
    #: Future confirmed bookings. Not cancelled, not refunded.
    future_bookings: int = 0
    #: Of those, the ones the member paid for — a standalone ticket or a
    #: session reserved against a pass they bought. These stay both
    #: preserved AND reachable after departure, through the
    #: per-reservation exception in ``spaces.retained_reservations``.
    #: The remainder came with membership and go with it, so the dialog
    #: has to describe the two groups differently.
    purchased_future_bookings: int = 0
    #: Purchased Pathway access that survives the departure.
    purchased_pathways: int = 0
    #: Purchased Pathway access that does NOT survive, because the
    #: platform gates ``included_with_offer`` on active membership.
    membership_gated_paid_pathways: int = 0
    #: Offerings kept in Your Collection. Always kept; counted so the
    #: dialog can say how many rather than make a bare promise.
    offerings_retained: int = 0

    @property
    def can_leave(self) -> bool:
        return self.live_payment_plans == 0


def live_payment_plan_count(
    db: Session, *, user_id: str, space_id: str,
) -> int:
    """Plans in this Collective that Stripe may still charge.

    Raw SQL for the same reason ``checkout_orchestration`` uses it for
    the sibling check: ``purchase_plans`` is read here by status string
    and importing the model would pull the finite-plan package into the
    membership path for one count.
    """
    from sqlalchemy import text

    placeholders = ", ".join(f":s{i}" for i in range(len(LIVE_PLAN_STATUSES)))
    params: dict[str, object] = {"uid": user_id, "sid": space_id}
    for i, value in enumerate(LIVE_PLAN_STATUSES):
        params[f"s{i}"] = value
    row = db.execute(
        text(
            "SELECT count(*) FROM purchase_plans "
            "WHERE member_user_id = :uid AND space_id = :sid "
            f"AND status IN ({placeholders})"
        ),
        params,
    ).scalar()
    return int(row or 0)


def live_plans_by_member(
    db: Session, *, space_id: str,
) -> dict[str, str]:
    """``{member_user_id: plan_id}`` for plans Stripe may still charge
    in this Collective.

    One query for a whole page of removed people, rather than a count
    per row. Returns at most one plan id per member — the warning asks
    "is there something outstanding", and a creator with two live plans
    for the same person still only needs taking to the same page.

    Why this exists rather than reading a stored flag
    ------------------------------------------------

    ``SpaceMembership.payment_action_required`` records that a removal
    *was taken* while a plan was collecting. That is audit: it happened,
    the creator acknowledged it, and it stays true forever.

    Whether the money is *still* outstanding is a different question,
    and a stored boolean is the wrong shape for it — it would have to be
    cleared by whoever ended the plan, and the plan can end in at least
    four ways: the creator cancels it, an administrator cancels it, it
    completes naturally, or Stripe's retries exhaust and it fails. A
    flag cleared by only some of those paths is worse than no flag,
    because it reads as "resolved" when it is not.

    So the warning is derived, here, from the plans themselves. It
    cannot drift, it needs no clearing logic, it covers every way a plan
    can end including ones nobody anticipated, and a *failed*
    cancellation leaves the plan live and therefore the warning
    standing — which is exactly the required behaviour.
    """
    from sqlalchemy import text

    placeholders = ", ".join(f":s{i}" for i in range(len(LIVE_PLAN_STATUSES)))
    params: dict[str, object] = {"sid": space_id}
    for i, value in enumerate(LIVE_PLAN_STATUSES):
        params[f"s{i}"] = value
    rows = db.execute(
        text(
            "SELECT member_user_id, id FROM purchase_plans "
            "WHERE space_id = :sid "
            f"AND status IN ({placeholders}) "
            "ORDER BY created_at"
        ),
        params,
    ).all()
    out: dict[str, str] = {}
    for member_user_id, plan_id in rows:
        out.setdefault(member_user_id, plan_id)
    return out


def summarise_departure(
    db: Session, *, user_id: str, space_id: str, now: datetime,
) -> DepartureConsequences:
    """Read-only. What leaving this Collective would cost and keep."""
    passes = (
        db.query(AccessPass)
        .filter(
            AccessPass.user_id == user_id,
            AccessPass.space_id == space_id,
            AccessPass.status.in_(
                [AccessPassStatus.active, AccessPassStatus.pending],
            ),
        )
        .all()
    )
    unused = 0
    for ap in passes:
        remaining = ap.remaining_credits
        if remaining:
            unused += remaining

    future_booking_rows = (
        db.query(EventBooking, Event)
        .join(Event, Event.id == EventBooking.event_id)
        .filter(
            EventBooking.user_id == user_id,
            EventBooking.status == BookingStatus.confirmed,
            Event.space_id == space_id,
            Event.starts_at > now,
        )
        .all()
    )
    future_bookings = len(future_booking_rows)
    purchased_future_bookings = sum(
        1 for booking, event in future_booking_rows
        if _retained.is_purchased_booking(booking, event)
    )

    entitlements = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.space_id == space_id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .all()
    )
    purchased = sum(1 for e in entitlements if e.source not in GRANTED_SOURCES)

    offerings = (
        db.query(OfferingEntitlement)
        .filter(
            OfferingEntitlement.user_id == user_id,
            OfferingEntitlement.space_id == space_id,
            OfferingEntitlement.status
            == OfferingEntitlementStatus.active.value,
        )
        .count()
    )

    return DepartureConsequences(
        live_payment_plans=live_payment_plan_count(
            db, user_id=user_id, space_id=space_id,
        ),
        active_passes=len(passes),
        unused_credits=unused,
        future_bookings=future_bookings,
        purchased_future_bookings=purchased_future_bookings,
        purchased_pathways=purchased,
        membership_gated_paid_pathways=_membership_gated_paid_pathways(
            db, user_id=user_id, space_id=space_id,
        ),
        offerings_retained=offerings,
    )


def _membership_gated_paid_pathways(
    db: Session, *, user_id: str, space_id: str,
) -> int:
    """Paid Pathway access this member loses by leaving.

    ``included_with_offer`` is the one access type whose unlock is paid
    for but whose gate still reads active membership — see the branch in
    ``spaces.routes._check_pathway_access``, which requires a member row
    *and* an unlock. Leaving therefore closes a Pathway the member
    bought an offer to reach, and the dialog has to say so rather than
    let them find out.
    """
    from app.models.platform import Pathway

    if not db.query(AccessPass.id).filter(
        AccessPass.user_id == user_id,
        AccessPass.space_id == space_id,
        AccessPass.status == AccessPassStatus.active,
    ).first():
        return 0
    return (
        db.query(Pathway)
        .filter(
            Pathway.space_id == space_id,
            Pathway.access_type == "included_with_offer",
            Pathway.status.in_(["active", "coming_soon"]),
        )
        .count()
    )


def end_membership(
    db: Session, *,
    membership: SpaceMembership,
    space: Space,
    actor_user_id: str | None,
    now: datetime,
    decision: RemovalDecision,
    revoke_purchased_access: bool,
    cancel_passes: bool,
    cancel_future_bookings: bool,
    note: str,
    payment_action_required: bool = False,
) -> RemovalOutcome:
    """End one membership. Writes without committing — the caller owns
    the transaction, because membership and the access that follows from
    it must land together or not at all.

    The three booleans are the creator/member difference made explicit
    rather than inferred from the actor, so each caller states what it
    is allowed to destroy and a reader can see both answers in one
    place. See the table in the module docstring.

    ``decision`` is required rather than defaulted. A default would have
    to be one of "voluntary" or "creator", and either choice makes a new
    caller that forgets to pass it silently wrong in a way that either
    reverses moderation or traps a member who left — so there is nothing
    to forget. It validates itself; see ``RemovalDecision``.
    """
    membership.status = SpaceMembershipStatus.removed
    membership.removal_kind = decision.kind
    membership.removal_reason = decision.reason
    membership.removal_note = decision.note
    membership.rejoin_blocked = decision.rejoin_blocked
    membership.removed_at = now
    membership.removed_by_user_id = actor_user_id
    # Only ever set here, never cleared here — resolving the payment is
    # a separate action by a person, not a side effect of a removal.
    if payment_action_required:
        membership.payment_action_required = True

    if decision.rejoin_blocked:
        record_restriction_event(
            db,
            space_id=space.id,
            user_id=membership.user_id,
            action=RESTRICTION_BLOCKED,
            actor_user_id=actor_user_id,
            note=decision.note,
            now=now,
        )

    entitlement_q = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == membership.user_id,
            PathwayEntitlement.space_id == space.id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
    )
    entitlements = entitlement_q.all()
    if not revoke_purchased_access:
        entitlements = [e for e in entitlements if e.source in GRANTED_SOURCES]
    for ent in entitlements:
        ent.status = EntitlementStatus.revoked
        ent.revoked_by_user_id = actor_user_id
        ent.revoked_at = now
        ent.notes = (ent.notes or "") + f" [{note}]"

    passes_cancelled = 0
    if cancel_passes:
        active_passes = (
            db.query(AccessPass)
            .filter(
                AccessPass.user_id == membership.user_id,
                AccessPass.space_id == space.id,
                AccessPass.status.in_(
                    [AccessPassStatus.active, AccessPassStatus.pending],
                ),
            )
            .all()
        )
        for ap in active_passes:
            ap.status = AccessPassStatus.cancelled
            ap.revoked_by_user_id = actor_user_id
            ap.revoked_at = now
        passes_cancelled = len(active_passes)

    bookings_cancelled = 0
    if cancel_future_bookings:
        future_bookings = (
            db.query(EventBooking)
            .join(Event, Event.id == EventBooking.event_id)
            .filter(
                EventBooking.user_id == membership.user_id,
                EventBooking.status == BookingStatus.confirmed,
                Event.space_id == space.id,
                Event.starts_at > now,
            )
            .all()
        )
        for booking in future_bookings:
            booking.status = BookingStatus.cancelled
            booking.cancelled_at = now
        bookings_cancelled = len(future_bookings)

    return RemovalOutcome(
        entitlements_revoked=len(entitlements),
        passes_cancelled=passes_cancelled,
        bookings_cancelled=bookings_cancelled,
    )


def is_banned(db: Session, *, user_id: str, space_id: str) -> bool:
    """Whether this person is barred from this Collective.

    The Rule F predicate. Asked before **every** acquisition from the
    Collective — paid or free, Offering or Pathway or Gathering ticket —
    which is what separates a ban from an ordinary removal: an
    ordinarily-removed person may still buy whatever does not need
    membership, and a banned person may buy nothing here at all.

    Reads the flag rather than inferring anything from ``removal_kind``
    or ``removal_reason``. A ban is an explicit decision and this is the
    column that records it.
    """
    return (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.rejoin_blocked.is_(True),
        )
        .first()
        is not None
    )


def record_restriction_event(
    db: Session, *,
    space_id: str,
    user_id: str,
    action: str,
    actor_user_id: str | None,
    note: str | None,
    now: datetime,
) -> None:
    """Append to the restriction ledger. Writes without committing."""
    from uuid import uuid4

    from app.models.platform import MembershipRestrictionEvent

    if action not in (RESTRICTION_BLOCKED, RESTRICTION_UNBLOCKED):
        raise RemovalDecisionError(f"unknown restriction action {action!r}")
    db.add(MembershipRestrictionEvent(
        id=str(uuid4()),
        space_id=space_id,
        user_id=user_id,
        action=action,
        actor_user_id=actor_user_id,
        note=note,
        created_at=now,
    ))


def lift_restriction(
    db: Session, *,
    membership: SpaceMembership,
    actor_user_id: str,
    note: str | None,
    now: datetime,
) -> None:
    """Clear a rejoin block, leaving a record that it was cleared.

    **Does not restore membership.** The person becomes free to rejoin
    or to buy their way back in; whether they do is theirs to decide.
    Nor does it restore anything that was revoked when they were
    removed — see ``membership_grant.reactivate`` for why reviving
    cancelled passes and bookings would be wrong.

    ``removal_kind`` and ``removal_reason`` are deliberately left as
    they are: the removal still happened for the reason recorded, and
    overwriting that history to say "unblocked" would lose it. The
    ledger carries the change.
    """
    membership.rejoin_blocked = False
    record_restriction_event(
        db,
        space_id=membership.space_id,
        user_id=membership.user_id,
        action=RESTRICTION_UNBLOCKED,
        actor_user_id=actor_user_id,
        note=note,
        now=now,
    )


__all__ = [
    "CARETAKER_ROLES",
    "REASON_INAPPROPRIATE_BEHAVIOUR",
    "REASON_MEMBER_REQUESTED",
    "REASON_NO_LONGER_REQUIRED",
    "REASON_OTHER",
    "REASON_PAYMENT_ISSUES",
    "REMOVAL_BY_ADMIN",
    "REMOVAL_BY_AUTO_ROLE",
    "REMOVAL_BY_CREATOR",
    "REMOVAL_KINDS",
    "REMOVAL_REASONS",
    "REMOVAL_VOLUNTARY",
    "RESTRICTION_BLOCKED",
    "RESTRICTION_UNBLOCKED",
    "RemovalDecision",
    "RemovalDecisionError",
    "URGENT_REASONS",
    "DepartureConsequences",
    "GRANTED_SOURCES",
    "LIVE_PLAN_STATUSES",
    "RemovalOutcome",
    "end_membership",
    "is_banned",
    "lift_restriction",
    "record_restriction_event",
    "live_payment_plan_count",
    "live_plans_by_member",
    "summarise_departure",
]
