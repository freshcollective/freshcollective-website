"""
/api/admin/community-care/* — review muscle for Fresh Collective.

Stage 2A ships the read + review surface plus a case-close endpoint
with resolution outcomes. Protective measures and suspensions land in
Stage 2C/2D.

Every endpoint here is:
  - Guarded by ``get_admin_user`` — binary admin role, no sub-role.
  - Gated by ``settings.community_care_enabled`` (default False).
    When the flag is off, endpoints return 503 so half-built surfaces
    can't be discovered by accident.

Every mutation appends a ``CommunityCareCaseEvent`` on the same
transaction as the mutation itself. Priority mutations require an
authenticated admin actor — no system-set priority is possible in
Stage 2A.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.admin.community_care.schemas import (
    AddNoteRequest,
    AdminSeedReportRequest,
    AssignReviewerRequest,
    CaseActionRow,
    CaseDetail,
    CaseEventRow,
    CaseListRow,
    CaseNoteRow,
    CaseSignals,
    CaseSummaryRequest,
    CloseCaseRequest,
    CommunityCareOverview,
    OutcomeCounts,
    IssueProtectiveActionRequest,
    IssueSupportiveActionRequest,
    ReportRow,
    ReverseActionRequest,
    UpdatePriorityRequest,
    UpdateStatusRequest,
)
from app.auth.dependencies import get_admin_user
from app.community_care.shared import (
    OPEN_STATUSES,
    active_protective_action_on_target,
    count_prior_cases_for_creator,
    count_prior_cases_for_member,
    count_reports_on_case,
    ensure_flag_on,
    find_open_case,
    name_map,
    next_case_number,
    snapshot_content,
    space_name_map,
    write_event,
)
from app.core.database import get_db
from app.models.community_care import (
    CommunityCareAction,
    CommunityCareCase,
    CommunityCareCaseEvent,
    CommunityCareCaseNote,
    CommunityCareReport,
    layer_for_kind,
)
from app.models.community_care import MemberRestriction
from app.models.notification import Notification
from app.models.platform import CommunityPost, PostComment, Space
from app.models.user import User


router = APIRouter(prefix="/api/admin/community-care", tags=["community-care"])


# The admin router keeps its original private aliases so callers inside
# this module (and any older tests reaching in) see no behaviour change
# when the helpers moved to ``app.community_care.shared`` in Stage 2B.
_OPEN_STATUSES = OPEN_STATUSES
_ensure_flag_on = ensure_flag_on
_next_case_number = next_case_number
_snapshot_content = snapshot_content
_write_event = write_event
_name_map = name_map
_space_names = space_name_map


def _find_open_case_for_report(
    db: Session, body: AdminSeedReportRequest
) -> CommunityCareCase | None:
    """Admin-seed intake dedupe. Delegates to the shared primitive on
    the three fields it takes from ``body``."""
    return find_open_case(
        db,
        target_post_id=body.target_post_id,
        target_comment_id=body.target_comment_id,
        target_member_user_id=body.target_member_user_id,
    )


def _hydrate_signals(db: Session, case: CommunityCareCase) -> CaseSignals:
    return CaseSignals(
        reports_on_case=count_reports_on_case(db, case.id),
        prior_cases_for_member=count_prior_cases_for_member(db, case),
        prior_cases_for_creator=count_prior_cases_for_creator(db, case),
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=CommunityCareOverview)
def get_overview(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CommunityCareOverview:
    _ensure_flag_on()

    open_statuses = list(_OPEN_STATUSES)

    # Communities needing care — distinct collectives with any open case
    communities_needing_care = (
        db.query(func.count(func.distinct(CommunityCareCase.subject_space_id)))
        .filter(
            CommunityCareCase.status.in_(open_statuses),
            CommunityCareCase.subject_space_id.isnot(None),
        )
        .scalar()
        or 0
    )
    # Conversations awaiting review — cases in status 'new'
    conversations_awaiting = (
        db.query(func.count(CommunityCareCase.id))
        .filter(CommunityCareCase.status == "new")
        .scalar()
        or 0
    )
    # Creator support requests — open cases of that content_type
    creator_requests = (
        db.query(func.count(CommunityCareCase.id))
        .filter(
            CommunityCareCase.content_type == "creator_request",
            CommunityCareCase.status.in_(open_statuses),
        )
        .scalar()
        or 0
    )

    # Wellbeing — locked rule (§10 of design doc)
    has_immediate = (
        db.query(func.count(CommunityCareCase.id))
        .filter(
            CommunityCareCase.priority == "immediate",
            CommunityCareCase.status.in_(open_statuses),
        )
        .scalar()
        or 0
    )
    has_high = (
        db.query(func.count(CommunityCareCase.id))
        .filter(
            CommunityCareCase.priority == "high",
            CommunityCareCase.status.in_(open_statuses),
        )
        .scalar()
        or 0
    )
    if has_immediate:
        wellbeing, label = "needs_care", "Needs care"
    elif has_high:
        wellbeing, label = "needs_attention", "Needs attention"
    else:
        wellbeing, label = "healthy", "Healthy"

    # Stage 2D — operational reporting. Simple lifetime counts, drawn
    # from the community_care_actions ledger. Protective_measures is
    # a rollup across the five protective kinds so the reporting
    # surface stays readable.
    def _count_kind(kind: str) -> int:
        return int(
            db.query(func.count(CommunityCareAction.id))
            .filter(CommunityCareAction.kind == kind)
            .scalar()
            or 0
        )

    protective_kinds = (
        "content_hidden", "posting_restriction", "creator_restriction",
        "collective_freeze", "suspension_pending_review",
    )
    protective_count = int(
        db.query(func.count(CommunityCareAction.id))
        .filter(
            CommunityCareAction.layer == "protective",
            CommunityCareAction.kind.in_(protective_kinds),
        )
        .scalar()
        or 0
    )
    no_action_count = int(
        db.query(func.count(CommunityCareCase.id))
        .filter(CommunityCareCase.status == "closed_no_action")
        .scalar()
        or 0
    )

    outcomes = OutcomeCounts(
        guidance=_count_kind("guidance"),
        reminders=_count_kind("reminder"),
        warnings=_count_kind("warning"),
        protective_measures=protective_count,
        no_further_action=no_action_count,
        account_cancellations=_count_kind("account_cancellation"),
        creator_cancellations=_count_kind("creator_account_cancellation"),
        collective_closures=_count_kind("collective_closure_removal"),
    )

    return CommunityCareOverview(
        communities_needing_care=int(communities_needing_care),
        conversations_awaiting_review=int(conversations_awaiting),
        creator_support_requests=int(creator_requests),
        overall_wellbeing=wellbeing,
        overall_wellbeing_label=label,
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Case list
# ---------------------------------------------------------------------------


@router.get("/cases", response_model=list[CaseListRow])
def list_cases(
    status_filter: str | None = None,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[CaseListRow]:
    _ensure_flag_on()

    q = db.query(CommunityCareCase).order_by(CommunityCareCase.opened_at.desc())
    if status_filter == "open":
        q = q.filter(CommunityCareCase.status.in_(list(_OPEN_STATUSES)))
    elif status_filter == "closed":
        q = q.filter(CommunityCareCase.status.in_(["resolved", "closed_no_action"]))
    elif status_filter:
        q = q.filter(CommunityCareCase.status == status_filter)

    cases = q.all()
    if not cases:
        return []

    user_ids = set()
    space_ids = set()
    for c in cases:
        if c.subject_member_user_id:
            user_ids.add(c.subject_member_user_id)
        if c.assigned_reviewer_user_id:
            user_ids.add(c.assigned_reviewer_user_id)
        if c.subject_space_id:
            space_ids.add(c.subject_space_id)
    users = _name_map(db, user_ids)
    spaces = _space_names(db, space_ids)

    return [
        CaseListRow(
            id=c.id,
            case_number=c.case_number,
            content_type=c.content_type,
            subject_space_id=c.subject_space_id,
            subject_space_name=spaces.get(c.subject_space_id) if c.subject_space_id else None,
            subject_member_user_id=c.subject_member_user_id,
            subject_member_name=users.get(c.subject_member_user_id) if c.subject_member_user_id else None,
            category=c.category,
            creator_request_scope=c.creator_request_scope,
            status=c.status,
            priority=c.priority,
            report_count=c.report_count,
            assigned_reviewer_user_id=c.assigned_reviewer_user_id,
            assigned_reviewer_name=users.get(c.assigned_reviewer_user_id) if c.assigned_reviewer_user_id else None,
            opened_at=c.opened_at,
            resolved_at=c.resolved_at,
        )
        for c in cases
    ]


# ---------------------------------------------------------------------------
# Case detail
# ---------------------------------------------------------------------------


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")

    reports = (
        db.query(CommunityCareReport)
        .filter(CommunityCareReport.case_id == case_id)
        .order_by(CommunityCareReport.created_at.asc())
        .all()
    )
    notes = (
        db.query(CommunityCareCaseNote)
        .filter(CommunityCareCaseNote.case_id == case_id)
        .order_by(CommunityCareCaseNote.created_at.asc())
        .all()
    )
    events = (
        db.query(CommunityCareCaseEvent)
        .filter(CommunityCareCaseEvent.case_id == case_id)
        .order_by(CommunityCareCaseEvent.occurred_at.asc())
        .all()
    )
    actions = (
        db.query(CommunityCareAction)
        .filter(CommunityCareAction.case_id == case_id)
        .order_by(CommunityCareAction.created_at.asc())
        .all()
    )

    user_ids: set[str] = set()
    for r in reports:
        if r.reporter_user_id:
            user_ids.add(r.reporter_user_id)
    for n in notes:
        if n.author_user_id:
            user_ids.add(n.author_user_id)
    for e in events:
        if e.actor_user_id:
            user_ids.add(e.actor_user_id)
    for a in actions:
        if a.issued_by_admin_user_id:
            user_ids.add(a.issued_by_admin_user_id)
    if case.assigned_reviewer_user_id:
        user_ids.add(case.assigned_reviewer_user_id)
    if case.subject_member_user_id:
        user_ids.add(case.subject_member_user_id)
    if case.subject_creator_user_id:
        user_ids.add(case.subject_creator_user_id)
    names = _name_map(db, user_ids)
    spaces = _space_names(db, {case.subject_space_id} if case.subject_space_id else set())

    return CaseDetail(
        id=case.id,
        case_number=case.case_number,
        case_summary=case.case_summary,
        content_type=case.content_type,
        subject_post_id=case.subject_post_id,
        subject_comment_id=case.subject_comment_id,
        subject_member_user_id=case.subject_member_user_id,
        subject_member_name=names.get(case.subject_member_user_id) if case.subject_member_user_id else None,
        subject_creator_user_id=case.subject_creator_user_id,
        subject_creator_name=names.get(case.subject_creator_user_id) if case.subject_creator_user_id else None,
        subject_space_id=case.subject_space_id,
        subject_space_name=spaces.get(case.subject_space_id) if case.subject_space_id else None,
        content_snapshot=case.content_snapshot,
        category=case.category,
        creator_request_scope=case.creator_request_scope,
        status=case.status,
        priority=case.priority,
        report_count=case.report_count,
        assigned_reviewer_user_id=case.assigned_reviewer_user_id,
        assigned_reviewer_name=names.get(case.assigned_reviewer_user_id) if case.assigned_reviewer_user_id else None,
        opened_at=case.opened_at,
        first_reviewed_at=case.first_reviewed_at,
        resolved_at=case.resolved_at,
        resolution_summary=case.resolution_summary,
        signals=_hydrate_signals(db, case),
        reports=[
            ReportRow(
                id=r.id,
                reporter_user_id=r.reporter_user_id,
                reporter_name=names.get(r.reporter_user_id) if r.reporter_user_id else None,
                reporter_kind=r.reporter_kind,
                content_type=r.content_type,
                category=r.category,
                reporter_note=r.reporter_note,
                created_at=r.created_at,
            )
            for r in reports
        ],
        notes=[
            CaseNoteRow(
                id=n.id,
                author_user_id=n.author_user_id,
                author_name=names.get(n.author_user_id) if n.author_user_id else None,
                body=n.body,
                is_internal=n.is_internal,
                created_at=n.created_at,
            )
            for n in notes
        ],
        events=[
            CaseEventRow(
                id=e.id,
                kind=e.kind,
                actor_user_id=e.actor_user_id,
                actor_name=names.get(e.actor_user_id) if e.actor_user_id else None,
                occurred_at=e.occurred_at,
                previous_value=e.previous_value,
                new_value=e.new_value,
                reason=e.reason,
                internal_note=e.internal_note,
                subject_content_ref=e.subject_content_ref,
            )
            for e in events
        ],
        actions=[
            CaseActionRow(
                id=a.id,
                layer=a.layer,
                kind=a.kind,
                issued_by_admin_user_id=a.issued_by_admin_user_id,
                issued_by_admin_name=names.get(a.issued_by_admin_user_id) if a.issued_by_admin_user_id else None,
                reason=a.reason,
                internal_note=a.internal_note,
                explanation_to_recipient=a.explanation_to_recipient,
                affected_user_id=a.affected_user_id,
                affected_space_id=a.affected_space_id,
                affected_post_id=a.affected_post_id,
                affected_comment_id=a.affected_comment_id,
                starts_at=a.starts_at,
                ends_at=a.ends_at,
                reversed_at=a.reversed_at,
                reversed_by_admin_user_id=a.reversed_by_admin_user_id,
                reversal_reason=a.reversal_reason,
                restores_action_id=a.restores_action_id,
                created_at=a.created_at,
            )
            for a in actions
        ],
    )


# ---------------------------------------------------------------------------
# Case events (audit trail as its own endpoint)
# ---------------------------------------------------------------------------


@router.get("/cases/{case_id}/events", response_model=list[CaseEventRow])
def list_case_events(
    case_id: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[CaseEventRow]:
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")

    events = (
        db.query(CommunityCareCaseEvent)
        .filter(CommunityCareCaseEvent.case_id == case_id)
        .order_by(CommunityCareCaseEvent.occurred_at.asc())
        .all()
    )
    actor_ids = {e.actor_user_id for e in events if e.actor_user_id}
    names = _name_map(db, actor_ids)

    return [
        CaseEventRow(
            id=e.id, kind=e.kind, actor_user_id=e.actor_user_id,
            actor_name=names.get(e.actor_user_id) if e.actor_user_id else None,
            occurred_at=e.occurred_at,
            previous_value=e.previous_value, new_value=e.new_value,
            reason=e.reason, internal_note=e.internal_note,
            subject_content_ref=e.subject_content_ref,
        )
        for e in events
    ]


# ---------------------------------------------------------------------------
# Admin-seed report intake (Stage 2A)
# ---------------------------------------------------------------------------


@router.post("/reports", response_model=CaseDetail, status_code=201)
def seed_report(
    body: AdminSeedReportRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    """Admin-only path used during Stage 2A to seed cases so the review
    surface can be exercised before member-facing intake ships in 2B.
    """
    _ensure_flag_on()

    # 'something_else' requires a note (also enforced by DB CHECK)
    if body.category == "something_else":
        note = (body.reporter_note or "").strip()
        if not note:
            raise HTTPException(
                status_code=422,
                detail="A note is required when category is 'something_else'.",
            )

    # Dedupe against an existing open case for the same subject
    case = _find_open_case_for_report(db, body)

    if case is None:
        now = datetime.utcnow()
        case = CommunityCareCase(
            id=str(uuid4()),
            case_number=_next_case_number(db, now),
            content_type=body.content_type,
            subject_post_id=body.target_post_id,
            subject_comment_id=body.target_comment_id,
            subject_member_user_id=body.target_member_user_id,
            subject_creator_user_id=body.subject_creator_user_id,
            subject_space_id=body.subject_space_id,
            content_snapshot=_snapshot_content(db, body.target_post_id, body.target_comment_id),
            category=body.category,
            status="new",
            priority="low",   # ← always low on open; admin sets priority
            report_count=1,
            opened_at=now,
        )
        db.add(case)
        db.flush()
        _write_event(
            db, case=case, kind="case_opened",
            actor_user_id=admin.id,
            new_value={"case_number": case.case_number, "content_type": case.content_type},
        )
    else:
        case.report_count = (case.report_count or 0) + 1
        case.updated_at = datetime.utcnow()

    report = CommunityCareReport(
        id=str(uuid4()),
        case_id=case.id,
        reporter_user_id=admin.id if body.reporter_kind == "admin" else None,
        reporter_kind=body.reporter_kind,
        content_type=body.content_type,
        target_post_id=body.target_post_id,
        target_comment_id=body.target_comment_id,
        target_member_user_id=body.target_member_user_id,
        category=body.category,
        reporter_note=body.reporter_note,
    )
    db.add(report)
    db.flush()
    _write_event(
        db, case=case, kind="report_attached",
        actor_user_id=admin.id,
        new_value={"report_id": report.id, "category": body.category},
    )

    db.commit()
    db.refresh(case)
    return get_case(case.id, _=admin, db=db)


# ---------------------------------------------------------------------------
# Assign / status / priority / notes
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/assign", response_model=CaseDetail)
def assign_reviewer(
    case_id: str,
    body: AssignReviewerRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")

    if body.reviewer_user_id:
        reviewer = db.query(User).filter(User.id == body.reviewer_user_id).first()
        if not reviewer:
            raise HTTPException(status_code=404, detail="Reviewer user not found.")

    previous = case.assigned_reviewer_user_id
    case.assigned_reviewer_user_id = body.reviewer_user_id
    case.updated_at = datetime.utcnow()
    if body.reviewer_user_id and case.first_reviewed_at is None:
        case.first_reviewed_at = datetime.utcnow()
    _write_event(
        db, case=case, kind="assigned",
        actor_user_id=admin.id,
        previous_value={"assigned_reviewer_user_id": previous},
        new_value={"assigned_reviewer_user_id": body.reviewer_user_id},
    )
    db.commit()
    db.refresh(case)
    return get_case(case_id, _=admin, db=db)


@router.patch("/cases/{case_id}/status", response_model=CaseDetail)
def update_status(
    case_id: str,
    body: UpdateStatusRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")

    if body.status == case.status:
        return get_case(case_id, _=admin, db=db)

    # Terminal statuses use the /close endpoint; keep this route for
    # intermediate transitions only.
    if body.status in {"resolved", "closed_no_action"}:
        raise HTTPException(
            status_code=422,
            detail="Use POST /cases/{id}/close to close a case with an outcome.",
        )

    previous = case.status
    case.status = body.status
    case.updated_at = datetime.utcnow()
    if case.first_reviewed_at is None and body.status == "reviewing":
        case.first_reviewed_at = datetime.utcnow()
    _write_event(
        db, case=case, kind="status_changed",
        actor_user_id=admin.id,
        previous_value={"status": previous},
        new_value={"status": body.status},
        reason=body.reason,
        internal_note=body.internal_note,
    )
    db.commit()
    db.refresh(case)
    return get_case(case_id, _=admin, db=db)


@router.patch("/cases/{case_id}/priority", response_model=CaseDetail)
def update_priority(
    case_id: str,
    body: UpdatePriorityRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    """Priority is human-only. Every event row records the acting admin
    — no `actor_user_id IS NULL` events for priority in Stage 2A."""
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")

    if body.priority == case.priority:
        return get_case(case_id, _=admin, db=db)

    previous = case.priority
    case.priority = body.priority
    case.updated_at = datetime.utcnow()
    _write_event(
        db, case=case, kind="priority_changed",
        actor_user_id=admin.id,     # never NULL — priority is always set by a person
        previous_value={"priority": previous},
        new_value={"priority": body.priority},
        reason=body.reason,
        internal_note=body.internal_note,
    )
    db.commit()
    db.refresh(case)
    return get_case(case_id, _=admin, db=db)


@router.post("/cases/{case_id}/notes", response_model=CaseNoteRow, status_code=201)
def add_note(
    case_id: str,
    body: AddNoteRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseNoteRow:
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")

    note = CommunityCareCaseNote(
        id=str(uuid4()),
        case_id=case_id,
        author_user_id=admin.id,
        body=body.body.strip(),
        is_internal=True,
    )
    db.add(note)
    db.flush()
    _write_event(
        db, case=case, kind="note_added",
        actor_user_id=admin.id,
        new_value={"note_id": note.id},
    )
    db.commit()
    db.refresh(note)

    return CaseNoteRow(
        id=note.id,
        author_user_id=admin.id,
        author_name=admin.name,
        body=note.body,
        is_internal=note.is_internal,
        created_at=note.created_at,
    )


# ---------------------------------------------------------------------------
# Close case (resolution outcomes attach here)
# ---------------------------------------------------------------------------


@router.post("/cases/{case_id}/close", response_model=CaseDetail)
def close_case(
    case_id: str,
    body: CloseCaseRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    """Close a case with zero or more resolution outcomes.

    - Empty ``resolution_actions`` → status ``closed_no_action``.
    - Exactly one action of kind ``no_further_action`` → status
      ``closed_no_action``.
    - Any other resolution outcomes → status ``resolved``. Each
      resolution row is written to ``community_care_actions``, an
      ``action_issued`` case event is written, and — in Stage 2D —
      real platform state changes are applied where the outcome
      demands it (see ``_apply_resolution_outcome`` below).

    Stage 2D requires ``case_summary`` to be set on the case before
    any non-no-action close. Empty summary + real resolution
    outcomes → 422 so the operational record is never lost. The
    ``resolution_summary`` field remains optional and, when omitted,
    is filled from ``case_summary`` at close so the two never diverge.
    """
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")

    if case.status in {"resolved", "closed_no_action"}:
        raise HTTPException(status_code=409, detail="Case is already closed.")

    actions = body.resolution_actions
    is_no_action = (
        len(actions) == 0
        or (len(actions) == 1 and actions[0].kind == "no_further_action")
    )
    new_status = "closed_no_action" if is_no_action else "resolved"

    # Stage 2D — real resolution outcomes require an operational summary.
    if not is_no_action:
        summary = (case.case_summary or "").strip()
        if not summary:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A case summary is required before a final resolution. "
                    "Save one via PATCH /cases/{id}/summary, then close."
                ),
            )

    now = datetime.utcnow()
    for req in actions:
        action = CommunityCareAction(
            id=str(uuid4()),
            case_id=case.id,
            layer="resolution",
            kind=req.kind,
            issued_by_admin_user_id=admin.id,
            reason=req.reason,
            internal_note=req.internal_note,
            explanation_to_recipient=req.explanation_to_recipient,
            affected_user_id=req.affected_user_id,
            affected_space_id=req.affected_space_id,
            affected_post_id=req.affected_post_id,
            affected_comment_id=req.affected_comment_id,
            restores_action_id=req.restores_action_id,
            starts_at=now,
        )
        db.add(action)
        db.flush()
        _write_event(
            db, case=case, kind="action_issued",
            actor_user_id=admin.id,
            new_value={"action_id": action.id, "layer": "resolution", "kind": req.kind},
            reason=req.reason,
            internal_note=req.internal_note,
        )
        _apply_resolution_outcome(db, action=action, case=case, admin=admin)

    previous = case.status
    case.status = new_status
    case.resolved_at = now
    if body.resolution_summary:
        case.resolution_summary = body.resolution_summary.strip()
    elif case.case_summary:
        # Freeze the operational summary into the close-time record so
        # future edits to case_summary can't rewrite history.
        case.resolution_summary = case.case_summary.strip()
    case.updated_at = now
    _write_event(
        db, case=case, kind="closed",
        actor_user_id=admin.id,
        previous_value={"status": previous},
        new_value={"status": new_status},
    )

    db.commit()
    db.refresh(case)
    return get_case(case_id, _=admin, db=db)


# ---------------------------------------------------------------------------
# PATCH /cases/{id}/summary — operational summary
# ---------------------------------------------------------------------------


@router.patch("/cases/{case_id}/summary", response_model=CaseDetail)
def update_case_summary(
    case_id: str,
    body: CaseSummaryRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    """Update the operational case summary while the case is open.

    Editable freely during investigation; refused (409) once the case
    is closed. Every change writes a ``note_added``-shaped case event
    with the new value in ``new_value``. The prior value is not
    preserved on the case row itself — the case events append-only
    trail is the record of every intermediate summary.
    """
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case.status in {"resolved", "closed_no_action"}:
        raise HTTPException(
            status_code=409,
            detail="This case is closed. Summaries are frozen after resolution.",
        )

    previous = case.case_summary
    case.case_summary = (body.case_summary or "").strip() or None
    case.updated_at = datetime.utcnow()
    _write_event(
        db, case=case, kind="note_added",
        actor_user_id=admin.id,
        previous_value={"case_summary": previous} if previous else None,
        new_value={"case_summary": case.case_summary},
    )
    db.commit()
    db.refresh(case)
    return get_case(case_id, _=admin, db=db)


# ---------------------------------------------------------------------------
# Stage 2D — resolution-outcome enforcement
# ---------------------------------------------------------------------------
#
# Called from ``close_case`` inside the same transaction that writes
# the resolution action row. Each branch is idempotent; each also
# sends the appropriate recipient notification via the Stage 2C
# ``_notify_recipient_action`` helper (with Stage 2D severity mapping).


_RESOLUTION_SEVERITY_BY_KIND: dict[str, str] = {
    "no_further_action": "routine",
    "restore_content": "action",
    "restore_account": "action",
    "restore_collective": "action",
    "account_cancellation": "urgent",
    "creator_account_cancellation": "urgent",
    "collective_closure_removal": "urgent",
}

_RESOLUTION_TITLES_BY_KIND: dict[str, str] = {
    "restore_content": "Your content has been restored",
    "restore_account": "Your account access has been restored",
    "restore_collective": "Your collective has been restored",
    "account_cancellation": "Your Fresh Collective account has been cancelled",
    "creator_account_cancellation": "Your creator role on Fresh Collective has been cancelled",
    "collective_closure_removal": "Your collective has been closed",
}


def _notify_resolution(
    db: Session,
    *,
    recipient_id: str,
    kind: str,
    case_number: str,
    explanation: str | None,
) -> None:
    severity = _RESOLUTION_SEVERITY_BY_KIND.get(kind, "action")
    title = _RESOLUTION_TITLES_BY_KIND.get(kind, "A note from Fresh Collective")
    base = (explanation or "").strip()
    message = base or "A Fresh Collective administrator will be in touch with more detail."
    # Cancellation and closure outcomes get an explicit access-change
    # sentence so the recipient understands what has changed.
    if kind == "account_cancellation":
        message += (
            "\n\nThis is a final resolution outcome. You will no longer be "
            "able to sign in or use Fresh Collective."
        )
    elif kind == "creator_account_cancellation":
        message += (
            "\n\nThis is a final resolution outcome. Your creator role has "
            "been cancelled. Your member access continues unaffected."
        )
    elif kind == "collective_closure_removal":
        message += (
            "\n\nThis is a final resolution outcome. The collective is closed "
            "to new members, renewals, purchases and bookings. Existing "
            "content remains readable in Fresh Collective's records."
        )
    elif kind in {"restore_content", "restore_account", "restore_collective"}:
        message += (
            "\n\nThe temporary protective measure has been lifted as the "
            "final outcome of this review."
        )
    message += f"\n\nIf you would like to reach us, reference {case_number}."
    notif = Notification(
        id=str(uuid4()),
        user_id=recipient_id,
        notification_type=f"community_care_{kind}",
        title=title,
        message=message,
        url=None,
        is_read=False,
        severity=severity,
    )
    db.add(notif)


def _apply_resolution_outcome(
    db: Session,
    *,
    action: CommunityCareAction,
    case: CommunityCareCase,
    admin: User,
) -> None:
    """Apply the real-world effect of a resolution outcome.

    Each branch is:
      * transactional with the recording of the action row;
      * idempotent — re-applying to already-terminal state is a no-op;
      * accompanied by an appropriate recipient notification.

    Restore outcomes do NOT edit the prior protective action rows;
    they simply write a new resolution row and clear the enforcement
    state. The audit trail remains complete on both directions.
    """
    kind = action.kind
    recipient_id: str | None = None
    if kind == "no_further_action":
        return  # nothing to enforce, no notification

    if kind == "restore_content":
        if action.affected_post_id:
            post = db.query(CommunityPost).filter(
                CommunityPost.id == action.affected_post_id
            ).first()
            if post is not None:
                post.cc_hidden_at = None
                post.cc_hidden_action_id = None
                recipient_id = post.author_id
        elif action.affected_comment_id:
            comment = db.query(PostComment).filter(
                PostComment.id == action.affected_comment_id
            ).first()
            if comment is not None:
                comment.cc_hidden_at = None
                comment.cc_hidden_action_id = None
                recipient_id = comment.author_id

    elif kind == "restore_account":
        if action.affected_user_id:
            user = db.query(User).filter(User.id == action.affected_user_id).first()
            if user is not None:
                user.suspended_at = None
                user.suspended_until = None
                user.suspension_reason = None
                user.suspended_by_action_id = None
                recipient_id = user.id

    elif kind == "restore_collective":
        if action.affected_space_id:
            space = db.query(Space).filter(Space.id == action.affected_space_id).first()
            if space is not None:
                space.frozen_at = None
                space.frozen_until = None
                space.freeze_reason = None
                space.frozen_by_action_id = None
                recipient_id = space.creator_id

    elif kind == "account_cancellation":
        if not action.affected_user_id:
            raise HTTPException(
                status_code=422,
                detail="account_cancellation requires affected_user_id.",
            )
        user = db.query(User).filter(User.id == action.affected_user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        user.cancelled_at = datetime.utcnow()
        user.cancellation_reason = action.internal_note or action.reason
        user.cancelled_by_action_id = action.id
        recipient_id = user.id

    elif kind == "creator_account_cancellation":
        if not action.affected_user_id:
            raise HTTPException(
                status_code=422,
                detail="creator_account_cancellation requires affected_user_id.",
            )
        user = db.query(User).filter(User.id == action.affected_user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        user.creator_cancelled_at = datetime.utcnow()
        user.creator_cancellation_reason = action.internal_note or action.reason
        user.creator_cancelled_by_action_id = action.id
        recipient_id = user.id

    elif kind == "collective_closure_removal":
        if not action.affected_space_id:
            raise HTTPException(
                status_code=422,
                detail="collective_closure_removal requires affected_space_id.",
            )
        space = db.query(Space).filter(Space.id == action.affected_space_id).first()
        if space is None:
            raise HTTPException(status_code=404, detail="Collective not found.")
        space.closed_at = datetime.utcnow()
        space.closure_reason = action.internal_note or action.reason
        space.closed_by_action_id = action.id
        recipient_id = space.creator_id

    if recipient_id:
        _notify_resolution(
            db,
            recipient_id=recipient_id,
            kind=kind,
            case_number=case.case_number,
            explanation=action.explanation_to_recipient,
        )


# ---------------------------------------------------------------------------
# Stage 2C — Supportive Responses + Protective Measures
# ---------------------------------------------------------------------------
#
# The separation between recording, notifying and enforcing is
# deliberate and mirrored in code shape:
#
#   1. ``_record_action`` writes an append-only
#      ``community_care_actions`` row plus an ``action_issued`` event.
#   2. ``_apply_protective_enforcement`` mutates the platform state
#      touched by the measure (cc_hidden, member_restrictions, spaces
#      frozen_at, users suspended_at).
#   3. ``_notify_recipient_action`` sends the recipient-facing message
#      with the agreed severity.
#
# All three happen in a single transaction so the audit row and the
# real-world state cannot drift apart.


_SEVERITY_BY_KIND: dict[str, str] = {
    # Supportive
    "guidance": "routine",
    "reminder": "routine",
    "warning": "action",
    # Protective
    "content_hidden": "action",
    "posting_restriction": "action",
    "creator_restriction": "action",
    "collective_freeze": "action",
    "suspension_pending_review": "urgent",
}


_TITLES_BY_KIND: dict[str, str] = {
    "guidance": "A note from Fresh Collective",
    "reminder": "A reminder from Fresh Collective",
    "warning": "A warning from Fresh Collective",
    "content_hidden": "Your content is no longer visible while we review",
    "posting_restriction": "Your posting is temporarily restricted",
    "creator_restriction": "Your creator functions are temporarily restricted",
    "collective_freeze": "Your collective is temporarily paused",
    "suspension_pending_review": "Your account has been suspended pending review",
}


def _record_action(
    db: Session,
    *,
    case: CommunityCareCase,
    admin: User,
    layer: str,
    kind: str,
    reason: str | None,
    internal_note: str | None,
    explanation_to_recipient: str | None,
    affected_user_id: str | None = None,
    affected_space_id: str | None = None,
    affected_post_id: str | None = None,
    affected_comment_id: str | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> CommunityCareAction:
    """Append a Community Care action row and its ``action_issued``
    event. Never mutated after creation — reversal writes new rows on
    top of this one (and updates the reversal fields *on this row* as
    part of the standard reversal ledger)."""
    now = starts_at or datetime.utcnow()
    action = CommunityCareAction(
        id=str(uuid4()),
        case_id=case.id,
        layer=layer,
        kind=kind,
        issued_by_admin_user_id=admin.id,
        reason=reason,
        internal_note=internal_note,
        explanation_to_recipient=explanation_to_recipient,
        affected_user_id=affected_user_id,
        affected_space_id=affected_space_id,
        affected_post_id=affected_post_id,
        affected_comment_id=affected_comment_id,
        starts_at=now,
        ends_at=ends_at,
    )
    db.add(action)
    db.flush()
    _write_event(
        db, case=case, kind="action_issued",
        actor_user_id=admin.id,
        new_value={
            "action_id": action.id, "layer": layer, "kind": kind,
            "affected_user_id": affected_user_id,
            "affected_space_id": affected_space_id,
            "affected_post_id": affected_post_id,
            "affected_comment_id": affected_comment_id,
        },
        reason=reason,
        internal_note=internal_note,
    )
    return action


def _notify_recipient_action(
    db: Session,
    *,
    recipient_id: str,
    kind: str,
    explanation: str | None,
    case_number: str,
) -> None:
    """Send the recipient a notification of the action taken, with the
    agreed severity. Every message reminds the recipient that they can
    contact Fresh Collective; none reveal the reporter."""
    severity = _SEVERITY_BY_KIND.get(kind, "action")
    title = _TITLES_BY_KIND.get(kind, "A note from Fresh Collective")
    base = (explanation or "").strip()
    message = base or "A Fresh Collective administrator will be in touch with more detail."
    # For measures with concrete effects, spell out what can and cannot
    # be done so the recipient has agency inside the constraint.
    if kind == "posting_restriction":
        message += (
            "\n\nWhile this restriction is in place you can still sign in, "
            "view collectives, pathways, and existing conversations, and "
            "manage your account. You cannot post, comment, reply, or react."
        )
    elif kind == "creator_restriction":
        message += (
            "\n\nWhile this restriction is in place you can still sign in "
            "and view your collective and existing content. You cannot "
            "publish or edit content, create or edit pathways, create or "
            "host gatherings, moderate members, or change collective "
            "settings."
        )
    elif kind == "collective_freeze":
        message += (
            "\n\nWhile the freeze is in place existing content remains "
            "visible. New posts, comments, reactions, bookings, "
            "purchases and settings changes are paused."
        )
    elif kind == "suspension_pending_review":
        message += (
            "\n\nThis is a temporary protective measure, not a finding "
            "or a punishment. You cannot sign in or access authenticated "
            "areas of the platform until the review is complete."
        )
    elif kind == "content_hidden":
        message += (
            "\n\nThis is not a permanent removal. If the review clears "
            "the content it will be restored."
        )
    message += f"\n\nIf you would like to reach us, reference {case_number}."
    notif = Notification(
        id=str(uuid4()),
        user_id=recipient_id,
        notification_type=f"community_care_{kind}",
        title=title,
        message=message,
        url=None,
        is_read=False,
        severity=severity,
    )
    db.add(notif)


def _apply_protective_enforcement(
    db: Session,
    *,
    action: CommunityCareAction,
) -> None:
    """Wire the platform state that gives a protective measure teeth.

    Every branch here is idempotent: re-applying the same enforcement
    to the same target is a no-op (the duplicate-action guard has
    already refused the request higher up). Every branch also cleanly
    reversible — see ``_reverse_protective_enforcement``."""
    kind = action.kind
    if kind == "content_hidden":
        if action.affected_post_id:
            post = db.query(CommunityPost).filter(
                CommunityPost.id == action.affected_post_id
            ).first()
            if post:
                post.cc_hidden_at = action.starts_at
                post.cc_hidden_action_id = action.id
        if action.affected_comment_id:
            comment = db.query(PostComment).filter(
                PostComment.id == action.affected_comment_id
            ).first()
            if comment:
                comment.cc_hidden_at = action.starts_at
                comment.cc_hidden_action_id = action.id
    elif kind in {"posting_restriction", "creator_restriction"}:
        restriction_kind = "posting" if kind == "posting_restriction" else "creator"
        assert action.affected_user_id is not None
        restriction = MemberRestriction(
            id=str(uuid4()),
            user_id=action.affected_user_id,
            space_id=action.affected_space_id,  # scoped for posting; ignored for creator
            kind=restriction_kind,
            starts_at=action.starts_at,
            ends_at=action.ends_at,
            reason=action.internal_note or action.reason,
            issued_by_admin_user_id=action.issued_by_admin_user_id,
            action_id=action.id,
        )
        db.add(restriction)
    elif kind == "collective_freeze":
        assert action.affected_space_id is not None
        space = db.query(Space).filter(Space.id == action.affected_space_id).first()
        if space is None:
            raise HTTPException(status_code=404, detail="Collective not found.")
        space.frozen_at = action.starts_at
        space.frozen_until = action.ends_at
        space.freeze_reason = action.internal_note or action.reason
        space.frozen_by_action_id = action.id
    elif kind == "suspension_pending_review":
        assert action.affected_user_id is not None
        user = db.query(User).filter(User.id == action.affected_user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        user.suspended_at = action.starts_at
        user.suspended_until = action.ends_at
        user.suspension_reason = action.internal_note or action.reason
        user.suspended_by_action_id = action.id


def _reverse_protective_enforcement(
    db: Session,
    *,
    action: CommunityCareAction,
) -> None:
    """Undo the platform state that the given action put in place.

    Ordering matches ``_apply_protective_enforcement`` and every branch
    is idempotent — reversing an already-reversed action is a no-op at
    the state layer (the caller still writes the audit event)."""
    kind = action.kind
    if kind == "content_hidden":
        if action.affected_post_id:
            post = db.query(CommunityPost).filter(
                CommunityPost.id == action.affected_post_id
            ).first()
            if post and post.cc_hidden_action_id == action.id:
                post.cc_hidden_at = None
                post.cc_hidden_action_id = None
        if action.affected_comment_id:
            comment = db.query(PostComment).filter(
                PostComment.id == action.affected_comment_id
            ).first()
            if comment and comment.cc_hidden_action_id == action.id:
                comment.cc_hidden_at = None
                comment.cc_hidden_action_id = None
    elif kind in {"posting_restriction", "creator_restriction"}:
        rows = (
            db.query(MemberRestriction)
            .filter(MemberRestriction.action_id == action.id)
            .all()
        )
        for r in rows:
            if r.reversed_at is None:
                r.reversed_at = datetime.utcnow()
    elif kind == "collective_freeze":
        if action.affected_space_id:
            space = db.query(Space).filter(Space.id == action.affected_space_id).first()
            if space and space.frozen_by_action_id == action.id:
                space.frozen_at = None
                space.frozen_until = None
                space.freeze_reason = None
                space.frozen_by_action_id = None
    elif kind == "suspension_pending_review":
        if action.affected_user_id:
            user = db.query(User).filter(User.id == action.affected_user_id).first()
            if user and user.suspended_by_action_id == action.id:
                user.suspended_at = None
                user.suspended_until = None
                user.suspension_reason = None
                user.suspended_by_action_id = None


# ---------------------------------------------------------------------------
# POST /cases/{id}/actions/supportive  —  Guidance / Reminder / Warning
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/actions/supportive",
    response_model=CaseDetail,
    status_code=201,
)
def issue_supportive_action(
    case_id: str,
    body: IssueSupportiveActionRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    """Record a Supportive Response and notify the recipient. Supportive
    Responses never restrict access — enforcement is the notification
    itself. They are never reversed (the case history keeps them
    permanently as part of the record)."""
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case.status in {"resolved", "closed_no_action"}:
        raise HTTPException(
            status_code=409,
            detail="Case is closed. Reopen a case before issuing further actions.",
        )
    recipient = db.query(User).filter(User.id == body.affected_user_id).first()
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient user not found.")

    action = _record_action(
        db,
        case=case,
        admin=admin,
        layer="supportive",
        kind=body.kind,
        reason=None,
        internal_note=body.internal_note,
        explanation_to_recipient=body.explanation_to_recipient,
        affected_user_id=body.affected_user_id,
    )
    _notify_recipient_action(
        db,
        recipient_id=body.affected_user_id,
        kind=body.kind,
        explanation=body.explanation_to_recipient,
        case_number=case.case_number,
    )
    case.updated_at = datetime.utcnow()
    if case.first_reviewed_at is None:
        case.first_reviewed_at = case.updated_at
    if case.status == "new":
        case.status = "reviewing"
    db.commit()
    db.refresh(case)
    return get_case(case_id, _=admin, db=db)


# ---------------------------------------------------------------------------
# POST /cases/{id}/actions/protective  —  Hide / Restriction / Freeze / Suspension
# ---------------------------------------------------------------------------


def _validate_protective_target(
    db: Session, body: IssueProtectiveActionRequest
) -> None:
    """Enforce per-kind target shape and verify the referenced rows
    exist. Rejects the shape at 422 (bad request) and missing rows at
    404 so operators can tell the difference in logs."""
    if body.kind == "content_hidden":
        if bool(body.affected_post_id) == bool(body.affected_comment_id):
            raise HTTPException(
                status_code=422,
                detail="content_hidden must target exactly one of post or comment.",
            )
        if body.affected_post_id:
            if not db.query(CommunityPost.id).filter(
                CommunityPost.id == body.affected_post_id
            ).first():
                raise HTTPException(status_code=404, detail="Post not found.")
        else:
            if not db.query(PostComment.id).filter(
                PostComment.id == body.affected_comment_id
            ).first():
                raise HTTPException(status_code=404, detail="Comment not found.")
    elif body.kind in {"posting_restriction", "creator_restriction",
                       "suspension_pending_review"}:
        if not body.affected_user_id:
            raise HTTPException(
                status_code=422,
                detail=f"{body.kind} requires affected_user_id.",
            )
        if not db.query(User.id).filter(User.id == body.affected_user_id).first():
            raise HTTPException(status_code=404, detail="User not found.")
    elif body.kind == "collective_freeze":
        if not body.affected_space_id:
            raise HTTPException(
                status_code=422,
                detail="collective_freeze requires affected_space_id.",
            )
        if not db.query(Space.id).filter(Space.id == body.affected_space_id).first():
            raise HTTPException(status_code=404, detail="Collective not found.")

    # Recipient-facing explanation is required whenever there is a
    # recipient. content_hidden may proceed without one — the recipient
    # is the post/comment author and the notification renders a
    # sensible default.
    if body.kind != "content_hidden":
        if not (body.explanation_to_recipient or "").strip():
            raise HTTPException(
                status_code=422,
                detail="A recipient-facing explanation is required for this measure.",
            )


@router.post(
    "/cases/{case_id}/actions/protective",
    response_model=CaseDetail,
    status_code=201,
)
def issue_protective_action(
    case_id: str,
    body: IssueProtectiveActionRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    _ensure_flag_on()

    case = db.query(CommunityCareCase).filter(CommunityCareCase.id == case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if case.status in {"resolved", "closed_no_action"}:
        raise HTTPException(
            status_code=409,
            detail="Case is closed. Reopen a case before issuing further actions.",
        )

    _validate_protective_target(db, body)

    # Duplicate protective action on the same live target = 409. Prevents
    # a double-clicked button from stacking two identical restrictions.
    existing = active_protective_action_on_target(
        db,
        kind=body.kind,
        affected_user_id=body.affected_user_id,
        affected_space_id=body.affected_space_id,
        affected_post_id=body.affected_post_id,
        affected_comment_id=body.affected_comment_id,
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An identical protective measure is already active on this target.",
        )

    action = _record_action(
        db,
        case=case,
        admin=admin,
        layer="protective",
        kind=body.kind,
        reason=body.reason,
        internal_note=body.internal_note,
        explanation_to_recipient=body.explanation_to_recipient,
        affected_user_id=body.affected_user_id,
        affected_space_id=body.affected_space_id,
        affected_post_id=body.affected_post_id,
        affected_comment_id=body.affected_comment_id,
        ends_at=body.ends_at,
    )
    _apply_protective_enforcement(db, action=action)

    # Notify recipients where there is one. content_hidden notifies the
    # content author; the other kinds notify affected_user_id (or, for
    # collective_freeze, the collective's creator).
    recipient_id: str | None = None
    if body.kind == "content_hidden":
        if body.affected_post_id:
            post = db.query(CommunityPost).filter(
                CommunityPost.id == body.affected_post_id
            ).first()
            recipient_id = post.author_id if post else None
        elif body.affected_comment_id:
            comment = db.query(PostComment).filter(
                PostComment.id == body.affected_comment_id
            ).first()
            recipient_id = comment.author_id if comment else None
    elif body.kind == "collective_freeze":
        assert body.affected_space_id is not None
        space = db.query(Space).filter(Space.id == body.affected_space_id).first()
        recipient_id = space.creator_id if space else None
    else:
        recipient_id = body.affected_user_id

    if recipient_id:
        _notify_recipient_action(
            db,
            recipient_id=recipient_id,
            kind=body.kind,
            explanation=body.explanation_to_recipient,
            case_number=case.case_number,
        )

    case.updated_at = datetime.utcnow()
    if case.first_reviewed_at is None:
        case.first_reviewed_at = case.updated_at
    if case.status in {"new"}:
        case.status = "action_required"
    db.commit()
    db.refresh(case)
    return get_case(case_id, _=admin, db=db)


# ---------------------------------------------------------------------------
# POST /actions/{action_id}/reverse  —  reverse a protective measure
# ---------------------------------------------------------------------------


@router.post(
    "/actions/{action_id}/reverse",
    response_model=CaseDetail,
)
def reverse_action(
    action_id: str,
    body: ReverseActionRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CaseDetail:
    """Reverse a Protective Measure.

    A reversal never edits or deletes the original action row. The
    reversal fields on that same row are the only mutable columns —
    they are effectively the reversal ledger's write-through cache
    onto the action being reversed. A new ``action_reversed`` event is
    appended to the case timeline in the same transaction so the audit
    trail records both sides.

    Supportive Responses are not reversible; they remain part of the
    case history."""
    _ensure_flag_on()

    action = db.query(CommunityCareAction).filter(
        CommunityCareAction.id == action_id
    ).first()
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found.")
    if action.layer != "protective":
        raise HTTPException(
            status_code=400,
            detail="Only protective measures can be reversed.",
        )
    if action.reversed_at is not None:
        raise HTTPException(status_code=409, detail="This action is already reversed.")

    case = db.query(CommunityCareCase).filter(
        CommunityCareCase.id == action.case_id
    ).first()
    if case is None:
        # Should never happen thanks to FK, but be explicit.
        raise HTTPException(status_code=404, detail="Case not found.")

    now = datetime.utcnow()
    action.reversed_at = now
    action.reversed_by_admin_user_id = admin.id
    action.reversal_reason = body.reversal_reason.strip()

    _reverse_protective_enforcement(db, action=action)

    _write_event(
        db, case=case, kind="action_reversed",
        actor_user_id=admin.id,
        previous_value={"action_id": action.id, "kind": action.kind},
        new_value={"reversed_at": now.isoformat()},
        reason=body.reversal_reason,
    )

    # Notify the affected party where there is one. Same routing as
    # issue: hides notify the content author; freezes notify the
    # creator; user-targeted measures notify the affected user.
    recipient_id: str | None = None
    if action.kind == "content_hidden":
        if action.affected_post_id:
            post = db.query(CommunityPost).filter(
                CommunityPost.id == action.affected_post_id
            ).first()
            recipient_id = post.author_id if post else None
        elif action.affected_comment_id:
            comment = db.query(PostComment).filter(
                PostComment.id == action.affected_comment_id
            ).first()
            recipient_id = comment.author_id if comment else None
    elif action.kind == "collective_freeze":
        if action.affected_space_id:
            space = db.query(Space).filter(Space.id == action.affected_space_id).first()
            recipient_id = space.creator_id if space else None
    else:
        recipient_id = action.affected_user_id

    if recipient_id:
        notif = Notification(
            id=str(uuid4()),
            user_id=recipient_id,
            notification_type=f"community_care_reversed_{action.kind}",
            title="Fresh Collective has lifted a temporary measure",
            message=(
                f"A protective measure on your account or content has been "
                f"lifted. Reason: {body.reversal_reason.strip()}. "
                f"You can reference {case.case_number} if you need to reach us."
            ),
            url=None,
            is_read=False,
            severity="action",
        )
        db.add(notif)

    case.updated_at = now
    db.commit()
    db.refresh(case)
    return get_case(case.id, _=admin, db=db)
