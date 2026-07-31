"""
/api/creator/build-your-collective/* — the guided creator ritual (Atlas v1.2).

Replaces `build_your_place.py`. A creator does not design an island — they
choose which curated Location their collective lives inside, then
personalise the collective's atmosphere, colour palette, identity
statement and welcome message.

Endpoints:

  GET    /options              — Locations + atmospheres + colour palettes
  GET    /draft                — the creator's in-progress draft (create mode)
  PUT    /draft                — upsert draft
  DELETE /draft                — abandon
  POST   /open                 — open a new collective from a completed draft
  PATCH  /{slug}               — update an existing collective's identity
                                  (used by change-location + edit-identity modes)

Natural Elements and Landscape are retired. The DB columns
`spaces.landscape_key` and `spaces.element_keys` remain nullable and are
no longer read or written by this router.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.core.database import get_db
from app.creator.plan_guards import (
    allowed_location_query,
    guard_active_collective_limit,
    guard_location_allowed,
    guard_paid_offers_enabled,
    is_platform_owner as _is_platform_owner,
)
from app.creator.schemas import slugify
from app.models.platform import (
    AtmosphereOption,
    ColourStory,
    Location,
    Space,
    SpaceDraft,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.creator_eligibility import AUTO_ROLE_SOURCE


router = APIRouter(prefix="/api/creator/build-your-collective", tags=["build-your-collective"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class LocationOptionOut(BaseModel):
    id: str
    key: str
    name: str
    description: str | None
    hero_artwork_url: str | None
    thumbnail_artwork_url: str | None
    location_type: str  # 'ATLAS' | 'COMMUNITY' | 'CORNERSTONE' — used by the picker to group

    model_config = {"from_attributes": True}


class AtmosphereOptionOut(BaseModel):
    key: str
    name: str

    model_config = {"from_attributes": True}


class ColourPaletteOut(BaseModel):
    """Formerly ColourStoryOut — renamed for Atlas v1.2."""
    key: str
    name: str
    palette: dict

    model_config = {"from_attributes": True}


class OptionsResponse(BaseModel):
    locations: list[LocationOptionOut]
    atmospheres: list[AtmosphereOptionOut]
    colour_palettes: list[ColourPaletteOut]


class DraftData(BaseModel):
    """The evolving JSON stored on space_drafts.data. All fields optional
    so drafts can be saved mid-step. Validation is only strict at open()."""
    step: int | None = None
    location_id: str | None = None
    atmosphere_keys: list[str] = Field(default_factory=list)
    colour_palette_key: str | None = None
    identity_statement: str | None = None
    welcome_message: str | None = None
    name: str | None = None
    description: str | None = None
    visibility: str | None = None  # 'public' | 'link' | 'private'
    pricing_type: str | None = None  # 'free' | 'contribution'
    pricing_amount_cents: int | None = None
    pricing_note: str | None = None


class DraftOut(BaseModel):
    data: DraftData


class OpenCollectiveResponse(BaseModel):
    slug: str
    name: str
    # Slug of the auto-grant collective (World Builders) the creator holds
    # active membership in, if any. The client uses this to route the
    # creator into World Builders after their new collective is opened.
    # None when no such membership exists.
    world_builders_slug: str | None = None


# ---------------------------------------------------------------------------
# GET /options — configurable vocabulary
# ---------------------------------------------------------------------------

@router.get("/options", response_model=OptionsResponse)
def get_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> OptionsResponse:
    # Location visibility rules:
    #   Platform Owner  → Cornerstones + Atlas + Community (grouped in that order)
    #   Community plan  → Community Locations only
    #   Creator/Pro     → Atlas Locations only
    # The frontend picker groups by location_type when multiple types are
    # returned.
    plan_locations = (
        allowed_location_query(current_user, db)
        .order_by(Location.position, Location.name)
        .all()
    )

    if _is_platform_owner(current_user):
        cornerstones = (
            db.query(Location)
            .filter(Location.status == "active", Location.location_type == "CORNERSTONE")
            .order_by(Location.position, Location.name)
            .all()
        )
        locations = list(cornerstones) + list(plan_locations)
    else:
        locations = plan_locations
    atmospheres = (
        db.query(AtmosphereOption)
        .filter(AtmosphereOption.is_active.is_(True))
        .order_by(AtmosphereOption.position)
        .all()
    )
    # Colour palettes read from the colour_stories table (name retained in
    # the DB for now; the wire-format name is Colour Palette per Atlas v1.2).
    palettes = (
        db.query(ColourStory)
        .filter(ColourStory.is_active.is_(True))
        .order_by(ColourStory.position)
        .all()
    )
    return OptionsResponse(
        locations=[LocationOptionOut.model_validate(l) for l in locations],
        atmospheres=[AtmosphereOptionOut.model_validate(a) for a in atmospheres],
        colour_palettes=[ColourPaletteOut.model_validate(p) for p in palettes],
    )


# ---------------------------------------------------------------------------
# GET/PUT/DELETE /draft — in-progress draft
# ---------------------------------------------------------------------------

def _get_draft(user_id: str, db: Session) -> SpaceDraft | None:
    return db.query(SpaceDraft).filter(SpaceDraft.user_id == user_id).first()


@router.get("/draft", response_model=DraftOut | None)
def get_draft(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    draft = _get_draft(current_user.id, db)
    if not draft:
        return None
    return DraftOut(data=DraftData(**(draft.data or {})))


class DraftUpsertRequest(BaseModel):
    data: DraftData


@router.put("/draft", response_model=DraftOut)
def upsert_draft(
    body: DraftUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> DraftOut:
    draft = _get_draft(current_user.id, db)
    payload = body.data.model_dump()
    if draft:
        draft.data = payload
    else:
        draft = SpaceDraft(
            id=str(uuid4()),
            user_id=current_user.id,
            data=payload,
        )
        db.add(draft)
    db.commit()
    db.refresh(draft)
    return DraftOut(data=DraftData(**draft.data))


@router.delete("/draft", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    draft = _get_draft(current_user.id, db)
    if draft:
        db.delete(draft)
        db.commit()


# ---------------------------------------------------------------------------
# POST /open — materialise the draft into a new collective
# ---------------------------------------------------------------------------


class OpenCollectiveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=300)

    location_id: str = Field(..., min_length=1)
    atmosphere_keys: list[str] = Field(...)
    colour_palette_key: str = Field(..., min_length=1)

    identity_statement: str = Field(..., min_length=1, max_length=500)
    welcome_message: str = Field(..., min_length=1)

    visibility: str = Field(default="public")
    pricing_type: str = Field(default="free")
    pricing_amount_cents: int | None = None
    pricing_note: str | None = Field(default=None, max_length=300)

    @field_validator("atmosphere_keys")
    @classmethod
    def _five_atmospheres(cls, v: list[str]) -> list[str]:
        if len(v) != 5:
            raise ValueError("Choose exactly five atmospheres.")
        if len(set(v)) != 5:
            raise ValueError("Atmosphere choices must be unique.")
        return v

    @field_validator("visibility")
    @classmethod
    def _visibility(cls, v: str) -> str:
        if v not in {"public", "link", "private"}:
            raise ValueError("Visibility must be public, link, or private.")
        return v

    @field_validator("pricing_type")
    @classmethod
    def _pricing_type(cls, v: str) -> str:
        if v not in {"free", "contribution"}:
            raise ValueError("Pricing must be free or contribution.")
        return v


def _unique_slug(base: str, existing: list[str]) -> str:
    slug = base
    counter = 2
    while slug in existing:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _validate_identity_keys(
    location_id: str,
    atmosphere_keys: list[str],
    colour_palette_key: str,
    db: Session,
    user: User,
) -> None:
    # Location eligibility is enforced by the plan_guards layer:
    #   - Platform Owner may pick Atlas + Cornerstones.
    #   - Community plan may pick from the configured Atlas subset (or all
    #     Atlas if the subset tuple is empty).
    #   - Creator/Pro may pick any active Atlas Location.
    # Cornerstones are refused for all creator plans regardless of scope.
    location = db.query(Location).filter(
        Location.id == location_id,
        Location.status == "active",
    ).first()
    if not location:
        raise HTTPException(400, detail="Location is no longer available.")
    guard_location_allowed(user, location, db)

    atm_keys = {
        k for (k,) in db.query(AtmosphereOption.key).filter(AtmosphereOption.is_active.is_(True)).all()
    }
    if set(atmosphere_keys) - atm_keys:
        raise HTTPException(400, detail="One of your atmosphere choices is no longer available.")
    if not db.query(ColourStory).filter(
        ColourStory.key == colour_palette_key, ColourStory.is_active.is_(True)
    ).first():
        raise HTTPException(400, detail="Colour palette is no longer available.")


@router.post("/open", response_model=OpenCollectiveResponse, status_code=201)
def open_collective(
    body: OpenCollectiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> OpenCollectiveResponse:
    # Enforce plan-level limits before anything else. Platform Owner is
    # bypassed inside each guard.
    guard_active_collective_limit(current_user, db)
    guard_paid_offers_enabled(current_user, db, body.pricing_type)

    _validate_identity_keys(body.location_id, body.atmosphere_keys, body.colour_palette_key, db, current_user)

    existing_slugs = [slug for (slug,) in db.query(Space.slug).all()]
    slug = _unique_slug(slugify(body.name), existing_slugs)

    space = Space(
        id=str(uuid4()),
        slug=slug,
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        creator_id=current_user.id,
        is_public=(body.visibility == "public"),
        visibility=body.visibility,
        status="draft",
        location_id=body.location_id,
        atmosphere_keys=body.atmosphere_keys,
        # DB column name unchanged (colour_story_key) — Atlas v1.2 API/UI
        # name is Colour Palette. Column rename deferred to cleanup migration.
        colour_story_key=body.colour_palette_key,
        identity_statement=body.identity_statement.strip(),
        welcome_message=body.welcome_message.strip(),
        pricing_type=body.pricing_type,
        pricing_amount_cents=body.pricing_amount_cents if body.pricing_type == "contribution" else None,
        pricing_note=body.pricing_note.strip() if body.pricing_note else None,
        themes=[],
    )
    db.add(space)
    db.flush()

    db.add(SpaceMembership(
        id=str(uuid4()),
        user_id=current_user.id,
        space_id=space.id,
        role=SpaceRole.creator,
        status=SpaceMembershipStatus.active,
        source="creator_owner",
    ))

    draft = _get_draft(current_user.id, db)
    if draft:
        db.delete(draft)

    db.commit()
    db.refresh(space)

    world_builders_slug = _find_world_builders_slug(current_user.id, db)
    return OpenCollectiveResponse(
        slug=space.slug,
        name=space.name,
        world_builders_slug=world_builders_slug,
    )


def _find_world_builders_slug(user_id: str, db: Session) -> str | None:
    """Return the slug of an auto-grant space (World Builders) the user
    holds active auto_role membership in, or None. Structural lookup —
    matches the reconciler's philosophy of discovering spaces by the
    ``auto_grant_role`` flag rather than a hardcoded slug."""
    row = (
        db.query(Space.slug)
        .join(SpaceMembership, SpaceMembership.space_id == Space.id)
        .filter(
            Space.auto_grant_role.isnot(None),
            SpaceMembership.user_id == user_id,
            SpaceMembership.source == AUTO_ROLE_SOURCE,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    return row[0] if row else None


# ---------------------------------------------------------------------------
# PATCH /{slug} — edit an existing collective's identity
# Used by both "Change Location" and "Edit Collective Identity" modes.
# ---------------------------------------------------------------------------


class UpdateIdentityRequest(BaseModel):
    """Update the identity of an existing collective. All fields optional
    so the frontend can send only what changed (change-location mode may
    change everything; edit-identity mode leaves location alone)."""
    location_id: str | None = None
    atmosphere_keys: list[str] | None = None
    colour_palette_key: str | None = None
    identity_statement: str | None = None
    welcome_message: str | None = None

    @field_validator("atmosphere_keys")
    @classmethod
    def _five_atmospheres_if_present(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if len(v) != 5:
            raise ValueError("Choose exactly five atmospheres.")
        if len(set(v)) != 5:
            raise ValueError("Atmosphere choices must be unique.")
        return v


def _managed_collective(slug: str, current_user: User, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(404, detail="Collective not found.")
    if space.creator_id == current_user.id:
        return space
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(403, detail="You do not manage this collective.")
    return space


@router.patch("/{slug}", response_model=OpenCollectiveResponse)
def update_identity(
    slug: str,
    body: UpdateIdentityRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> OpenCollectiveResponse:
    space = _managed_collective(slug, current_user, db)

    if body.location_id is not None:
        # Location eligibility is enforced by the plan_guards layer — see
        # _validate_identity_keys for the same rule set.
        location = db.query(Location).filter(
            Location.id == body.location_id,
            Location.status == "active",
        ).first()
        if not location:
            raise HTTPException(400, detail="Location is no longer available.")
        guard_location_allowed(current_user, location, db)
        space.location_id = body.location_id
    if body.atmosphere_keys is not None:
        atm_keys = {
            k for (k,) in db.query(AtmosphereOption.key).filter(AtmosphereOption.is_active.is_(True)).all()
        }
        if set(body.atmosphere_keys) - atm_keys:
            raise HTTPException(400, detail="One of your atmosphere choices is no longer available.")
        space.atmosphere_keys = body.atmosphere_keys
    if body.colour_palette_key is not None:
        if not db.query(ColourStory).filter(
            ColourStory.key == body.colour_palette_key, ColourStory.is_active.is_(True)
        ).first():
            raise HTTPException(400, detail="Colour palette is no longer available.")
        space.colour_story_key = body.colour_palette_key
    if body.identity_statement is not None:
        space.identity_statement = body.identity_statement.strip() or None
    if body.welcome_message is not None:
        space.welcome_message = body.welcome_message.strip() or None

    db.commit()
    db.refresh(space)
    return OpenCollectiveResponse(slug=space.slug, name=space.name)
