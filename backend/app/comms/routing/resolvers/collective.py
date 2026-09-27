"""Resolvers for collective-membership events.

R2A coverage: ``collective.invitation.sent`` — one recipient (the
prospective member), addressed by the email the creator entered on
the draft invitation. The recipient almost never has a Fresh
Collective account yet, so we address them via
``recipient_address_override`` and fall back to the inviter's
user_id for ``ResolvedRecipient.user_id`` (the decision pipeline
requires a real id).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.comms.models import CommunicationEvent
from app.comms.routing.resolver import ResolvedRecipient, resolver_for


@resolver_for("collective.invitation.sent")
class InvitationSentResolver:
    event_type = "collective.invitation.sent"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        payload = event.payload or {}
        target = payload.get("recipient_email")
        if not isinstance(target, str) or not target:
            return []
        # A prospective member usually has no account yet. We need a
        # real user_id for the ResolvedRecipient (the decision layer
        # loads preferences off it); the inviter is the only party we
        # can be sure has one, and using them keeps the audit trail
        # honest ("this send was authorised by this inviter").
        pipeline_user_id = event.actor_user_id
        if not pipeline_user_id:
            return []
        return [
            ResolvedRecipient(
                user_id=pipeline_user_id,
                role_in_event="invitee",
                human_reason=(
                    "A creator invited you to join their Collective on "
                    "Fresh Collective."
                ),
                recipient_address_override=target,
                template_context={
                    "inviter_name":     payload.get("inviter_name") or "",
                    "collective_name":  payload.get("collective_name") or "",
                    "accept_url":       payload.get("accept_url") or "",
                },
            ),
        ]


@resolver_for("collective.purchase.received")
class CollectivePurchaseReceivedResolver:
    """Who hears that someone bought access to this Collective.

    The Collective's leaders, resolved the way every other creator-authority
    check on the platform resolves them: the owner
    (``Space.creator_id``) **or** an active ``SpaceMembership`` with role
    creator/moderator. That is what ``creator/routes._get_managed_space``
    and ``services/space_viewer.SpaceViewer.is_leader`` both mean by a
    leader.

    Worth stating because the older in-app booking hook
    (``notification_service.trigger_event_booking_creator``) does **not**
    include the owner — it reads membership rows alone. For a Collective
    whose owner holds no membership row (the legacy case
    ``space_viewer`` documents) that hook notifies nobody at all. This
    resolver follows the canonical rule instead, so the person who runs
    the Collective is always told that something sold.

    The purchaser is excluded: a creator buying from their own Collective
    does not need to be told they did.
    """

    event_type = "collective.purchase.received"

    def resolve(
        self, db: Session, event: CommunicationEvent,
    ) -> list[ResolvedRecipient]:
        from app.models.platform import (
            Space,
            SpaceMembership,
            SpaceMembershipStatus,
            SpaceRole,
        )

        payload = event.payload or {}
        space_id = (event.context or {}).get("space_id") or payload.get("space_id")
        if not space_id:
            return []

        space = db.query(Space).filter(Space.id == space_id).first()
        if space is None:
            return []

        buyer_id = event.actor_user_id
        leader_ids: list[str] = []
        if space.creator_id and space.creator_id != buyer_id:
            leader_ids.append(space.creator_id)
        for (user_id,) in (
            db.query(SpaceMembership.user_id)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
                SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
            )
            .all()
        ):
            if user_id != buyer_id and user_id not in leader_ids:
                leader_ids.append(user_id)

        keys = (
            "buyer_name", "collective_name", "experience_name",
            "amount_display", "payment_mode", "session_count", "cta_url",
        )
        context = {k: payload.get(k) for k in keys}
        return [
            ResolvedRecipient(
                user_id=leader_id,
                role_in_event="creator",
                human_reason=(
                    "Someone bought access to a Collective you run on "
                    "Fresh Collective."
                ),
                template_context=context,
            )
            for leader_id in leader_ids
        ]
