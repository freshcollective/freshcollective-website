"""World Management → Communications → Email Templates (admin API).

Seven endpoints, all behind ``get_admin_user``. No UI yet.

Two things are load-bearing here and worth stating up front.

**Preview and send use the canonical renderer.** There is no second
rendering path anywhere in this module — drafts reach the real template
through a ContextVar, so a preview cannot drift from what a member
would receive. A preview built from its own renderer is worse than no
preview.

**Test-send deliberately bypasses the communications ledger.** It
renders canonically and hands the payload straight to the provider. It
creates no ``CommunicationEvent``, no intent and no delivery row,
because the ledger is a record of *member* communications and a test is
not one. Writing to it would pollute dedupe keys, preference
accounting and lifecycle reporting for the sake of an admin pressing a
button. See ``test_send_email_template``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.preferences import locked_categories_for_channel
from app.brand.email import email_logo_url, preview_brand_logo
from app.comms.registry import (
    category_for_topic,
    get_event_definition,
    is_transactional_event,
)
from app.comms.rollout import is_event_live
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.editable import (
    SYSTEM,
    TemplateDeclaration,
    admin_declarations,
    get_declaration,
    preview_overrides,
    substitute,
    validate_slot_value,
)
from app.comms.templates.registry import get_template_for
from app.core.database import get_db
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/communications/email-templates",
    tags=["admin", "communications"],
)

TEST_SUBJECT_PREFIX = "[TEST] "

# The only difference between a test send and the preview the admin was
# just looking at. Named so a test can reconstruct the transformation
# exactly and assert byte equality with the preview, rather than
# checking for a few substrings and hoping.
TEST_BANNER_TEXT = (
    "This is a test email sent from Fresh Collective World Management. "
    "It was rendered with sample data and is not a real notification."
)


# ---------------------------------------------------------------------------
# Sample context
# ---------------------------------------------------------------------------
#
# Preview and test-send both need a plausible ``template_context``. It
# is assembled from the declared merge fields' samples plus the
# non-editable values a template still needs in order to render. Every
# value is obviously fake and none is read from a real row, so neither
# endpoint can touch business state.

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
    "ended_at":          "2026-10-25T00:00:00",
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


class TemplateListItem(BaseModel):
    template_key: str
    display_name: str
    category: str
    audience: str
    classification: str
    editable: bool
    subject_editable: bool
    is_transactional: bool
    customised: bool
    overridden_slot_count: int
    has_stale_default: bool


class MergeFieldOut(BaseModel):
    name: str
    sample: str
    description: str


class PreviewVariantOptionOut(BaseModel):
    value: str
    label: str
    is_default: bool


class PreviewVariantOut(BaseModel):
    """A preview-only control, described in product terms.

    The internal context key each option sets is deliberately absent
    from the response. The UI has no use for it, and leaving it out
    means no client can come to depend on a flag name.
    """

    variant_id: str
    label: str
    help_text: str
    options: list[PreviewVariantOptionOut]


class SlotOut(BaseModel):
    slot_id: str
    label: str
    help_text: str
    multiline: bool
    max_length: int
    required_fields: list[str]
    default: str
    override: str | None
    effective: str
    customised: bool
    default_changed: bool


class TemplateDetail(BaseModel):
    template_key: str
    event_type: str
    display_name: str
    category: str
    audience: str
    classification: str
    editable: bool
    subject_editable: bool
    is_transactional: bool
    is_live: bool
    customised: bool
    slots: list[SlotOut]
    merge_fields: list[MergeFieldOut]
    locked_notes: list[str]
    preview_variants: list[PreviewVariantOut]


class SaveRequest(BaseModel):
    overrides: dict[str, str]


class PreviewRequest(BaseModel):
    """``mode='effective'`` layers ``drafts`` over saved overrides — what
    the member would get if the drafts were saved. ``mode='default'``
    ignores everything stored, which is how the editor shows what
    "reset to default" would give."""

    mode: str = Field(default="effective", pattern="^(effective|default)$")
    drafts: dict[str, str] = Field(default_factory=dict)
    # ``{variant_id: option_value}``, both resolved against the
    # declaration. A closed enumeration rather than free context keys —
    # the caller selects a declared state and cannot name one itself.
    variant: dict[str, str] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    template_key: str
    mode: str
    subject: str
    preheader: str | None
    html: str
    text: str
    effective_slots: dict[str, str]
    errors: dict[str, list[str]]


class TestSendRequest(PreviewRequest):
    pass


class TestSendResponse(BaseModel):
    sent_to: str
    subject: str
    accepted: bool
    detail: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require(template_key: str) -> TemplateDeclaration:
    """The declaration behind a template key, or a 404.

    An internal diagnostic answers the same 404 as a key that does not
    exist. Excluding it from the list alone would leave it reachable by
    anyone who typed the key, and "absent from World Management" should
    mean absent from every endpoint World Management is built on.
    """
    decl = get_declaration(template_key)
    if decl is None or decl.internal:
        raise HTTPException(status_code=404, detail="Unknown email template.")
    return decl


def _require_editable(decl: TemplateDeclaration) -> None:
    if not decl.is_editable:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{decl.display_name} is system-controlled. Its wording states "
                "facts about money, access or security and is not editable."
            ),
        )


def _locked_email_categories(db: Session) -> frozenset[str]:
    return locked_categories_for_channel(db, CHANNEL_EMAIL_TRANSACTIONAL)


def _is_transactional(
    decl: TemplateDeclaration, locked_categories: frozenset[str],
) -> bool:
    """Whether a member can switch this email off — which is the only
    thing the admin surface claims when it says "Transactional".

    Two mechanisms can take the choice away and the admin needs the
    answer, not the mechanism. An audited event-level lock
    (``TRANSACTIONAL_EVENT_TYPES``) is one; a locked (category,
    channel) default seeded in the database is the other, and it is
    what currently makes the welcome email undroppable even though a
    welcome is not a receipt. Reporting only the first would leave the
    list saying "a member can turn this off" about emails no member
    can turn off.
    """
    if is_transactional_event(decl.event_type):
        return True
    definition = get_event_definition(decl.event_type)
    if definition is None:  # pragma: no cover — declarations mirror the registry
        return False
    return category_for_topic(definition.topic) in locked_categories


def _stored(db: Session, template_key: str) -> dict[str, CommunicationTemplateOverride]:
    rows = (
        db.query(CommunicationTemplateOverride)
        .filter(CommunicationTemplateOverride.template_key == template_key)
        .all()
    )
    return {r.slot_id: r for r in rows}


def _detail(
    db: Session,
    decl: TemplateDeclaration,
    locked_categories: frozenset[str] | None = None,
) -> TemplateDetail:
    if locked_categories is None:
        locked_categories = _locked_email_categories(db)
    rows = _stored(db, decl.template_key)
    slots: list[SlotOut] = []
    for s in decl.slots:
        row = rows.get(s.slot_id)
        slots.append(SlotOut(
            slot_id=s.slot_id,
            label=s.label,
            help_text=s.help_text,
            multiline=s.multiline,
            max_length=s.max_length,
            required_fields=list(s.required_fields),
            default=s.default,
            override=row.value if row else None,
            effective=row.value if row else s.default,
            customised=row is not None,
            # The admin's copy is never overwritten — this only tells the
            # UI that Fresh Collective's own wording has moved on since
            # they customised it, so it can offer the comparison.
            default_changed=bool(
                row and row.default_fingerprint != s.fingerprint()
            ),
        ))
    return TemplateDetail(
        template_key=decl.template_key,
        event_type=decl.event_type,
        display_name=decl.display_name,
        category=decl.category,
        audience=decl.audience,
        classification=decl.classification,
        editable=decl.is_editable,
        subject_editable=decl.subject_editable,
        is_transactional=_is_transactional(decl, locked_categories),
        is_live=is_event_live(decl.event_type),
        customised=bool(rows),
        slots=slots,
        merge_fields=[
            MergeFieldOut(name=f.name, sample=f.sample, description=f.description)
            for f in decl.merge_fields
        ],
        locked_notes=list(decl.locked_notes),
        preview_variants=[
            PreviewVariantOut(
                variant_id=v.variant_id,
                label=v.label,
                help_text=v.help_text,
                options=[
                    PreviewVariantOptionOut(
                        value=o.value, label=o.label,
                        is_default=(o is v.default_option),
                    )
                    for o in v.options
                ],
            )
            for v in decl.preview_variants
        ],
    )


def _render(
    decl: TemplateDeclaration,
    overrides: dict[str, str],
    variant: dict[str, str],
    brand_logo_url: str | None = None,
) -> tuple[str, str, str]:
    """Render through the canonical template and shell."""
    template = get_template_for(decl.event_type, CHANNEL_EMAIL_TRANSACTIONAL)
    if template is None:  # pragma: no cover — declarations mirror the registry
        raise HTTPException(
            status_code=500,
            detail=f"No renderer registered for {decl.event_type}.",
        )
    ctx = sample_context(decl)
    # The overlay comes from the declaration, never from the request
    # body. The request only names which declared option it wants.
    try:
        ctx.update(decl.variant_context(variant))
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc.args[0])) from exc
    recipient = ResolvedRecipient(
        user_id="preview", role_in_event="preview",
        human_reason="Preview — not a real send.",
        template_context=ctx,
    )
    # The brand header resolves off a session the preview does not
    # have, so the caller hands in the URL it resolved. Same template,
    # same shell, same logo a real send would carry.
    with preview_overrides({decl.template_key: overrides}), \
            preview_brand_logo(brand_logo_url):
        payload = template.render(None, None, recipient)
    return payload.subject, payload.body_html or "", payload.body_text or ""


def _resolve_for_preview(
    db: Session, decl: TemplateDeclaration, body: PreviewRequest,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Effective overrides for a preview, plus per-slot validation errors.

    ``default`` mode returns nothing, so the canonical defaults are used.
    ``effective`` mode is saved overrides with any valid drafts layered
    on top. An invalid draft is reported and dropped rather than
    rendered, so the preview shows what would actually be sent.
    """
    if body.mode == "default":
        return {}, {}

    effective = {k: r.value for k, r in _stored(db, decl.template_key).items()}
    errors: dict[str, list[str]] = {}
    for slot_id, value in body.drafts.items():
        problems = validate_slot_value(decl, slot_id, value)
        if problems:
            errors[slot_id] = problems
        else:
            effective[slot_id] = value
    return effective, errors


