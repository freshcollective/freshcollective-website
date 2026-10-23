"""Creator Studio → Settings → Welcome Email.

One Collective's own wording for the email its first-time members
receive. The copy lives in the same ``communication_template_overrides``
table the admin portal writes, distinguished only by ``space_id`` —
there is no second template system, no second renderer and no second
storage shape.

What a creator may change, and what they may not
------------------------------------------------

Five slots of **voice**: subject, heading, message, button label,
signature. That is the whole surface.

The button's **destination** is not among them. It is generated from
the Collective's slug by ``collective_welcome_emit.collective_url`` and
handed to the shell as the CTA, so a creator can rename the button but
has no field through which to aim it anywhere else. Same structural
stance the editable-copy system takes platform-wide: a slot exists for
wording, never for a link.

Inheritance
-----------

    system default  →  platform admin override  →  this Collective

Resolution is per slot, so a creator who rewrites only the subject
keeps inheriting later improvements to the platform's heading. Restore
Default deletes this Collective's rows rather than copying the default
into them, which is what keeps that inheritance alive afterwards.

Isolation
---------

Every handler resolves the Collective through ``_get_managed_space``,
the same owner-or-leader check the rest of Creator Studio uses, and
every query is filtered by that resolved ``space.id``. A creator cannot
name another Collective's id and reach its copy, and the admin's own
loader reads ``space_id IS NULL`` only, so neither side can see or
overwrite the other's wording.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_verified_creator_user
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.editable import (
    get_declaration,
    preview_overrides,
    validate_slot_value,
)
from app.comms.templates.registry import get_template_for
from app.core.database import get_db
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)
from app.models.platform import Space
from app.models.user import User
from app.services.collective_welcome_emit import collective_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/creator", tags=["creator-welcome-email"])

TEMPLATE_KEY = "collective.membership.welcome.email_transactional"

_BASE = "/spaces/{slug}/welcome-email"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SlotView(BaseModel):
    slot_id: str
    label: str
    help_text: str
    multiline: bool
    max_length: int
    #: The value in force for this Collective right now.
    value: str
    #: What it would fall back to — platform override if one exists,
    #: otherwise the Fresh Collective default.
    inherited_default: str
    #: True when this Collective has its own stored row for this slot.
    customised: bool


class WelcomeEmailDetail(BaseModel):
    space_slug: str
    collective_name: str
    enabled: bool
    #: Generated, never editable. Shown so a creator can see where the
    #: button goes before they rename it.
    collective_url: str
    slots: list[SlotView]
    merge_fields: list[dict]
    customised: bool


class SaveRequest(BaseModel):
    enabled: bool | None = None
    overrides: dict[str, str] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    #: "effective" renders saved copy with drafts layered on; "default"
    #: ignores this Collective's rows entirely.
    mode: str = "effective"
    drafts: dict[str, str] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    subject: str
    html: str
    text: str
    errors: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decl():
    decl = get_declaration(TEMPLATE_KEY)
    if decl is None:  # pragma: no cover — declaration ships with the code
        raise HTTPException(
            status_code=500, detail="Welcome email template is not declared.",
        )
    return decl


def _space(slug: str, user: User, db: Session) -> Space:
    from app.creator.routes import _get_managed_space

    return _get_managed_space(slug, user, db)


def _rows(db: Session, space_id: str | None) -> dict[str, CommunicationTemplateOverride]:
    """Stored rows for ONE scope. ``None`` is the platform scope."""
    q = db.query(CommunicationTemplateOverride).filter(
        CommunicationTemplateOverride.template_key == TEMPLATE_KEY,
    )
    q = q.filter(
        CommunicationTemplateOverride.space_id.is_(None)
        if space_id is None
        else CommunicationTemplateOverride.space_id == space_id
    )
    return {r.slot_id: r for r in q.all()}


def _detail(db: Session, space: Space) -> WelcomeEmailDetail:
    decl = _decl()
    platform = _rows(db, None)
    mine = _rows(db, space.id)
    slots = []
    for s in decl.slots:
        inherited = platform[s.slot_id].value if s.slot_id in platform else s.default
        row = mine.get(s.slot_id)
        slots.append(SlotView(
            slot_id=s.slot_id,
            label=s.label,
            help_text=s.help_text,
            multiline=s.multiline,
            max_length=s.max_length,
            value=row.value if row is not None else inherited,
            inherited_default=inherited,
            customised=row is not None,
        ))
    return WelcomeEmailDetail(
        space_slug=space.slug,
        collective_name=space.name or "",
        enabled=bool(getattr(space, "welcome_email_enabled", True)),
        collective_url=collective_url(space),
        slots=slots,
        merge_fields=[
            {"name": f.name, "description": f.description, "sample": f.sample}
            for f in decl.merge_fields
        ],
        customised=bool(mine),
    )


def _sample_context(space: Space, db: Session) -> dict:
    """Preview context built from the REAL Collective.

    Not the declaration's generic sample: a creator previewing their
    welcome must see their own Collective's name and their own
    destination, which is the whole point of previewing it here rather
    than in the admin portal.
    """
    from app.services.collective_welcome_emit import _creator_name

    return {
        "space_id":          space.id,
        "collective_name":   space.name or "",
        "member_first_name": "Tom",
        "creator_name":      _creator_name(db, space),
        "collective_url":    collective_url(space),
        "join_source":       "joined",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(_BASE, response_model=WelcomeEmailDetail)
def get_welcome_email(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> WelcomeEmailDetail:
    return _detail(db, _space(slug, current_user, db))


@router.put(_BASE, response_model=WelcomeEmailDetail)
def save_welcome_email(
    slug: str,
    body: SaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> WelcomeEmailDetail:
    """Save this Collective's wording and/or its on-off switch.

    A value equal to what this Collective would otherwise inherit
    deletes the row instead of storing it. "Customised" should mean
    "differs from what I would have got", so a creator who edits and
    types the original back genuinely returns to inheriting — and keeps
    receiving later improvements to the platform default.
    """
    space = _space(slug, current_user, db)
    decl = _decl()

    errors: dict[str, list[str]] = {}
    for slot_id, value in body.overrides.items():
        problems = validate_slot_value(decl, slot_id, value)
        if problems:
            errors[slot_id] = problems
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    platform = _rows(db, None)
    mine = _rows(db, space.id)
    now = datetime.utcnow()

    for slot_id, value in body.overrides.items():
        slot = decl.slot(slot_id)
        inherited = (
            platform[slot_id].value if slot_id in platform else slot.default
        )
        existing = mine.get(slot_id)
        if value == inherited:
            if existing is not None:
                db.delete(existing)
            continue
        if existing is not None:
            existing.value = value
            existing.default_fingerprint = slot.fingerprint()
            existing.updated_by_user_id = current_user.id
            existing.updated_at = now
        else:
            db.add(CommunicationTemplateOverride(
                id=f"cto_{uuid.uuid4().hex[:16]}",
                template_key=TEMPLATE_KEY,
                slot_id=slot_id,
                value=value,
                default_fingerprint=slot.fingerprint(),
                updated_by_user_id=current_user.id,
                space_id=space.id,
                created_at=now,
                updated_at=now,
            ))

    if body.enabled is not None:
        space.welcome_email_enabled = bool(body.enabled)
        logger.info(
            "welcome email: space=%s enabled=%s by user=%s",
            space.id, body.enabled, current_user.id,
        )

    db.commit()
    return _detail(db, space)


@router.delete(_BASE, response_model=WelcomeEmailDetail)
def restore_welcome_email_default(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> WelcomeEmailDetail:
    """Drop this Collective's wording and inherit again.

    Deletes the rows rather than writing the default into them. Copying
    the default in would freeze it: the Collective would keep today's
    wording forever and silently miss every later improvement, while
    still reporting itself as customised.
    """
    space = _space(slug, current_user, db)
    for row in _rows(db, space.id).values():
        db.delete(row)
    db.commit()
    logger.info(
        "welcome email: space=%s restored to default by user=%s",
        space.id, current_user.id,
    )
    return _detail(db, space)


@router.post(_BASE + "/preview", response_model=PreviewResponse)
def preview_welcome_email(
    slug: str,
    body: PreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_creator_user),
) -> PreviewResponse:
    """Render exactly what a member would receive. Writes nothing.

    Goes through the registered template and the canonical shell, with
    this Collective's real name and real destination — the same path a
    real send takes. A preview-only renderer is how previews drift from
    production, so there isn't one.
    """
    space = _space(slug, current_user, db)
    decl = _decl()

    effective: dict[str, str] = {}
    errors: dict[str, list[str]] = {}
    if body.mode != "default":
        platform = _rows(db, None)
        effective = {k: r.value for k, r in platform.items()}
        effective.update({k: r.value for k, r in _rows(db, space.id).items()})
        for slot_id, value in body.drafts.items():
            problems = validate_slot_value(decl, slot_id, value)
            if problems:
                # Reported and dropped, never rendered — the preview must
                # show what would actually be sent.
                errors[slot_id] = problems
            else:
                effective[slot_id] = value

    template = get_template_for(decl.event_type, CHANNEL_EMAIL_TRANSACTIONAL)
    if template is None:  # pragma: no cover
        raise HTTPException(
            status_code=500, detail="No renderer registered for this email.",
        )
    recipient = ResolvedRecipient(
        user_id=current_user.id,
        role_in_event="new_member",
        human_reason="Preview",
        template_context=_sample_context(space, db),
    )
    # ``preview_overrides`` makes the resolver read these drafts instead
    # of the database, so the render exercises the real template without
    # a preview-specific code path.
    with preview_overrides({TEMPLATE_KEY: effective}):
        payload = template.render(db, None, recipient)
    return PreviewResponse(
        subject=payload.subject,
        html=payload.body_html,
        text=payload.body_text,
        errors=errors,
    )
