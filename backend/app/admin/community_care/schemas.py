"""
Pydantic schemas for the Community Care admin surface — Stage 2A.

Shapes echo `app.models.community_care`. Enum values are validated
against the model-level string tuples so the schema, the model, and
migration 084's CHECK constraints stay in lockstep.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.community_care import (
    ACTION_KINDS,
    ACTION_LAYERS,
    CASE_CONTENT_TYPES,
    CASE_PRIORITIES,
    CASE_STATUSES,
    CREATOR_REQUEST_SCOPES,
    REPORT_CATEGORIES,
    REPORTER_KINDS,
    layer_for_kind,
)


# ---------------------------------------------------------------------------
# Overview (top of the Community Care page)
# ---------------------------------------------------------------------------


class OutcomeCounts(BaseModel):
    """Stage 2D operational reporting — simple counts of actions taken
    over the lifetime of the deployment. No time windows or trends —
    those can be added later if genuinely useful."""
    guidance: int
    reminders: int
    warnings: int
    protective_measures: int
    no_further_action: int
    account_cancellations: int
    creator_cancellations: int
    collective_closures: int


class CommunityCareOverview(BaseModel):
    """The four hero cards on the Community Care page.

    Wellbeing rule (locked): Healthy when no open case has priority
    'high' or 'immediate'; Needs attention when any open case is 'high';
    Needs care when any open case is 'immediate'. Case-volume and SLA
    heuristics are deliberately deferred.
    """
    communities_needing_care: int
    conversations_awaiting_review: int
    creator_support_requests: int
    overall_wellbeing: str            # 'healthy' | 'needs_attention' | 'needs_care'
    overall_wellbeing_label: str      # human-facing string for the card value
    outcomes: OutcomeCounts


# ---------------------------------------------------------------------------
# Case list + detail
# ---------------------------------------------------------------------------


class CaseListRow(BaseModel):
    id: str
    case_number: str
    content_type: str
    subject_space_id: str | None
    subject_space_name: str | None
    subject_member_user_id: str | None
    subject_member_name: str | None
    category: str | None
    creator_request_scope: str | None
    status: str
    priority: str
    report_count: int
    assigned_reviewer_user_id: str | None
    assigned_reviewer_name: str | None
    opened_at: datetime
    resolved_at: datetime | None


class ReportRow(BaseModel):
    id: str
    reporter_user_id: str | None
    reporter_name: str | None          # admin-only view; name displayed to reviewers
    reporter_kind: str
    content_type: str
    category: str
    reporter_note: str | None
    created_at: datetime


class CaseNoteRow(BaseModel):
    id: str
    author_user_id: str | None
    author_name: str | None
    body: str
    is_internal: bool
    created_at: datetime


class CaseEventRow(BaseModel):
    id: str
    kind: str
    actor_user_id: str | None
    actor_name: str | None
    occurred_at: datetime
    previous_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    reason: str | None
    internal_note: str | None
    subject_content_ref: dict[str, Any] | None


class CaseActionRow(BaseModel):
    id: str
    layer: str
    kind: str
    issued_by_admin_user_id: str | None
    issued_by_admin_name: str | None
    reason: str | None
    internal_note: str | None
    explanation_to_recipient: str | None
    affected_user_id: str | None
    affected_space_id: str | None
    affected_post_id: str | None
    affected_comment_id: str | None
    starts_at: datetime
    ends_at: datetime | None
    reversed_at: datetime | None
    reversed_by_admin_user_id: str | None
    reversal_reason: str | None
    restores_action_id: str | None
    created_at: datetime


class CaseSignals(BaseModel):
    """Facts a reviewer may find useful, never recommendations.
    Priority remains admin-set — no auto-suggestion is made from these."""
    reports_on_case: int
    prior_cases_for_member: int    # cases involving the same reported member
    prior_cases_for_creator: int   # cases involving the same collective's creator


class CaseDetail(BaseModel):
    id: str
    case_number: str
    case_summary: str | None
    content_type: str
    subject_post_id: str | None
    subject_comment_id: str | None
    subject_member_user_id: str | None
    subject_member_name: str | None
    subject_creator_user_id: str | None
    subject_creator_name: str | None
    subject_space_id: str | None
    subject_space_name: str | None
    content_snapshot: dict[str, Any] | None
    category: str | None
    creator_request_scope: str | None
    status: str
    priority: str
    report_count: int
    assigned_reviewer_user_id: str | None
    assigned_reviewer_name: str | None
    opened_at: datetime
    first_reviewed_at: datetime | None
    resolved_at: datetime | None
    resolution_summary: str | None
    signals: CaseSignals
    reports: list[ReportRow]
    notes: list[CaseNoteRow]
    events: list[CaseEventRow]
    actions: list[CaseActionRow]


# ---------------------------------------------------------------------------
# Write requests
# ---------------------------------------------------------------------------


class AdminSeedReportRequest(BaseModel):
    """Admin-only intake path used to seed cases for review testing in
    Stage 2A. Member-facing intake ships in Stage 2B."""
    reporter_kind: str = "admin"
    content_type: str
    target_post_id: str | None = None
    target_comment_id: str | None = None
    target_member_user_id: str | None = None
    subject_space_id: str | None = None
    subject_creator_user_id: str | None = None
    category: str
    reporter_note: str | None = None

    @field_validator("reporter_kind")
    @classmethod
    def _valid_reporter_kind(cls, v: str) -> str:
        if v not in REPORTER_KINDS:
            raise ValueError(f"reporter_kind must be one of {list(REPORTER_KINDS)}")
        return v

    @field_validator("content_type")
    @classmethod
    def _valid_content_type(cls, v: str) -> str:
        if v not in CASE_CONTENT_TYPES:
            raise ValueError(f"content_type must be one of {list(CASE_CONTENT_TYPES)}")
        return v

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in REPORT_CATEGORIES:
            raise ValueError(f"category must be one of {list(REPORT_CATEGORIES)}")
        return v


class AssignReviewerRequest(BaseModel):
    reviewer_user_id: str | None    # None to unassign


class UpdateStatusRequest(BaseModel):
    status: str
    reason: str | None = None
    internal_note: str | None = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in CASE_STATUSES:
            raise ValueError(f"status must be one of {list(CASE_STATUSES)}")
        return v


class UpdatePriorityRequest(BaseModel):
    """Priority is set by an admin, always. The endpoint refuses if the
    request cannot identify the acting admin — no system-set priority
    exists in Stage 2A."""
    priority: str
    reason: str | None = None
    internal_note: str | None = None

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, v: str) -> str:
        if v not in CASE_PRIORITIES:
            raise ValueError(f"priority must be one of {list(CASE_PRIORITIES)}")
        return v


class AddNoteRequest(BaseModel):
    body: str = Field(..., min_length=1)


class ResolutionAction(BaseModel):
    """A single resolution row to attach on close. Multiple rows may be
    issued in the same close request (e.g. creator cancellation +
    per-collective closure decisions — case-by-case, never cascading)."""
    kind: str
    reason: str | None = None
    internal_note: str | None = None
    explanation_to_recipient: str | None = None
    affected_user_id: str | None = None
    affected_space_id: str | None = None
    affected_post_id: str | None = None
    affected_comment_id: str | None = None
    restores_action_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _resolution_kind(cls, v: str) -> str:
        if v not in ACTION_KINDS:
            raise ValueError(f"kind must be a known action kind")
        if layer_for_kind(v) != "resolution":
            raise ValueError(f"kind {v!r} is not a resolution — use the appropriate endpoint")
        return v


class IssueSupportiveActionRequest(BaseModel):
    """Issue a Supportive Response — ``guidance``, ``reminder``, or
    ``warning``. Every field except ``internal_note`` is required.

    Supportive Responses always have a specific recipient (a member or
    a creator) and always carry a recipient-facing explanation. They
    do not restrict access; enforcement is purely educational
    (notification only).
    """
    kind: str
    affected_user_id: str
    explanation_to_recipient: str = Field(..., min_length=1)
    internal_note: str | None = None

    @field_validator("kind")
    @classmethod
    def _supportive(cls, v: str) -> str:
        if v not in ACTION_KINDS:
            raise ValueError("kind is not a known action kind")
        if layer_for_kind(v) != "supportive":
            raise ValueError(f"kind {v!r} is not a supportive response")
        return v


class IssueProtectiveActionRequest(BaseModel):
    """Issue a Protective Measure.

    Every kind has a specific target shape:

    - ``content_hidden`` → post_id or comment_id
    - ``posting_restriction`` → affected_user_id (space_id optional)
    - ``creator_restriction`` → affected_user_id
    - ``collective_freeze`` → affected_space_id
    - ``suspension_pending_review`` → affected_user_id

    ``reason`` is required internally. ``explanation_to_recipient`` is
    required whenever the measure has a recipient (all kinds except
    ``content_hidden`` on its own).
    """
    kind: str
    affected_user_id: str | None = None
    affected_space_id: str | None = None
    affected_post_id: str | None = None
    affected_comment_id: str | None = None
    reason: str = Field(..., min_length=1)
    internal_note: str | None = None
    explanation_to_recipient: str | None = None
    ends_at: datetime | None = None

    @field_validator("kind")
    @classmethod
    def _protective(cls, v: str) -> str:
        if v not in ACTION_KINDS:
            raise ValueError("kind is not a known action kind")
        if layer_for_kind(v) != "protective":
            raise ValueError(f"kind {v!r} is not a protective measure")
        # Stage 2C does not implement ``content_removed_from_public``;
        # remove has its own resolution-layer counterpart in Stage 2D.
        if v == "content_removed_from_public":
            raise ValueError(
                "content_removed_from_public ships in Stage 2D — use content_hidden here."
            )
        return v


class ReverseActionRequest(BaseModel):
    """Reverse an active Protective Measure.

    Reason is required so the audit trail carries a rationale for both
    directions of the action.
    """
    reversal_reason: str = Field(..., min_length=1)


class CloseCaseRequest(BaseModel):
    """Close a case with a final resolution.

    The Stage 2A "no action" path remains available: an empty
    ``resolution_actions`` list — or a single ``no_further_action``
    row — closes the case as ``closed_no_action``.

    Any other resolution kinds are applied as real state changes in
    Stage 2D:

    - ``restore_content`` clears the CC hide on a post or comment.
    - ``restore_account`` clears the suspension on a user.
    - ``restore_collective`` clears the freeze on a collective.
    - ``account_cancellation`` sets ``users.cancelled_at`` (terminal).
    - ``creator_account_cancellation`` sets ``users.creator_cancelled_at``.
    - ``collective_closure_removal`` sets ``spaces.closed_at`` (terminal).

    Stage 2D requires ``case_summary`` to be present on the case before
    any non-no-action close.
    """
    resolution_actions: list[ResolutionAction] = Field(default_factory=list)
    resolution_summary: str | None = None


class CaseSummaryRequest(BaseModel):
    """Set or clear the operational Case Summary. Editable while the
    case is still open; refused (409) once the case has been closed."""
    case_summary: str | None = None
