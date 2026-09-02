"""Community routes — posts, comments, polls, reactions, search.

Community Phase 1 additions:
  - Extended post_type vocabulary (poll, question, celebration, share).
  - Poll create + vote endpoints; results computed at read time.
  - @mention resolution on write (client-authored, server-validated).
  - Threaded comment replies (`parent_comment_id`).
  - Member search endpoint for @-autocomplete.
  - Community search endpoint (ILIKE, scoped to current space).
  - Notification triggers for mentions, comment replies, and
    caretaker-answered questions.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.storage import save_media_file
from app.models.platform import (
    CommunityPost,
    CommentReaction,
    ConversationChannel,
    Poll,
    PollOption,
    PollVote,
    PostComment,
    PostReaction,
    PostType,
    Space,
    SpaceMembership,
    SpaceRole,
    SpaceMembershipStatus,
)
from app.models.user import User
from app.community.mentions import sanitize_mentions
from app.community.sanitize import sanitize_post_body
from app.community.schemas import (
    ALLOWED_REACTION_EMOJIS,
    CastVoteRequest,
    CommentItem,
    CreateCommentRequest,
    CreatePostRequest,
    MemberSuggestion,
    PollInput,
    PollOptionView,
    PollView,
    PostAuthor,
    PostDetail,
    PostSummary,
    ReactionCount,
    SearchHit,
    SearchResponse,
)
from app.services.notification_service import (
    trigger_caretaker_reply_to_question,
    trigger_comment_reply,
    trigger_mention,
    trigger_new_post,
    trigger_reply_to_comment,
)
from app.services.scheduled_publisher import publish_due_posts
from app.services.channel_permissions import (
    accessible_channels_for_user,
    accessible_user_ids_for_channel,
    can_comment,
    can_post,
    can_react,
    can_view_channel,
    is_active_space_member,
    is_caretaker,
)

router = APIRouter(prefix="/api/spaces", tags=["community"])


def _emit_comment_created(db, background_tasks, *, post, comment, commenter, space) -> None:
    """R2A helper — emit ``community.comment.created`` and schedule
    the routing pipeline. The event's payload carries the post
    author id (the sole recipient the resolver returns) plus the
    view URL and commenter name so the template can render without
    re-querying the DB.
    """
    from app.comms import Source, emit as comms_emit
    from app.comms.rollout import schedule_routing_if_needed
    from app.core.config import settings as _settings

    post_title = getattr(post, "title", None) or "your post"
    commenter_name = getattr(commenter, "name", None) or "Someone"
    view_url = (
        f"{_settings.frontend_origin.rstrip('/')}/spaces/{space.slug}/community/{post.id}"
        if space else ""
    )

    ev = comms_emit(
        db,
        event_type="community.comment.created",
        source_type=Source.CREATOR,
        source_id=commenter.id,
        actor_user_id=commenter.id,
        subject_type="post_comment",
        subject_id=comment.id,
        context={"space_id": space.id if space else None},
        payload={
            "post_id":         post.id,
            "post_author_id":  post.author_id,
            "post_title":      post_title,
            "comment_id":      comment.id,
            "commenter_name":  commenter_name,
            "view_url":        view_url,
        },
    )
    db.commit()
    schedule_routing_if_needed(background_tasks, ev, "community.comment.created")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_space_or_404(slug: str, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _get_channel_by_slug_or_default(
    space: Space, channel_slug: str | None, db: Session,
) -> ConversationChannel:
    """Look up a Channel by slug within the Space, or return the
    Space's default Common Room when no slug is given."""
    q = db.query(ConversationChannel).filter(ConversationChannel.space_id == space.id)
    if channel_slug:
        c = q.filter(ConversationChannel.slug == channel_slug).first()
        if not c:
            raise HTTPException(404, detail="Channel not found.")
        return c
    c = q.filter(ConversationChannel.is_default.is_(True)).first()
    if not c:
        raise HTTPException(500, detail="Space has no default Channel — migration missing.")
    return c


def _get_channel_for_post(post: CommunityPost, db: Session) -> ConversationChannel:
    c = db.query(ConversationChannel).filter(ConversationChannel.id == post.channel_id).first()
    if not c:
        # Should be impossible after migration 076 — but be defensive.
        raise HTTPException(500, detail="Post has no Channel.")
    return c


def _build_author(user: User) -> PostAuthor:
    return PostAuthor(id=user.id, name=user.name, email=user.email)


def _build_post_reactions(post_reactions: list[PostReaction], current_user_id: str) -> list[ReactionCount]:
    counts: dict[str, int] = {}
    reacted: set[str] = set()
    for r in post_reactions:
        counts[r.emoji] = counts.get(r.emoji, 0) + 1
        if r.user_id == current_user_id:
            reacted.add(r.emoji)
    return [ReactionCount(emoji=e, count=c, reacted=e in reacted) for e, c in counts.items()]


def _build_comment_reactions(comment_reactions: list[CommentReaction], current_user_id: str) -> list[ReactionCount]:
    counts: dict[str, int] = {}
    reacted: set[str] = set()
    for r in comment_reactions:
        counts[r.emoji] = counts.get(r.emoji, 0) + 1
        if r.user_id == current_user_id:
            reacted.add(r.emoji)
    return [ReactionCount(emoji=e, count=c, reacted=e in reacted) for e, c in counts.items()]


