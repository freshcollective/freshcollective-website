"""Creator-side Offering management — Phase B4.

Seven endpoints: list, create, read, update, readiness, publish, retire.
No file upload, no About blocks, no member routes, no checkout — each
deliberately a later stage.

Two things here differ from every other creator surface, and both are
deliberate.

**Owner-only.** Every other Creator Studio endpoint uses
``_get_managed_space``, which accepts the owner *or* an active
membership with role ``creator``/``moderator``. Offerings use
:func:`_get_owned_space` instead, which accepts the owner alone. The
approved rule is that Offering management is restricted to the
Collective's owner for Phase 1; a moderator helping run a community
should not be able to put a product on sale under someone else's payout
account. ``_get_managed_space`` itself is untouched, so moderator
permissions elsewhere are unchanged.

**Flag-gated as a router dependency.** ``require_offerings_enabled`` is
attached to every route in this module rather than checked inside each
handler, so a new endpoint added here cannot forget it. The flag
governs *new Offering activity*. It deliberately does **not** govern
downloads of files a member already owns — that asymmetry is the
approved separation and is implemented in
``app/uploads/authorization.py``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.creator.plan_guards import (
    guard_offering_limit,
    guard_paid_offers_enabled,
    offering_allowance,
)
from app.creator.routes import get_creator_user
from app.creator.schemas_offerings import (
    OfferingCreateRequest,
    OfferingDetailResponse,
    OfferingReadinessResponse,
    OfferingSummaryResponse,
    OfferingUpdateRequest,
)
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingPricingKind,
    OfferingStatus,
)
from app.models.platform import Space
from app.models.user import User
from app.services import offering_readiness

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------


def require_offerings_enabled() -> None:
    """Refuse every route in this module while Offerings is disabled.

    **503, not 404.** The distinction matters for the two audiences: a
    404 would tell a developer the route does not exist, sending them
    looking for a bug, whereas 503 says "built, not switched on". No
    Offering can be created, edited or published through these routes
    while the flag is False, which is the requirement; concealing their
    existence is not.

    There is deliberately **no admin or platform-owner bypass**. A
    bypass is how unfinished functionality reaches production: an
    operator with the right role would be able to create real Offerings
    in a real Collective before the feature is ready, and those rows
    would then be indistinguishable from intended ones. Turning the flag
    on is the only way in, and that is a deployment decision rather than
    a permission.
    """
    if not settings.offerings_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Offerings are not available yet.",
        )


router = APIRouter(
    prefix="/api/creator",
    tags=["creator-offerings"],
    dependencies=[Depends(require_offerings_enabled)],
)


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------


def _get_owned_space(slug: str, user: User, db: Session) -> Space:
    """The Collective, only if this user owns it.

    Stricter than ``_get_managed_space`` by design — see the module
    docstring. Modelled on the ownership check in ``delete_space``,
    which is the existing precedent for an owner-only creator action.

    Platform creators get nothing from their role alone: ownership is a
    relationship to *this* Collective, and a creator account elsewhere
    is not one. A platform admin is likewise not an owner here;
    cross-Collective oversight lives in the admin portal, as it does for
    every other Creator Studio endpoint.

    **404, not 403, when the caller is not the owner.** A 403 would
    confirm that a Collective with this slug exists and that someone
    else owns it. Refusing identically to "no such Collective" is what
    stops this endpoint being used to enumerate other people's
    Collectives.
    """
    space = db.query(Space).filter(Space.slug == slug).first()
    if space is None or space.creator_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collective not found.",
        )
    return space


def _get_offering(space: Space, offering_slug: str, db: Session) -> Offering:
    """Resolve an Offering *through* its Collective.

    Scoped to the space the caller has already been authorised for, so a
    slug belonging to another Collective is a 404 rather than a leak.
    """
    row = (
        db.query(Offering)
        .filter(
            Offering.space_id == space.id,
            Offering.slug == offering_slug,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Offering not found.",
        )
    return row


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    base = _SLUG_STRIP.sub("-", (title or "").lower()).strip("-")
    return base[:100] or "offering"


def _unique_slug(space: Space, title: str, db: Session) -> str:
    """A slug unique within this Collective.

    Uniqueness is per Collective, matching ``offerings_space_slug_unique``
    — two Collectives may each sell "morning-pages". The suffix loop is
    bounded; the unique constraint is the real guarantee and a collision
    past the bound surfaces as an integrity error rather than a silent
    overwrite.
    """
    base = _slugify(title)
    candidate = base
    for n in range(2, 100):
        exists = (
            db.query(Offering.id)
            .filter(Offering.space_id == space.id, Offering.slug == candidate)
            .first()
        )
        if exists is None:
            return candidate
        candidate = f"{base}-{n}"
    return f"{base}-{uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _file_counts(offering: Offering, db: Session) -> tuple[int, int]:
    """(current files, current files that have passed)."""
    rows = (
        db.query(OfferingFile.validation_status)
        .filter(
            OfferingFile.offering_id == offering.id,
            OfferingFile.superseded_at.is_(None),
        )
        .all()
    )
    return len(rows), sum(1 for (s,) in rows if s == "passed")


def _summary(offering: Offering, db: Session) -> dict:
    total, passed = _file_counts(offering, db)
    return {
        "id": offering.id,
        "slug": offering.slug,
        "title": offering.title,
        "summary": offering.summary,
        "cover_image_url": offering.cover_image_url,
        "status": offering.status,
        "pricing_kind": offering.pricing_kind,
        "price_cents": offering.price_cents,
        "file_count": total,
        "files_passed": passed,
        "published_at": offering.published_at,
        "retired_at": offering.retired_at,
        "updated_at": offering.updated_at,
    }


def _detail(offering: Offering, db: Session) -> dict:
    d = _summary(offering, db)
    d["description"] = offering.description
    d["fulfilment_kind"] = offering.fulfilment_kind
    d["created_at"] = offering.created_at
    # Acquisition count, available now so the creator surface has it from
    # the start. Active entitlements only — a revoked one is not a sale
    # anyone still holds.
    d["acquisition_count"] = (
        db.query(OfferingEntitlement.id)
        .filter(
            OfferingEntitlement.offering_id == offering.id,
            OfferingEntitlement.status
            == OfferingEntitlementStatus.active.value,
        )
        .count()
    )
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/spaces/{slug}/offerings",
    response_model=list[OfferingSummaryResponse],
    summary="List this Collective's Offerings (all statuses)",
)
def list_offerings(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """Every Offering, including drafts and retired ones.

    Retired Offerings are included rather than filtered out: the creator
    still manages them, their purchasers still hold them, and hiding
    them here would make a retired product look deleted.
    """
    space = _get_owned_space(slug, current_user, db)
    rows = (
        db.query(Offering)
        .filter(Offering.space_id == space.id)
        .order_by(Offering.created_at.desc())
        .all()
    )
    return [_summary(o, db) for o in rows]


@router.post(
    "/spaces/{slug}/offerings",
    response_model=OfferingDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft Offering",
)
def create_offering(
    slug: str,
    body: OfferingCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Create a draft. Nothing is published and nothing is priced yet.

    The plan quota is enforced **under a row lock on the Collective**.
    Without it, two simultaneous creates could both count four existing
    Offerings and both insert, taking a Community creator to six. The
    lock serialises them so the second request counts five and is
    refused — the same discipline the Gathering hold uses to stop two
    buyers taking one seat.
    """
    space = _get_owned_space(slug, current_user, db)

    # Serialise concurrent creates for this Collective before counting.
    db.execute(
        text("SELECT id FROM spaces WHERE id = :id FOR UPDATE"),
        {"id": space.id},
    )
    guard_offering_limit(current_user, space, db)

    title = body.title.strip()
    offering = Offering(
        id=str(uuid4()),
        space_id=space.id,
        created_by_user_id=current_user.id,
        slug=_unique_slug(space, title, db),
        title=title,
        summary=(body.summary or "").strip() or None,
        status=OfferingStatus.draft.value,
    )
    db.add(offering)
    db.commit()
    db.refresh(offering)
    logger.info(
        "offering created: id=%s space=%s by=%s",
        offering.id, space.id, current_user.id,
    )
    return _detail(offering, db)


