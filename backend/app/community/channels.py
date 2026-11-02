"""Channel CRUD + membership endpoints.

Every mutation gates through `app.services.channel_permissions`. Read
endpoints call the same permission helpers so a leaked ID cannot
enumerate hidden Channels.

Deletion is deliberately conservative: the two system Channels
(🌱 Start Here and 🏡 Common Room) can never be deleted; other
Channels can only be deleted when empty (archive is the primary
caretaker action).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.platform import (
    ChannelExperienceLink,
    ChannelMembership,
    CommunityPost,
    ConversationChannel,
    Enrollment,
    Event,
    EventSeries,
    Pathway,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.channel_permissions import (
    accessible_channels_for_user,
    can_archive,
    can_delete,
    can_manage_members,
    is_caretaker,
)
from app.services.channel_types import (
    CREATOR_ASSIGNABLE_TYPES,
    GROUP_LABEL_BY_TYPE,
    LINKED_TYPES,
    icon_for,
)
from app.services import channel_membership as _chm
from app.spaces import area_access, area_policies


member_router = APIRouter(prefix="/api/spaces", tags=["channels-member"])
creator_router = APIRouter(prefix="/api/creator/spaces", tags=["channels-creator"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class ChannelSummary(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    icon_emoji: str | None  # always the type-derived icon (system default)
    channel_type: str
    group_label: str | None  # frontend groups channels by this heading
    is_default: bool
    is_system: bool
    is_archived: bool
    show_in_navigation: bool
    member_posting_allowed: bool
    comments_allowed: bool
    polls_allowed: bool
    scheduling_allowed: bool
    pathway_id: str | None
    gathering_id: str | None
    series_id: str | None = None
    # Human-readable name of the linked Pathway / Gathering / Series,
    # resolved server-side so the Creator Studio card + member selector
    # can render "Linked to · <name>" without a sibling fetch.
    # Populated only for the corresponding channel_type; NULL otherwise.
    pathway_title: str | None = None
    pathway_archived: bool = False
    gathering_title: str | None = None
    gathering_archived: bool = False
    series_title: str | None = None
    series_archived: bool = False
    #: Every linked experience, with its title resolved server-side so
    #: the Creator Studio card and member selector can render a
    #: readable summary without a sibling fetch. The three singular
    #: fields above remain for older clients and name only the first of
    #: each kind.
    linked_experiences: list[LinkedExperienceOut] = Field(default_factory=list)
    unread_count: int = 0  # reserved for future; always 0 today


class ChannelMemberOut(BaseModel):
    user_id: str
    display_name: str
    email: str | None
    role: str
    source: str


class ChannelManageDetail(ChannelSummary):
    """Extra fields creators care about that we don't leak to members."""
    post_count: int
    private_member_count: int
    created_at: datetime
    updated_at: datetime


class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = None
    description: str | None = None
    # Icons are strictly type-driven — no icon input from creators.
    channel_type: str = "open"  # open | private | pathway | gathering | series
    pathway_id: str | None = None
    gathering_id: str | None = None
    series_id: str | None = None
    member_posting_allowed: bool = True
    comments_allowed: bool = True
    polls_allowed: bool = True
    scheduling_allowed: bool = True
    show_in_navigation: bool = True
    initial_member_user_ids: list[str] = Field(default_factory=list)
    #: Any combination of Pathways, Gatherings and Series. Supersedes
    #: the three singular fields above, which are still accepted so an
    #: older client keeps working.
    linked_experiences: list[ExperienceRef] = Field(default_factory=list)


class ChannelUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    # icon_emoji intentionally omitted — icons are type-driven now.
    member_posting_allowed: bool | None = None
    comments_allowed: bool | None = None
    polls_allowed: bool | None = None
    scheduling_allowed: bool | None = None
    show_in_navigation: bool | None = None
    #: The access arrangement. Previously unchangeable after creation,
    #: which is why a channel born from a Pathway could never become an
    #: ordinary open one.
    channel_type: str | None = None
    #: The complete set of links. None means "not supplied, leave
    #: alone" — an edit to the name must not silently unlink
    #: everything.
    linked_experiences: list[ExperienceRef] | None = None
    #: Required when the change lets more people read conversations
    #: that already exist. See ``_broadens_access``.
    confirm_broadening: bool = False


class ExperienceRef(BaseModel):
    """One experience a channel links to."""
    type: str  # pathway | gathering | series
    id: str


class LinkedExperienceOut(ExperienceRef):
    title: str | None = None
    is_archived: bool = False


class ChannelMemberAdd(BaseModel):
    user_ids: list[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_space_or_404(slug: str, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        # Also try draft — creator management surfaces need to reach draft
        # collectives; access is gated by caretaker checks anyway.
        space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(404, detail="Space not found.")
    return space


def _get_channel_or_404(space_id: str, channel_id_or_slug: str, db: Session) -> ConversationChannel:
    q = db.query(ConversationChannel).filter(ConversationChannel.space_id == space_id)
    channel = q.filter(ConversationChannel.id == channel_id_or_slug).first()
    if not channel:
        channel = q.filter(ConversationChannel.slug == channel_id_or_slug).first()
    if not channel:
        raise HTTPException(404, detail="Channel not found.")
    return channel


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str, existing: set[str]) -> str:
    base = _SLUG_RE.sub("-", name.lower()).strip("-") or "channel"
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def ensure_system_channels(
    space_id: str,
    db: Session,
    *,
    created_by: str | None = None,
) -> None:
    """Idempotently provision the two permanent system Channels
    (Start Here + Common Room) for a Space.

    Called from `create_space` so every new collective is born with
    both. Existing collectives are already seeded by migration 077
    (Start Here) and migration 078 (Common Room icon/name). Safe to
    call on any Space — existing system rows are left untouched.
    """
    have = {
        (row.channel_type, row.slug)
        for row in db.query(ConversationChannel.channel_type, ConversationChannel.slug)
        .filter(
            ConversationChannel.space_id == space_id,
            ConversationChannel.is_system.is_(True),
        )
        .all()
    }

    if not any(t == "start_here" for t, _ in have):
        db.add(ConversationChannel(
            id=str(uuid.uuid4()),
            space_id=space_id,
            name="Start Here",
            slug="start-here",
            description=(
                "Welcome, introductions and the little things that help "
                "everyone find their feet here."
            ),
            icon_emoji=None,  # icon comes from channel_type
            channel_type="start_here",
            is_default=False,
            is_system=True,
            show_in_navigation=True,
            position=-10,
            member_posting_allowed=True,
            comments_allowed=True,
            polls_allowed=False,
            scheduling_allowed=True,
            created_by=created_by,
        ))

    if not any(t == "general" for t, _ in have):
        db.add(ConversationChannel(
            id=str(uuid.uuid4()),
            space_id=space_id,
            name="Common Room",
            slug="general",  # keep 'general' slug so URLs stay stable
            description="Where everyday conversations naturally unfold.",
            icon_emoji=None,  # icon comes from channel_type
            channel_type="general",
            is_default=True,
            is_system=True,
            show_in_navigation=True,
            position=0,
            member_posting_allowed=True,
            comments_allowed=True,
            polls_allowed=True,
            scheduling_allowed=True,
            created_by=created_by,
        ))

    db.flush()


def ensure_pathway_channel(
    space_id: str,
    pathway_id: str,
    pathway_title: str,
    db: Session,
    *,
    created_by: str | None = None,
    description: str | None = None,
) -> ConversationChannel:
    """Idempotent: returns the pathway Channel, creating it if missing.

    Called from `create_pathway` (auto-provisioning) and from any
    future migration/backfill that needs to guarantee a Channel per
    Pathway. Safe to call repeatedly.
    """
    existing = (
        db.query(ConversationChannel)
        .filter(
            ConversationChannel.space_id == space_id,
            ConversationChannel.channel_type == "pathway",
            ConversationChannel.pathway_id == pathway_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    slugs = {c[0] for c in db.query(ConversationChannel.slug).filter(
        ConversationChannel.space_id == space_id
    ).all()}
    channel = ConversationChannel(
        id=str(uuid.uuid4()),
        space_id=space_id,
        name=pathway_title.strip(),
        slug=_slugify(pathway_title, slugs),
        description=(description or f"Support and discussion for members completing this pathway.").strip(),
        icon_emoji=None,
        channel_type="pathway",
        is_default=False,
        is_system=False,
        show_in_navigation=True,
        member_posting_allowed=True,
        comments_allowed=True,
        polls_allowed=True,
        scheduling_allowed=True,
        pathway_id=pathway_id,
        created_by=created_by,
    )
    db.add(channel)
    db.flush()
    return channel


def ensure_gathering_channel(
    space_id: str,
    gathering_id: str,
    gathering_title: str,
    db: Session,
    *,
    created_by: str | None = None,
    description: str | None = None,
) -> ConversationChannel:
    """Idempotent: returns the gathering Channel, creating it if missing.

    Access derives from `EventBooking` (status='confirmed'). Attendees
    keep access after the event so conversations naturally continue
    before, during, and after the gathering.
    """
    existing = (
        db.query(ConversationChannel)
        .filter(
            ConversationChannel.space_id == space_id,
            ConversationChannel.channel_type == "gathering",
            ConversationChannel.gathering_id == gathering_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    slugs = {c[0] for c in db.query(ConversationChannel.slug).filter(
        ConversationChannel.space_id == space_id
    ).all()}
    channel = ConversationChannel(
        id=str(uuid.uuid4()),
        space_id=space_id,
        name=gathering_title.strip(),
        slug=_slugify(gathering_title, slugs),
        description=(description or "Everything related to this gathering — before, during and after.").strip(),
        icon_emoji=None,
        channel_type="gathering",
        is_default=False,
        is_system=False,
        show_in_navigation=True,
        member_posting_allowed=True,
        comments_allowed=True,
        polls_allowed=True,
        scheduling_allowed=True,
        gathering_id=gathering_id,
        created_by=created_by,
    )
    db.add(channel)
    db.flush()
    return channel


#: Which arrangements can read which history. Ordered loosest first,
#: so a move up this list is a broadening.
_AUDIENCE_BREADTH = {"private": 0, "pathway": 1, "gathering": 1, "series": 1,
                     "open": 2, "general": 2, "start_here": 2}


def _broadens_access(old_type: str, new_type: str) -> bool:
    """Would this change let more people read what is already posted?

    Private → open is the obvious one. Linked → open is the same
    problem at a smaller scale: a conversation held among the people
    who bought something becomes readable by the whole Collective.

    Narrowing needs no confirmation — nobody is newly exposed — and
    neither does a sideways move between linked types.
    """
    return _AUDIENCE_BREADTH.get(new_type, 2) > _AUDIENCE_BREADTH.get(old_type, 0)


def _validate_experience_refs(
    refs: list[ExperienceRef], space: Space, db: Session,
) -> list[ExperienceRef]:
    """Every reference must name something in THIS Collective.

    The previous code carried a comment promising exactly this and
    then only checked the Series branch, so a caretaker of Collective A
    could link a channel to Collective B's Pathway or Gathering. The
    check now covers all three, which is the point of doing it in one
    place.

    Drafts are allowed deliberately: a creator sets up the channel
    before announcing the Pathway, and an unpublished experience admits
    nobody until it has enrolments, so linking one grants no access.
    """
    from app.models.platform import Event, EventSeries, Pathway

    seen: set[tuple[str, str]] = set()
    out: list[ExperienceRef] = []
    for ref in refs:
        key = (ref.type, ref.id)
        if key in seen:
            continue
        seen.add(key)

        if ref.type == "pathway":
            model, column = Pathway, Pathway.space_id
        elif ref.type == "gathering":
            model, column = Event, Event.space_id
        elif ref.type == "series":
            model, column = EventSeries, EventSeries.space_id
        else:
            raise HTTPException(
                400,
                detail=f"Unknown experience type {ref.type!r}.",
            )
        exists = (
            db.query(model.id)
            .filter(model.id == ref.id, column == space.id)
            .first()
        )
        if exists is None:
            raise HTTPException(
                400,
                detail=(
                    f"That {ref.type} is not in this Collective."
                ),
            )
        out.append(ref)
    return out


def _links_for(channel_ids: list[str], db: Session) -> dict[str, list[ExperienceRef]]:
    """``{channel_id: [refs]}`` in one query, for list endpoints."""
    if not channel_ids:
        return {}
    out: dict[str, list[ExperienceRef]] = {}
    rows = (
        db.query(ChannelExperienceLink)
        .filter(ChannelExperienceLink.channel_id.in_(channel_ids))
        .all()
    )
    for row in rows:
        out.setdefault(row.channel_id, []).append(
            ExperienceRef(type=row.experience_type, id=row.experience_id),
        )
    return out


def _replace_links(
    channel: ConversationChannel,
    refs: list[ExperienceRef],
    db: Session,
    *,
    created_by: str | None,
) -> list[ExperienceRef]:
    """Make the channel's links exactly ``refs``. Returns the new ones.

    Removing a link removes nobody from the channel — that is the §5
    rule, and it is why this returns only the additions: they are the
    ones that need a backfill.
    """
    import uuid as _uuid

    current = {
        (row.experience_type, row.experience_id): row
        for row in db.query(ChannelExperienceLink).filter(
            ChannelExperienceLink.channel_id == channel.id,
        )
    }
    wanted = {(r.type, r.id) for r in refs}

    for key, row in current.items():
        if key not in wanted:
            db.delete(row)

    added: list[ExperienceRef] = []
    for ref in refs:
        if (ref.type, ref.id) in current:
            continue
        db.add(ChannelExperienceLink(
            id=f"cel_{_uuid.uuid4().hex[:16]}",
            channel_id=channel.id,
            pathway_id=ref.id if ref.type == "pathway" else None,
            event_id=ref.id if ref.type == "gathering" else None,
            series_id=ref.id if ref.type == "series" else None,
            created_by=created_by,
        ))
        added.append(ref)
    db.flush()

    # Keep the legacy singular columns in step so anything still
    # reading them, including the permission service's safety net,
    # sees a consistent picture.
    first = {t: i for t, i in reversed([(r.type, r.id) for r in refs])}
    channel.pathway_id = first.get("pathway")
    channel.gathering_id = first.get("gathering")
    channel.series_id = first.get("series")
    return added


def _summary_from(
    channel: ConversationChannel,
    *,
    pathway_titles: dict[str, tuple[str, bool]] | None = None,
    gathering_titles: dict[str, tuple[str, bool]] | None = None,
    series_titles: dict[str, tuple[str, bool]] | None = None,
    links: list[ExperienceRef] | None = None,
) -> ChannelSummary:
    """Serialise a channel row for the wire.

    ``pathway_titles`` / ``gathering_titles`` / ``series_titles`` (all
    optional) are the bulk-lookup maps produced by
    ``_resolve_link_titles``. Values are ``(title, is_archived)``
    tuples. When absent the linked-title fields fall back to NULL —
    safe for callers that don't need them.
    """
    pw_title: str | None = None
    pw_archived = False
    if channel.pathway_id and pathway_titles is not None:
        entry = pathway_titles.get(channel.pathway_id)
        if entry is not None:
            pw_title, pw_archived = entry
    gt_title: str | None = None
    gt_archived = False
    if channel.gathering_id and gathering_titles is not None:
        entry = gathering_titles.get(channel.gathering_id)
        if entry is not None:
            gt_title, gt_archived = entry
    sr_title: str | None = None
    sr_archived = False
    if channel.series_id and series_titles is not None:
        entry = series_titles.get(channel.series_id)
        if entry is not None:
            sr_title, sr_archived = entry
    title_maps = {
        "pathway": pathway_titles or {},
        "gathering": gathering_titles or {},
        "series": series_titles or {},
    }
    linked: list[LinkedExperienceOut] = []
    for ref in (links or []):
        entry = title_maps[ref.type].get(ref.id)
        linked.append(LinkedExperienceOut(
            type=ref.type, id=ref.id,
            title=entry[0] if entry else None,
            is_archived=entry[1] if entry else False,
        ))

    return ChannelSummary(
        id=channel.id,
        slug=channel.slug,
        name=channel.name,
        description=channel.description,
        icon_emoji=icon_for(channel.channel_type, channel.icon_emoji),
        channel_type=channel.channel_type,
        group_label=GROUP_LABEL_BY_TYPE.get(channel.channel_type),
        is_default=channel.is_default,
        is_system=channel.is_system,
        is_archived=channel.is_archived,
        show_in_navigation=channel.show_in_navigation,
        member_posting_allowed=channel.member_posting_allowed,
        comments_allowed=channel.comments_allowed,
        polls_allowed=channel.polls_allowed,
        scheduling_allowed=channel.scheduling_allowed,
        pathway_id=channel.pathway_id,
        gathering_id=channel.gathering_id,
        series_id=channel.series_id,
        pathway_title=pw_title,
        pathway_archived=pw_archived,
        gathering_title=gt_title,
        gathering_archived=gt_archived,
        series_title=sr_title,
        series_archived=sr_archived,
        linked_experiences=linked,
    )


def _resolve_link_titles(
    channels: list[ConversationChannel], db: Session,
    links: dict[str, list[ExperienceRef]] | None = None,
) -> tuple[
    dict[str, tuple[str, bool]],
    dict[str, tuple[str, bool]],
    dict[str, tuple[str, bool]],
]:
    """Bulk-fetch ``(title, is_archived)`` for every linked Pathway /
    Gathering / Series referenced by the given channels. Three
    round-trips total, regardless of channel count."""
    pw_ids = {c.pathway_id for c in channels if c.pathway_id}
    gt_ids = {c.gathering_id for c in channels if c.gathering_id}
    sr_ids = {c.series_id for c in channels if c.series_id}
    # A channel linked to several Gatherings names only the first in
    # its legacy column, so the link rows are the real id set. Without
    # this the second and later experiences render with a null title.
    for refs in (links or {}).values():
        for ref in refs:
            if ref.type == "pathway":
                pw_ids.add(ref.id)
            elif ref.type == "gathering":
                gt_ids.add(ref.id)
            else:
                sr_ids.add(ref.id)
    pathway_titles: dict[str, tuple[str, bool]] = {}
    if pw_ids:
        for row in (
            db.query(Pathway.id, Pathway.title, Pathway.status)
            .filter(Pathway.id.in_(pw_ids))
            .all()
        ):
            status_val = row.status.value if hasattr(row.status, "value") else str(row.status)
            pathway_titles[row.id] = (row.title, status_val == "archived")
    gathering_titles: dict[str, tuple[str, bool]] = {}
    if gt_ids:
        for row in (
            db.query(Event.id, Event.title, Event.status)
            .filter(Event.id.in_(gt_ids))
            .all()
        ):
            status_val = row.status if isinstance(row.status, str) else (
                row.status.value if hasattr(row.status, "value") else str(row.status)
            )
            gathering_titles[row.id] = (row.title, status_val == "archived")
    series_titles: dict[str, tuple[str, bool]] = {}
    if sr_ids:
        for row in (
            db.query(EventSeries.id, EventSeries.title, EventSeries.status)
            .filter(EventSeries.id.in_(sr_ids))
            .all()
        ):
            status_val = row.status if isinstance(row.status, str) else (
                row.status.value if hasattr(row.status, "value") else str(row.status)
            )
            series_titles[row.id] = (row.title, status_val == "archived")
    return pathway_titles, gathering_titles, series_titles


def _detail_from(
    channel: ConversationChannel,
    db: Session,
    *,
    links: list[ExperienceRef] | None = None,
    pathway_titles: dict[str, tuple[str, bool]] | None = None,
    gathering_titles: dict[str, tuple[str, bool]] | None = None,
    series_titles: dict[str, tuple[str, bool]] | None = None,
) -> ChannelManageDetail:
    post_count = (
        db.query(func.count(CommunityPost.id))
        .filter(CommunityPost.channel_id == channel.id)
        .scalar()
    ) or 0
    private_members = (
        db.query(func.count(ChannelMembership.id))
        .filter(
            ChannelMembership.channel_id == channel.id,
            # Tombstones must not inflate the member count a creator
            # reads on the card.
            ChannelMembership.status == "active",
        )
        .scalar()
    ) or 0
    base = _summary_from(
        channel,
        pathway_titles=pathway_titles,
        gathering_titles=gathering_titles,
        series_titles=series_titles,
        links=links,
    ).model_dump()
    return ChannelManageDetail(
        **base,
        post_count=post_count,
        private_member_count=private_members,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


# ---------------------------------------------------------------------------
# Member-facing — list Channels the user can view
# ---------------------------------------------------------------------------


@member_router.get("/{slug}/channels", response_model=list[ChannelSummary])
def list_member_channels(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChannelSummary]:
    space = _get_space_or_404(slug, db)
    # The doorway, before the rooms behind it. The feed, the post
    # detail and search all open with this; without it a member whose
    # Conversations Area is shut could still enumerate the names and
    # descriptions of Channels whose posts they are refused.
    #
    # Safe for the Creator Studio callers of this endpoint: a leader,
    # owner or platform admin reaches every Area unconditionally —
    # ``SpaceViewer.qualifies`` and ``is_leader`` are true for them
    # without a membership row (see ``resolve_area_access``). Only a
    # learner in an ``active_access`` Collective holding no access is
    # newly refused, which is what the feed already does to them.
    area_access.require_area(
        db, space, current_user, area_policies.AREA_CONVERSATIONS,
    )
    channels = accessible_channels_for_user(current_user, space, db, include_archived=True)
    # Members only see Channels the creator chose to surface in navigation.
    # Caretakers still see everything.
    if not is_caretaker(current_user, space, db):
        channels = [c for c in channels if c.show_in_navigation]
    link_map = _links_for([c.id for c in channels], db)
    pw_titles, gt_titles, sr_titles = _resolve_link_titles(
        channels, db, link_map,
    )
    return [
        _summary_from(
            c,
            pathway_titles=pw_titles,
            gathering_titles=gt_titles,
            series_titles=sr_titles,
            links=link_map.get(c.id, []),
        )
        for c in channels
    ]


# ---------------------------------------------------------------------------
# Creator management
# ---------------------------------------------------------------------------


def _require_caretaker(current_user: User, space: Space, db: Session) -> None:
    if not is_caretaker(current_user, space, db):
        raise HTTPException(403, detail="Caretakers only.")


@creator_router.get("/{slug}/channels", response_model=list[ChannelManageDetail])
def list_creator_channels(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChannelManageDetail]:
    space = _get_space_or_404(slug, db)
    _require_caretaker(current_user, space, db)
    channels = (
        db.query(ConversationChannel)
        .filter(ConversationChannel.space_id == space.id)
        .order_by(
            ConversationChannel.is_default.desc(),
            ConversationChannel.is_archived.asc(),
            ConversationChannel.position.asc(),
            ConversationChannel.name.asc(),
        )
        .all()
    )
    link_map = _links_for([c.id for c in channels], db)
    pw_titles, gt_titles, sr_titles = _resolve_link_titles(
        channels, db, link_map,
    )
    return [
        _detail_from(
            c,
            db,
            pathway_titles=pw_titles,
            gathering_titles=gt_titles,
            series_titles=sr_titles,
            links=link_map.get(c.id, []),
        )
        for c in channels
    ]


@creator_router.post("/{slug}/channels", response_model=ChannelManageDetail, status_code=201)
def create_channel(
    slug: str,
    body: ChannelCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelManageDetail:
    space = _get_space_or_404(slug, db)
    _require_caretaker(current_user, space, db)
    if body.channel_type not in CREATOR_ASSIGNABLE_TYPES:
        raise HTTPException(
            400,
            detail="channel_type must be one of: " + ", ".join(CREATOR_ASSIGNABLE_TYPES),
        )
    # Collect the links from either shape: the new list, or the three
    # singular fields an older client still sends.
    refs: list[ExperienceRef] = list(body.linked_experiences)
    if not refs:
        for kind, value in (
            ("pathway", body.pathway_id),
            ("gathering", body.gathering_id),
            ("series", body.series_id),
        ):
            if value:
                refs.append(ExperienceRef(type=kind, id=value))

    if body.channel_type in LINKED_TYPES and not refs:
        raise HTTPException(
            400,
            detail=(
                "A linked-experience Channel needs at least one "
                "Pathway, Gathering or Series."
            ),
        )
    # One validation for all three types. This previously checked only
    # the Series branch despite a comment claiming otherwise, so a
    # caretaker of Collective A could link to Collective B's Pathway or
    # Gathering.
    refs = _validate_experience_refs(refs, space, db)

    existing = {c[0] for c in db.query(ConversationChannel.slug).filter(
        ConversationChannel.space_id == space.id
    ).all()}
    channel_slug = body.slug and body.slug.strip().lower() or None
    if channel_slug and channel_slug in existing:
        raise HTTPException(400, detail="A Channel with that slug already exists.")
    if not channel_slug:
        channel_slug = _slugify(body.name, existing)

    channel = ConversationChannel(
        id=str(uuid.uuid4()),
        space_id=space.id,
        name=body.name.strip(),
        slug=channel_slug,
        description=(body.description or "").strip() or None,
        # Icons are strictly type-driven — never let creators specify.
        icon_emoji=None,
        channel_type=body.channel_type,
        is_default=False,
        is_system=False,
        show_in_navigation=body.show_in_navigation,
        member_posting_allowed=body.member_posting_allowed,
        comments_allowed=body.comments_allowed,
        polls_allowed=body.polls_allowed,
        scheduling_allowed=body.scheduling_allowed,
        created_by=current_user.id,
    )
    db.add(channel)
    db.flush()

    if refs:
        # Writes the link rows and keeps the three legacy columns in
        # step, so the permission service's fallback agrees with them.
        _replace_links(channel, refs, db, created_by=current_user.id)
        # Everyone who already qualifies joins now. A creator linking
        # November's circle to a new channel expects November's
        # attendees to be in it, not just whoever buys next.
        _chm.backfill_channel(db, channel=channel, space=space)

    if body.initial_member_user_ids:
        # Not restricted to private channels any more: a creator
        # seeding a linked channel with a few people is the same
        # action, and `admit` is idempotent so an initial member who
        # also qualifies does not get two rows.
        for uid in dict.fromkeys(body.initial_member_user_ids):
            _chm.admit(
                db, channel_id=channel.id, user_id=uid,
                source=_chm.SOURCE_MANUAL,
            )
    db.commit()
    db.refresh(channel)
    link_map = _links_for([channel.id], db)
    pw_titles, gt_titles, sr_titles = _resolve_link_titles(
        [channel], db, link_map,
    )
    return _detail_from(
        channel, db,
        pathway_titles=pw_titles,
        gathering_titles=gt_titles,
        series_titles=sr_titles,
        links=link_map.get(channel.id, []),
    )


@creator_router.patch("/{slug}/channels/{channel_id}", response_model=ChannelManageDetail)
def update_channel(
    slug: str,
    channel_id: str,
    body: ChannelUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelManageDetail:
    space = _get_space_or_404(slug, db)
    _require_caretaker(current_user, space, db)
    channel = _get_channel_or_404(space.id, channel_id, db)
    # System channels: Start Here is fully locked; Common Room may be
    # renamed and re-described, but nothing else may change.
    if channel.is_system and channel.channel_type == "start_here":
        raise HTTPException(
            400,
            detail="Start Here is a system Channel and cannot be edited.",
        )
    system_general = channel.is_system and channel.channel_type == "general"
    if body.name is not None:
        channel.name = body.name.strip()
    if body.description is not None:
        channel.description = body.description.strip() or None
    for field in ("member_posting_allowed", "comments_allowed", "polls_allowed",
                  "scheduling_allowed", "show_in_navigation"):
        v = getattr(body, field)
        if v is None:
            continue
        if system_general:
            # Only name and description are editable on Common Room.
            continue
        setattr(channel, field, v)

    # ---- Access arrangement -------------------------------------
    if body.channel_type is not None and not system_general:
        if body.channel_type not in CREATOR_ASSIGNABLE_TYPES:
            raise HTTPException(
                400,
                detail="channel_type must be one of: "
                       + ", ".join(CREATOR_ASSIGNABLE_TYPES),
            )
        if body.channel_type != channel.channel_type:
            if _broadens_access(channel.channel_type, body.channel_type) \
                    and not body.confirm_broadening:
                # 409 rather than 400: the request is well-formed and
                # permitted, it just has a consequence the creator has
                # not acknowledged. Silently widening who can read an
                # existing private conversation is the one outcome this
                # endpoint must never produce on its own.
                raise HTTPException(
                    409,
                    detail={
                        "code": "would_broaden_access",
                        "message": (
                            "This change would let more people read "
                            "conversations that already exist in this "
                            "channel. Confirm to continue."
                        ),
                        "from": channel.channel_type,
                        "to": body.channel_type,
                    },
                )
            channel.channel_type = body.channel_type

    # ---- Linked experiences --------------------------------------
    # None means "not supplied". An edit to the name must not unlink
    # everything, which an empty-list default would have done.
    if body.linked_experiences is not None and not system_general:
        refs = _validate_experience_refs(body.linked_experiences, space, db)
        if channel.channel_type in LINKED_TYPES and not refs:
            raise HTTPException(
                400,
                detail=(
                    "A linked-experience Channel needs at least one "
                    "Pathway, Gathering or Series."
                ),
            )
        added = _replace_links(
            channel, refs, db, created_by=current_user.id,
        )
        if added:
            # Only the additions need a backfill. Removing a link
            # removes nobody — see the §5 rule in channel_membership.
            _chm.backfill_channel(db, channel=channel, space=space)
    db.commit()
    db.refresh(channel)
    link_map = _links_for([channel.id], db)
    pw_titles, gt_titles, sr_titles = _resolve_link_titles(
        [channel], db, link_map,
    )
    return _detail_from(
        channel, db,
        pathway_titles=pw_titles,
        gathering_titles=gt_titles,
        series_titles=sr_titles,
        links=link_map.get(channel.id, []),
    )


@creator_router.post("/{slug}/channels/{channel_id}/archive", response_model=ChannelManageDetail)
def archive_channel(
    slug: str,
    channel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelManageDetail:
    space = _get_space_or_404(slug, db)
    channel = _get_channel_or_404(space.id, channel_id, db)
    if not can_archive(current_user, channel, space, db):
        raise HTTPException(403, detail="This Channel cannot be archived.")
    channel.is_archived = True
    channel.archived_at = datetime.utcnow()
    channel.archived_by = current_user.id
    db.commit()
    db.refresh(channel)
    link_map = _links_for([channel.id], db)
    pw_titles, gt_titles, sr_titles = _resolve_link_titles(
        [channel], db, link_map,
    )
    return _detail_from(
        channel, db,
        pathway_titles=pw_titles,
        gathering_titles=gt_titles,
        series_titles=sr_titles,
        links=link_map.get(channel.id, []),
    )


@creator_router.post("/{slug}/channels/{channel_id}/restore", response_model=ChannelManageDetail)
def restore_channel(
    slug: str,
    channel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelManageDetail:
    space = _get_space_or_404(slug, db)
    _require_caretaker(current_user, space, db)
    channel = _get_channel_or_404(space.id, channel_id, db)
    channel.is_archived = False
    channel.archived_at = None
    channel.archived_by = None
    db.commit()
    db.refresh(channel)
    link_map = _links_for([channel.id], db)
    pw_titles, gt_titles, sr_titles = _resolve_link_titles(
        [channel], db, link_map,
    )
    return _detail_from(
        channel, db,
        pathway_titles=pw_titles,
        gathering_titles=gt_titles,
        series_titles=sr_titles,
        links=link_map.get(channel.id, []),
    )


@creator_router.delete("/{slug}/channels/{channel_id}", status_code=204)
def delete_channel(
    slug: str,
    channel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanent deletion — only allowed on empty non-default Channels.

    Archiving is the primary caretaker action; the UI should route
    caretakers to Archive unless the Channel is genuinely empty.
    """
    space = _get_space_or_404(slug, db)
    _require_caretaker(current_user, space, db)
    channel = _get_channel_or_404(space.id, channel_id, db)
    if not can_delete(current_user, channel, space, db):
        raise HTTPException(
            400,
            detail="This Channel is a permanent part of the collective and cannot be deleted.",
        )
    post_count = (
        db.query(func.count(CommunityPost.id))
        .filter(CommunityPost.channel_id == channel.id)
        .scalar()
    ) or 0
    if post_count > 0:
        raise HTTPException(
            400,
            detail=(
                "This Channel still contains conversations. Archive it instead, "
                "or move/delete the contents first."
            ),
        )
    db.delete(channel)
    db.commit()


# ---------------------------------------------------------------------------
# Private-channel membership
# ---------------------------------------------------------------------------


@creator_router.get("/{slug}/channels/{channel_id}/members", response_model=list[ChannelMemberOut])
def list_channel_members(
    slug: str,
    channel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChannelMemberOut]:
    space = _get_space_or_404(slug, db)
    channel = _get_channel_or_404(space.id, channel_id, db)
    if not can_manage_members(current_user, channel, space, db):
        raise HTTPException(403, detail="Caretakers only.")
    rows = (
        db.query(ChannelMembership, User)
        .join(User, User.id == ChannelMembership.user_id)
        .filter(
            ChannelMembership.channel_id == channel.id,
            # Tombstones are bookkeeping, not people in the room.
            ChannelMembership.status == "active",
        )
        .order_by(User.name)
        .all()
    )
    return [
        ChannelMemberOut(
            user_id=u.id,
            display_name=u.name or u.email.split("@")[0],
            email=u.email,
            role=m.role,
            source=m.source,
        )
        for m, u in rows
    ]


@creator_router.post("/{slug}/channels/{channel_id}/members", response_model=list[ChannelMemberOut])
def add_channel_members(
    slug: str,
    channel_id: str,
    body: ChannelMemberAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChannelMemberOut]:
    space = _get_space_or_404(slug, db)
    channel = _get_channel_or_404(space.id, channel_id, db)
    if not can_manage_members(current_user, channel, space, db):
        raise HTTPException(403, detail="Caretakers only.")
    # Private AND linked channels both have real membership now, so a
    # creator can add somebody to a Gathering channel who never bought
    # a ticket — which is the point of "creators decide who belongs".
    # Open channels still derive their audience from the Collective.
    if channel.channel_type not in ("private", *LINKED_TYPES):
        raise HTTPException(
            400,
            detail=(
                "Open Channels include every Collective member, so they "
                "have no separate membership list."
            ),
        )
    # Only add users who are active Space members.
    active = {
        r.user_id for r in db.query(SpaceMembership.user_id).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.user_id.in_(body.user_ids),
        ).all()
    }
    for uid in dict.fromkeys(body.user_ids):
        if uid not in active:
            continue
        # ``manual`` source, which matters twice: it lifts a previous
        # creator removal (nothing else may), and it protects them from
        # being swept out again if their experience access is revoked.
        _chm.admit(
            db, channel_id=channel.id, user_id=uid,
            source=_chm.SOURCE_MANUAL,
        )
    db.commit()
    return list_channel_members(slug, channel_id, db, current_user)


@creator_router.delete("/{slug}/channels/{channel_id}/members/{user_id}", status_code=204)
def remove_channel_member(
    slug: str,
    channel_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    space = _get_space_or_404(slug, db)
    channel = _get_channel_or_404(space.id, channel_id, db)
    if not can_manage_members(current_user, channel, space, db):
        raise HTTPException(403, detail="Caretakers only.")
    # A tombstone, not a DELETE. The row's absence is what an
    # automatic admission would read as "never joined, and qualifies,
    # so add them" — so deleting it would mean the member's next
    # purchase quietly undid this decision.
    #
    # It takes nothing else away: no booking is cancelled, no Pathway
    # access revoked, no payment touched, no Collective membership
    # changed, and their existing posts and replies stay where they
    # are.
    _chm.remove(
        db,
        channel_id=channel.id,
        user_id=user_id,
        reason=_chm.REASON_CREATOR,
        actor_user_id=current_user.id,
    )
    db.commit()
