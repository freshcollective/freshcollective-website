"""
Pydantic schemas for member-facing Community Care intake (Stage 2B).

These endpoints are the calm side of Community Care — they exist to
open a case and reassure the reporter. Nothing here issues protective
or resolution actions; those remain admin-only and land in later
stages.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.community_care import (
    CREATOR_REQUEST_SCOPES,
    REPORT_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Member report intake — used from the three-dot menu on posts/comments.
# ---------------------------------------------------------------------------


class MemberReportRequest(BaseModel):
    """A member's report of a post or comment.

    Exactly one of ``target_post_id`` / ``target_comment_id`` must be
    set. The backend resolves the reported member and the space from
    that reference — the client is never trusted with those mappings.
    """
    target_post_id: str | None = None
    target_comment_id: str | None = None
    category: str
    reporter_note: str | None = None

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        if v not in REPORT_CATEGORIES:
            raise ValueError(f"category must be one of {list(REPORT_CATEGORIES)}")
        return v


class MemberReportAcknowledgement(BaseModel):
    """What the reporter sees after a successful submission.

    Deliberately does not echo the case number, subject, or state.
    The reporter is told the report was received; the review happens
    in a different room and the reporter identity is never disclosed
    to the reported person.
    """
    received_at: datetime
    message: str = (
        "Thank you. A Fresh Collective administrator will review this. "
        "Reports are handled with care and your identity is never disclosed "
        "to the person reported."
    )


# ---------------------------------------------------------------------------
# Creator Support request — used from the creator dashboard.
# ---------------------------------------------------------------------------


class CreatorSupportRequest(BaseModel):
    """A creator asking Fresh Collective for support.

    Scope is one of the five agreed categories. Description is
    required — free-text so the creator can explain in their own words.
    ``subject_space_id`` is optional; when set, the endpoint verifies
    the requesting creator is actually a creator on that space before
    the case is opened.
    """
    scope: str
    subject_space_id: str | None = None
    description: str = Field(..., min_length=1)

    @field_validator("scope")
    @classmethod
    def _valid_scope(cls, v: str) -> str:
        if v not in CREATOR_REQUEST_SCOPES:
            raise ValueError(f"scope must be one of {list(CREATOR_REQUEST_SCOPES)}")
        return v


class CreatorSupportAcknowledgement(BaseModel):
    """What the creator sees after opening a support request.

    Unlike member reports, the creator does see the case number — they
    filed the request themselves so echoing it back is not a leak, and
    it gives them something to reference if they follow up.
    """
    case_number: str
    received_at: datetime
    message: str = (
        "Your request has been received. A Fresh Collective administrator "
        "will be in touch."
    )
