"""
Primitives shared by admin review (``app.admin.community_care``) and
member intake (``app.community_care.routes``).

Every mutation to a case must go through :func:`write_event` on the
same session so the append-only audit trail stays complete. Every
intake path goes through :func:`find_open_case`, :func:`snapshot_content`,
and :func:`next_case_number` so admin-seeded and member-filed reports
open identical case shapes.

Stage 2A introduced these as private helpers on the admin router;
Stage 2B lifts them into a shared module without changing behaviour.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.community_care import (
    CommunityCareCase,
    CommunityCareCaseEvent,
    CommunityCareReport,
)
from app.models.platform import CommunityPost, PostComment, Space
from app.models.user import User


# ---------------------------------------------------------------------------
# Statuses that count as "open" — used for dedupe and overview counters.
# ---------------------------------------------------------------------------

OPEN_STATUSES: frozenset[str] = frozenset({
    "new", "reviewing", "waiting_info", "action_required",
})


# ---------------------------------------------------------------------------
# Guard — refuse when Community Care is not enabled on this deployment.
# ---------------------------------------------------------------------------


def ensure_flag_on() -> None:
    """Refuse when Community Care is not yet enabled for this deployment.

    Returns 503 so half-built surfaces can't be discovered by accident
    from an admin or member endpoint alike.
    """
    if not settings.community_care_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Community Care is not yet enabled on this deployment.",
        )


# ---------------------------------------------------------------------------
# Case-number allocator — CC-YYYY-NNNN
# ---------------------------------------------------------------------------


def next_case_number(db: Session, opened_at: datetime) -> str:
    """Allocate the next ``CC-YYYY-NNNN`` number for the given year.

    Reads the count of existing cases whose ``case_number`` begins with
    ``CC-<year>-`` and adds one. Two concurrent inserts on the same year
    would collide on the UNIQUE constraint; retry is left to the caller
    because Stage 2A/2B intake volume is low enough that a simple
    allocator suffices.
    """
    prefix = f"CC-{opened_at.year}-"
    n = (
        db.query(func.count(CommunityCareCase.id))
        .filter(CommunityCareCase.case_number.like(f"{prefix}%"))
        .scalar()
        or 0
    )
    return f"{prefix}{n + 1:04d}"


# ---------------------------------------------------------------------------
# Case matching for dedupe
# ---------------------------------------------------------------------------


def find_open_case(
    db: Session,
    *,
    target_post_id: str | None = None,
    target_comment_id: str | None = None,
    target_member_user_id: str | None = None,
) -> CommunityCareCase | None:
    """Return an open case with the same subject as the incoming report.

    Subject match order (first match wins):
      * post — exact match on ``subject_post_id``
      * comment — exact match on ``subject_comment_id``
      * member behaviour — same ``subject_member_user_id`` and no
        post/comment on the case (behaviour report, not content report)

    Returns ``None`` when the report has no dedupe subject or when no
    open case matches. Callers open a fresh case in that case.
    """
    q = db.query(CommunityCareCase).filter(
        CommunityCareCase.status.in_(list(OPEN_STATUSES))
    )
    if target_post_id:
        q = q.filter(CommunityCareCase.subject_post_id == target_post_id)
    elif target_comment_id:
        q = q.filter(CommunityCareCase.subject_comment_id == target_comment_id)
    elif target_member_user_id:
        q = q.filter(
            CommunityCareCase.subject_member_user_id == target_member_user_id,
            CommunityCareCase.subject_post_id.is_(None),
            CommunityCareCase.subject_comment_id.is_(None),
        )
    else:
        return None
    return q.order_by(CommunityCareCase.opened_at.desc()).first()


# ---------------------------------------------------------------------------
# Content snapshot — captured at intake and retained through review.
# ---------------------------------------------------------------------------


def snapshot_content(
    db: Session, post_id: str | None, comment_id: str | None
) -> dict | None:
    """Capture the reported content at report time as a JSON blob.

    Survives later edits or deletion of the source row (the DB-level
    FK is ``ON DELETE SET NULL``). Retention: 12 months after the case
    is ``resolved`` or ``closed_no_action`` — handled by a separate
    purge job outside intake.
    """
    if post_id:
        row = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
        if row:
            return {
                "kind": "post",
                "id": row.id,
                "author_id": row.author_id,
                "title": row.title,
                "body": row.body,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
    if comment_id:
        row = db.query(PostComment).filter(PostComment.id == comment_id).first()
        if row:
            return {
                "kind": "comment",
                "id": row.id,
                "post_id": row.post_id,
                "author_id": row.author_id,
                "body": row.body,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
    return None


# ---------------------------------------------------------------------------
# Content resolution helpers — used by member intake to derive the
# subject_space_id / subject_member_user_id from the reported content.
# ---------------------------------------------------------------------------


def resolve_post_subject(
    db: Session, post_id: str
) -> tuple[str | None, str | None]:
    """Return ``(space_id, author_id)`` for the given post, or
    ``(None, None)`` if the post does not exist. Used by member intake
    to fill in ``subject_space_id`` and ``subject_member_user_id``
    without asking the client (who could not be trusted with that
    mapping anyway)."""
    row = db.query(CommunityPost).filter(CommunityPost.id == post_id).first()
    if row is None:
        return None, None
    return row.space_id, row.author_id


def resolve_comment_subject(
    db: Session, comment_id: str
) -> tuple[str | None, str | None, str | None]:
    """Return ``(space_id, author_id, post_id)`` for the given comment,
    or ``(None, None, None)`` if the comment does not exist. The comment
    row itself does not store ``space_id`` — it is derived from the
    parent post so intake is one lookup here instead of two at the
    router."""
    row = db.query(PostComment).filter(PostComment.id == comment_id).first()
    if row is None:
        return None, None, None
    post = (
        db.query(CommunityPost)
        .filter(CommunityPost.id == row.post_id)
        .first()
    )
    space_id = post.space_id if post else None
    return space_id, row.author_id, row.post_id


# ---------------------------------------------------------------------------
# Event writer — every case mutation appends one of these
# ---------------------------------------------------------------------------


def write_event(
    db: Session,
    *,
    case: CommunityCareCase,
    kind: str,
    actor_user_id: str | None,
    previous_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
    internal_note: str | None = None,
    subject_content_ref: dict | None = None,
) -> CommunityCareCaseEvent:
    """Append an audit event to the case on the same session.

    Never mutated once written — the whole point of the audit table is
    that history cannot be rewritten from application code.
    """
    ev = CommunityCareCaseEvent(
        id=str(uuid4()),
        case_id=case.id,
        kind=kind,
        actor_user_id=actor_user_id,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
        internal_note=internal_note,
        subject_content_ref=subject_content_ref,
    )
    db.add(ev)
    return ev


# ---------------------------------------------------------------------------
# Small hydrators — used by both admin listing and (soon) member
# acknowledgement responses.
# ---------------------------------------------------------------------------


def name_map(db: Session, user_ids: set[str]) -> dict[str, str | None]:
    """Return ``{user_id: name}`` for the requested set. Missing ids are
    omitted from the result (not returned as ``None``)."""
    if not user_ids:
        return {}
    rows = db.query(User.id, User.name).filter(User.id.in_(user_ids)).all()
    return {uid: name for uid, name in rows}


def space_name_map(db: Session, space_ids: set[str]) -> dict[str, str]:
    """Return ``{space_id: name}`` for the requested set."""
    if not space_ids:
        return {}
    return dict(
        db.query(Space.id, Space.name).filter(Space.id.in_(space_ids)).all()
    )


# ---------------------------------------------------------------------------
# Reports-count hydration — used by admin case detail signal panel.
# ---------------------------------------------------------------------------


def count_reports_on_case(db: Session, case_id: str) -> int:
    return int(
        db.query(func.count(CommunityCareReport.id))
        .filter(CommunityCareReport.case_id == case_id)
        .scalar()
        or 0
    )


def count_prior_cases_for_member(db: Session, case: CommunityCareCase) -> int:
    if not case.subject_member_user_id:
        return 0
    return int(
        db.query(func.count(CommunityCareCase.id))
        .filter(
            CommunityCareCase.subject_member_user_id == case.subject_member_user_id,
            CommunityCareCase.id != case.id,
        )
        .scalar()
        or 0
    )


def count_prior_cases_for_creator(db: Session, case: CommunityCareCase) -> int:
    if not case.subject_creator_user_id:
        return 0
    return int(
        db.query(func.count(CommunityCareCase.id))
        .filter(
            CommunityCareCase.subject_creator_user_id == case.subject_creator_user_id,
            CommunityCareCase.id != case.id,
        )
        .scalar()
        or 0
    )


# ---------------------------------------------------------------------------
# Enforcement helpers (Stage 2C)
# ---------------------------------------------------------------------------
#
# Read-only predicates called from the write-path guards on posts,
# comments, reactions, creator content, and the auth dependency. They
# return booleans; the calling endpoint decides which HTTP status is
# appropriate for its context (usually 403 for restrictions and freeze,
# 401 for suspension since sessions are being revoked).


def is_user_suspended(user) -> bool:
    """True when the user has an active member-level suspension.

    Suspension pending review is temporary; ``suspended_until`` may be
    null (indefinite pending review) or a future timestamp (auto-lift
    at that point). Both count as active.
    """
    if getattr(user, "suspended_at", None) is None:
        return False
    until = getattr(user, "suspended_until", None)
    if until is None:
        return True
    return until > datetime.utcnow()


def has_active_posting_restriction(
    db: Session, user_id: str, space_id: str | None = None
) -> bool:
    """True when the user has an active ``posting`` restriction that
    applies to the given space.

    Restrictions may be scoped to a single space (``space_id`` set on
    the restriction row) or platform-wide (``space_id`` null). A
    platform-wide row always applies; a scoped row applies only when
    ``space_id`` matches. When the caller does not know the space
    context (e.g. account settings) they can pass ``None`` and only
    platform-wide restrictions are considered.
    """
    from app.models.community_care import MemberRestriction

    now = datetime.utcnow()
    q = db.query(MemberRestriction).filter(
        MemberRestriction.user_id == user_id,
        MemberRestriction.kind == "posting",
        MemberRestriction.reversed_at.is_(None),
    )
    rows = q.all()
    for r in rows:
        if r.ends_at is not None and r.ends_at <= now:
            continue
        if r.space_id is None:
            return True
        if space_id is not None and r.space_id == space_id:
            return True
    return False


def has_active_creator_restriction(db: Session, user_id: str) -> bool:
    """True when the user has an active ``creator`` restriction. Creator
    restrictions are always platform-wide (``space_id`` is ignored)."""
    from app.models.community_care import MemberRestriction

    now = datetime.utcnow()
    rows = (
        db.query(MemberRestriction)
        .filter(
            MemberRestriction.user_id == user_id,
            MemberRestriction.kind == "creator",
            MemberRestriction.reversed_at.is_(None),
        )
        .all()
    )
    for r in rows:
        if r.ends_at is not None and r.ends_at <= now:
            continue
        return True
    return False


def is_user_cancelled(user) -> bool:
    """True when the user's member account has been permanently
    cancelled by a Stage 2D resolution outcome.

    Cancellation is terminal — it is never "reversed" by editing the
    original case. If Fresh Collective later wishes to reinstate the
    person, that happens through a new case, not by clearing this
    column.
    """
    return getattr(user, "cancelled_at", None) is not None


def is_creator_cancelled(user) -> bool:
    """True when the user's creator role has been cancelled.

    Terminal — same treatment as ``is_user_cancelled``. Members-side
    access is preserved (creator cancellation removes creator
    capabilities only; ``suspended_at`` and ``cancelled_at`` are
    distinct concepts).
    """
    return getattr(user, "creator_cancelled_at", None) is not None


def is_space_closed(space) -> bool:
    """True when the collective has been closed by a Stage 2D
    resolution outcome. Terminal."""
    return getattr(space, "closed_at", None) is not None


def is_space_frozen(space) -> bool:
    """True when the collective is currently in a Community Care freeze.

    ``frozen_at`` set and (``frozen_until`` null or future) counts as
    active. Reversal clears both, so no separate ``is_frozen`` flag is
    needed.
    """
    if getattr(space, "frozen_at", None) is None:
        return False
    until = getattr(space, "frozen_until", None)
    if until is None:
        return True
    return until > datetime.utcnow()


def is_post_cc_hidden(post) -> bool:
    return getattr(post, "cc_hidden_at", None) is not None


def is_comment_cc_hidden(comment) -> bool:
    return getattr(comment, "cc_hidden_at", None) is not None


def active_protective_action_on_target(
    db: Session,
    *,
    kind: str,
    affected_user_id: str | None = None,
    affected_space_id: str | None = None,
    affected_post_id: str | None = None,
    affected_comment_id: str | None = None,
):
    """Return the currently-active protective action of ``kind`` on the
    given target, or ``None`` if there is no active row.

    "Active" means ``reversed_at`` is null and ``ends_at`` is null or in
    the future. Used by the issue endpoint to refuse a duplicate
    protective action against the same target (409 Conflict) so a
    double-clicked button cannot stack two restrictions.
    """
    from app.models.community_care import CommunityCareAction

    now = datetime.utcnow()
    q = (
        db.query(CommunityCareAction)
        .filter(
            CommunityCareAction.layer == "protective",
            CommunityCareAction.kind == kind,
            CommunityCareAction.reversed_at.is_(None),
        )
    )
    if affected_user_id is not None:
        q = q.filter(CommunityCareAction.affected_user_id == affected_user_id)
    if affected_space_id is not None:
        q = q.filter(CommunityCareAction.affected_space_id == affected_space_id)
    if affected_post_id is not None:
        q = q.filter(CommunityCareAction.affected_post_id == affected_post_id)
    if affected_comment_id is not None:
        q = q.filter(CommunityCareAction.affected_comment_id == affected_comment_id)
    for row in q.all():
        if row.ends_at is not None and row.ends_at <= now:
            continue
        return row
    return None
