"""May this person buy membership of this Collective?

Paid membership does not create a new way in. It adds a fee to the ways
that already exist, so every existing restriction still has to hold —
and a card being charged must never be able to overturn one.

The rules, in the order they are asked:

1. **Billing is switched on.** Otherwise there is nothing to sell.
2. **The Collective charges for membership.** A free Collective has no
   subscription to open.
3. **They are not banned.** ``membership_removal.is_banned`` — the same
   predicate pay-in-full checkout asks.
4. **Their membership row does not bar readmission.** A creator's
   removal, an admin's revocation, a removal whose provenance was never
   recorded, or a ``paused`` row. Reuses
   ``checkout_orchestration``'s own readmission block, so the answer
   cannot drift from the one every other paid door gets.
5. **They are not already an active member.** Nothing to buy.
6. **Membership is deliverable at all** — the Collective is not
   auto-managed, where membership is computed from platform eligibility
   rather than bought.

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

from app.models.platform import (
    Space, SpaceMembership, SpaceMembershipStatus,
)
from app.models.user import User
from app.services import membership_removal
from app.spaces import membership_pricing

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Refusal:
    status_code: int
    code: str
    message: str


#: Membership is already live — there is nothing to buy.
ALREADY_ACTIVE = Refusal(
    status_code=409,
    code="already_active_member",
    message="You're already a member of this collective.",
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

    if membership_removal.is_banned(db, user_id=user.id, space_id=space.id):
        logger.info(
            "membership checkout refused: banned user=%s space=%s",
            user.id, space.id,
        )
        return NOT_ELIGIBLE

    # The same readmission question every other paid door asks, asked
    # through the same helper so the two cannot answer differently.
    from app.services.checkout_orchestration import (
        _membership_readmission_block,
    )
    blocked = _membership_readmission_block(db, user=user, space=space)
    if blocked is not None:
        logger.info(
            "membership checkout refused: readmission blocked user=%s "
            "space=%s — %s", user.id, space.id, blocked,
        )
        return NOT_ELIGIBLE

    existing = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user.id,
        )
        .first()
    )
    if existing is not None:
        status = (
            existing.status.value
            if hasattr(existing.status, "value") else str(existing.status)
        )
        if status == SpaceMembershipStatus.active.value:
            return ALREADY_ACTIVE

    return None
