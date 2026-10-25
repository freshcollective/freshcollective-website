"""Membership that arrives with a purchase.

One helper, used by every fulfilment path, so "did buying this make me
a member?" has the same answer whether the person bought a term pass, a
Pathway, a Series, or a single Gathering ticket.

Reactivation, and why it is narrow
----------------------------------

``SpaceMembership.status`` has three values — ``active``, ``paused``,
``removed`` — and there is no separate banned state. That sounds like
``removed`` is safe to reverse. It is not, because three very different
decisions all write it:

* a creator removing a member (``creator.routes.remove_member``) —
  moderation;
* an admin revoking a fraudulent or disputed purchase
  (``admin.access_revocation``), which already limits itself to rows
  with ``source='purchase'`` precisely to avoid disturbing invited,
  self-joined, owner and platform-granted rows;
* the auto-grant sweep (``services.creator_eligibility``) when someone
  stops being an eligible creator — this writes ``paused`` and
  ``removed`` on World Builders-style Collectives.

The row itself records no provenance for its own removal, so the rule
here is drawn from ``source`` — what brought the membership into
existence — and kept deliberately narrow:

* **no row** → create one;
* **active** → leave it completely alone, including its ``source``;
* **removed**, and the source is one a person chose for themselves
  (``joined``) or one a purchase created (``purchase``,
  ``ticket_purchase``, ``stripe_paid``) → reactivate. They bought their
  way back in;
* **paused**, or any other source (``auto_role``, ``creator_owner``,
  ``invited``, ``manual``, ``manual_grant``, ``creator_pass``,
  ``template``) → leave untouched and report it. Those states are held
  by the platform or by a person's decision, and a card being charged
  is not consent to overturn either.

A Collective that manages its own membership (``auto_grant_role``) is
never touched at all.

A refused reactivation, and who stops it reaching here
------------------------------------------------------

``checkout_orchestration.check_membership_deliverable_or_raise``
(Rule E) refuses, before any payment is taken, the two purchases that
cannot be delivered without membership. So the refusal below should not
normally be reached by somebody who has just paid; when it is, the
cause is eligibility changing while the buyer was inside Stripe
Checkout, and the branch logs at ERROR for exactly that reason.

The purchase itself still fulfils — that is deliberate, because
refusing a membership is not grounds for taking payment and delivering
nothing. The two kinds Rule E refuses up front are:

* **paying to join a ``purchase_required`` Collective.** Membership
  *was* the product. Verified: the buyer is charged and
  ``skipped_reason='removal_creator'`` is returned.
* **an offer that includes Pathway access.** The
  ``included_with_offer`` branch of
  ``spaces.routes._check_pathway_access`` requires an active membership
  alongside the unlock, so the Pathway stays shut (403) even though the
  offer was paid for.

Anything that does not read membership is delivered normally — a
``one_time`` Pathway entitlement, an Offering, a standalone Gathering
ticket, a term pass.

Note the direction of the trade. Before removal provenance existed this
case "worked", in that buying again silently reinstated a removed
member — which is precisely the moderation bypass this release closes.
Rule E is the other half: refuse the *checkout* rather than take
payment and then decline.

Removal provenance (migration 166) closed the gap this docstring used
to describe. ``source`` still says how a membership *began*, and the
rule above still reads it — but it is no longer the only question.
``space_memberships.removal_kind`` now says how the membership *ended*,
and :func:`may_rejoin` requires it to be ``voluntary`` before any path
restores a row. So a creator's removal is no longer reversible by
buying again, and a historical ``removed`` row whose provenance was
never recorded (``removal_kind IS NULL``) stays refused rather than
being assumed harmless.

The two conditions are both necessary and do different work:
``REACTIVATABLE_SOURCES`` asks "was this a relationship the person
chose?", ``may_rejoin`` asks "may this ending be reversed?". A
membership an admin revoked for fraud fails the second while passing
the first, which is exactly the case the first could not catch.

A creator removal is admitted or refused by ``rejoin_blocked``, which
the creator sets explicitly when they remove somebody. Most removals
are administrative and let the person back; a ban is the exception and
has to be chosen, with a written reason. See
``services.membership_removal.RemovalDecision``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus

logger = logging.getLogger(__name__)

#: Sources whose ``removed`` rows a later purchase may restore. Every
#: one of these came from the buyer's own action — joining, or paying.
REACTIVATABLE_SOURCES: frozenset[str] = frozenset({
    "joined", "purchase", "ticket_purchase", "stripe_paid",
})

#: What this service writes when it creates a row.
PURCHASE_SOURCE = "purchase"


def may_rejoin(membership: SpaceMembership) -> bool:
    """Whether this ``removed`` membership may be restored.

    The one rule, read by both restoring paths — the free Join button
    (``spaces.routes.join_space``) and a purchase
    (:func:`ensure_membership_for_purchase`) — so a person cannot get
    back in through one door after being refused at the other.

    **Allow-list, not a deny-list.** It requires ``voluntary``
    explicitly rather than excluding ``creator``, and that asymmetry is
    the whole point:

    * a historical removal from before migration 166 has
      ``removal_kind IS NULL``. We do not know what it was. Refusing it
      keeps every moderation decision that was never written down in
      force, and the person it wrongly catches can be re-added by the
      creator — which now works. The opposite default would silently
      reverse removals nobody can reconstruct.
    * a future removal path that forgets to stamp a kind, or invents a
      new one, reads as "not voluntary" and refuses. The failure mode
      of this predicate is a member who has to ask, never a removal
      that quietly undoes itself.

    A ``paused`` or ``active`` row is not this function's business —
    callers check status first.
    """
    from app.services.membership_removal import (
        REMOVAL_BY_CREATOR,
        REMOVAL_VOLUNTARY,
    )

    kind = membership.removal_kind or None
    if kind == REMOVAL_VOLUNTARY:
        # They chose to go. Nobody barred them.
        return True
    if kind == REMOVAL_BY_CREATOR:
        # A creator removal is not automatically a ban — most are
        # administrative tidying, and the creator says which when they
        # remove somebody. ``rejoin_blocked`` is that decision; the
        # reason recorded alongside it deliberately does not imply it.
        return not bool(membership.rejoin_blocked)
    # ``admin`` (a revoked, disputed purchase), ``auto_role`` (platform
    # eligibility, not a choice), and NULL (historical, unknown) all
    # refuse. Of those, NULL is the one that matters most: see the
    # allow-list note above.
    return False


@dataclass(frozen=True)
class MembershipOutcome:
    """What happened, in terms a caller can log or return."""

    created: bool = False
    reactivated: bool = False
    #: Present when an existing row was deliberately left alone —
    #: names the state so the caller can say why nothing changed.
    skipped_reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.created or self.reactivated


def ensure_membership_for_purchase(
    db: Session, *,
    user_id: str,
    space_id: str,
    now: datetime,
    source: str = PURCHASE_SOURCE,
) -> MembershipOutcome:
    """Make the buyer a member, if that is the right thing to do.

    Writes into the caller's session without committing — fulfilment
    owns the transaction, and membership must land or not land with the
    access it accompanies.
    """
    space = db.query(Space).filter(Space.id == space_id).first()
    if space is not None and space.auto_grant_role is not None:
        # World Builders and friends: membership is computed from
        # platform eligibility, not bought.
        return MembershipOutcome(skipped_reason="auto_managed_collective")

    existing = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == user_id,
        )
        .first()
    )

    if existing is None:
        db.add(SpaceMembership(
            id=str(uuid4()),
            space_id=space_id,
            user_id=user_id,
            role="learner",
            status=SpaceMembershipStatus.active,
            source=source,
            joined_at=now,
        ))
        logger.info(
            "membership_grant: joined user=%s space=%s source=%s",
            user_id, space_id, source,
        )
        return MembershipOutcome(created=True)

    status = (
        existing.status.value
        if hasattr(existing.status, "value") else str(existing.status)
    )
    if status == SpaceMembershipStatus.active.value:
        return MembershipOutcome(skipped_reason="already_active")

    if status != SpaceMembershipStatus.removed.value:
        # ``paused`` today; anything new tomorrow. Unknown states are
        # left alone rather than guessed at.
        return MembershipOutcome(skipped_reason=f"status_{status}")

    if (existing.source or "") not in REACTIVATABLE_SOURCES:
        return MembershipOutcome(skipped_reason=f"source_{existing.source}")

    if not may_rejoin(existing):
        # A card being charged is not consent to overturn a creator's
        # moderation, and it never was — this is the gap the module
        # docstring used to name. The purchase itself is NOT reversed
        # here: whatever was bought is still granted, because refusing
        # to restore a membership is not grounds for taking payment and
        # giving nothing. What the buyer does not get back is
        # membership, and the access that only membership confers.
        # ERROR, not info. By the time this function is called a
        # purchase has already been fulfilled, so a refusal here means
        # somebody has paid and has not become a member. Checkout
        # Rule E refuses this case up front, which leaves one way to
        # reach it: eligibility changed while the buyer was inside
        # Stripe — a creator removing them mid-Checkout. Nothing can be
        # safely automated in response (a refund is an operator's
        # decision, not a webhook's), so it is reported loudly enough
        # for somebody to act on.
        logger.error(
            "membership_grant: PAID BUT NOT ADMITTED — user=%s space=%s "
            "removal_kind=%s. A purchase fulfilled but membership was "
            "refused; eligibility changed after checkout began. Needs a "
            "human decision: readmit the buyer, or refund via Stripe.",
            user_id, space_id, existing.removal_kind,
        )
        return MembershipOutcome(
            skipped_reason=(
                # A block is reported as a block rather than as its
                # kind. Both refuse, but only one is something a creator
                # can lift, and a caller reading the outcome should be
                # able to tell them apart.
                "rejoin_blocked" if existing.rejoin_blocked
                else f"removal_{existing.removal_kind or 'unknown'}"
            ),
        )

    reactivate(existing, now=now)
    logger.info(
        "membership_grant: reactivated user=%s space=%s original_source=%s",
        user_id, space_id, existing.source,
    )
    return MembershipOutcome(reactivated=True)


def reactivate(membership: SpaceMembership, *, now: datetime) -> None:
    """Bring a ``removed`` membership back, in place.

    Reactivation rather than a fresh row, and not only because
    ``space_memberships_user_space_unique`` spans every status and would
    refuse the insert. The row carries history worth keeping —
    ``joined_at``, ``source``, the record that this person was here
    before — and a replacement row would throw all of it away to say
    something the old row already says.

    ``joined_at`` is deliberately NOT restamped: it records when the
    relationship began, which has not changed. The provenance of the
    departure is cleared, because there is no longer a departure to
    describe.

    Refuses outright on a blocked membership — see below. Restores
    **nothing else.** No pass is recreated, no entitlement
    un-revoked, no booking un-cancelled, no charge made or repeated.
    Whatever was revoked when the membership ended stays revoked, and
    anything the returning member needs they acquire again the ordinary
    way. The alternative — reviving cancelled artefacts on rejoin —
    would hand back paid access nobody paid for twice, and would
    resurrect bookings for Gatherings that have since happened.
    """
    if membership.rejoin_blocked:
        # Raise rather than clear it. Every caller is supposed to have
        # established that this person may return — ``may_rejoin`` for
        # the member-initiated doors, an explicit 409 for the creator's
        # re-add — so arriving here with a live block is a caller that
        # skipped its check, and silently lifting the ban would be the
        # worst possible response to that.
        #
        # The ``space_memberships_block_needs_removal`` CHECK would
        # catch it a moment later anyway; this says what went wrong
        # instead of surfacing a constraint violation.
        raise ValueError(
            "cannot reactivate a membership whose rejoining is blocked — "
            "lift the restriction first",
        )

    membership.status = SpaceMembershipStatus.active
    # ``source`` is left as it was. It records how this membership first
    # came to exist, which stays true — the same reasoning the
    # entitlement reactivation path uses when it preserves ``source``
    # rather than stamping the newest cause over the original one.
    membership.removal_kind = None
    membership.removal_reason = None
    membership.removal_note = None
    membership.removed_at = None
    membership.removed_by_user_id = None
    # ``payment_action_required`` is deliberately NOT cleared. An
    # unresolved instalment plan does not stop existing because the
    # person came back — the money question is still open, and only the
    # person resolving it should close it.