@router.get(
    "/spaces/{slug}/offerings/{offering_slug}",
    response_model=OfferingDetailResponse,
    summary="Read one Offering",
)
def get_offering(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_owned_space(slug, current_user, db)
    return _detail(_get_offering(space, offering_slug, db), db)


@router.patch(
    "/spaces/{slug}/offerings/{offering_slug}",
    response_model=OfferingDetailResponse,
    summary="Update details, cover or pricing intent",
)
def update_offering(
    slug: str,
    offering_slug: str,
    body: OfferingUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Partial update. Only fields present in the body are touched.

    Pricing is validated here as well as at publish, because a creator
    should learn that their plan forbids a paid price when they set it
    rather than when they try to publish.

    The slug is **not** updated when the title changes. A published
    Offering's URL is something a creator may have shared, and silently
    moving it would break those links. Renaming the URL would be a
    separate, deliberate action.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)

    data = body.model_dump(exclude_unset=True)

    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="Title cannot be empty.")
        offering.title = title
    if "summary" in data:
        offering.summary = (data["summary"] or "").strip() or None
    if "description" in data:
        offering.description = data["description"] or None
    if "cover_image_url" in data:
        url = data["cover_image_url"] or None
        if url is not None and not offering_readiness.is_acceptable_cover(url):
            # Allow-listed shapes only — a curated platform default or a
            # file this platform stored. See ``is_acceptable_cover``.
            raise HTTPException(
                status_code=422,
                detail="That cover image isn't one we can use.",
            )
        offering.cover_image_url = url

    if "pricing_kind" in data:
        kind = data["pricing_kind"]
        price = data.get("price_cents", offering.price_cents)
        if kind == OfferingPricingKind.free.value:
            # Enforced here and by ``ck_offerings_pricing_shape``.
            offering.pricing_kind = kind
            offering.price_cents = None
        elif kind == OfferingPricingKind.one_time.value:
            # Plan eligibility, reusing the existing commercial guard
            # rather than a second copy of the rule.
            guard_paid_offers_enabled(current_user, db, "paid")
            if price is None or price <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="A paid Offering needs a price above zero.",
                )
            offering.pricing_kind = kind
            offering.price_cents = int(price)
        else:
            raise HTTPException(
                status_code=422, detail="Pricing must be free or one_time.",
            )
    elif "price_cents" in data:
        # A price without a kind is meaningless, and silently inventing
        # ``one_time`` would be a pricing decision made by the server.
        raise HTTPException(
            status_code=422,
            detail="Choose free or one-time purchase before setting a price.",
        )

    db.commit()
    db.refresh(offering)
    return _detail(offering, db)


