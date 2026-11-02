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
    private    — every user with an active ChannelMembership row
                 + caretakers.
    pathway / gathering / series — "linked-experience" channels. See
                 below; the three types are now one rule.

Linked-experience channels
--------------------------
A linked channel names any number of Pathways, Gatherings and Series
through ``channel_experience_links``. Qualifying for **any one** of
them admits you.

Membership is **materialised and authoritative**, not recomputed. The
order is:

    1. a ``removed`` row  → denied, whatever else is true
    2. an ``active`` row  → allowed
    3. qualifies right now through any linked experience → allowed
       (this is admission; a hook or the backfill writes the row)

This is a deliberate reversal of the previous rule, which recomputed
access on every check and whose docstring said so: "revoke the grant,
lose the Channel". That was right when a channel *was* a Pathway's
discussion. It is wrong for an ongoing community: Kelly's November
circle finishes, and the member stays in the Women's Circle channel
while December's attendees arrive alongside them.

What the reversal does NOT do is grant anything but conversation.
``ChannelMembership`` is read only here and by the activity feed —
no entitlement or access path consults it — so a retained channel
membership cannot become access to paid Pathway material, a Gathering
ticket, or Series benefits.

Step 3 only ever *adds*. Nothing in the read path removes a row, which
is what makes membership outlive the experience. Removal happens in
exactly two places: a creator acting deliberately, and an actual
revocation of access (see ``channel_membership`` service).

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
    Enrollment,
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
from app.services.pathway_access import (
    compute_pathway_access,
    users_with_included_with_offer_access,
)
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


def is_caretaker_here(user: User | None, space: Space, db: Session) -> bool:
    """Caretaker *of this Collective* — ownership or a caretaker role in
    it. Deliberately NOT the global platform-admin role.

    This is the predicate the member-facing surfaces use: viewing a
    channel, reading its feed, posting, commenting, reacting.

    Why it exists
    -------------
    ``is_caretaker`` answers True for ``User.role == "admin"`` anywhere
    on the platform, and ``can_view_channel`` consulted it before it
    looked at the channel type. So the platform administrator — who is
    also an ordinary member of other people's Collectives — could see
    and post in a channel linked only to a draft Pathway they had never
    enrolled in, and the draft check was never reached. A creator's
    explicit removal did not stop them either.

    Holding a global role is not participation in somebody else's
    community. Administrative reach is still available where it is
    deliberate and legible — archiving, deleting, managing members,
    moderating, and the ``/api/admin`` surface, all of which keep
    ``is_caretaker``.

    Owners and creator/moderator members are untouched: they keep every
    channel in their own Collective.
    """
    if user is None:
        return False
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


#: Channel types whose audience comes from linked experiences.
LINKED_CHANNEL_TYPES: tuple[str, ...] = ("pathway", "gathering", "series")

#: Types whose audience is already "every active member of the
#: Collective". Nothing is withheld in them, so a platform admin
#: reaching them withholds nothing either — and Creator Studio,
#: Community Care moderation and support all read them for Collectives
#: the admin is not a member of.
UNRESTRICTED_CHANNEL_TYPES: tuple[str, ...] = ("start_here", "general", "open")


def platform_admin_may_inspect(
    user: User | None, channel: ConversationChannel,
) -> bool:
    """Whether the global admin role alone opens this channel.

    It does for the unrestricted types and nowhere else. ``private``
    and the linked types are the ones whose whole purpose is that not
    everyone is in them, so the global role stops at their door and the
    administrator is treated as whatever they are in that Collective —
    which, in somebody else's community, is an ordinary member.
    """
    return (
        user is not None
        and user.role == "admin"
        and channel.channel_type in UNRESTRICTED_CHANNEL_TYPES
    )


def _membership_row(user_id: str, channel_id: str, db: Session):
    return (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.user_id == user_id,
            ChannelMembership.channel_id == channel_id,
        )
        .first()
    )


def _is_private_channel_member(user_id: str, channel_id: str, db: Session) -> bool:
    """A removed row is not a member.

    Private channels previously treated the mere presence of a row as
    membership, which was fine when removal meant DELETE. Removal is
    now a tombstone, so presence is no longer the question — status is.
    """
    row = _membership_row(user_id, channel_id, db)
    return row is not None and row.status == "active"


