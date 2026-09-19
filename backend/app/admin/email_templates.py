"""Admin preview for editable email copy (Phase A).

One read-only endpoint. It renders through the **real** template and
the **real** shell with draft overrides held in memory, so a preview
cannot disagree with what a member would actually receive — a preview
built from a second renderer is worse than no preview at all.

Nothing here writes. No override row is created, no communication event
is emitted, no business state is read beyond the template declaration
itself: the context is sample data assembled from the declared merge
fields.

Phase B adds list / get / save / reset / test-send alongside this.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.rollout import is_event_live
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.editable import (
    TemplateDeclaration,
    preview_overrides,
    get_declaration,
    validate_slot_value,
)
from app.comms.templates.registry import get_template_for
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/communications/email-templates",
    tags=["admin", "communications"],
)


# ---------------------------------------------------------------------------
# Sample context
# ---------------------------------------------------------------------------
#
# Preview needs a plausible ``template_context``. Rather than hand-write
# one per template, build it from the declared merge fields' samples and
# top it up with the non-editable values a template still needs to
# render (URLs, amounts, flags). Those extras are clearly fake and never
# read from real rows.

_NON_MERGE_SAMPLES: dict[str, Any] = {
    "verify_url":        "https://example.test/verify-email?token=sample",
    "reset_url":         "https://example.test/reset-password?token=sample",
    "next_url":          "https://example.test/dashboard",
    "accept_url":        "https://example.test/invites/sample",
    "gathering_url":     "https://example.test/spaces/sample/events/sample",
    "cta_url":           "https://example.test/spaces/sample/series/sample",
    "view_url":          "https://example.test/posts/sample",
    "member_url":        "https://example.test/purchases/sample",
    "repair_url":        "https://example.test/purchases/sample",
    "retry_url":         "https://example.test/offers/sample",
    "billing_url":       "https://example.test/creator-studio/billing",
    "first_name":        "Ada",
    "is_fresh_creator":  False,
    "was_reactivated":   False,
    "added_by_creator":  False,
    "was_ticketed":      True,
    "is_full_refund":    False,
    "was_suspended":     False,
    "payment_mode":      "plan",
    "amount_cents":      3780,
    "total_paid_cents":  37800,
    "currency":          "AUD",
    "installments_paid": 1,
    "installments_expected": 10,
    "session_count":     8,
    "first_starts_at":   "Friday 19 September at 9:00am",
    "last_starts_at":    "Friday 7 November at 9:00am",
    "grace_expires_at":  "2026-10-01T00:00:00",
    "current_period_end": "2026-10-25T00:00:00",
    "schedule_preview":  [
        {"title": "Week 1", "when": "Fri 19 Sep, 9:00am"},
        {"title": "Week 2", "when": "Fri 26 Sep, 9:00am"},
    ],
}


def sample_context(decl: TemplateDeclaration) -> dict[str, Any]:
    ctx = dict(_NON_MERGE_SAMPLES)
    for mf in decl.merge_fields:
        ctx[mf.source_key] = mf.sample
    return ctx


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    """Draft overrides to preview. Empty previews the shipped defaults,
    which is how the editor shows "what reset would give you"."""

    overrides: dict[str, str] = Field(default_factory=dict)
    # ``added_by_creator`` / ``is_fresh_creator`` style switches, so the
    # editor can preview each copy variant.
    variant: dict[str, bool] = Field(default_factory=dict)


class MergeFieldOut(BaseModel):
    name: str
    sample: str
    description: str


class SlotOut(BaseModel):
    slot_id: str
    label: str
    help_text: str
    default: str
    current: str
    multiline: bool
    max_length: int
    required_fields: list[str]


class PreviewResponse(BaseModel):
    template_key: str
    display_name: str
    category: str
    audience: str
    classification: str
    is_live: bool
    subject: str
    html: str
    text: str
    slots: list[SlotOut]
    merge_fields: list[MergeFieldOut]
    locked_notes: list[str]
    errors: dict[str, list[str]]


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _render_with(
    db: Session,
    decl: TemplateDeclaration,
    overrides: dict[str, str],
    variant: dict[str, bool],
) -> tuple[str, str, str]:
    """Render through the canonical template + shell.

    ``db`` is passed as ``None`` into the template so the resolver does
    not consult stored overrides — a preview shows exactly the drafts
    the caller supplied, never a mix of draft and saved.
    """
    template = get_template_for(decl.event_type, CHANNEL_EMAIL_TRANSACTIONAL)
    if template is None:  # pragma: no cover — declarations mirror the registry
        raise HTTPException(
            status_code=500,
            detail=f"No renderer registered for {decl.event_type}.",
        )

    ctx = sample_context(decl)
    ctx.update({k: bool(v) for k, v in variant.items()})

    recipient = ResolvedRecipient(
        user_id="preview",
        role_in_event="preview",
        human_reason="Preview — not a real send.",
        template_context=ctx,
    )

    with preview_overrides({decl.template_key: overrides}):
        payload = template.render(None, None, recipient)

    return payload.subject, payload.body_html or "", payload.body_text or ""


@router.post("/{template_key}/preview", response_model=PreviewResponse)
def preview_email_template(
    template_key: str,
    body: PreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PreviewResponse:
    """Render one email with draft overrides. Read-only."""
    decl = get_declaration(template_key)
    if decl is None:
        raise HTTPException(status_code=404, detail="Unknown email template.")

    # Validate every draft. Invalid slots are reported and dropped, so
    # the preview shows what would actually be sent — the default —
    # rather than silently rendering something unsavable.
    errors: dict[str, list[str]] = {}
    usable: dict[str, str] = {}
    for slot_id, value in body.overrides.items():
        problems = validate_slot_value(decl, slot_id, value)
        if problems:
            errors[slot_id] = problems
        else:
            usable[slot_id] = value

    subject, html, text = _render_with(db, decl, usable, body.variant)

    stored: dict[str, str] = {}   # Phase B populates this from the DB.
    return PreviewResponse(
        template_key=decl.template_key,
        display_name=decl.display_name,
        category=decl.category,
        audience=decl.audience,
        classification=decl.classification,
        is_live=is_event_live(decl.event_type),
        subject=subject,
        html=html,
        text=text,
        slots=[
            SlotOut(
                slot_id=s.slot_id,
                label=s.label,
                help_text=s.help_text,
                default=s.default,
                current=body.overrides.get(
                    s.slot_id, stored.get(s.slot_id, s.default),
                ),
                multiline=s.multiline,
                max_length=s.max_length,
                required_fields=list(s.required_fields),
            )
            for s in decl.slots
        ],
        merge_fields=[
            MergeFieldOut(name=f.name, sample=f.sample, description=f.description)
            for f in decl.merge_fields
        ],
        locked_notes=list(decl.locked_notes),
        errors=errors,
    )
