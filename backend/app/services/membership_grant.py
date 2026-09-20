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

The known gap, stated plainly: a creator who removes a member whose row
says ``source='purchase'`` will see that person return if they buy
again, because nothing records *who* removed them. Recording removal
provenance is the fix, and it belongs with the member-management work
rather than here.
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

    existing.status = SpaceMembershipStatus.active
    # ``source`` is left as it was. It records how this membership first
    # came to exist, which stays true — the same reasoning the
    # entitlement reactivation path uses when it preserves ``source``
    # rather than stamping the newest cause over the original one.
    logger.info(
        "membership_grant: reactivated user=%s space=%s original_source=%s",
        user_id, space_id, existing.source,
    )
    return MembershipOutcome(reactivated=True)