def qualifies_through_any_linked_experience(
    user: User, channel: ConversationChannel, space: Space, db: Session,
) -> bool:
    """Does this user have access to at least ONE linked experience?

    Any one is enough — that is the whole point of linking several.
    Someone who bought November's circle qualifies for the channel that
    also names December's, without having bought December.

    This is the *admission* predicate. It is not what keeps anybody in
    the channel; the materialised membership row does that.
    """
    from app.models.platform import ChannelExperienceLink

    links = (
        db.query(ChannelExperienceLink)
        .filter(ChannelExperienceLink.channel_id == channel.id)
        .all()
    )
    # Fall back to the legacy columns when no link rows exist. During
    # rollout a channel is linked by migration 177, but a channel
    # written by code that predates it would otherwise have no links
    # at all and lock its members out.
    if not links:
        return _qualifies_legacy(user, channel, space, db)

    for link in links:
        if link.pathway_id is not None:
            if _has_pathway_channel_access(user, link.pathway_id, space, db):
                return True
        elif link.event_id is not None:
            if _is_confirmed_gathering_attendee(user.id, link.event_id, db):
                return True
        elif link.series_id is not None:
            if _has_series_channel_access(user, link.series_id, space, db):
                return True
    return False


def _qualifies_legacy(
    user: User, channel: ConversationChannel, space: Space, db: Session,
) -> bool:
    """The pre-177 single-column rule, kept only as a safety net."""
    ct = channel.channel_type
    if ct == "pathway" and channel.pathway_id:
        return _has_pathway_channel_access(user, channel.pathway_id, space, db)
    if ct == "gathering" and channel.gathering_id:
        return _is_confirmed_gathering_attendee(user.id, channel.gathering_id, db)
    if ct == "series" and channel.series_id:
        return _has_series_channel_access(user, channel.series_id, space, db)
    return False


def _legacy_link_shim(channel: ConversationChannel):
    """A stand-in link row built from the pre-177 single columns."""
    from app.models.platform import ChannelExperienceLink

    for attr, field in (
        ("pathway_id", "pathway_id"),
        ("gathering_id", "event_id"),
        ("series_id", "series_id"),
    ):
        value = getattr(channel, attr, None)
        if value:
            return ChannelExperienceLink(
                id="legacy", channel_id=channel.id, **{field: value},
            )
    return None


def acquisition_for_linked_channel(
    user: User, channel: ConversationChannel, space: Space, db: Session,
) -> tuple[str, str] | None:
    """What this user personally DID to belong here, if anything.

    Returns ``(kind, experience_id)`` for the first linked experience
    the user holds a participation record for, or None.

    This is deliberately narrower than
    ``qualifies_through_any_linked_experience``, and the difference is
    the whole point. That predicate answers "may they open this
    channel right now", which is correctly satisfied by being a
    caretaker, or by the Pathway simply being free to all members.
    This one answers "did they join" — a confirmed booking, an
    acquired Pathway, a Series pass.

    Materialising membership is permanent, so it must only record the
    second. A caretaker's reach comes from their role and should
    disappear with it, not harden into a membership row. A free
    Pathway's audience is "every member", which is not a list of people
    who joined anything, and would outlive the Pathway being free.

    Nobody loses access by being excluded here: the admission clause
    in ``can_access_linked_channel`` still lets them in for as long as
    they genuinely qualify.
    """
    from app.models.access_pass import AccessPass, AccessPassStatus
    from app.models.platform import BookingStatus, ChannelExperienceLink
    from app.services.pathway_access import (
        WITHHELD_STATUSES,
        retains_acquired_access,
    )

    links = (
        db.query(ChannelExperienceLink)
        .filter(ChannelExperienceLink.channel_id == channel.id)
        .all()
    )
    if not links:
        # A channel whose linked experience has since been deleted, or
        # one written before migration 177. Fall back to the legacy
        # columns so its members are still recognised.
        links = [_legacy_link_shim(channel)]
        links = [link for link in links if link is not None]
    now = datetime.utcnow()
    for link in links:
        if link.event_id is not None:
            row = (
                db.query(EventBooking.id)
                .filter(
                    EventBooking.user_id == user.id,
                    EventBooking.event_id == link.event_id,
                    EventBooking.status == BookingStatus.confirmed,
                )
                .first()
            )
            if row is not None:
                return ("gathering", link.event_id)
        elif link.pathway_id is not None:
            # A withheld Pathway admits nobody new, whatever they
            # hold. ``draft`` was never offered and ``coming_soon`` is
            # not open yet, and the canonical rule denies non-
            # caretakers regardless of entitlement. Anyone who already
            # joined keeps their seat through their membership row,
            # which ``can_access_linked_channel`` reads first —
            # reverting a Pathway to draft does not evict people.
            #
            # ``archived`` is deliberately NOT here: acquired access
            # survives archiving, which ``retains_acquired_access``
            # below is exactly the check for.
            pathway_status = db.query(Pathway.status).filter(
                Pathway.id == link.pathway_id,
            ).scalar()
            pathway_status = getattr(pathway_status, "value", pathway_status)
            if pathway_status in WITHHELD_STATUSES:
                continue

            # Two signals, because the platform records a paid join and
            # a free join in different places.
            #
            # 1. An acquisition — active unexpired entitlement, or a
            #    pass on an Option including it. Revocation- and
            #    expiry-aware, and it deliberately does not count
            #    membership. Written by purchase fulfilment and by
            #    creator/admin grants; NEVER written for a free
            #    Pathway.
            if retains_acquired_access(
                db, user_id=user.id, space_id=space.id,
                pathway_id=link.pathway_id,
            ):
                return ("pathway", link.pathway_id)
            # 2. An Enrollment, but ONLY for the two access types that
            #    can never produce an acquisition record.
            #
            #    ``free`` and ``included`` Pathways are reachable by
            #    virtue of membership, and nothing is ever written when
            #    somebody takes one up — there is no join endpoint, and
            #    no PathwayEntitlement is created. The one trace they
            #    leave is an Enrollment, which ``complete_step`` writes
            #    lazily the first time they mark a step done. That is
            #    the only line the data supports between browsing a
            #    free Pathway and doing it.
            #
            #    For ``one_time``, ``subscription`` and
            #    ``included_with_offer`` the acquisition record above
            #    is authoritative and an Enrollment must NOT stand in
            #    for it: a progress row with no live entitlement is
            #    precisely the member whose access was revoked or has
            #    expired. Letting it count would undo a revocation —
            #    see test_enrollment_only_member_cannot_see_paid_
            #    pathway_channel and its revocation sibling, which pin
            #    that rule.
            pathway_row = db.get(Pathway, link.pathway_id)
            access_type = getattr(pathway_row, "access_type", None)
            access_type = getattr(access_type, "value", access_type)
            if access_type in ("free", "included"):
                row = (
                    db.query(Enrollment.id)
                    .filter(
                        Enrollment.user_id == user.id,
                        Enrollment.pathway_id == link.pathway_id,
                    )
                    .first()
                )
                if row is not None:
                    return ("pathway", link.pathway_id)
        elif link.series_id is not None:
            row = (
                db.query(AccessPass.id)
                .filter(
                    AccessPass.user_id == user.id,
                    AccessPass.space_id == space.id,
                    AccessPass.eligible_series_id == link.series_id,
                    AccessPass.status == AccessPassStatus.active,
                    (AccessPass.valid_until.is_(None)
                     | (AccessPass.valid_until > now)),
                )
                .first()
            )
            if row is not None:
                return ("series", link.series_id)
    return None


