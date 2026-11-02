"""Joining and leaving Conversation channels.

One module owns every write to ``channel_memberships`` so the rules
below exist in a single place rather than at each of the half-dozen
call sites that can trigger one.

The rules
---------
Admission is idempotent and never overrides a creator. A repeated
Stripe webhook, a reconciliation pass and a manual backfill can all
run against the same person and the result is one row.

Removal has two reasons, and they behave differently on the way back
in:

  ``creator``        a deliberate decision. A later purchase does NOT
                     undo it. Only the creator adding the person back
                     does.
  ``access_revoked`` their access was taken away — refunded, or
                     removed for cause. A genuine new purchase MAY
                     re-admit them, because nobody decided they
                     personally should be out of the conversation.

Those two must stay distinct. Collapsing them either lets a refund
permanently bar somebody who buys again, or lets buying again overrule
the creator.

What this module never does
---------------------------
It never removes anybody because an experience ended, was completed,
expired, was archived, or was unlinked. That is the point of
materialising membership at all: Kelly's November circle finishes and
the member stays. Only the two paths above remove a row, and neither
is a clock.

It also never touches entitlements, bookings, payments or Collective
membership. A channel is a conversation; removing somebody from it
takes nothing else away from them.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform import (
    ChannelExperienceLink,
    ChannelMembership,
    ConversationChannel,
    Space,
)

logger = logging.getLogger(__name__)

#: How a membership came about.
SOURCE_EXPERIENCE = "experience"
SOURCE_MANUAL = "manual"

#: Why a membership ended.
REASON_CREATOR = "creator"
REASON_ACCESS_REVOKED = "access_revoked"

EXPERIENCE_COLUMNS = {
    "pathway": ChannelExperienceLink.pathway_id,
    "gathering": ChannelExperienceLink.event_id,
    "series": ChannelExperienceLink.series_id,
}


def _new_id() -> str:
    return f"chm_{uuid.uuid4().hex[:16]}"


def channels_linked_to(
    db: Session, *, space_id: str, kind: str, experience_id: str,
) -> list[ConversationChannel]:
    """Every channel in this Collective that names this experience.

    Scoped by ``space_id`` as well as by the link, so a stale link to
    an experience that has moved Collective cannot pull somebody into a
    channel they have no business in.
    """
    column = EXPERIENCE_COLUMNS.get(kind)
    if column is None:
        raise ValueError(f"unknown experience kind {kind!r}")
    return (
        db.query(ConversationChannel)
        .join(
            ChannelExperienceLink,
            ChannelExperienceLink.channel_id == ConversationChannel.id,
        )
        .filter(
            column == experience_id,
            ConversationChannel.space_id == space_id,
        )
        .all()
    )


def admit(
    db: Session,
    *,
    channel_id: str,
    user_id: str,
    source: str = SOURCE_EXPERIENCE,
) -> str:
    """Add somebody to a channel. Returns what happened.

    One of: ``already_member``, ``added``, ``readmitted``,
    ``blocked_by_creator_removal``.

    The last is not a failure. It is the mechanism working: a creator
    took this person out, and an automatic process asking for them back
    is exactly what the tombstone exists to refuse.
    """
    existing = (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.channel_id == channel_id,
            ChannelMembership.user_id == user_id,
        )
        .first()
    )

    if existing is not None:
        if existing.status == "active":
            return "already_member"
        if existing.removed_reason == REASON_CREATOR and source != SOURCE_MANUAL:
            logger.info(
                "channel_membership: refusing automatic re-admission of %s "
                "to %s — removed by creator",
                user_id, channel_id,
            )
            return "blocked_by_creator_removal"
        existing.status = "active"
        existing.source = source
        existing.removed_reason = None
        existing.removed_at = None
        existing.removed_by = None
        db.flush()
        return "readmitted"

    row = ChannelMembership(
        id=_new_id(),
        channel_id=channel_id,
        user_id=user_id,
        role="member",
        source=source,
        status="active",
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Two webhooks for the same purchase, racing on
        # UNIQUE(channel_id, user_id). The other one won, which is the
        # outcome we wanted anyway.
        db.rollback()
        return "already_member"
    return "added"


def admit_for_experience(
    db: Session,
    *,
    space_id: str,
    kind: str,
    experience_id: str,
    user_id: str,
) -> dict[str, str]:
    """Admit somebody to every channel linked to one experience.

    Called from the authoritative moments — a confirmed booking, an
    enrolment, an access grant. Qualifying for ONE linked experience is
    enough, so no check against the channel's other links happens here.

    Returns ``{channel_id: outcome}``, which is what makes a caller's
    log line useful when somebody qualifies through two experiences at
    once and should still end up with one row per channel.
    """
    out: dict[str, str] = {}
    for channel in channels_linked_to(
        db, space_id=space_id, kind=kind, experience_id=experience_id,
    ):
        out[channel.id] = admit(
            db, channel_id=channel.id, user_id=user_id,
            source=SOURCE_EXPERIENCE,
        )
    return out


def remove(
    db: Session,
    *,
    channel_id: str,
    user_id: str,
    reason: str,
    actor_user_id: str | None = None,
) -> str:
    """Remove somebody, leaving a tombstone rather than deleting.

    Returns ``removed`` or ``not_a_member``.

    The row is kept because its absence is what an automatic process
    would read as "never joined, and qualifies, so add them". Deleting
    it would mean the next purchase webhook quietly undid the creator.
    """
    if reason not in (REASON_CREATOR, REASON_ACCESS_REVOKED):
        raise ValueError(f"unknown removal reason {reason!r}")

    row = (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.channel_id == channel_id,
            ChannelMembership.user_id == user_id,
        )
        .first()
    )
    if row is None:
        if reason == REASON_CREATOR:
            # Record the decision even though they were never
            # materialised: they may still qualify through a linked
            # experience, and without the tombstone the admission
            # predicate would let them straight back in.
            db.add(ChannelMembership(
                id=_new_id(),
                channel_id=channel_id,
                user_id=user_id,
                role="member",
                source=SOURCE_EXPERIENCE,
                status="removed",
                removed_reason=reason,
                removed_at=datetime.utcnow(),
                removed_by=actor_user_id,
            ))
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return "not_a_member"
            return "removed"
        return "not_a_member"

    if row.status == "removed":
        return "removed"
    row.status = "removed"
    row.removed_reason = reason
    row.removed_at = datetime.utcnow()
    row.removed_by = actor_user_id
    db.flush()
    return "removed"


def revoke_for_experience(
    db: Session,
    *,
    space_id: str,
    kind: str,
    experience_id: str,
    user_id: str,
) -> dict[str, str]:
    """Access to an experience was revoked — leave its channels.

    Revocation means a refund or a removal for cause, which is not the
    same as a Gathering finishing or a pass expiring. Those retain
    membership; this does not.

    A creator-added member is left alone. The creator put them in the
    channel deliberately, and their having also once bought something
    is beside the point.
    """
    out: dict[str, str] = {}
    for channel in channels_linked_to(
        db, space_id=space_id, kind=kind, experience_id=experience_id,
    ):
        row = (
            db.query(ChannelMembership)
            .filter(
                ChannelMembership.channel_id == channel.id,
                ChannelMembership.user_id == user_id,
            )
            .first()
        )
        if row is not None and row.source == SOURCE_MANUAL:
            out[channel.id] = "kept_creator_added"
            continue
        out[channel.id] = remove(
            db, channel_id=channel.id, user_id=user_id,
            reason=REASON_ACCESS_REVOKED,
        )
    return out


def backfill_channel(
    db: Session, *, channel: ConversationChannel, space: Space,
) -> dict[str, int]:
    """Admit everybody who already qualifies for this channel.

    Run when an experience is newly linked, so the people who bought
    November's circle months ago are in the channel the moment it names
    that Gathering — and when materialising a channel that predates
    this model.

    Uses the real access functions via the permission service rather
    than a reimplementation in SQL. Getting
    ``compute_pathway_access`` subtly wrong here would silently admit
    or exclude real members.

    Creator removals are respected: ``admit`` refuses them, so a
    backfill cannot undo a decision.
    """
    from app.models.platform import SpaceMembership, SpaceMembershipStatus
    from app.models.user import User
    from app.services import channel_permissions as perms

    counts = {"added": 0, "already_member": 0, "blocked_by_creator_removal": 0,
              "readmitted": 0, "considered": 0}

    members = (
        db.query(User)
        .join(SpaceMembership, SpaceMembership.user_id == User.id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .all()
    )
    for user in members:
        counts["considered"] += 1
        if not perms.qualifies_through_any_linked_experience(
            user, channel, space, db,
        ):
            continue
        outcome = admit(
            db, channel_id=channel.id, user_id=user.id,
            source=SOURCE_EXPERIENCE,
        )
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts
