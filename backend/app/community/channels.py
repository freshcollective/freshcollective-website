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
    ChannelMembership,
    CommunityPost,
    ConversationChannel,
    Enrollment,
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
    icon_for,
)


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
    channel_type: str = "open"  # open | private | pathway | gathering
    pathway_id: str | None = None
    gathering_id: str | None = None
    member_posting_allowed: bool = True
    comments_allowed: bool = True
    polls_allowed: bool = True
    scheduling_allowed: bool = True
    show_in_navigation: bool = True
    initial_member_user_ids: list[str] = Field(default_factory=list)


class ChannelUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    # icon_emoji intentionally omitted — icons are type-driven now.
    member_posting_allowed: bool | None = None
    comments_allowed: bool | None = None
    polls_allowed: bool | None = None
    scheduling_allowed: bool | None = None
    show_in_navigation: bool | None = None


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


def _summary_from(channel: ConversationChannel) -> ChannelSummary:
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
    )


def _detail_from(channel: ConversationChannel, db: Session) -> ChannelManageDetail:
    post_count = (
        db.query(func.count(CommunityPost.id))
        .filter(CommunityPost.channel_id == channel.id)
        .scalar()
    ) or 0
    private_members = (
        db.query(func.count(ChannelMembership.id))
        .filter(ChannelMembership.channel_id == channel.id)
        .scalar()
    ) or 0
    base = _summary_from(channel).model_dump()
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
    channels = accessible_channels_for_user(current_user, space, db, include_archived=True)
    # Members only see Channels the creator chose to surface in navigation.
    # Caretakers still see everything.
    if not is_caretaker(current_user, space, db):
        channels = [c for c in channels if c.show_in_navigation]
    return [_summary_from(c) for c in channels]


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
    return [_detail_from(c, db) for c in channels]


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
    if body.channel_type == "pathway" and not body.pathway_id:
        raise HTTPException(400, detail="Pathway Channels require pathway_id.")
    if body.channel_type == "gathering" and not body.gathering_id:
        raise HTTPException(400, detail="Gathering Channels require gathering_id.")

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
        pathway_id=body.pathway_id if body.channel_type == "pathway" else None,
        gathering_id=body.gathering_id if body.channel_type == "gathering" else None,
        created_by=current_user.id,
    )
    db.add(channel)
    db.flush()
    if body.channel_type == "private" and body.initial_member_user_ids:
        for uid in dict.fromkeys(body.initial_member_user_ids):  # dedupe
            db.add(ChannelMembership(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                user_id=uid,
                source="manual",
            ))
    db.commit()
    db.refresh(channel)
    return _detail_from(channel, db)


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
    db.commit()
    db.refresh(channel)
    return _detail_from(channel, db)


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
    return _detail_from(channel, db)


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
    return _detail_from(channel, db)


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
        .filter(ChannelMembership.channel_id == channel.id)
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
    # Only meaningful for private channels; open/pathway derive access
    # from their own sources so silently no-op the add.
    if channel.channel_type != "private":
        raise HTTPException(400, detail="Only private Channels have manual membership.")
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
        row = ChannelMembership(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            user_id=uid,
            source="manual",
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # already a member
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
    (
        db.query(ChannelMembership)
        .filter(
            ChannelMembership.channel_id == channel.id,
            ChannelMembership.user_id == user_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