@router.get(
    "/spaces/{slug}/offerings/{offering_slug}/readiness",
    response_model=OfferingReadinessResponse,
    summary="What still needs attention before publishing",
)
def get_offering_readiness(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Advisory. The publish endpoint re-evaluates and is authoritative."""
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)
    result = offering_readiness.evaluate(
        db, offering=offering, space=space, owner=current_user,
    )
    out = result.as_dict()
    out["offering_limit"] = offering_allowance(current_user, db)
    return out


@router.post(
    "/spaces/{slug}/offerings/{offering_slug}/publish",
    response_model=OfferingDetailResponse,
    summary="Publish an Offering",
)
def publish_offering(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Publish, after re-checking every requirement server-side.

    The readiness response the creator saw is not trusted: a file may
    have been removed or quarantined since, and the only check that
    counts is the one taken at the moment of publishing.

    Retired Offerings are not republished here. Bringing one back is a
    product decision — purchasers exist, the price may be stale — and
    not something to fall out of a generic publish call.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)

    if offering.status == OfferingStatus.retired.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Offering has been retired and can't be republished.",
        )

    result = offering_readiness.evaluate(
        db, offering=offering, space=space, owner=current_user,
    )
    if not result.ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "This Offering isn't ready to publish yet.",
                "unmet": result.unmet_ids,
                "requirements": [r.as_dict() for r in result.requirements],
            },
        )

    offering.status = OfferingStatus.published.value
    # Set once, on first publish, and not cleared by a later unpublish —
    # it records when the thing first became available, which stays true.
    if offering.published_at is None:
        offering.published_at = datetime.utcnow()
    db.commit()
    db.refresh(offering)
    logger.info(
        "offering published: id=%s space=%s by=%s",
        offering.id, space.id, current_user.id,
    )
    return _detail(offering, db)


@router.post(
    "/spaces/{slug}/offerings/{offering_slug}/retire",
    response_model=OfferingDetailResponse,
    summary="Retire an Offering — stops new acquisitions, keeps existing ones",
)
def retire_offering(
    slug: str,
    offering_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Stop selling. Keep serving.

    Nothing about existing ownership changes: entitlements are
    untouched, files stay exactly where they are, and download
    authorisation never consults an Offering's status — which is what
    makes "retired but still downloadable" a property of the
    architecture rather than a behaviour to remember.

    When acquisition exists (Phase D) it will refuse a retired
    Offering. There is nothing to refuse yet.
    """
    space = _get_owned_space(slug, current_user, db)
    offering = _get_offering(space, offering_slug, db)

    if offering.status == OfferingStatus.retired.value:
        return _detail(offering, db)   # idempotent

    offering.status = OfferingStatus.retired.value
    offering.retired_at = datetime.utcnow()
    db.commit()
    db.refresh(offering)
    logger.info(
        "offering retired: id=%s space=%s by=%s",
        offering.id, space.id, current_user.id,
    )
    return _detail(offering, db)


__all__ = ["router", "require_offerings_enabled"]
