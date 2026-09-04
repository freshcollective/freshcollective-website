"""
/api/community-care/* — member-facing intake for Community Care.

Stage 2B ships two endpoints:

  * ``POST /api/community-care/reports`` — a member reports a post or
    comment. Opens a case (or dedupes to an existing open case) and
    sends a routine acknowledgement notification.
  * ``POST /api/community-care/creator-support`` — a creator asks
    Fresh Collective for help. Opens a ``creator_request`` case and
    sends a routine acknowledgement notification.

Both endpoints:
  * are gated by ``settings.community_care_enabled`` (503 when off)
  * require an authenticated user (member for reports; creator role
    for creator support)
  * are rate-limited at the IP layer to keep the intake calm and to
    make abuse loud in logs
  * write to the same case tables as admin-seed intake and produce the
    same audit-trail events, so a reviewer opening a case cannot tell
    from the audit log alone whether the report originated from a
    member or an admin (except by the ``reporter_kind`` column, which
    is intentional and reviewable).

Real enforcement (protective / suspension / cancellation) remains
Stage 2C/2D territory. Nothing here hides content, restricts users, or
notifies a reported person.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    get_creator_user,
    get_current_user,
    get_verified_creator_user,
    get_verified_current_user,
)
from app.core.rate_limit import client_ip_for_rate_limit
from app.community_care.schemas import (
    CreatorSupportAcknowledgement,
    CreatorSupportRequest,
    MemberReportAcknowledgement,
    MemberReportRequest,
)
from app.community_care.shared import (
    ensure_flag_on,
    find_open_case,
    next_case_number,
    resolve_comment_subject,
    resolve_post_subject,
    snapshot_content,
    write_event,
)
from app.core.database import get_db
from app.models.community_care import (
    CommunityCareCase,
    CommunityCareReport,
)
from app.models.notification import Notification
from app.models.platform import Space, SpaceMembership, SpaceRole
from app.models.user import User


router = APIRouter(prefix="/api/community-care", tags=["community-care"])

# Rate limiter — key function lives in ``app.core.rate_limit`` and
# handles both BFF-authenticated identity claims (per browser client IP)
# and public-path Cloudflare-derived identity. Intake volume is low;
# these ceilings exist to keep abuse visible in logs, not to block
# honest members.
limiter = Limiter(key_func=client_ip_for_rate_limit)


# ---------------------------------------------------------------------------
# Small helpers local to intake
# ---------------------------------------------------------------------------


def _resolve_creator_for_space(db: Session, space_id: str) -> str | None:
    """Return the ``user_id`` of the creator role on ``space_id``, or
    ``None`` if the space has no creator membership. Used to attach
    ``subject_creator_user_id`` on incoming member reports so the
    admin signal panel can surface prior cases involving the same
    creator's collective."""
    row = (
        db.query(SpaceMembership.user_id)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.role == SpaceRole.creator,
        )
        .first()
    )
    return row[0] if row else None


def _notify_reporter_acknowledgement(
    db: Session, *, recipient_id: str, case_number: str
) -> None:
    """Send a routine acknowledgement notification to the reporter.

    Committed on the same session as the report itself so a failure
    here rolls back the intake — we would rather refuse the report and
    show an error than accept a report and leave the member wondering
    if it went through.
    """
    notif = Notification(
        id=str(uuid4()),
        user_id=recipient_id,
        notification_type="community_care_report_received",
        title="Report received",
        message=(
            "Thank you for letting us know. A Fresh Collective administrator "
            "will review this. Your identity is not disclosed to the person "
            "reported."
        ),
        url=None,
        is_read=False,
        severity="routine",
    )
    db.add(notif)


def _notify_creator_support_acknowledgement(
    db: Session, *, recipient_id: str, case_number: str
) -> None:
    notif = Notification(
        id=str(uuid4()),
        user_id=recipient_id,
        notification_type="community_care_creator_support_received",
        title="Support request received",
        message=(
            f"Your request ({case_number}) has been received. A Fresh Collective "
            "administrator will be in touch."
        ),
        url="/creator/support",
        is_read=False,
        severity="routine",
    )
    db.add(notif)


# ---------------------------------------------------------------------------
# POST /api/community-care/reports  —  member intake
# ---------------------------------------------------------------------------


@router.post(
    "/reports",
    response_model=MemberReportAcknowledgement,
    status_code=201,
)
@limiter.limit("10/hour")
def submit_member_report(
    request: Request,
    body: MemberReportRequest,
    current_user: User = Depends(get_verified_current_user),  # SEC-009
    db: Session = Depends(get_db),
) -> MemberReportAcknowledgement:
    """A member reports a post or comment.

    Validation:
      * flag must be on
      * exactly one of ``target_post_id`` / ``target_comment_id`` must
        be set
      * the referenced content must exist
      * ``category == 'something_else'`` requires a non-empty note
      * members cannot report their own content (silently ignored on
        the review side, but flagged loudly here so the UI can hide
        the option)

    Behaviour:
      * subject_space_id and subject_member_user_id are derived from
        the reported content — the client is never trusted with them
      * dedupes to any open case for the same subject; report_count
        increments and a ``report_attached`` event is written
      * a fresh case is opened otherwise with a snapshot of the
        reported content and priority ``low``
      * a routine acknowledgement notification is sent to the reporter
    """
    ensure_flag_on()

    # Exactly one target
    if bool(body.target_post_id) == bool(body.target_comment_id):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of target_post_id or target_comment_id.",
        )

    # 'something_else' requires a note
    if body.category == "something_else":
        note = (body.reporter_note or "").strip()
        if not note:
            raise HTTPException(
                status_code=422,
                detail="Please add a short explanation when choosing 'Something else'.",
            )

    # Resolve subject from the reported content — server-derived, never
    # taken from the client.
    if body.target_post_id:
        space_id, author_id = resolve_post_subject(db, body.target_post_id)
        if space_id is None:
            raise HTTPException(status_code=404, detail="Post not found.")
        content_type = "post"
        target_post_id = body.target_post_id
        target_comment_id: str | None = None
    else:
        assert body.target_comment_id is not None
        space_id, author_id, _post_id = resolve_comment_subject(db, body.target_comment_id)
        if space_id is None:
            raise HTTPException(status_code=404, detail="Comment not found.")
        content_type = "comment"
        target_post_id = None
        target_comment_id = body.target_comment_id

    if author_id and author_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot report your own content.",
        )

    subject_creator_user_id = _resolve_creator_for_space(db, space_id) if space_id else None

    # Dedupe onto an existing open case on the same subject.
    case = find_open_case(
        db,
        target_post_id=target_post_id,
        target_comment_id=target_comment_id,
        target_member_user_id=None,
    )

    now = datetime.utcnow()
    if case is None:
        case = CommunityCareCase(
            id=str(uuid4()),
            case_number=next_case_number(db, now),
            content_type=content_type,
            subject_post_id=target_post_id,
            subject_comment_id=target_comment_id,
            subject_member_user_id=author_id,
            subject_creator_user_id=subject_creator_user_id,
            subject_space_id=space_id,
            content_snapshot=snapshot_content(db, target_post_id, target_comment_id),
            category=body.category,
            status="new",
            priority="low",
            report_count=1,
            opened_at=now,
        )
        db.add(case)
        db.flush()
        write_event(
            db,
            case=case,
            kind="case_opened",
            actor_user_id=current_user.id,
            new_value={
                "case_number": case.case_number,
                "content_type": case.content_type,
                "reporter_kind": "member",
            },
        )
    else:
        case.report_count = (case.report_count or 0) + 1
        case.updated_at = now

    report = CommunityCareReport(
        id=str(uuid4()),
        case_id=case.id,
        reporter_user_id=current_user.id,
        reporter_kind="member",
        content_type=content_type,
        target_post_id=target_post_id,
        target_comment_id=target_comment_id,
        target_member_user_id=author_id,
        category=body.category,
        reporter_note=(body.reporter_note or "").strip() or None,
    )
    db.add(report)
    db.flush()
    write_event(
        db,
        case=case,
        kind="report_attached",
        actor_user_id=current_user.id,
        new_value={
            "report_id": report.id,
            "category": body.category,
            "reporter_kind": "member",
        },
    )

    _notify_reporter_acknowledgement(
        db, recipient_id=current_user.id, case_number=case.case_number
    )

    db.commit()

    return MemberReportAcknowledgement(received_at=now)


# ---------------------------------------------------------------------------
# POST /api/community-care/creator-support  —  creator support intake
# ---------------------------------------------------------------------------


@router.post(
    "/creator-support",
    response_model=CreatorSupportAcknowledgement,
    status_code=201,
)
@limiter.limit("10/hour")
def submit_creator_support_request(
    request: Request,
    body: CreatorSupportRequest,
    current_user: User = Depends(get_verified_creator_user),  # SEC-009
    db: Session = Depends(get_db),
) -> CreatorSupportAcknowledgement:
    """A creator asks Fresh Collective for support.

    Scope must be one of the five agreed categories. If a specific
    collective is named, the requesting creator must actually be a
    creator on it — otherwise the endpoint refuses (403).

    Every creator support request opens a fresh case. Unlike member
    reports, dedupe is deliberately not applied here: two separate
    asks from the same creator on different days are two separate
    conversations, not the same one.
    """
    ensure_flag_on()

    # Verify the named collective, if any, is genuinely theirs.
    if body.subject_space_id is not None:
        space = (
            db.query(Space).filter(Space.id == body.subject_space_id).first()
        )
        if space is None:
            raise HTTPException(status_code=404, detail="Collective not found.")
        is_creator_of_space = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.space_id == body.subject_space_id,
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.role == SpaceRole.creator,
            )
            .first()
            is not None
        )
        if not is_creator_of_space and current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="You are not the creator of that collective.",
            )

    now = datetime.utcnow()
    case = CommunityCareCase(
        id=str(uuid4()),
        case_number=next_case_number(db, now),
        content_type="creator_request",
        subject_space_id=body.subject_space_id,
        subject_creator_user_id=current_user.id,
        creator_request_scope=body.scope,
        status="new",
        priority="low",
        report_count=0,          # creator requests are not "reports"
        opened_at=now,
    )
    db.add(case)
    db.flush()

    write_event(
        db,
        case=case,
        kind="case_opened",
        actor_user_id=current_user.id,
        new_value={
            "case_number": case.case_number,
            "content_type": "creator_request",
            "scope": body.scope,
        },
        internal_note=body.description.strip(),
    )

    _notify_creator_support_acknowledgement(
        db, recipient_id=current_user.id, case_number=case.case_number
    )

    db.commit()

    return CreatorSupportAcknowledgement(
        case_number=case.case_number,
        received_at=now,
    )
