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
    pathway    — every user who currently has access to the linked
                 Pathway under the canonical ``compute_pathway_access``
                 rule (paid, plan-based, complimentary/manual grant,
                 or a legitimate free/included path) + caretakers.
                 Enrollment progress history is NOT an independent
                 access source — revoke the grant, lose the Channel.
    gathering  — every user with a confirmed EventBooking on the linked
                 gathering + caretakers.
    series     — every user who currently has access to the linked
                 EventSeries under the canonical ``compute_series_access``
                 rule (an active, not-yet-expired AccessPass whose
                 ``eligible_series_id`` matches — covering pay-in-full,
                 finite plan, and manual grants uniformly) + caretakers.
                 A confirmed EventBooking on a single gathering inside
                 the series is NOT a Series-access source. Revoke or
                 expire the pass, lose the Channel.

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

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.platform import (
    ChannelMembership,
    ConversationChannel,
    EntitlementStatus,
    Event,
    EventBooking,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.pathway_access import compute_pathway_access
from app.services.series_access import compute_series_access


# ---------------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------------


def is_space_owner(user: User | None, space: Space) -> bool:
    """SEC-005-E — per-Collective ownership predicate. Owners always
    retain authority over their Collective even without a matching
    ``SpaceMembership`` row (legacy Collectives predating
    ``create_space``'s auto-inserted creator_owner membership rely on
    this branch)."""
    return user is not None and space.creator_id == user.id


def is_caretaker(user: User | None, space: Space, db: Session) -> bool:
    """Caretaker of the Space — may view, moderate, manage members,
    schedule, archive, and restore Channels here.

    Post SEC-005-E: platform ``User.role == "creator"`` is a platform
    capability (may enter Creator Studio); it is NOT global authority
    over other creators' Collectives. Caretaker status now requires
    one of:

      * platform ``admin`` — preserved unchanged;
      * ``Space.creator_id`` ownership;
      * active ``SpaceMembership`` with role in {creator, moderator}.
    """
    if user is None:
        return False
    if user.role == "admin":
        return True
    if is_space_owner(user, space):
        return True
    return has_space_caretaker_membership(user.id, space.id, db)


def has_space_caretaker_membership(user_id: str, space_id: str, db: Session) -> bool:
    """Public — active SpaceMembership with role in {creator, moderator}.
    Exposed so peer modules (event_permissions, community moderation,
    messages) can share the same predicate rather than reimplement it."""
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


def is_active_space_member(user_id: str, space_id: str, db: Session) -> bool:
    """Public — exposed so peer modules (e.g. community upload endpoints)
    can reuse the same active-membership predicate the channel gate
    already uses. Kept alongside ``is_caretaker`` as the two building
    blocks callers may compose without reimplementing membership
    semantics."""
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


def _has_pathway_channel_access(
    user: User, pathway_id: str, space: Space, db: Session,
) -> bool:
    """Pathway-linked Channel visibility mirrors the canonical
    ``compute_pathway_access`` rule for the linked Pathway.

    Deliberately NOT keyed on ``Enrollment`` — that's a progress-
    tracking record, not an access grant. A member who completed a
    step but later had their access revoked must lose the Channel
    the moment the last legitimate access source disappears.
    """
    pathway = db.query(Pathway).filter(Pathway.id == pathway_id).first()
    if pathway is None:
        return False
    return compute_pathway_access(user, pathway, space, db)


def _has_series_channel_access(
    user: User, series_id: str, space: Space, db: Session,
) -> bool:
    """Series-linked Channel visibility mirrors the canonical
    ``compute_series_access`` rule for the linked EventSeries.

    A confirmed ``EventBooking`` on a single session inside the
    series is not a Series-access source; attending one gathering
    doesn't buy you the whole term. Access requires an active,
    not-yet-expired ``AccessPass`` whose ``eligible_series_id``
    matches (covers pay-in-full, finite plan, and manual grants
    uniformly) or caretaker privilege.
    """
    series = db.query(EventSeries).filter(EventSeries.id == series_id).first()
    if series is None:
        return False
    return compute_series_access(user, series, space, db)


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
    if not is_active_space_member(user.id, space.id, db):
        return False

    ct = channel.channel_type
    # System channels and creator-made open channels are visible to
    # every active space member.
    if ct in ("start_here", "general", "open"):
        return True
    if ct == "private":
        return _is_private_channel_member(user.id, channel.id, db)
    if ct == "pathway":
        return channel.pathway_id is not None and _has_pathway_channel_access(
            user, channel.pathway_id, space, db,
        )
    if ct == "gathering":
        return channel.gathering_id is not None and _is_confirmed_gathering_attendee(
            user.id, channel.gathering_id, db,
        )
    if ct == "series":
        return channel.series_id is not None and _has_series_channel_access(
            user, channel.series_id, space, db,
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
        # Mention-autocomplete must use the same effective permission
        # as ``can_view_channel``. Build the set branch-by-branch to
        # match ``compute_pathway_access`` without a per-user loop,
        # then intersect with the Space's active membership so a stray
        # AccessPass or PathwayEntitlement held by a non-space-member
        # cannot surface (the view-side gate does the same via
        # ``is_active_space_member``).
        pathway = (
            db.query(Pathway).filter(Pathway.id == channel.pathway_id).first()
        )
        if pathway is None:
            return caretaker_ids
        p_status = (
            pathway.status.value if hasattr(pathway.status, "value")
            else str(pathway.status)
        )
        if p_status in ("draft", "archived", "coming_soon"):
            # Canonical rule: only caretakers can access these Pathways.
            return caretaker_ids
        active_member_ids = {
            row.user_id
            for row in db.query(SpaceMembership.user_id)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        }
        access_type = (
            pathway.access_type.value if hasattr(pathway.access_type, "value")
            else str(pathway.access_type or "free")
        )
        if access_type in ("free", "included"):
            return active_member_ids | caretaker_ids
        if access_type == "included_with_offer":
            # Unlock set derived from PaymentOptionGrant — the single
            # source of truth. Filter out draft Options; keep
            # published (currently sold) and archived (historical
            # buyers still hold valid passes).
            from app.models.payment_option import (
                PaymentOption as _PO,
                PaymentOptionStatus as _POS,
            )
            from app.models.payment_option_grant import (
                PaymentOptionGrant as _POG,
            )
            unlock_option_ids_q = (
                db.query(_POG.payment_option_id)
                .join(_PO, _PO.id == _POG.payment_option_id)
                .filter(
                    _POG.grant_kind == "pathway",
                    _POG.pathway_id == pathway.id,
                    _PO.status.in_([_POS.published, _POS.archived]),
                )
            )
            now = datetime.utcnow()
            rows = db.query(AccessPass.user_id).filter(
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
                AccessPass.payment_option_id.in_(unlock_option_ids_q),
                (AccessPass.valid_until.is_(None) | (AccessPass.valid_until > now)),
            ).all()
            candidates = {r.user_id for r in rows}
            return (candidates & active_member_ids) | caretaker_ids
        # one_time / subscription — active, non-expired PathwayEntitlement.
        now = datetime.utcnow()
        rows = db.query(PathwayEntitlement.user_id).filter(
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None) | (PathwayEntitlement.ends_at > now)),
        ).all()
        candidates = {r.user_id for r in rows}
        return (candidates & active_member_ids) | caretaker_ids
    if ct == "gathering" and channel.gathering_id:
        from app.models.platform import BookingStatus  # local import — avoids cycle
        rows = db.query(EventBooking.user_id).filter(
            EventBooking.event_id == channel.gathering_id,
            EventBooking.status == BookingStatus.confirmed,
        ).all()
        return {r.user_id for r in rows} | caretaker_ids
    if ct == "series" and channel.series_id:
        # Mirror ``compute_series_access`` for the linked EventSeries.
        # Deliberately no EventBooking join — attending a single
        # session in the series is not a Series-access source.
        active_member_ids = {
            row.user_id
            for row in db.query(SpaceMembership.user_id)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .all()
        }
        now = datetime.utcnow()
        rows = db.query(AccessPass.user_id).filter(
            AccessPass.space_id == space.id,
            AccessPass.eligible_series_id == channel.series_id,
            AccessPass.status == AccessPassStatus.active,
            (AccessPass.valid_until.is_(None) | (AccessPass.valid_until > now)),
        ).all()
        candidates = {r.user_id for r in rows}
        return (candidates & active_member_ids) | caretaker_ids
    return caretaker_ids