def _resolve_post_type(raw: str) -> PostType:
    """Coerce the string post_type from the wire into the enum."""
    try:
        return PostType(raw)
    except ValueError:
        return PostType.reflection


def _post_type_str(pt: object) -> str:
    return pt.value if hasattr(pt, "value") else str(pt)


# ---------------------------------------------------------------------------
# Poll helpers
# ---------------------------------------------------------------------------


def _build_poll_view(
    poll: Poll | None,
    db: Session,
    current_user_id: str,
) -> PollView | None:
    if poll is None:
        return None
    votes = poll.votes
    total_voters = len({v.user_id for v in votes})
    my_option_ids = {v.option_id for v in votes if v.user_id == current_user_id}
    user_has_voted = bool(my_option_ids)
    is_closed = poll.closes_at is not None and poll.closes_at <= datetime.utcnow()
    show_results = poll.show_results_before_vote or user_has_voted or is_closed

    option_counts: dict[str, int] = {}
    for v in votes:
        option_counts[v.option_id] = option_counts.get(v.option_id, 0) + 1

    options = [
        PollOptionView(
            id=o.id,
            label=o.label,
            position=o.position,
            vote_count=option_counts.get(o.id, 0) if show_results else 0,
            voted=o.id in my_option_ids,
        )
        for o in poll.options
    ]

    return PollView(
        allow_multiple=poll.allow_multiple,
        is_anonymous=poll.is_anonymous,
        show_results_before_vote=poll.show_results_before_vote,
        closes_at=poll.closes_at,
        total_voters=total_voters if show_results else 0,
        user_has_voted=user_has_voted,
        can_edit=total_voters == 0,
        is_closed=is_closed,
        show_results=show_results,
        options=options,
    )


def _create_poll_for_post(poll_input: PollInput, post: CommunityPost, db: Session) -> Poll:
    poll = Poll(
        post_id=post.id,
        allow_multiple=poll_input.allow_multiple,
        is_anonymous=poll_input.is_anonymous,
        show_results_before_vote=poll_input.show_results_before_vote,
        closes_at=poll_input.closes_at,
    )
    db.add(poll)
    for i, opt in enumerate(poll_input.options):
        db.add(PollOption(
            id=str(uuid.uuid4()),
            poll_id=post.id,
            position=i,
            label=opt.label.strip(),
        ))
    return poll


# ---------------------------------------------------------------------------
# Community feed
# ---------------------------------------------------------------------------

@router.get("/{slug}/community", response_model=list[PostSummary])
def list_community_posts(
    slug: str,
    channel: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PostSummary]:
    """Return visible published posts in a Channel — pinned first,
    then newest. Scheduled posts are excluded until the publisher
    transitions them. When `channel` is omitted, the Space's default
    Common Room is used."""
    space = _get_space_or_404(slug, db)

    # Resolve + authorise the Channel.
    target = _get_channel_by_slug_or_default(space, channel, db)
    if not can_view_channel(current_user, target, space, db):
        # 404 rather than 403 so guessed private Channels don't leak.
        raise HTTPException(404, detail="Channel not found.")

    # Belt-and-braces: publish any due posts before we query the feed, so
    # a member request never observes a stale "just missed publish time"
    # state even if the background loop is delayed.
    try:
        publish_due_posts(db)
    except Exception:
        # Non-fatal — the loop will catch up.
        pass

    posts = (
        db.query(CommunityPost)
        .options(
            joinedload(CommunityPost.author),
            joinedload(CommunityPost.reactions),
            joinedload(CommunityPost.poll).joinedload(Poll.options),
            joinedload(CommunityPost.poll).joinedload(Poll.votes),
        )
        .filter(
            CommunityPost.space_id == space.id,
            CommunityPost.channel_id == target.id,
            CommunityPost.is_visible.is_(True),
            # Community Care — hide any post currently held by a CC action
            CommunityPost.cc_hidden_at.is_(None),
            CommunityPost.publication_status == "published",
        )
        .order_by(CommunityPost.is_pinned.desc(), CommunityPost.created_at.desc())
        .all()
    )

    if not posts:
        return []

    post_ids = [p.id for p in posts]
    # Comment counts are naturally scoped to the (already filtered)
    # post_ids list, so no extra publication filter is needed here —
    # scheduled posts simply aren't in post_ids.
    comment_counts: dict[str, int] = dict(
        db.query(PostComment.post_id, func.count(PostComment.id))
        .filter(
            PostComment.post_id.in_(post_ids),
            PostComment.is_visible.is_(True),
            PostComment.cc_hidden_at.is_(None),
        )
        .group_by(PostComment.post_id)
        .all()
    )

    return [
        PostSummary(
            id=p.id,
            post_type=_post_type_str(p.post_type),
            title=p.title,
            body=p.body,
            image_url=p.image_url,
            is_pinned=p.is_pinned,
            author=_build_author(p.author),
            comment_count=comment_counts.get(p.id, 0),
            created_at=p.created_at,
            reactions=_build_post_reactions(p.reactions, current_user.id),
            mentioned_user_ids=list(p.mentioned_user_ids or []),
            poll=_build_poll_view(p.poll, db, current_user.id),
            publication_status=p.publication_status,
            scheduled_for=p.scheduled_for,
            scheduling_timezone=p.scheduling_timezone,
            published_at=p.published_at,
        )
        for p in posts
    ]


