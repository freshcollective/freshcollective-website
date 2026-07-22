"""Central access-control for Conversation Channels.

Every backend endpoint that touches a Channel — reading a feed, opening
a post, casting a poll vote, autocompleting a mention, scheduling a
publish, archiving, restoring, managing membership — must go through
this module. Endpoint code MUST NOT re-implement its own rules.

Rules
-----

Caretaker
    A user is a caretaker of a Space if they are the platform admin,
    the platform 'creator' role, OR they hold an active
    SpaceMembership with role in {creator, moderator}. Caretakers can
    always view, moderate, manage members, schedule, archive, and
    restore Channels in their Space.

By channel_type
    start_here — every active SpaceMembership user (system, 🌱 Start Here).
    general    — every active SpaceMembership user (system, 🏡 Common Room).
    open       — every active SpaceMembership user (creator-made).
    private    — every user with a ChannelMembership row + caretakers.
    pathway    — every user with an active Enrollment on the linked
                 Pathway + caretakers.
    gathering  — every user with a confirmed EventBooking on the linked
                 gathering + caretakers.

Archived Channels
    Still viewable to whoever could view them pre-archive. Not
    postable, not commentable, not schedulable — even for caretakers.
    Caretakers may still Restore.

Draft Space
    Never blocks Channel access on its own — the front door to the
    Space handles that. This service assumes the caller has already
    confirmed the user's Space membership.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.platform import (
    ChannelMembership,
    ConversationChannel,
    Enrollment,
    Event,
    EventBooking,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User


# ---------------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------------


def is_caretaker(user: User | None, space: Space, db: Session) -> bool:
    if user is None:
        return False
    if user.role in ("admin", "creator"):
        return True
    return _has_space_caretaker_membership(user.id, space.id, db)


def _has_space_caretaker_membership(user_id: str, space_id: str, db: Session) -> bool:
    row = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
        )
        .first()
    )
    return row is not None


def _is_active_space_member(user_id: str, space_id: str, db: Session) -> bool:
    row = (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    return row is not None


def _is_private_channel_member(user_id: str, channel_id: str, db: Session) -> bool:
    row = (
        db.query(ChannelMembership.id)
        .filter(
            ChannelMembership.user_id == user_id,
            ChannelMembership.channel_id == channel_id,
        )
        .first()
    )
    return row is not None


def _is_active_pathway_enrollee(user_id: str, pathway_id: str, db: Session) -> bool:
    row = (
        db.query(Enrollment.id)
        .filter(
            Enrollment.user_id == user_id,
            Enrollment.pathway_id == pathway_id,
            Enrollment.status == "active",
        )
        .first()
    )
    return row is not None


def _is_confirmed_gathering_attendee(user_id: str, gathering_id: str, db: Session) -> bool:
    """Access to a gathering Channel is granted by a confirmed
    EventBooking. Registrants keep access after the event so the
    conversation naturally continues before, during, and after."""
    from app.models.platform import BookingStatus  # local import — avoids cycle
    row = (
        db.query(EventBooking.id)
        .filter(
            EventBooking.user_id == user_id,
            EventBooking.event_id == gathering_id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .first()
    )
    return row is not None


# ---------------------------------------------------------------------------
# View / interact / manage predicates
# ---------------------------------------------------------------------------


def can_view_channel(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    """Can this user see the Channel + read its posts?

    A caretaker of the Space always can. Otherwise the discriminator
    decides:
    """
    if user is None:
        return False
    if is_caretaker(user, space, db):
        return True

    # Ordinary users must at least be active in the Space; a suspended
    # membership loses access even to open Channels.
    if not _is_active_space_member(user.id, space.id, db):
        return False

    ct = channel.channel_type
    # System channels and creator-made open channels are visible to
    # every active space member.
    if ct in ("start_here", "general", "open"):
        return True
    if ct == "private":
        return _is_private_channel_member(user.id, channel.id, db)
    if ct == "pathway":
        return channel.pathway_id is not None and _is_active_pathway_enrollee(
            user.id, channel.pathway_id, db,
        )
    if ct == "gathering":
        return channel.gathering_id is not None and _is_confirmed_gathering_attendee(
            user.id, channel.gathering_id, db,
        )
    return False


def can_post(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    if not can_view_channel(user, channel, space, db):
        return False
    if channel.is_archived:
        return False
    if is_caretaker(user, space, db):
        return True
    return bool(channel.member_posting_allowed)


def can_comment(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    if not can_view_channel(user, channel, space, db):
        return False
    if channel.is_archived:
        return False
    if is_caretaker(user, space, db):
        return True
    return bool(channel.comments_allowed)


def can_react(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    # Reactions follow view + not-archived (caretakers included; we
    # allow reactions on archived posts too? no — read-only means
    # no new activity).
    if not can_view_channel(user, channel, space, db):
        return False
    return not channel.is_archived


def can_schedule(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    if not is_caretaker(user, space, db):
        return False
    if channel.is_archived:
        return False
    return bool(channel.scheduling_allowed)


def can_moderate(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    return is_caretaker(user, space, db)


def can_manage_members(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    # Only meaningful for private Channels — but the check is caretaker-
    # only regardless of channel type, so the endpoint may safely gate.
    return is_caretaker(user, space, db)


def can_archive(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    # System channels (Start Here + General) are permanent parts of
    # every collective and cannot be archived.
    if channel.is_system or channel.is_default:
        return False
    return is_caretaker(user, space, db)


def can_delete(
    user: User | None,
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> bool:
    """Permanent deletion. System channels are always protected."""
    if channel.is_system or channel.is_default:
        return False
    return is_caretaker(user, space, db)


# ---------------------------------------------------------------------------
# Bulk helpers — used by nav, search scoping, mention autocomplete
# ---------------------------------------------------------------------------


def accessible_channels_for_user(
    user: User | None,
    space: Space,
    db: Session,
    *,
    include_archived: bool = True,
) -> list[ConversationChannel]:
    """Every Channel the user may view within this Space, ordered
    default-first then by position then by name."""
    # Ordering: system channels first (Start Here 🌱 before General 🌍,
    # thanks to their negative position); then everything else by
    # position, then name. `is_system` is redundant in the sort today
    # because system channels already have position <= 0, but keeping
    # it defensive makes the intent obvious.
    q = (
        db.query(ConversationChannel)
        .filter(ConversationChannel.space_id == space.id)
        .order_by(
            ConversationChannel.is_system.desc(),
            ConversationChannel.position.asc(),
            ConversationChannel.name.asc(),
        )
    )
    if not include_archived:
        q = q.filter(ConversationChannel.is_archived.is_(False))
    channels = q.all()
    # Filter down to what this user can actually view. The permission
    # rules are cheap and this list is typically small (<20 rows).
    return [c for c in channels if can_view_channel(user, c, space, db)]


def accessible_user_ids_for_channel(
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> set[str]:
    """Users who can view this Channel. Used by the @mention
    autocomplete endpoint to scope suggestions."""
    caretaker_ids = {
        row.user_id
        for row in db.query(SpaceMembership.user_id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
        )
        .all()
    }

    ct = channel.channel_type
    if ct in ("start_here", "general", "open"):
        base = {
            row.user_id
            for row in db.query(SpaceMembership.user_id)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        }
        return base | caretaker_ids
    if ct == "private":
        rows = db.query(ChannelMembership.user_id).filter(
            ChannelMembership.channel_id == channel.id
        ).all()
        return {r.user_id for r in rows} | caretaker_ids
    if ct == "pathway" and channel.pathway_id:
        rows = db.query(Enrollment.user_id).filter(
            Enrollment.pathway_id == channel.pathway_id,
            Enrollment.status == "active",
        ).all()
        return {r.user_id for r in rows} | caretaker_ids
    if ct == "gathering" and channel.gathering_id:
        from app.models.platform import BookingStatus  # local import — avoids cycle
        rows = db.query(EventBooking.user_id).filter(
            EventBooking.event_id == channel.gathering_id,
            EventBooking.status == BookingStatus.confirmed,
        ).all()
        return {r.user_id for r in rows} | caretaker_ids
    return caretaker_ids
