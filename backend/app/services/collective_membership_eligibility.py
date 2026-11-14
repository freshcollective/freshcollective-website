"""May this person buy membership of this Collective?

Paid membership does not create a new way in. It adds a fee to the ways
that already exist, so every existing restriction still has to hold —
and a card being charged must never be able to overturn one.

The rules, in the order they are asked:

1. **Billing is switched on.** Otherwise there is nothing to sell.
2. **The Collective charges for membership.** A free Collective has no
   subscription to open.
3. **Membership is deliverable at all** — the Collective is not
   auto-managed, where membership is computed from platform
   eligibility rather than bought.
4. **They do not own the place.** A creator does not buy membership of
   their own Collective, and the sweep never pauses them, so there is
   nothing here for them to hold.
5. **They are not banned.** ``membership_removal.is_banned`` — the same
   predicate pay-in-full checkout asks.
6. **Their membership row does not bar readmission.** A creator's
   removal, an admin's revocation, or a removal whose provenance was
   never recorded. Reuses ``checkout_orchestration``'s own readmission
   block, so the answer cannot drift from the one every other paid
   door gets — with one documented exception, below.
7. **They do not already pay to be here.** Not *they are not a member*
   — see below.

Being a member is not the same as paying to be one
--------------------------------------------------
This is the distinction the whole free-to-paid transition rests on.

A Collective with a hundred free members decides to charge from 1
January. Every one of those hundred is an **active member** who holds
**no agreement**, and each of them has to be able to buy one — without
leaving, without rejoining, and without losing the history they
already have. So the question asked here is whether they already hold
an agreement, never whether they are already a member.

Refusing an active member was this module's original rule, and it was
right while the only way to be a member of a paid Collective was to
have paid: the two questions had one answer. The transition is what
separates them.

What still refuses, so the relaxation does not become a hole:

* an agreement that already satisfies the requirement — ``active``,
  ``past_due`` or ``cancel_scheduled``, the same three the sweep
  accepts — because a second one would charge twice for one place;
* a ban, a creator's removal, an admin's revocation, every one of them
  unchanged;
* the Collective's own join policy, which the route asks before this
  is ever called.

A ``pending`` agreement deliberately does not refuse. It is a checkout
nobody has paid for, and the billing layer hands the member back their
own live Stripe Session rather than opening a second one — so a member
who closed the tab can pick it up where they left it.

The ``paused`` exception
------------------------
The shared readmission block refuses a ``paused`` membership row, and
for every other paid door that is correct. Here it would be a trap:
the transition sweep pauses exactly the members who did not subscribe
in time, and a paused member who then wants to pay is the single case
this stage exists to serve. Refusing them would leave the one group
the system deliberately created with no way back.

It is safe to make the exception *here* and nowhere else, because
inside a Collective this module will still be talking to, ``paused``
has only one author. ``creator_eligibility`` pauses only memberships
in Collectives with an ``auto_grant_role``, and those are refused two
rules earlier. That leaves the billing lapse and the transition sweep
— both of them this system's own doing, and both of them cured by
paying. The fulfilment side already agrees: a verified invoice calls
``collective_membership_access.reactivate_paused_membership``, which
exists for precisely this and refuses a ``removed`` row at any price.

What this deliberately does **not** do
--------------------------------------
It does not consult ``join_policy``. Paid membership is an additional
condition on joining, never a replacement for it, so an invite-only or
approval-required Collective keeps its own door and this keeps the fee.
Stage 5A.0's join gate holds the other half, and the two are composed by
the route rather than folded together here.

Nor does it treat an invitation as a waiver. An invitation grants
eligibility to join; it has never granted free access to something
priced, and inferring a comp from one would make every paid Collective
free to anyone the creator ever invited.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.platform import Space, SpaceMembershipStatus
from app.models.user import User
from app.services import collective_membership_access as access
from app.services import membership_removal
from app.spaces import membership_pricing

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Refusal:
    status_code: int
    code: str
    message: str


#: They already pay to be here. Not "already a member" — see the
#: module docstring for why those are different questions.
ALREADY_SUBSCRIBED = Refusal(
    status_code=409,
    code="already_subscribed",
    message="You already have a membership subscription here.",
)

#: A creator does not buy membership of their own Collective.
OWN_COLLECTIVE = Refusal(
    status_code=409,
    code="membership_own_collective",
    message="This is your collective — your membership of it never lapses.",
)

#: Not for sale here.
NOT_PAID = Refusal(
    status_code=409,
    code="membership_not_paid",
    message="This collective does not charge for membership.",
)

#: The feature is not switched on for this deployment.
NOT_AVAILABLE = Refusal(
    status_code=409,
    code="membership_billing_unavailable",
    message="Paid membership isn't available yet.",
)

#: Deliberately vague, and deliberately 402. A checkout error is not the
#: place to disclose a moderation decision, and the member-facing answer
#: is "not right now, speak to the creator" — the same wording and the
#: same code as checkout Rule E.
NOT_ELIGIBLE = Refusal(
    status_code=402,
    code="membership_not_available_to_you",
    message=(
        "Membership of this collective cannot be purchased right now. "
        "Please contact the collective's creator."
    ),
)

#: Membership here is computed, not sold.
AUTO_MANAGED = Refusal(
    status_code=409,
    code="membership_auto_managed",
    message="Membership of this collective is managed by Fresh Collective.",
)


#: The one readmission block this module overrides, and the only one.
#:
#: Named rather than inlined so the exception is greppable from the
#: shared helper that produces it — ``_membership_readmission_block``
#: returns ``f"status_{status}"`` for anything that is neither active
#: nor removed.
PAUSED_BLOCK: str = f"status_{SpaceMembershipStatus.paused.value}"


def refusal_for(
    db: Session, *, user: User, space: Space,
) -> Refusal | None:
    """Why this person may not subscribe, or ``None`` if they may."""
    if not membership_pricing.billing_enabled():
        return NOT_AVAILABLE
    if not membership_pricing.is_paid_membership(space.pricing_type):
        return NOT_PAID
    if getattr(space, "auto_grant_role", None) is not None:
        return AUTO_MANAGED
    if space.creator_id == user.id:
        return OWN_COLLECTIVE

    if membership_removal.is_banned(db, user_id=user.id, space_id=space.id):
        logger.info(
            "membership checkout refused: banned user=%s space=%s",
            user.id, space.id,
        )
        return NOT_ELIGIBLE

    # The same readmission question every other paid door asks, asked
    # through the same helper so the two cannot answer differently —
    # except for ``paused``, which here means "the sweep did this, and
    # paying is the cure". See the module docstring.
    from app.services.checkout_orchestration import (
        _membership_readmission_block,
    )
    blocked = _membership_readmission_block(db, user=user, space=space)
    if blocked is not None and blocked != PAUSED_BLOCK:
        logger.info(
            "membership checkout refused: readmission blocked user=%s "
            "space=%s — %s", user.id, space.id, blocked,
        )
        return NOT_ELIGIBLE

    # Already paying? Then there is nothing to buy. Being a *member*
    # is not what is asked here — an active free member of a
    # Collective that has started charging is exactly who this path
    # is for.
    if access.holds_satisfying_agreement(
        db, user_id=user.id, space_id=space.id,
    ):
        return ALREADY_SUBSCRIBED

    return None