def _preheader_of(decl: TemplateDeclaration, overrides: dict[str, str]) -> str | None:
    slot = decl.slot("preheader")
    if slot is None:
        return None
    raw = overrides.get("preheader", slot.default)
    return substitute(raw, decl, sample_context(decl))


# ---------------------------------------------------------------------------
# 1. List
# ---------------------------------------------------------------------------


@router.get("", response_model=list[TemplateListItem])
def list_email_templates(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> list[TemplateListItem]:
    """Every email template that currently sends to a member.

    Two exclusions, both computed rather than hand-maintained.
    Templates whose topic is not live are left out — an admin polishing
    copy nobody receives is wasted effort, and they appear here
    automatically if their topic is ever switched on. Internal
    diagnostics are left out because they are not member emails and
    nobody writes copy for them.
    """
    out: list[TemplateListItem] = []
    locked_categories = _locked_email_categories(db)
    for decl in admin_declarations():
        if not is_event_live(decl.event_type):
            continue
        rows = _stored(db, decl.template_key)
        stale = any(
            decl.slot(sid) is not None
            and row.default_fingerprint != decl.slot(sid).fingerprint()
            for sid, row in rows.items()
        )
        out.append(TemplateListItem(
            template_key=decl.template_key,
            display_name=decl.display_name,
            category=decl.category,
            audience=decl.audience,
            classification=decl.classification,
            editable=decl.is_editable,
            subject_editable=decl.subject_editable,
            is_transactional=_is_transactional(decl, locked_categories),
            customised=bool(rows),
            overridden_slot_count=len(rows),
            has_stale_default=stale,
        ))
    return out


# ---------------------------------------------------------------------------
# 2. Detail
# ---------------------------------------------------------------------------


@router.get("/{template_key}", response_model=TemplateDetail)
def get_email_template(
    template_key: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> TemplateDetail:
    return _detail(db, _require(template_key))


# ---------------------------------------------------------------------------
# 3. Save
# ---------------------------------------------------------------------------


@router.put("/{template_key}", response_model=TemplateDetail)
def save_email_template_overrides(
    template_key: str,
    body: SaveRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> TemplateDetail:
    """Upsert overrides for the slots supplied. All-or-nothing.

    A value identical to the Fresh Collective default deletes the
    override rather than storing one — customised state should mean
    "this differs", so an admin who edits and then types the original
    back genuinely returns to default and keeps receiving future
    improvements to it.
    """
    decl = _require(template_key)
    _require_editable(decl)

    errors: dict[str, list[str]] = {}
    for slot_id, value in body.overrides.items():
        problems = validate_slot_value(decl, slot_id, value)
        if problems:
            errors[slot_id] = problems
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    rows = _stored(db, template_key)
    now = datetime.utcnow()
    for slot_id, value in body.overrides.items():
        slot = decl.slot(slot_id)
        existing = rows.get(slot_id)
        if value == slot.default:
            if existing is not None:
                db.delete(existing)
                logger.info(
                    "email template: %s.%s reset to default by admin %s "
                    "(submitted value equalled the default)",
                    template_key, slot_id, admin.id,
                )
            continue
        if existing is not None:
            existing.value = value
            existing.default_fingerprint = slot.fingerprint()
            existing.updated_by_user_id = admin.id
            existing.updated_at = now
        else:
            db.add(CommunicationTemplateOverride(
                id=f"cto_{uuid.uuid4().hex[:16]}",
                template_key=template_key,
                slot_id=slot_id,
                value=value,
                default_fingerprint=slot.fingerprint(),
                updated_by_user_id=admin.id,
                created_at=now,
                updated_at=now,
            ))
        logger.info(
            "email template: %s.%s customised by admin %s",
            template_key, slot_id, admin.id,
        )
    db.commit()
    return _detail(db, decl)


# ---------------------------------------------------------------------------
# 4 & 5. Reset
# ---------------------------------------------------------------------------


@router.delete("/{template_key}/slots/{slot_id}", response_model=TemplateDetail)
def reset_email_template_slot(
    template_key: str,
    slot_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> TemplateDetail:
    """Delete one override. The code default takes over immediately."""
    decl = _require(template_key)
    _require_editable(decl)
    if decl.slot(slot_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"{decl.display_name} has no editable field {slot_id!r}.",
        )
    row = _stored(db, template_key).get(slot_id)
    if row is not None:
        db.delete(row)
        db.commit()
        logger.info(
            "email template: %s.%s reset to default by admin %s",
            template_key, slot_id, admin.id,
        )
    return _detail(db, decl)


@router.delete("/{template_key}", response_model=TemplateDetail)
def reset_email_template(
    template_key: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> TemplateDetail:
    """Delete every override for this template."""
    decl = _require(template_key)
    _require_editable(decl)
    rows = _stored(db, template_key)
    for row in rows.values():
        db.delete(row)
    if rows:
        db.commit()
        logger.info(
            "email template: %s fully reset to defaults by admin %s (%d slots)",
            template_key, admin.id, len(rows),
        )
    return _detail(db, decl)


# ---------------------------------------------------------------------------
# 6. Preview
# ---------------------------------------------------------------------------


@router.post("/{template_key}/preview", response_model=PreviewResponse)
def preview_email_template(
    template_key: str,
    body: PreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
) -> PreviewResponse:
    """Render one email. Read-only — writes nothing, sends nothing."""
    decl = _require(template_key)
    effective, errors = _resolve_for_preview(db, decl, body)
    subject, html, text = _render(
        decl, effective, body.variant, email_logo_url(db),
    )
    return PreviewResponse(
        template_key=decl.template_key,
        mode=body.mode,
        subject=subject,
        preheader=_preheader_of(decl, effective),
        html=html,
        text=text,
        effective_slots={
            s.slot_id: effective.get(s.slot_id, s.default) for s in decl.slots
        },
        errors=errors,
    )


# ---------------------------------------------------------------------------
# 7. Test send
# ---------------------------------------------------------------------------


@router.post("/{template_key}/test-send", response_model=TestSendResponse)
def test_send_email_template(
    template_key: str,
    body: TestSendRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> TestSendResponse:
    """Send this email to the signed-in admin, marked as a test.

    Two deliberate narrowings.

    **The recipient is not a parameter.** It is read from the session,
    so the endpoint cannot be aimed at a member however it is called.
    The address must also be verified — sending test traffic to an
    unverified address risks a bounce against Fresh Collective's sender
    reputation.

    **It does not touch the communications ledger.** No
    ``CommunicationEvent``, no intent, no delivery row. The ledger
    records what members were sent; a test is not that, and writing to
    it would consume dedupe keys and distort preference and lifecycle
    reporting. The payload goes straight to the provider — the same
    provider, the same shell, the same rendered bytes a member would
    receive, minus the bookkeeping.
    """
    decl = _require(template_key)

    recipient_address = (admin.email or "").strip()
    if not recipient_address:
        raise HTTPException(
            status_code=400, detail="Your admin account has no email address.",
        )
    if getattr(admin, "email_verified_at", None) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Verify your own email address before sending test emails."
            ),
        )

    # Resolved through exactly the same path the preview endpoint uses,
    # from exactly the same request shape — ``mode``, ``drafts`` and
    # ``variant`` all included. The admin presses Send test while
    # looking at a rendered email, so the test must be that email; one
    # that quietly sent something else would be worse than none.
    effective, errors = _resolve_for_preview(db, decl, body)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    subject, html, text = _render(
        decl, effective, body.variant, email_logo_url(db),
    )

    # Marked as a test at render time, never by editing a slot — the
    # stored copy and the code defaults are untouched by this. This is
    # the only difference from the preview.
    subject = f"{TEST_SUBJECT_PREFIX}{subject}"
    text = f"[TEST] {TEST_BANNER_TEXT}\n\n{text}"
    html = _inject_test_banner(html, TEST_BANNER_TEXT)

    from app.comms.providers import get as get_provider
    from app.comms.providers.base import RenderedPayload

    result = get_provider("resend").send(RenderedPayload(
        to=recipient_address,
        subject=subject,
        body_html=html,
        body_text=text,
        metadata={"notification_type": "admin_template_test"},
    ))
    logger.info(
        "email template test-send: %s → admin %s accepted=%s",
        template_key, admin.id, result.accepted,
    )
    return TestSendResponse(
        sent_to=recipient_address,
        subject=subject,
        accepted=bool(result.accepted),
        detail=result.error_detail,
    )


def _inject_test_banner(html: str, banner: str) -> str:
    """Put a visible TEST notice at the top of the rendered document.

    Operates on the canonical output rather than the template, so the
    stored copy and the code defaults are untouched and the rest of the
    email is byte-for-byte what a member would receive.
    """
    import html as _html
    marker = "<table role=\"presentation\" width=\"100%\""
    notice = (
        '<div style="background:#B45309;color:#FFFFFF;padding:10px 16px;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'font-size:13px;line-height:1.5;text-align:center;">'
        f"<strong>TEST EMAIL</strong> — {_html.escape(banner)}</div>"
    )
    if marker in html:
        return html.replace(marker, notice + marker, 1)
    return notice + html  # pragma: no cover — shell always has the table