# ---------------------------------------------------------------------------
# Single post with comments
# ---------------------------------------------------------------------------

@router.get("/{slug}/community/{post_id}", response_model=PostDetail)
def get_community_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostDetail:
    space = _get_space_or_404(slug, db)
    post = (
        db.query(CommunityPost)
        .options(
            joinedload(CommunityPost.author),
            joinedload(CommunityPost.reactions),
            joinedload(CommunityPost.comments).joinedload(PostComment.author),
            joinedload(CommunityPost.comments).joinedload(PostComment.reactions),
            joinedload(CommunityPost.poll).joinedload(Poll.options),
            joinedload(CommunityPost.poll).joinedload(Poll.votes),
        )
        .filter(
            CommunityPost.id == post_id,
            CommunityPost.space_id == space.id,
            CommunityPost.is_visible.is_(True),
        )
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    # Community Care — hide a CC-held post from non-admin viewers.
    if post.cc_hidden_at is not None and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    # Channel access gate — a guessed post ID can't leak private / pathway
    # / archived-to-non-members content. 404 rather than 403 to avoid
    # confirming that a specific ID exists.
    channel = _get_channel_for_post(post, db)
    if not can_view_channel(current_user, channel, space, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    # Only caretakers can preview a scheduled post via its direct URL;
    # everyone else sees a 404, so a guessed post ID can't leak
    # unpublished content.
    if post.publication_status != "published" and not _can_moderate(current_user, space, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    # Community Care — cc-hidden comments are invisible to non-admins,
    # same as posts. Admins still see them via the review surface.
    is_admin_viewer = current_user.role == "admin"
    visible_comments = [
        c for c in post.comments
        if c.is_visible and (is_admin_viewer or c.cc_hidden_at is None)
    ]
    # Map author_id → display name so replies can show "in reply to @name"
    # without an extra fetch per comment.
    author_names = {c.author_id: (c.author.name or c.author.email.split("@")[0])
                    for c in visible_comments}

    return PostDetail(
        id=post.id,
        post_type=_post_type_str(post.post_type),
        title=post.title,
        body=post.body,
        image_url=post.image_url,
        is_pinned=post.is_pinned,
        author=_build_author(post.author),
        comments=[
            CommentItem(
                id=c.id,
                body=c.body,
                image_url=c.image_url,
                author=_build_author(c.author),
                created_at=c.created_at,
                reactions=_build_comment_reactions(c.reactions, current_user.id),
                parent_comment_id=c.parent_comment_id,
                parent_author_name=(
                    author_names.get(_parent_author_id(c, visible_comments))
                    if c.parent_comment_id else None
                ),
                mentioned_user_ids=list(c.mentioned_user_ids or []),
            )
            for c in visible_comments
        ],
        created_at=post.created_at,
        reactions=_build_post_reactions(post.reactions, current_user.id),
        mentioned_user_ids=list(post.mentioned_user_ids or []),
        poll=_build_poll_view(post.poll, db, current_user.id),
        publication_status=post.publication_status,
        scheduled_for=post.scheduled_for,
        scheduling_timezone=post.scheduling_timezone,
        published_at=post.published_at,
    )


def _parent_author_id(comment: PostComment, all_comments: list[PostComment]) -> str | None:
    if not comment.parent_comment_id:
        return None
    for c in all_comments:
        if c.id == comment.parent_comment_id:
            return c.author_id
    return None


# ---------------------------------------------------------------------------
# Create post
# ---------------------------------------------------------------------------

@router.post("/{slug}/community", response_model=PostSummary, status_code=status.HTTP_201_CREATED)
def create_community_post(
    slug: str,
    body: CreatePostRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PostSummary:
    space = _get_space_or_404(slug, db)

    # Community Care — freeze and posting-restriction gates. Both
    # apply here regardless of caretaker status; a member with an
    # active posting restriction cannot post even in an unfrozen
    # collective, and a frozen collective cannot receive new content
    # even from its caretakers.
    from app.community_care.shared import (
        has_active_posting_restriction, is_space_closed, is_space_frozen,
    )
    if is_space_closed(space):
        raise HTTPException(403, detail="This collective has been closed.")
    if is_space_frozen(space):
        raise HTTPException(403, detail="This collective is temporarily paused by Fresh Collective.")
    if has_active_posting_restriction(db, current_user.id, space.id):
        raise HTTPException(403, detail="Your posting is temporarily restricted by Fresh Collective.")

    post_type_str = body.validate_post_type()
    if post_type_str == "poll" and body.poll is None:
        raise HTTPException(400, detail="A poll post must include poll options.")
    if body.poll is not None and post_type_str != "poll":
        # Silently coerce — a poll payload always implies a poll post.
        post_type_str = "poll"

    # Resolve destination Channel + gate on can_post. Falls back to the
    # Space's Common Room when the client omits `channel_slug` —
    # keeps existing composers working without changes.
    target_channel = _get_channel_by_slug_or_default(space, body.channel_slug, db)
    if not can_post(current_user, target_channel, space, db):
        raise HTTPException(403, detail="You cannot post to this Channel.")
    if target_channel.is_archived:
        raise HTTPException(400, detail="This Channel is archived and cannot receive new posts.")
    if post_type_str == "poll" and not target_channel.polls_allowed:
        raise HTTPException(400, detail="Polls are disabled in this Channel.")

    # Determine caretaker status once — controls scheduling + pinning.
    caretaker = _can_moderate(current_user, space, db)

    # Scheduling gates (creator-only, active-collective-only, future time,
    # poll close date must be after publish time).
    scheduled_for: datetime | None = body.scheduled_for
    scheduling_timezone: str | None = None
    if scheduled_for is not None:
        if not caretaker:
            raise HTTPException(403, detail="Only caretakers can schedule posts.")
        if space.status != "active":
            raise HTTPException(
                400,
                detail="This collective must be published before conversations can be scheduled.",
            )
        # Normalise to naive UTC — the DB column has no timezone.
        if scheduled_for.tzinfo is not None:
            scheduled_for = scheduled_for.astimezone(tz=None).replace(tzinfo=None)
        if scheduled_for <= datetime.utcnow():
            raise HTTPException(400, detail="Scheduled time must be in the future.")
        if body.poll is not None and body.poll.closes_at is not None:
            close = body.poll.closes_at
            if close.tzinfo is not None:
                close = close.astimezone(tz=None).replace(tzinfo=None)
            if close <= scheduled_for:
                raise HTTPException(
                    400,
                    detail="Poll close date must be after the scheduled publication time.",
                )
        scheduling_timezone = (body.scheduling_timezone or space.timezone or None)

    # Pinning — only caretakers may pin at create time. Members silently
    # get is_pinned=False so an ordinary composer request can't sneak
    # a post to the top of the feed.
    is_pinned = bool(body.is_pinned and caretaker)

    mentioned = sanitize_mentions(db, space.id, current_user.id, body.mentioned_user_ids)

    now = datetime.utcnow()
    publication_status = "scheduled" if scheduled_for is not None else "published"
    post = CommunityPost(
        id=str(uuid.uuid4()),
        space_id=space.id,
        channel_id=target_channel.id,
        author_id=current_user.id,
        post_type=_resolve_post_type(post_type_str),
        title=body.title or None,
        # SEC-001 — sanitise at the write boundary so every render
        # surface (including dangerouslySetInnerHTML sinks) can trust
        # what it reads back.
        body=sanitize_post_body(body.body.strip()),
        image_url=body.image_url or None,
        mentioned_user_ids=mentioned,
        is_pinned=is_pinned,
        is_visible=True,
        publication_status=publication_status,
        scheduled_for=scheduled_for,
        scheduling_timezone=scheduling_timezone,
        published_at=None if publication_status == "scheduled" else now,
        notifications_processed_at=None if publication_status == "scheduled" else now,
    )
    db.add(post)
    if body.poll is not None:
        _create_poll_for_post(body.poll, post, db)
    db.commit()
    db.refresh(post)

    if publication_status == "published":
        background_tasks.add_task(trigger_new_post, post.id, space.id, current_user.id)
        for uid in mentioned:
            background_tasks.add_task(
                trigger_mention, post.id, None, current_user.id, uid,
            )
        # Communications Layer (M5c) — emit the event alongside the
        # legacy trigger. Shadow mode observes; live mode swaps in
        # (the legacy trigger no-ops when the topic is live).
        from app.comms import Source, emit as comms_emit
        from app.comms.rollout import schedule_routing_if_needed
        _comms_event = comms_emit(
            db,
            event_type="community.post.published",
            source_type=Source.CREATOR,
            source_id=current_user.id,
            actor_user_id=current_user.id,
            subject_type="post", subject_id=post.id,
            context={"space_id": space.id, "collective_name": space.name},
            payload={"post_id": post.id, "excerpt": (body.body or "")[:280]},
        )
        db.commit()
        schedule_routing_if_needed(
            background_tasks, _comms_event, "community.post.published",
        )
    # For scheduled posts: no triggers fire now. The publisher loop
    # (or on-demand publish check) fires them at publication time and
    # stamps `notifications_processed_at` so retries can't duplicate.

    return PostSummary(
        id=post.id,
        post_type=_post_type_str(post.post_type),
        title=post.title,
        body=post.body,
        image_url=post.image_url,
        is_pinned=post.is_pinned,
        author=_build_author(current_user),
        comment_count=0,
        created_at=post.created_at,
        reactions=[],
        mentioned_user_ids=mentioned,
        poll=_build_poll_view(post.poll, db, current_user.id),
        publication_status=post.publication_status,
        scheduled_for=post.scheduled_for,
        scheduling_timezone=post.scheduling_timezone,
        published_at=post.published_at,
    )


# ---------------------------------------------------------------------------
# Create comment
# ---------------------------------------------------------------------------

@router.post(
    "/{slug}/community/{post_id}/comments",
    response_model=CommentItem,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    slug: str,
    post_id: str,
    body: CreateCommentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommentItem:
    space = _get_space_or_404(slug, db)

    # Community Care — freeze / posting-restriction gates apply before
    # any post-shape checks so the responses are consistent regardless
    # of whether the target post exists.
    from app.community_care.shared import (
        has_active_posting_restriction, is_post_cc_hidden, is_space_frozen,
    )
    if is_space_frozen(space):
        raise HTTPException(403, detail="This collective is temporarily paused by Fresh Collective.")
    if has_active_posting_restriction(db, current_user.id, space.id):
        raise HTTPException(403, detail="Your posting is temporarily restricted by Fresh Collective.")

    post = (
        db.query(CommunityPost)
        .filter(
            CommunityPost.id == post_id,
            CommunityPost.space_id == space.id,
            CommunityPost.is_visible.is_(True),
        )
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    # A CC-hidden post is invisible to members; comments cannot be
    # attached to it while the review is in progress.
    if is_post_cc_hidden(post):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    # Scheduled posts don't accept comments until they publish — the
    # composer isn't visible to members, but guard the endpoint too so
    # a direct request can't sneak comments onto an unpublished post.
    if post.publication_status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    # Channel gate for both view (guessed IDs) and comment permission.
    parent_channel = _get_channel_for_post(post, db)
    if not can_view_channel(current_user, parent_channel, space, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    if not can_comment(current_user, parent_channel, space, db):
        raise HTTPException(403, detail="Comments are not allowed in this Channel.")

    parent: PostComment | None = None
    if body.parent_comment_id:
        parent = (
            db.query(PostComment)
            .filter(
                PostComment.id == body.parent_comment_id,
                PostComment.post_id == post.id,
                PostComment.is_visible.is_(True),
            )
            .first()
        )
        if not parent:
            raise HTTPException(400, detail="Parent comment not found.")

    mentioned = sanitize_mentions(db, space.id, current_user.id, body.mentioned_user_ids)

    comment = PostComment(
        id=str(uuid.uuid4()),
        post_id=post.id,
        author_id=current_user.id,
        body=body.body.strip(),
        image_url=body.image_url or None,
        parent_comment_id=parent.id if parent else None,
        mentioned_user_ids=mentioned,
        is_visible=True,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Notifications — layered so the same commenter never receives two
    # notifications for the same event (handled inside the triggers).
    if parent is not None:
        background_tasks.add_task(
            trigger_reply_to_comment,
            post.id, comment.id, parent.id, current_user.id,
        )
    else:
        background_tasks.add_task(
            trigger_comment_reply, post.id, comment.id, current_user.id,
        )
        # R2A: emit the comms event alongside the legacy in-app
        # notification trigger. The trigger continues to create the
        # in-app notification row; its email-send step is guarded by
        # `_rollout_is_live("community.comment.created")` and no-ops
        # once the topic is live. Comms handles the email through the
        # routing pipeline instead.
        if post.author_id != current_user.id:
            _emit_comment_created(
                db, background_tasks,
                post=post, comment=comment, commenter=current_user,
                space=space,
            )
    for uid in mentioned:
        background_tasks.add_task(
            trigger_mention, post.id, comment.id, current_user.id, uid,
        )
    if post.post_type == PostType.question and post.author_id != current_user.id:
        # If the commenter is a caretaker (space creator/moderator or
        # platform admin/creator), the question author gets an extra
        # ping — resolved inside the trigger.
        background_tasks.add_task(
            trigger_caretaker_reply_to_question,
            post.id, comment.id, current_user.id,
        )

    parent_author_name = None
    if parent is not None:
        parent_author = db.query(User).filter(User.id == parent.author_id).first()
        if parent_author:
            parent_author_name = parent_author.name or parent_author.email.split("@")[0]

    return CommentItem(
        id=comment.id,
        body=comment.body,
        image_url=comment.image_url,
        author=_build_author(current_user),
        created_at=comment.created_at,
        reactions=[],
        parent_comment_id=comment.parent_comment_id,
        parent_author_name=parent_author_name,
        mentioned_user_ids=mentioned,
    )


# ---------------------------------------------------------------------------
# Poll voting
# ---------------------------------------------------------------------------

@router.post("/{slug}/community/{post_id}/poll/vote", response_model=PollView)
def vote_on_poll(
    slug: str,
    post_id: str,
    body: CastVoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PollView:
    space = _get_space_or_404(slug, db)

    # Community Care — voting is a posting-shaped action; block on
    # freeze or posting restriction.
    from app.community_care.shared import (
        has_active_posting_restriction, is_space_closed, is_space_frozen,
    )
    if is_space_closed(space):
        raise HTTPException(403, detail="This collective has been closed.")
    if is_space_frozen(space):
        raise HTTPException(403, detail="This collective is temporarily paused by Fresh Collective.")
    if has_active_posting_restriction(db, current_user.id, space.id):
        raise HTTPException(403, detail="Your posting is temporarily restricted by Fresh Collective.")

    poll = (
        db.query(Poll)
        .join(CommunityPost, CommunityPost.id == Poll.post_id)
        .filter(
            Poll.post_id == post_id,
            CommunityPost.space_id == space.id,
            CommunityPost.is_visible.is_(True),
            CommunityPost.cc_hidden_at.is_(None),
            # Scheduled polls cannot be voted on until they publish.
            CommunityPost.publication_status == "published",
        )
        .first()
    )
    if not poll:
        raise HTTPException(404, detail="Poll not found.")

    # Channel access gate — no vote-by-guessed-URL into a hidden Channel.
    parent_post = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
    if parent_post is None:
        raise HTTPException(404, detail="Poll not found.")
    poll_channel = _get_channel_for_post(parent_post, db)
    if not can_view_channel(current_user, poll_channel, space, db):
        raise HTTPException(404, detail="Poll not found.")
    if poll_channel.is_archived:
        raise HTTPException(400, detail="This Channel is archived.")
    if poll.closes_at is not None and poll.closes_at <= datetime.utcnow():
        raise HTTPException(400, detail="This poll has closed.")

    valid_option_ids = {o.id for o in poll.options}
    chosen = [oid for oid in body.option_ids if oid in valid_option_ids]

    if not poll.allow_multiple and len(chosen) > 1:
        raise HTTPException(400, detail="This poll accepts a single choice only.")

    # Replace the current voter's votes wholesale so single/multi swap
    # semantics are simple: "here is my current set of choices".
    db.query(PollVote).filter(
        PollVote.poll_id == poll.post_id,
        PollVote.user_id == current_user.id,
    ).delete(synchronize_session=False)
    for oid in chosen:
        db.add(PollVote(
            id=str(uuid.uuid4()),
            poll_id=poll.post_id,
            option_id=oid,
            user_id=current_user.id,
        ))
    db.commit()

    # Refresh vote list for the view builder.
    db.refresh(poll)
    return _build_poll_view(poll, db, current_user.id)


# ---------------------------------------------------------------------------
# Member search — used by @mention autocomplete
# ---------------------------------------------------------------------------

@router.get("/{slug}/members/search", response_model=list[MemberSuggestion])
def search_space_members(
    slug: str,
    q: str = "",
    limit: int = 8,
    channel: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MemberSuggestion]:
    """Autocomplete-friendly member lookup, strictly scoped to the
    current collective. If `channel` is passed, results are additionally
    narrowed to users who can access that Channel — a user must never be
    mentionable into a conversation they cannot open."""
    space = _get_space_or_404(slug, db)

    # Channel scope (mention autocomplete). Absent → treat as if the
    # caller is in the default Common Room so open-Channel behaviour
    # is preserved for existing callers.
    target_channel = _get_channel_by_slug_or_default(space, channel, db)
    if not can_view_channel(current_user, target_channel, space, db):
        raise HTTPException(404, detail="Channel not found.")
    allowed_ids = accessible_user_ids_for_channel(target_channel, space, db)

    query = (
        db.query(User, SpaceMembership.role)
        .join(SpaceMembership, SpaceMembership.user_id == User.id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            User.id.in_(allowed_ids) if allowed_ids else False,
        )
    )
    q_stripped = q.strip()
    if q_stripped:
        pattern = f"%{q_stripped}%"
        query = query.filter(
            or_(User.name.ilike(pattern), User.email.ilike(pattern))
        )
    rows = query.order_by(User.name).limit(max(1, min(limit, 20))).all()
    return [
        MemberSuggestion(
            id=u.id,
            display_name=u.name or u.email.split("@")[0],
            avatar_url=getattr(u, "avatar_url", None),
            role=role.value if hasattr(role, "value") else str(role),
        )
        for u, role in rows
    ]


# ---------------------------------------------------------------------------
# Community search
# ---------------------------------------------------------------------------

@router.get("/{slug}/community/search", response_model=SearchResponse)
def search_community(
    slug: str,
    q: str = "",
    type: str | None = None,
    channel: str | None = None,
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """Search conversations in the collective, scoped to Channels the
    current user can access.

    `channel` param:
        None or 'all'  → across every accessible Channel (default)
        <slug>         → restrict to that Channel (still access-checked)

    Search never returns content from a Channel the caller cannot view;
    scheduled posts remain excluded; archived-Channel content surfaces
    for authorised viewers with an Archived flag on the row."""
    space = _get_space_or_404(slug, db)
    q_stripped = q.strip()
    if not q_stripped:
        return SearchResponse(query="", total=0, hits=[])
    pattern = f"%{q_stripped}%"

    # Resolve which Channel IDs this user is allowed to search across.
    if channel and channel != "all":
        target = _get_channel_by_slug_or_default(space, channel, db)
        if not can_view_channel(current_user, target, space, db):
            raise HTTPException(404, detail="Channel not found.")
        allowed_channel_ids = [target.id]
    else:
        allowed_channel_ids = [
            c.id for c in accessible_channels_for_user(current_user, space, db)
        ]
    if not allowed_channel_ids:
        return SearchResponse(query=q_stripped, total=0, hits=[])

    # ---- posts (title / body / author name) -----------------------------
    post_query = (
        db.query(CommunityPost, User)
        .join(User, User.id == CommunityPost.author_id)
        .filter(
            CommunityPost.space_id == space.id,
            CommunityPost.channel_id.in_(allowed_channel_ids),
            CommunityPost.is_visible.is_(True),
            # Scheduled posts must not surface in search until publication.
            CommunityPost.publication_status == "published",
        )
    )
    if type and type != "all":
        try:
            post_query = post_query.filter(CommunityPost.post_type == PostType(type))
        except ValueError:
            pass
    post_query = post_query.filter(
        or_(
            CommunityPost.title.ilike(pattern),
            CommunityPost.body.ilike(pattern),
            User.name.ilike(pattern),
        )
    ).order_by(CommunityPost.created_at.desc()).limit(limit)

    hits: list[SearchHit] = []
    seen_posts: set[str] = set()
    for post, author in post_query.all():
        seen_posts.add(post.id)
        field, source = _pick_match_field_for_post(post, author, q_stripped)
        hits.append(SearchHit(
            kind="post",
            post_id=post.id,
            post_type=_post_type_str(post.post_type),
            post_title=post.title,
            author_name=author.name or author.email.split("@")[0],
            excerpt=_make_excerpt(source, q_stripped),
            created_at=post.created_at,
            match_field=field,
        ))

    # ---- comments (body / author name; type filter applied to parent post) ----
    remaining = max(0, limit - len(hits))
    if remaining > 0:
        comment_query = (
            db.query(PostComment, CommunityPost, User)
            .join(CommunityPost, CommunityPost.id == PostComment.post_id)
            .join(User, User.id == PostComment.author_id)
            .filter(
                CommunityPost.space_id == space.id,
                CommunityPost.channel_id.in_(allowed_channel_ids),
                CommunityPost.is_visible.is_(True),
                CommunityPost.publication_status == "published",
                PostComment.is_visible.is_(True),
            )
        )
        if type and type != "all":
            try:
                comment_query = comment_query.filter(CommunityPost.post_type == PostType(type))
            except ValueError:
                pass
        comment_query = comment_query.filter(
            or_(PostComment.body.ilike(pattern), User.name.ilike(pattern))
        ).order_by(PostComment.created_at.desc()).limit(remaining)

        for comment, post, author in comment_query.all():
            hits.append(SearchHit(
                kind="comment",
                post_id=post.id,
                post_type=_post_type_str(post.post_type),
                post_title=post.title,
                author_name=author.name or author.email.split("@")[0],
                excerpt=_make_excerpt(comment.body, q_stripped),
                created_at=comment.created_at,
                match_field="comment" if q_stripped.lower() in comment.body.lower() else "author",
            ))

    return SearchResponse(query=q_stripped, total=len(hits), hits=hits[:limit])


def _pick_match_field_for_post(post: CommunityPost, author: User, q: str) -> tuple[str, str]:
    ql = q.lower()
    if post.title and ql in post.title.lower():
        return "title", post.title
    if ql in post.body.lower():
        return "body", post.body
    return "author", author.name or author.email


def _make_excerpt(source: str, q: str, radius: int = 60) -> str:
    """Return a short excerpt around the first case-insensitive match."""
    if not source:
        return ""
    lower = source.lower()
    idx = lower.find(q.lower())
    if idx < 0:
        return source[:2 * radius].strip()
    start = max(0, idx - radius)
    end = min(len(source), idx + len(q) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(source) else ""
    return f"{prefix}{source[start:end].strip()}{suffix}"


# ---------------------------------------------------------------------------
# Image upload for community posts/comments
# ---------------------------------------------------------------------------

@router.post("/{slug}/community/upload-image", status_code=201)
async def upload_community_image(
    slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    # SEC-005-C — uploads land in the collective's storage namespace
    # (``uploads/media/{slug}/community/…``). Being authenticated is
    # not enough: a stranger with an fc-web account must not be able
    # to write files into a Collective they cannot even read. Require
    # an active membership or caretaker (creator/moderator, plus the
    # existing platform-admin / platform-creator bypass carried by
    # ``is_caretaker``).
    space = _get_space_or_404(slug, db)
    if not (
        is_caretaker(current_user, space, db)
        or is_active_space_member(current_user.id, space.id, db)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of this collective to upload community images.",
        )

    data = await file.read()
    try:
        _, file_url, _, _, _ = save_media_file(
            data=data,
            original_name=file.filename or "image.jpg",
            mime_type=file.content_type or "image/jpeg",
            space_slug=f"{slug}/community",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"url": file_url}


# ---------------------------------------------------------------------------
# Reactions — posts
# ---------------------------------------------------------------------------

@router.post("/{slug}/community/{post_id}/reactions/{emoji}", status_code=200)
def toggle_post_reaction(
    slug: str,
    post_id: str,
    emoji: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if emoji not in ALLOWED_REACTION_EMOJIS:
        raise HTTPException(status_code=400, detail="Emoji not allowed.")
    space = _get_space_or_404(slug, db)

    # SEC-005-A — verify the post belongs to the URL Collective before
    # touching anything else. Prior code loaded the reaction row by
    # unscoped ``post_id``, letting an authenticated caller react to
    # any post in any Collective (including private / link-only) by
    # supplying an unrelated post_id in a slug they *can* see.
    post = (
        db.query(CommunityPost)
        .filter(CommunityPost.id == post_id, CommunityPost.space_id == space.id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    # Central channel gate — enforces active space membership, channel
    # visibility (private/pathway/gathering channels are respected),
    # and not-archived. Caretakers pass automatically.
    channel = _get_channel_for_post(post, db)
    if not can_react(current_user, channel, space, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You cannot react to this post.")

    # Community Care — reactions are a posting-shaped write; block on
    # freeze or posting restriction. Now correctly scoped to the actual
    # post's Collective (proven equal to the URL slug's Collective above).
    from app.community_care.shared import (
        has_active_posting_restriction, is_space_closed, is_space_frozen,
    )
    if is_space_closed(space):
        raise HTTPException(403, detail="This collective has been closed.")
    if is_space_frozen(space):
        raise HTTPException(403, detail="This collective is temporarily paused by Fresh Collective.")
    if has_active_posting_restriction(db, current_user.id, space.id):
        raise HTTPException(403, detail="Your posting is temporarily restricted by Fresh Collective.")

    existing = (
        db.query(PostReaction)
        .filter_by(post_id=post.id, user_id=current_user.id, emoji=emoji)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"reacted": False}

    reaction = PostReaction(
        id=str(uuid.uuid4()),
        post_id=post.id,
        user_id=current_user.id,
        emoji=emoji,
    )
    db.add(reaction)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"reacted": True}


# ---------------------------------------------------------------------------
# Reactions — comments
# ---------------------------------------------------------------------------

@router.post("/{slug}/community/{post_id}/comments/{comment_id}/reactions/{emoji}", status_code=200)
def toggle_comment_reaction(
    slug: str,
    post_id: str,
    comment_id: str,
    emoji: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if emoji not in ALLOWED_REACTION_EMOJIS:
        raise HTTPException(status_code=400, detail="Emoji not allowed.")
    space = _get_space_or_404(slug, db)

    # SEC-005-B — walk the (space → post → comment) object chain before
    # doing anything else. Prior code loaded the reaction row by
    # unscoped ``comment_id`` and *ignored* the ``post_id`` URL param
    # entirely, so any comment in the system could be reacted to by
    # supplying any (slug, post_id) tuple.
    post = (
        db.query(CommunityPost)
        .filter(CommunityPost.id == post_id, CommunityPost.space_id == space.id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    comment = (
        db.query(PostComment)
        .filter(PostComment.id == comment_id, PostComment.post_id == post.id)
        .first()
    )
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")

    channel = _get_channel_for_post(post, db)
    if not can_react(current_user, channel, space, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You cannot react to this comment.")

    # Community Care — same rationale as SEC-005-A above; now scoped
    # to the actual comment's Collective.
    from app.community_care.shared import (
        has_active_posting_restriction, is_space_closed, is_space_frozen,
    )
    if is_space_closed(space):
        raise HTTPException(403, detail="This collective has been closed.")
    if is_space_frozen(space):
        raise HTTPException(403, detail="This collective is temporarily paused by Fresh Collective.")
    if has_active_posting_restriction(db, current_user.id, space.id):
        raise HTTPException(403, detail="Your posting is temporarily restricted by Fresh Collective.")

    existing = (
        db.query(CommentReaction)
        .filter_by(comment_id=comment.id, user_id=current_user.id, emoji=emoji)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"reacted": False}

    reaction = CommentReaction(
        id=str(uuid.uuid4()),
        comment_id=comment.id,
        user_id=current_user.id,
        emoji=emoji,
    )
    db.add(reaction)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"reacted": True}


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------

def _can_moderate(user: User, space: Space, db: Session) -> bool:
    """Return True if this user can moderate community content in the space."""
    if user.role in ("admin", "creator"):
        return True
    row = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
            SpaceMembership.status == "active",
        )
        .first()
    )
    return row is not None


@router.delete("/{slug}/community/{post_id}", status_code=204)
def hide_community_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Soft-hide a community post. Only moderators/creators/admins may hide others' posts."""
    space = _get_space_or_404(slug, db)
    post = (
        db.query(CommunityPost)
        .filter(CommunityPost.id == post_id, CommunityPost.space_id == space.id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    if post.author_id != current_user.id and not _can_moderate(current_user, space, db):
        raise HTTPException(status_code=403, detail="You do not have permission to remove this post.")
    post.is_visible = False
    db.commit()


@router.delete("/{slug}/community/{post_id}/comments/{comment_id}", status_code=204)
def hide_community_comment(
    slug: str,
    post_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Soft-hide a comment. Only moderators/creators/admins may hide others' comments."""
    space = _get_space_or_404(slug, db)
    comment = (
        db.query(PostComment)
        .join(CommunityPost, CommunityPost.id == PostComment.post_id)
        .filter(
            PostComment.id == comment_id,
            PostComment.post_id == post_id,
            CommunityPost.space_id == space.id,
        )
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found.")
    if comment.author_id != current_user.id and not _can_moderate(current_user, space, db):
        raise HTTPException(status_code=403, detail="You do not have permission to remove this comment.")
    comment.is_visible = False
    db.commit()