def can_access_linked_channel(
    user: User, channel: ConversationChannel, space: Space, db: Session,
) -> bool:
    """Membership first, qualification second — and removal beats both.

    The ordering is the feature. Checking qualification first would
    mean a creator's removal lasted until the member's next purchase
    webhook; checking membership first without the tombstone would mean
    a removal could never be expressed at all for somebody who still
    qualifies.
    """
    # Caretakers of this Collective first, so the helper gives the same
    # answer as ``can_view_channel`` when called on its own. The
    # qualification path below runs with ``as_member=True`` and would
    # otherwise refuse an owner.
    if is_caretaker_here(user, space, db):
        return True
    row = _membership_row(user.id, channel.id, db)
    if row is not None:
        if row.status == "removed":
            return False
        return True
    # Admission requires having JOINED one of the linked experiences,
    # not merely being able to open it.
    #
    # This used to ask ``qualifies_through_any_linked_experience``,
    # which is satisfied for every member of the Collective whenever a
    # linked Pathway is free — so browsing a free Pathway opened its
    # channel. Being able to view an experience is not joining it.
    return acquisition_for_linked_channel(user, channel, space, db) is not None


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
    # ``as_member`` so a global admin role cannot answer this
    # question: ownership and caretaker membership were already
    # settled by ``is_caretaker_here`` before we got here.
    return compute_pathway_access(user, pathway, space, db, as_member=True)


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
    return compute_series_access(user, series, space, db, as_member=True)


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
    # Caretakers *of this Collective*, not holders of a global role.
    if is_caretaker_here(user, space, db):
        return True
    # The global role still opens the channels that are open to
    # everyone anyway — Creator Studio and Community Care read these
    # for Collectives the admin has no membership in.
    if platform_admin_may_inspect(user, channel):
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
    if ct in LINKED_CHANNEL_TYPES:
        return can_access_linked_channel(user, channel, space, db)
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
    # Narrow predicate again: a global admin must not bypass a
    # creator's participation settings in a restricted channel of
    # somebody else's Collective.
    if is_caretaker_here(user, space, db):
        return True
    if platform_admin_may_inspect(user, channel):
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
    # Narrow predicate again: a global admin must not bypass a
    # creator's participation settings in a restricted channel of
    # somebody else's Collective.
    if is_caretaker_here(user, space, db):
        return True
    if platform_admin_may_inspect(user, channel):
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
    autocomplete endpoint to scope suggestions.

    For linked-experience channels this must agree with
    ``can_access_linked_channel``, so the qualification-derived set
    below is only half the answer: a member who was admitted months ago
    and whose Gathering has since finished is still in the channel and
    must still be mentionable, and a member the creator removed must
    not be — even while they still qualify.
    """
    if channel.channel_type not in LINKED_CHANNEL_TYPES:
        return _qualification_audience(channel, space, db)

    # Linked channels ask the real gate, once per active member,
    # rather than assembling a second set-shaped answer.
    #
    # Every set-shaped version of this drifted. The first was keyed on
    # the legacy single columns, so a channel linked to three
    # Gatherings only ever considered one of them; narrowing that set
    # afterwards inherited the same blind spot and returned nobody for
    # a channel whose legacy column was empty. ``can_access_linked_
    # channel`` already encodes membership, tombstones, acquisition and
    # caretaker status in the right order, so this cannot disagree
    # with what the member actually experiences.
    members = (
        db.query(User)
        .join(SpaceMembership, SpaceMembership.user_id == User.id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .all()
    )
    audience = {
        user.id for user in members
        if can_access_linked_channel(user, channel, space, db)
    }
    # Retained members who have since left the Collective are not in
    # the loop above; their row still says they belong here, and a
    # removal still outranks it.
    rows = (
        db.query(ChannelMembership.user_id, ChannelMembership.status)
        .filter(ChannelMembership.channel_id == channel.id)
        .all()
    )
    audience |= {r.user_id for r in rows if r.status == "active"}
    audience -= {r.user_id for r in rows if r.status == "removed"}
    return audience | _caretaker_ids(space, db)


def _caretaker_ids(space: Space, db: Session) -> set[str]:
    return {
        row.user_id
        for row in db.query(SpaceMembership.user_id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
        )
        .all()
    }


def _qualification_audience(
    channel: ConversationChannel,
    space: Space,
    db: Session,
) -> set[str]:
    """Who qualifies today, by channel type.

    Unchanged from the pre-177 rule and still keyed on the legacy
    single experience columns. That is deliberate and safe: it only
    ever *adds* to the audience the materialised rows already describe,
    and admission writes a row the moment anybody qualifies, so a
    multi-link channel's audience arrives through membership rather
    than through this set.
    """
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
        # ``status`` matters here too: removal is a tombstone now, so a
        # removed member would otherwise stay mentionable.
        rows = db.query(ChannelMembership.user_id).filter(
            ChannelMembership.channel_id == channel.id,
            ChannelMembership.status == "active",
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
        from app.services.pathway_access import (
            RETIRED_STATUS,
            WITHHELD_STATUSES,
            users_retaining_acquired_access,
        )

        if p_status in WITHHELD_STATUSES:
            # Canonical rule: only caretakers can reach these Pathways.
            return caretaker_ids
        # Archived Pathways keep their purchasers, so the channel keeps
        # them too — otherwise a member who still has the Pathway could
        # read its conversation and never be offered as a mention.
        #
        # Narrowing, like the other two surfaces: the per-access-type
        # sets below are computed as normal and then intersected with
        # the holders, so nobody is added by the Pathway being
        # archived. Caretakers are unioned back in at every return.
        retained_ids: set[str] | None = None
        if p_status == RETIRED_STATUS:
            retained_ids = users_retaining_acquired_access(
                db, space_id=space.id, pathway_id=pathway.id,
            )

        def _allow(candidates: set[str]) -> set[str]:
            """Apply the archive narrowing, then add the caretakers.

            One place, so the three access-type branches below cannot
            each forget it differently."""
            if retained_ids is not None:
                candidates = candidates & retained_ids
            return candidates | caretaker_ids

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
            return _allow(active_member_ids)
        if access_type == "included_with_offer":
            # Unlock-holders come from the canonical helper so this set
            # cannot drift from the per-user predicate
            # ``can_view_channel`` applies via ``compute_pathway_access``.
            # Holding an AccessPass on an including Option OR an active
            # PathwayEntitlement for the Pathway both count.
            candidates = users_with_included_with_offer_access(
                db, space_id=space.id, pathway_id=pathway.id,
            )
            return _allow(candidates & active_member_ids)
        # one_time / subscription — active, non-expired PathwayEntitlement.
        now = datetime.utcnow()
        rows = db.query(PathwayEntitlement.user_id).filter(
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None) | (PathwayEntitlement.ends_at > now)),
        ).all()
        candidates = {r.user_id for r in rows}
        return _allow(candidates & active_member_ids)
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
