"""
/api/creator/* — routes for creator/admin users to manage their Spaces.

Permission model:
- All endpoints require role in ('creator', 'admin') via get_creator_user.
- Space-specific endpoints additionally verify the caller owns the space
  OR has a creator/moderator membership in that space.
"""

import json
import pathlib
import re
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import false as sa_false, func, text
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_creator_user
from app.community_care.shared import (
    has_active_creator_restriction,
    is_space_closed,
    is_space_frozen,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.storage import delete_file, save_file, save_media_file
from app.creator.plan_config import (
    ALL_PLANS,
    ORGANISATION,
    PlanCapability,
    get_plan_capability,
)
from app.creator.plan_guards import (
    guard_active_collective_limit,
    guard_location_allowed,
    guard_offer_pages_enabled,
    guard_paid_offers_enabled,
    is_platform_owner as _is_platform_owner,
)
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AccessRequestOut,
    AddMemberRequest,
    AddMemberResponse,
    AttendanceUpdateRequest,
    CreatorBillingResponse,
    CreatorMemberItem,
    CreatorPaymentSetup,
    CreatorPaymentSummary,
    CreatorPaymentTransactionOut,
    CreatorPlanOut,
    CreatorSubscriptionOut,
    CreatorUsage,
    EntitlementOut,
    GrantEntitlementRequest,
    GrantPassRequest,
    GrantPassResponse,
    RevokeEntitlementRequest,
    AboutBlockReorderRequest,
    AboutBlockResponse,
    AboutBlockUpdateRequest,
    MemberBookingItem,
    MemberPathwayAccessItem,
    BookedMemberItem,
    BulkEventCreateResponse,
    EventCreateRequest,
    EventResponse,
    EventUpdateRequest,
    ManualBookingRequest,
    MemberActivePassOut,
    RecurringBookingRequest,
    RecurringBookingResponse,
    RecurringBookingItem,
    PassSummary,
    InvitationCreateRequest,
    InvitationResponse,
    BlockMediaInfo,
    LibraryFolderCreateRequest,
    LibraryFolderResponse,
    LibraryFolderUpdateRequest,
    LibraryItem,
    LibraryFileInfo,
    LibraryLinkInfo,
    LibraryListResponse,
    MediaAssetResponse,
    MediaAssetUpdateRequest,
    OfferPageCreateRequest,
    OfferPageResponse,
    OfferPageSummary,
    OfferPageUpdateRequest,
    PathwayCreateRequest,
    PathwayResponse,
    PathwayUpdateRequest,
    GatheringSeriesCreateRequest,
    GatheringSeriesResponse,
    GatheringSeriesSummary,
    GatheringSeriesUpdateRequest,
    GenerateSchedulesRequest,
    PaymentOptionCreateRequest,
    PaymentOptionResponse,
    PaymentOptionScheduleCreateRequest,
    PaymentOptionScheduleResponse,
    PaymentOptionScheduleUpdateRequest,
    PaymentOptionUpdateRequest,
    SeriesPaymentOptionCreateRequest,
    SeriesPaymentOptionUpdateRequest,
    ResourceCreateRequest,
    ResourcePathwayInfo,
    ResourceResponse,
    ResourceUpdateRequest,
    ResourceUsageReference,
    ResourceUsageResponse,
    MediaUsageReference,
    MediaUsageResponse,
    PostCreateRequest,
    PostManageResponse,
    PostUpdateRequest,
    ReorderRequest,
    SectionCreateRequest,
    SectionResponse,
    SectionUpdateRequest,
    SpaceCreateRequest,
    SpaceDetail,
    SpaceUpdateRequest,
    StepBlockCreateRequest,
    StepBlockReorderRequest,
    StepBlockResponse,
    StepBlockUpdateRequest,
    StepCreateRequest,
    StepResourceCreateRequest,
    StepResourceResponse,
    StepResourceUpdateRequest,
    StepResponse,
    StepUpdateRequest,
    slugify,
    AccessPassAdminOut,
)
from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.creator_billing import CreatorPlan, CreatorSubscription
from app.models.payment import PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType, PayoutStatus
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    BookingStatus,
    EntitlementSource,
    EntitlementStatus,
    PathwayEntitlement,
    CommunityPost,
    CreatorMediaAsset,
    Enrollment,
    Event,
    EventBooking,
    EventSeries,
    LibraryFolder,
    ManualMember,
    OfferPage,
    ManualMemberStatus,
    ManualMemberPathwayAccess,
    Pathway,
    PathwayAboutBlock,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    PathwayStepManualRelease,
    PathwayUnlockRequirement,
    Space,
    SpaceAccessRequest,
    SpaceInvitation,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceResource,
    space_resource_pathways,
    SpaceRole,
    StepBlockType,
    StepProgress,
    StepResource,
)
from app.models.user import User
from app.services.banner_image_validator import (
    BannerImageValidationError,
    validate_banner_image_url,
)
from app.services.button_validator import (
    ButtonValidationError,
    normalise_button_style,
    normalise_new_tab,
    validate_button_text,
    validate_button_url,
)
from app.services.embed_validator import EmbedValidationError, extract_and_validate_embed_url
from app.services.gathering_types import normalise_access_type
from app.services.notification_service import trigger_new_step
from app.spaces.schemas import SpaceSummary

router = APIRouter(prefix="/api/creator", tags=["creator"])


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _space_detail_response(space: Space, db: Session) -> dict:
    """Build a SpaceDetail-compatible dict with derived_has_paid_internal_content
    injected. Also hydrates the Atlas v1.2 identity fields (Location + Colour
    Palette + atmosphere/identity/welcome) so the frontend can drive the
    Collective Home panel and the palette-based theme without a second call.

    Discovery pillar: also hydrates ``primary_place`` from the linked
    SpacePlace row so the Place & Feel tab can render the current
    Geographic Location.
    """
    from app.models.platform import Location, ColourStory
    from app.models.place import Place, SpacePlace
    data = SpaceDetail.model_validate(space).model_dump()
    data['derived_has_paid_internal_content'] = _derived_has_paid_content(space.id, db)
    data['location_id'] = space.location_id
    data['atmosphere_keys'] = list(space.atmosphere_keys or [])
    data['identity_statement'] = space.identity_statement
    data['welcome_message'] = space.welcome_message
    data['colour_palette_key'] = space.colour_story_key
    # Hydrate Location
    if space.location_id:
        loc = db.query(Location).filter(Location.id == space.location_id).first()
        if loc:
            data['location'] = {
                "id": loc.id,
                "key": loc.key,
                "name": loc.name,
                "description": loc.description,
                "hero_artwork_url": loc.hero_artwork_url,
                # Long-form Atlas Entry, sourced from World Management.
                # Read-only in Creator Studio — the Atlas Entry helps a
                # Creator understand the feeling and story of their
                # chosen island, but never becomes something they
                # manage. Editing lives in /admin/atlas.
                "atlas_entry": loc.atlas_entry,
            }
    # Hydrate Colour Palette
    if space.colour_story_key:
        cs = db.query(ColourStory).filter(ColourStory.key == space.colour_story_key).first()
        if cs:
            data['colour_palette'] = {"key": cs.key, "name": cs.name, "palette": cs.palette}
    # Hydrate Place & Feel — Geographic Location (nullable; only set
    # once a Creator has picked one).
    data['connection_style'] = space.connection_style
    link = db.query(SpacePlace).filter(SpacePlace.space_id == space.id).first()
    if link is not None:
        place = db.query(Place).filter(Place.id == link.place_id).first()
        if place is not None:
            data['primary_place'] = {
                "id": place.id,
                "slug": place.slug,
                "name": place.name,
                "region": place.region,
                "country_code": place.country_code,
            }
    return data


def _derived_has_paid_content(space_id: str, db: Session) -> bool:
    """True if the space has at least one active paid pathway."""
    from app.models.platform import Pathway  # local import to avoid circular
    return db.query(Pathway).filter(
        Pathway.space_id == space_id,
        Pathway.status == "active",
        Pathway.access_type.in_(("one_time", "subscription")),
        Pathway.price_cents.isnot(None),
        Pathway.price_cents > 0,
    ).first() is not None


def _ensure_creator_write_allowed(user: User, space: Space, db: Session) -> None:
    """Refuse a creator-side write when Community Care has restricted
    the creator, frozen the collective, or closed it.

    Admins bypass restriction/freeze so caretaker triage and reversal
    can proceed; closure is terminal and blocks even admin writes on
    the collective's ordinary content (closure is not "reversed" —
    that would need a new case with its own resolution).
    """
    if is_space_closed(space):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This collective has been closed.",
        )
    if user.role == "admin":
        return
    if is_space_frozen(space):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This collective is temporarily paused by Fresh Collective.",
        )
    if has_active_creator_restriction(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your creator functions are temporarily restricted by Fresh Collective.",
        )


def _get_managed_space(slug: str, user: User, db: Session) -> Space:
    """Return the Space if the user owns it or is a creator/moderator.

    Platform admins do not get automatic creator rights over other creators'
    collectives here — for cross-collective oversight, use the admin portal
    (`/admin/...`). Creator Studio treats admins like any other creator.
    """
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    is_owner = space.creator_id == user.id
    if not is_owner:
        mem = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == user.id,
                SpaceMembership.role.in_(["creator", "moderator"]),
                SpaceMembership.status == "active",
            )
            .first()
        )
        if not mem:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage this Space.",
            )
    return space


def _get_pathway(space: Space, pathway_slug: str, db: Session) -> Pathway:
    pathway = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id, Pathway.slug == pathway_slug)
        .first()
    )
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")
    return pathway


def _get_gathering_series(space: Space, series_slug: str, db: Session) -> EventSeries:
    series = (
        db.query(EventSeries)
        .filter(EventSeries.space_id == space.id, EventSeries.slug == series_slug)
        .first()
    )
    if not series:
        raise HTTPException(status_code=404, detail="Gathering Series not found.")
    return series


def _validate_series_id_for_space(
    series_id: str | None, space: Space, db: Session,
) -> str | None:
    """Resolve an incoming Gathering Series id against the given
    Space. Returns the id verbatim when it matches a series in this
    space; returns None when the caller passed None; raises 400 when
    the id references a series in a different space or doesn't exist.

    Reused by event create + bulk create + update so the same
    ownership rule applies wherever an Event can be attached to a
    Series.
    """
    if series_id is None:
        return None
    series = (
        db.query(EventSeries)
        .filter(EventSeries.id == series_id, EventSeries.space_id == space.id)
        .first()
    )
    if not series:
        raise HTTPException(
            status_code=400,
            detail="Gathering Series not found in this Collective.",
        )
    return series.id


def _enforce_series_pass_invariant(
    resulting_access_type: str | None,
    resulting_series_id: str | None,
) -> None:
    """Reject any Event state where ``booking_access_type`` is
    ``'included_with_series'`` but ``series_id`` is null.

    Called after resolving the FINAL post-update values so a caller
    can, in a single PATCH, change the access type away from Series
    pass AND clear the series id — that combination is fine because
    the resulting access type is no longer ``included_with_series``.
    The invariant only rejects the invalid pairing itself.
    """
    from app.services.gathering_types import normalise_access_type as _norm
    if _norm(resulting_access_type) == "included_with_series" and not resulting_series_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "\"Included with a Series pass\" requires the Gathering to "
                "belong to a Gathering Series. Either attach it to a Series "
                "or change the access type."
            ),
        )


def _unique_slug(base: str, existing: list[str]) -> str:
    slug = base
    counter = 2
    while slug in existing:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _pathway_slug(space: Space, title: str, exclude_id: str | None, db: Session) -> str:
    existing = [
        p.slug for p in db.query(Pathway.slug)
        .filter(Pathway.space_id == space.id, Pathway.id != exclude_id)
        .all()
    ]
    return _unique_slug(slugify(title), existing)


def _step_slug(pathway: Pathway, title: str, exclude_id: str | None, db: Session) -> str:
    existing = [
        s.slug for s in db.query(PathwayStep.slug)
        .filter(PathwayStep.pathway_id == pathway.id, PathwayStep.id != exclude_id)
        .all()
    ]
    return _unique_slug(slugify(title), existing)


def _get_step(pathway: Pathway, step_slug: str, db: Session) -> PathwayStep:
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id,
        PathwayStep.slug == step_slug,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")
    return step


def _get_resource(step: PathwayStep, resource_id: str, db: Session) -> StepResource:
    resource = db.query(StepResource).filter(
        StepResource.id == resource_id,
        StepResource.step_id == step.id,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return resource


def _normalise_banner_image(raw: str | None) -> str | None:
    """Validate a banner_image_url field; raise HTTPException(400) on rejection."""
    try:
        return validate_banner_image_url(raw)
    except BannerImageValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _normalise_button_fields(patch: dict) -> dict:
    """
    Validate and normalise the fields used by `button` blocks.

    Required fields (`embed_url`, `label`) are only validated when the
    creator has actually entered values — empty/null is accepted so that
    a stub button block can be created from the Add-block menu and
    configured later in the edit form. Style and new-tab markers are
    always normalised because they have safe defaults.
    """
    try:
        if patch.get("embed_url"):
            patch["embed_url"] = validate_button_url(patch["embed_url"])
        if patch.get("label"):
            patch["label"] = validate_button_text(patch["label"])
        if "caption" in patch:
            patch["caption"] = normalise_button_style(patch["caption"])
        if "content" in patch:
            patch["content"] = normalise_new_tab(patch["content"])
    except ButtonValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return patch


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

def _creator_plan_out(plan: CreatorPlan | None, capability: PlanCapability | None) -> CreatorPlanOut:
    """Merge a DB `CreatorPlan` row and the capability record from
    `plan_config` into the API shape. Either side may be missing:

      - `plan=None, capability=Organisation` — Organisation is not stored in
        the DB; the response synthesises the card from capability alone.
      - `plan=<row>, capability=None` — the DB has a plan slug this codebase
        doesn't know about. Legacy row — fall back to DB values and empty
        capability defaults.

    Never invent numeric values. Missing → None; `to be defined` is the
    frontend's responsibility to display."""
    if plan is not None:
        plan_id = plan.id
        name = plan.name
        slug = plan.slug
        description = plan.description
        monthly_price_cents = plan.monthly_price_cents
        currency = plan.currency
        transaction_fee_basis_points = plan.transaction_fee_basis_points
        collective_limit = plan.collective_limit
        pathway_limit = plan.pathway_limit
        media_storage_limit_mb = plan.media_storage_limit_mb
        creator_admin_seat_limit = plan.creator_admin_seat_limit
    elif capability is not None:
        plan_id = f"synthetic-{capability.slug}"
        name = capability.display_name
        slug = capability.slug
        description = capability.positioning
        monthly_price_cents = capability.monthly_price_cents
        currency = capability.currency
        transaction_fee_basis_points = capability.transaction_fee_basis_points
        collective_limit = capability.active_collective_limit
        pathway_limit = None
        media_storage_limit_mb = capability.storage_allowance_mb
        creator_admin_seat_limit = capability.caretaker_limit_per_collective
    else:
        raise ValueError("Both plan and capability were None.")

    cap = capability
    return CreatorPlanOut(
        id=plan_id,
        name=name,
        slug=slug,
        description=description,
        monthly_price_cents=monthly_price_cents,
        currency=currency,
        transaction_fee_basis_points=transaction_fee_basis_points,
        collective_limit=collective_limit,
        pathway_limit=pathway_limit,
        media_storage_limit_mb=media_storage_limit_mb,
        creator_admin_seat_limit=creator_admin_seat_limit,
        tagline=cap.tagline if cap else "",
        positioning=cap.positioning if cap else "",
        active_collective_limit=cap.active_collective_limit if cap else collective_limit,
        member_allowance_per_collective=cap.member_allowance_per_collective if cap else None,
        pooled_member_allowance=cap.pooled_member_allowance if cap else None,
        caretaker_limit_per_collective=cap.caretaker_limit_per_collective if cap else None,
        storage_allowance_mb=cap.storage_allowance_mb if cap else media_storage_limit_mb,
        location_scope=cap.location_scope if cap else "atlas_full",
        analytics_level=cap.analytics_level if cap else "basic",
        paid_offers_enabled=cap.paid_offers_enabled if cap else False,
        pathways_enabled=cap.pathways_enabled if cap else False,
        gatherings_enabled=cap.gatherings_enabled if cap else False,
        resources_enabled=cap.resources_enabled if cap else False,
        automations_enabled=cap.automations_enabled if cap else False,
        commercial_use=cap.commercial_use if cap else False,
        approval_required=cap.approval_required if cap else False,
        is_self_service=cap.is_self_service if cap else True,
        is_purchasable=cap.is_purchasable if cap else True,
        card_headline=cap.card_headline if cap else "",
        card_features=list(cap.card_features) if cap else [],
    )


# Canonical display order: Community → Creator → Pro → Organisation.
_PLAN_ORDER = {p.slug: i for i, p in enumerate(ALL_PLANS)}


@router.get("/billing", response_model=CreatorBillingResponse)
def get_creator_billing(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorBillingResponse:
    """
    Return billing state for the authenticated user.

    Two account types are supported:

    - Platform Owner (`role='admin'`): NOT on any creator subscription plan.
      `current_plan`, `subscription`, and `available_plans` are omitted
      (None / empty). Usage counts are returned but there is no limit to
      compare them against. Transaction fees do not apply. This is the
      canonical architecture — Platform Owner is a distinct account type
      that sits alongside the Creator plans (Free / Plus / Pro), not on top
      of them.

    - Creator (`role='creator'`): on a creator subscription plan (Free by
      default). `current_plan`, `subscription`, `available_plans` populated.
    """

    is_platform_owner = current_user.role == "admin"

    # Usage: count all non-archived spaces this user manages (owns directly
    # OR holds creator/moderator membership in). This matches what the
    # Creator Studio sidebar lists so both show the same number. Archived
    # spaces do not count toward any creator plan limit. Draft collectives
    # do count toward creator plan limits because they still occupy
    # creator capacity. For platform owners, this number is displayed but
    # never compared against a limit.
    _owned_ids: set[str] = {
        row[0]
        for row in db.query(Space.id)
        .filter(
            Space.creator_id == current_user.id,
            Space.status.notin_(["archived"]),
        )
        .all()
    }
    _member_ids: set[str] = {
        row[0]
        for row in db.query(SpaceMembership.space_id)
        .join(Space, Space.id == SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
            Space.status.notin_(["archived"]),
        )
        .all()
    }
    managed_space_ids = _owned_ids | _member_ids
    collectives_used = len(managed_space_ids)

    creator_space_ids = list(managed_space_ids)
    pathways_used = (
        db.query(func.count(Pathway.id))
        .filter(Pathway.space_id.in_(creator_space_ids))
        .scalar()
    ) if creator_space_ids else 0

    payment_setup = CreatorPaymentSetup(
        # Platform Owner never subscribes to a creator plan, so creator
        # billing is meaningfully "not applicable" — surfaced separately
        # by the frontend, not implied by this boolean.
        creator_billing_connected=False,
        member_payments_connected=settings.stripe_enabled,
        stripe_connect_connected=False,
        stripe_test_mode=bool(
            settings.stripe_secret_key
            and settings.stripe_secret_key.startswith("sk_test_")
        ),
    )

    usage = CreatorUsage(
        collectives_used=collectives_used,
        pathways_used=pathways_used,
        media_storage_used_mb=None,  # TODO: sum media asset file sizes when tracked
    )

    # Platform Owner: return the account without any plan attached.
    if is_platform_owner:
        return CreatorBillingResponse(
            current_plan=None,
            subscription=None,
            usage=usage,
            available_plans=[],
            payment_setup=payment_setup,
            is_platform_owner=True,
        )

    # Creator: attach the current plan and full plan lineup.
    subscription = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == current_user.id,
            CreatorSubscription.status.in_(["active", "trialing"]),
        )
        .first()
    )
    db_plans = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .all()
    )
    current_plan_row = (
        subscription.plan if subscription
        else (min(db_plans, key=lambda p: p.monthly_price_cents) if db_plans else None)
    )
    if not current_plan_row:
        raise HTTPException(status_code=500, detail="No creator plans are configured.")

    if not subscription:
        from datetime import datetime as dt
        sub_out = CreatorSubscriptionOut(
            id="",
            status="active",
            starts_at=dt.utcnow(),
            ends_at=None,
            stripe_connected=False,
        )
    else:
        sub_out = CreatorSubscriptionOut(
            id=subscription.id,
            status=subscription.status.value if hasattr(subscription.status, "value") else str(subscription.status),
            starts_at=subscription.starts_at,
            ends_at=subscription.ends_at,
            stripe_connected=False,
        )

    # Merge DB rows with capability records. Community/Creator/Pro come
    # from DB (real plans users can subscribe to). Organisation is added as
    # a synthetic entry so the pricing UI can render its "Talk to us" card
    # without inserting a fake subscribable plan into the database.
    db_out = [
        _creator_plan_out(row, get_plan_capability(row.slug))
        for row in db_plans
    ]
    org_out = _creator_plan_out(None, ORGANISATION)
    available_out = sorted(
        [*db_out, org_out],
        key=lambda p: _PLAN_ORDER.get(p.slug, 999),
    )

    return CreatorBillingResponse(
        current_plan=_creator_plan_out(
            current_plan_row, get_plan_capability(current_plan_row.slug)
        ),
        subscription=sub_out,
        usage=usage,
        available_plans=available_out,
        payment_setup=payment_setup,
        is_platform_owner=False,
    )


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

@router.get("/spaces", response_model=list[SpaceSummary])
def list_my_spaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[Space]:
    owned = db.query(Space).filter(Space.creator_id == current_user.id).all()
    membered = (
        db.query(Space)
        .join(SpaceMembership, SpaceMembership.space_id == Space.id)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .all()
    )
    seen = {s.id for s in owned}
    return owned + [s for s in membered if s.id not in seen]


@router.post("/spaces", response_model=SpaceDetail, status_code=201)
def create_space(
    body: SpaceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    # Enforce the plan's active_collective_limit before creating a new
    # collective. Platform Owner is bypassed inside the guard.
    guard_active_collective_limit(current_user, db)

    existing_slugs = [slug for (slug,) in db.query(Space.slug).all()]
    slug = _unique_slug(slugify(body.name), existing_slugs)
    space = Space(
        id=str(uuid4()),
        slug=slug,
        name=body.name.strip(),
        tagline=body.tagline.strip() if body.tagline else None,
        description=body.description.strip() if body.description else None,
        about_content=body.about_content.strip() if body.about_content else None,
        creator_id=current_user.id,
        is_public=body.is_public,
        themes=body.themes,
        status="draft",
    )
    db.add(space)
    db.flush()  # assign space.id before creating membership

    # Auto-create creator membership so the owner appears as a member
    db.add(SpaceMembership(
        id=str(uuid4()),
        user_id=current_user.id,
        space_id=space.id,
        role=SpaceRole.creator,
        status=SpaceMembershipStatus.active,
        source="creator_owner",
    ))

    # Provision the two permanent system Channels so every new
    # collective is born with 🌱 Start Here and 🏡 Common Room.
    from app.community.channels import ensure_system_channels
    ensure_system_channels(space.id, db, created_by=current_user.id)

    db.commit()
    db.refresh(space)
    return space


@router.get("/spaces/{slug}", response_model=SpaceDetail)
def get_space(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    return _space_detail_response(space, db)


@router.patch("/spaces/{slug}", response_model=SpaceDetail)
def update_space(
    slug: str,
    body: SpaceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    space = _get_managed_space(slug, current_user, db)
    _ensure_creator_write_allowed(current_user, space, db)
    # Auto-managed collectives (World Builders): editable fields like
    # identity, about content, timezone and themes are allowed; access
    # and pricing fields are frozen because Fresh Collective owns them.
    # The frontend hides these fields entirely; this guard is the
    # safety net for a hand-crafted request.
    if space.auto_grant_role is not None:
        _AUTO_MANAGED_LOCKED_FIELDS = (
            "is_public",
            "status",
            "pricing_type",
            "pricing_amount_cents",
            "pricing_currency",
            "pricing_note",
            "has_paid_internal_content",
            "included_access_summary",
            "paid_content_summary",
        )
        for _field in _AUTO_MANAGED_LOCKED_FIELDS:
            _incoming = getattr(body, _field, None)
            if _incoming is None:
                continue
            if getattr(space, _field, None) != _incoming:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "This collective is managed automatically by Fresh Collective. "
                        f"'{_field}' cannot be changed here."
                    ),
                )
    if body.name is not None:
        space.name = body.name.strip()
    if body.slug is not None and body.slug != space.slug:
        conflict = (
            db.query(Space)
            .filter(Space.slug == body.slug, Space.id != space.id)
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This URL is already in use by another collective.",
            )
        space.slug = body.slug
    if body.tagline is not None:
        space.tagline = body.tagline.strip() or None
    if body.description is not None:
        space.description = body.description.strip() or None
    if body.about_content is not None:
        space.about_content = body.about_content.strip() or None
    if body.is_public is not None:
        space.is_public = body.is_public
    if body.status is not None:
        space.status = body.status
    if body.timezone is not None:
        space.timezone = body.timezone
    if body.themes is not None:
        space.themes = body.themes
    if body.pricing_type is not None:
        space.pricing_type = body.pricing_type
        if body.pricing_type == "free":
            space.pricing_amount_cents = None
    if body.pricing_amount_cents is not None:
        space.pricing_amount_cents = body.pricing_amount_cents
    if body.pricing_currency is not None:
        space.pricing_currency = body.pricing_currency
    if body.pricing_note is not None:
        space.pricing_note = body.pricing_note.strip() or None
    if body.has_paid_internal_content is not None:
        space.has_paid_internal_content = body.has_paid_internal_content
    if body.included_access_summary is not None:
        space.included_access_summary = body.included_access_summary.strip() or None
    if body.paid_content_summary is not None:
        space.paid_content_summary = body.paid_content_summary.strip() or None
    if body.guidance_start_title is not None:
        space.guidance_start_title = body.guidance_start_title.strip() or None
    if body.guidance_start_body is not None:
        space.guidance_start_body = body.guidance_start_body.strip() or None
    if body.guidance_focus_title is not None:
        space.guidance_focus_title = body.guidance_focus_title.strip() or None
    if body.guidance_focus_body is not None:
        space.guidance_focus_body = body.guidance_focus_body.strip() or None
    if body.guidance_links_title is not None:
        space.guidance_links_title = body.guidance_links_title.strip() or None
    if body.guidance_links_body is not None:
        space.guidance_links_body = body.guidance_links_body.strip() or None

    # ---- Place & Feel — Discovery pillar ------------------------------
    # Resolve and link the Geographic Location on save (drafts
    # included). Publishing controls discoverability, not whether the
    # relationship exists.
    _apply_place_and_feel(space, body, db)

    db.commit()
    db.refresh(space)
    return _space_detail_response(space, db)


def _apply_place_and_feel(space: Space, body: SpaceUpdateRequest, db: Session) -> None:
    """Update connection_style + Geographic Location link consistently.

    Rules (per docs/foundations/discovery-connection-belonging-location-model.md):

      * If connection_style is 'online' → clear any SpacePlace link.
      * If 'in_person' or 'both' and primary_place_id is provided →
        replace the current link (a Collective has at most one
        Primary Location today).
      * If 'in_person' or 'both' is set for the first time and no
        primary_place_id is provided → leave the link as-is (Creator
        may be flipping the toggle before picking; the UI enforces
        the required-choice, this is a graceful backend behaviour).
      * primary_place_id="" explicitly clears the link even when
        connection_style is 'in_person' or 'both' (Creator has
        cleared the picker).
    """
    from app.models.place import Place, SpacePlace

    style_changed = body.connection_style is not None
    place_id_provided = body.primary_place_id is not None

    if style_changed:
        space.connection_style = body.connection_style  # type: ignore[assignment]

    # Online → clear any existing link and stop.
    if space.connection_style == "online":
        db.query(SpacePlace).filter(SpacePlace.space_id == space.id).delete()
        return

    # in_person / both → apply the requested primary_place_id if the
    # client sent one.
    if place_id_provided:
        raw_id = (body.primary_place_id or "").strip()
        if raw_id == "":
            # Explicit clear.
            db.query(SpacePlace).filter(SpacePlace.space_id == space.id).delete()
            return
        target = db.query(Place).filter(Place.id == raw_id).first()
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "That Geographic Location isn't recognised. "
                    "Please pick it again from the search."
                ),
            )
        # Replace any existing link with the new primary.
        db.query(SpacePlace).filter(SpacePlace.space_id == space.id).delete()
        db.add(SpacePlace(space_id=space.id, place_id=target.id))


@router.post("/spaces/{slug}/cover", response_model=SpaceDetail)
async def upload_cover_image(
    slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    space = _get_managed_space(slug, current_user, db)
    filename = file.filename or "cover.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png"):
        raise HTTPException(status_code=400, detail="Only JPG and PNG images are allowed.")
    data = await file.read()
    if space.cover_image_url:
        old_rel = space.cover_image_url.removeprefix("/api/uploads/")
        delete_file(old_rel)
    rel_path, _, _ = save_file(data, filename, file.content_type or "image/jpeg", "covers")
    space.cover_image_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(space)
    return _space_detail_response(space, db)


@router.post("/spaces/{slug}/logo", response_model=SpaceDetail)
async def upload_logo(
    slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    """Upload an optional Collective Logo — the "hosted by" mark shown
    subtly beside the collective name. Location artwork remains the
    primary visual identity."""
    space = _get_managed_space(slug, current_user, db)
    filename = file.filename or "logo.png"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(status_code=400, detail="Only JPG, PNG, and WebP images are allowed.")
    data = await file.read()
    if space.logo_url:
        old_rel = space.logo_url.removeprefix("/api/uploads/")
        delete_file(old_rel)
    rel_path, _, _ = save_file(data, filename, file.content_type or "image/png", f"logos/{space.slug}")
    space.logo_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(space)
    return _space_detail_response(space, db)


@router.delete("/spaces/{slug}/logo", response_model=SpaceDetail)
def clear_logo(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> Space:
    space = _get_managed_space(slug, current_user, db)
    if space.logo_url:
        try:
            delete_file(space.logo_url.removeprefix("/api/uploads/"))
        except Exception:  # noqa: BLE001
            pass
        space.logo_url = None
        db.commit()
        db.refresh(space)
    return _space_detail_response(space, db)


# ---------------------------------------------------------------------------
# People / member pathway access  (entitlement-based)
# ---------------------------------------------------------------------------

def _pathway_progress_maps(
    user_id: str,
    pathway_ids: list[str],
    db: Session,
) -> tuple[dict[str, int], dict[str, int], dict[str, datetime], set[str]]:
    """
    Return (step_count_map, completed_count_map, last_activity_map,
            pathways_with_any_progress) for the given user and pathway ids.
    """
    step_count_rows = (
        db.query(PathwayStep.pathway_id, func.count(PathwayStep.id).label("cnt"))
        .filter(PathwayStep.pathway_id.in_(pathway_ids))
        .group_by(PathwayStep.pathway_id)
        .all()
    )
    step_count_map = {r.pathway_id: r.cnt for r in step_count_rows}

    step_rows = (
        db.query(PathwayStep.id, PathwayStep.pathway_id)
        .filter(PathwayStep.pathway_id.in_(pathway_ids))
        .all()
    )
    step_to_pathway: dict[str, str] = {r.id: r.pathway_id for r in step_rows}
    all_step_ids = list(step_to_pathway.keys())

    completed_count_map: dict[str, int] = {}
    last_activity_map: dict[str, datetime] = {}
    pathways_with_any_progress: set[str] = set()

    if all_step_ids:
        completed_records = (
            db.query(StepProgress)
            .filter(
                StepProgress.user_id == user_id,
                StepProgress.step_id.in_(all_step_ids),
                StepProgress.completed_at.isnot(None),
            )
            .all()
        )
        for rec in completed_records:
            pid = step_to_pathway.get(rec.step_id)
            if not pid:
                continue
            completed_count_map[pid] = completed_count_map.get(pid, 0) + 1
            if rec.completed_at and (
                pid not in last_activity_map or rec.completed_at > last_activity_map[pid]
            ):
                last_activity_map[pid] = rec.completed_at

        any_progress = (
            db.query(StepProgress.step_id)
            .filter(
                StepProgress.user_id == user_id,
                StepProgress.step_id.in_(all_step_ids),
            )
            .all()
        )
        pathways_with_any_progress = {
            step_to_pathway[r.step_id] for r in any_progress if r.step_id in step_to_pathway
        }

    return step_count_map, completed_count_map, last_activity_map, pathways_with_any_progress


@router.get(
    "/spaces/{slug}/members/{user_id}/pathway-access",
    response_model=list[MemberPathwayAccessItem],
)
def get_member_pathway_access(
    slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[MemberPathwayAccessItem]:
    """
    Return pathways in the space that this member has a meaningful relationship with,
    using pathway_entitlements as the source of truth for paid access.
    """
    space = _get_managed_space(slug, current_user, db)

    membership = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this space.")

    pathways = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id)
        .order_by(Pathway.position)
        .all()
    )
    if not pathways:
        return []

    pathway_ids = [p.id for p in pathways]

    # Active entitlements for this user in this space
    entitlements = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.pathway_id.in_(pathway_ids),
        )
        .order_by(PathwayEntitlement.created_at.desc())
        .all()
    )
    # Keep the most recent entitlement per pathway (any status) for display
    entitlement_map: dict[str, PathwayEntitlement] = {}
    for ent in entitlements:
        if ent.pathway_id not in entitlement_map:
            entitlement_map[ent.pathway_id] = ent

    # Active-only set for access checks
    active_entitlement_pathway_ids = {
        ent.pathway_id
        for ent in entitlements
        if (ent.status.value if hasattr(ent.status, "value") else str(ent.status)) == "active"
    }

    step_count_map, completed_count_map, last_activity_map, pathways_with_any_progress = (
        _pathway_progress_maps(user_id, pathway_ids, db)
    )

    result: list[MemberPathwayAccessItem] = []
    for pathway in pathways:
        p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
        access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
        entitlement = entitlement_map.get(pathway.id)
        ent_status = None
        ent_source = None
        if entitlement:
            ent_status = entitlement.status.value if hasattr(entitlement.status, "value") else str(entitlement.status)
            ent_source = entitlement.source.value if hasattr(entitlement.source, "value") else str(entitlement.source)

        total_steps = step_count_map.get(pathway.id, 0)
        completed_steps = completed_count_map.get(pathway.id, 0)
        progress_pct = round((completed_steps / total_steps) * 100) if total_steps > 0 else 0
        last_activity_at = last_activity_map.get(pathway.id)
        has_any_progress = pathway.id in pathways_with_any_progress
        has_active_entitlement = pathway.id in active_entitlement_pathway_ids

        # Skip draft/archived/coming_soon — not shown in People panel
        if p_status in ("coming_soon", "draft", "archived"):
            continue

        # Access state and label
        if access_type == "free":
            access_state = "accessible"
            access_label = "Free"
            access_source = "free"
        elif access_type == "included":
            access_state = "accessible"
            access_label = "Included"
            access_source = "included"
        elif has_active_entitlement:
            access_state = "accessible"
            if ent_source == "manual_grant":
                access_label = "Manual grant"
            elif ent_source == "one_time_purchase":
                access_label = "Purchased"
            elif ent_source == "subscription":
                access_label = "Subscribed"
            elif ent_source == "admin":
                access_label = "Admin"
            else:
                access_label = "Granted"
            access_source = ent_source
        elif ent_status == "revoked":
            access_state = "revoked"
            access_label = "Revoked"
            access_source = ent_source
        elif ent_status in ("expired", "cancelled"):
            access_state = ent_status
            access_label = ent_status.capitalize()
            access_source = ent_source
        else:
            access_state = "locked"
            access_label = "Locked"
            access_source = None

        # Filtering: only show if there is a meaningful relationship
        if access_type in ("free", "included") and not has_any_progress and not entitlement:
            continue
        if access_type in ("one_time", "subscription") and not entitlement:
            continue

        result.append(
            MemberPathwayAccessItem(
                id=pathway.id,
                slug=pathway.slug,
                title=pathway.title,
                pathway_status=p_status,
                access_type=access_type,
                price_cents=pathway.price_cents,
                currency=pathway.currency or "AUD",
                billing_interval=pathway.billing_interval,
                access_state=access_state,
                access_label=access_label,
                access_source=access_source,
                total_steps=total_steps,
                completed_steps=completed_steps,
                progress_pct=progress_pct,
                last_activity_at=last_activity_at,
                enrollment_status=ent_status,
            )
        )

    return result


@router.post(
    "/spaces/{slug}/members/{user_id}/pathway-access/grant",
    response_model=EntitlementOut,
    status_code=201,
)
def grant_pathway_access(
    slug: str,
    user_id: str,
    body: GrantEntitlementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> EntitlementOut:
    """Manually grant a member access to a paid pathway."""
    space = _get_managed_space(slug, current_user, db)

    membership = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this space.")

    pathway = (
        db.query(Pathway)
        .filter(Pathway.id == body.pathway_id, Pathway.space_id == space.id)
        .first()
    )
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found in this space.")

    access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
    if access_type in ("free", "included"):
        raise HTTPException(
            status_code=400,
            detail=f"This pathway is '{access_type}' — all eligible members already have access. Manual grants are only needed for paid pathways.",
        )

    # Check for an existing active entitlement
    existing = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Member already has active access to this pathway.")

    # Check for a revoked entitlement to reactivate
    revoked = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.revoked,
        )
        .order_by(PathwayEntitlement.revoked_at.desc())
        .first()
    )
    if revoked:
        revoked.status = EntitlementStatus.active
        revoked.revoked_at = None
        revoked.revoked_by_user_id = None
        revoked.granted_by_user_id = current_user.id
        revoked.notes = body.notes
        revoked.source = EntitlementSource.manual_grant
        revoked.starts_at = datetime.utcnow()
        db.commit()
        db.refresh(revoked)
        ent = revoked
    else:
        ent = PathwayEntitlement(
            id=str(uuid4()),
            user_id=user_id,
            space_id=space.id,
            pathway_id=pathway.id,
            source=EntitlementSource.manual_grant,
            status=EntitlementStatus.active,
            starts_at=datetime.utcnow(),
            granted_by_user_id=current_user.id,
            notes=body.notes,
        )
        db.add(ent)
        db.commit()
        db.refresh(ent)

    granter = db.query(User).filter(User.id == ent.granted_by_user_id).first() if ent.granted_by_user_id else None
    return EntitlementOut(
        id=ent.id,
        pathway_id=pathway.id,
        pathway_slug=pathway.slug,
        pathway_title=pathway.title,
        pathway_status=pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        access_type=access_type,
        source=ent.source.value if hasattr(ent.source, "value") else str(ent.source),
        status=ent.status.value if hasattr(ent.status, "value") else str(ent.status),
        starts_at=ent.starts_at,
        ends_at=ent.ends_at,
        granted_by_name=granter.name if granter else None,
        revoked_by_name=None,
        revoked_at=None,
        notes=ent.notes,
        total_steps=db.query(func.count(PathwayStep.id)).filter(PathwayStep.pathway_id == pathway.id).scalar() or 0,
        completed_steps=0,
        progress_pct=0,
        last_activity_at=None,
    )


@router.post(
    "/spaces/{slug}/members/{user_id}/pathway-access/revoke",
    response_model=EntitlementOut,
)
def revoke_pathway_access(
    slug: str,
    user_id: str,
    body: RevokeEntitlementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> EntitlementOut:
    """Revoke a member's access to a paid pathway."""
    space = _get_managed_space(slug, current_user, db)

    pathway = (
        db.query(Pathway)
        .filter(Pathway.id == body.pathway_id, Pathway.space_id == space.id)
        .first()
    )
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found in this space.")

    access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
    if access_type in ("free", "included"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot revoke access to a '{access_type}' pathway — access is automatic. To restrict access, change the pathway's access type.",
        )

    entitlement = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .first()
    )
    if not entitlement:
        raise HTTPException(status_code=404, detail="No active entitlement found for this member and pathway.")

    entitlement.status = EntitlementStatus.revoked
    entitlement.revoked_by_user_id = current_user.id
    entitlement.revoked_at = datetime.utcnow()
    if body.notes:
        entitlement.notes = body.notes
    db.commit()
    db.refresh(entitlement)

    revoker = db.query(User).filter(User.id == current_user.id).first()
    granter = db.query(User).filter(User.id == entitlement.granted_by_user_id).first() if entitlement.granted_by_user_id else None
    return EntitlementOut(
        id=entitlement.id,
        pathway_id=pathway.id,
        pathway_slug=pathway.slug,
        pathway_title=pathway.title,
        pathway_status=pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        access_type=access_type,
        source=entitlement.source.value if hasattr(entitlement.source, "value") else str(entitlement.source),
        status=entitlement.status.value if hasattr(entitlement.status, "value") else str(entitlement.status),
        starts_at=entitlement.starts_at,
        ends_at=entitlement.ends_at,
        granted_by_name=granter.name if granter else None,
        revoked_by_name=revoker.name if revoker else None,
        revoked_at=entitlement.revoked_at,
        notes=entitlement.notes,
        total_steps=db.query(func.count(PathwayStep.id)).filter(PathwayStep.pathway_id == pathway.id).scalar() or 0,
        completed_steps=0,
        progress_pct=0,
        last_activity_at=None,
    )


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

def _invitation_response(inv: "SpaceInvitation", db: Session) -> InvitationResponse:
    from app.models.platform import PaymentOption
    data = InvitationResponse.model_validate(inv)
    if inv.payment_option_id:
        opt = db.query(PaymentOption).filter_by(id=inv.payment_option_id).first()
        data.payment_option_name = opt.name if opt else None
    return data


@router.get("/spaces/{slug}/invitations", response_model=list[InvitationResponse])
def list_invitations(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[InvitationResponse]:
    space = _get_managed_space(slug, current_user, db)
    invitations = (
        db.query(SpaceInvitation)
        .filter(SpaceInvitation.space_id == space.id)
        .order_by(SpaceInvitation.created_at.desc())
        .all()
    )
    return [_invitation_response(inv, db) for inv in invitations]


@router.post("/spaces/{slug}/invitations", response_model=InvitationResponse, status_code=201)
def create_invitation(
    slug: str,
    body: InvitationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> InvitationResponse:
    space = _get_managed_space(slug, current_user, db)

    # Reject if email already belongs to an active member of this space
    existing_member = (
        db.query(SpaceMembership)
        .join(User, User.id == SpaceMembership.user_id)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == "active",
            func.lower(User.email) == body.email,  # body.email already lowercased
        )
        .first()
    )
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person is already a member of this collective.",
        )

    # Reject duplicate pending invitation
    existing_invite = (
        db.query(SpaceInvitation)
        .filter(
            SpaceInvitation.space_id == space.id,
            SpaceInvitation.email == body.email,
        )
        .first()
    )
    if existing_invite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person has already been invited to this collective.",
        )

    invitation = SpaceInvitation(
        id=str(uuid4()),
        space_id=space.id,
        email=body.email,
        name=body.name,
        role=body.role,
        note=body.note,
        invited_by_id=current_user.id,
        token=str(uuid4()),
        payment_option_id=body.payment_option_id,
        payment_status=body.payment_status,
        # sent_at=None → draft; caller must POST /send to actually email
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return _invitation_response(invitation, db)


@router.delete("/spaces/{slug}/invitations/{invitation_id}", status_code=204)
def delete_invitation(
    slug: str,
    invitation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    invitation = (
        db.query(SpaceInvitation)
        .filter(
            SpaceInvitation.space_id == space.id,
            SpaceInvitation.id == invitation_id,
        )
        .first()
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    db.delete(invitation)
    db.commit()


@router.post("/spaces/{slug}/invitations/{invitation_id}/send", response_model=InvitationResponse)
def send_invitation(
    slug: str,
    invitation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> InvitationResponse:
    """Mark a draft invitation as sent and dispatch the invitation email.

    Delivery is best-effort: ``sent_at`` records the operator's intent
    and is set even if the transactional email step logs an error, so
    an operator can always re-send from the same UI once delivery is
    fixed. See ``email_service.py`` for the missing-key / missing-from
    behaviour.
    """
    from app.services.email_service import email_service
    from app.services.email_templates import invitation_email
    from app.core.config import settings as _settings

    space = _get_managed_space(slug, current_user, db)
    invitation = (
        db.query(SpaceInvitation)
        .filter(
            SpaceInvitation.space_id == space.id,
            SpaceInvitation.id == invitation_id,
        )
        .first()
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invitation.sent_at is not None:
        raise HTTPException(status_code=409, detail="Invitation has already been sent.")

    accept_url = f"{_settings.frontend_origin.rstrip('/')}/invites/{invitation.token}"
    inviter_name = current_user.name or current_user.email
    subject, html = invitation_email(
        inviter_name=inviter_name,
        collective_name=space.name,
        accept_url=accept_url,
    )
    email_service.send(to=invitation.email, subject=subject, html_body=html)

    invitation.sent_at = datetime.utcnow()
    db.commit()
    db.refresh(invitation)
    return _invitation_response(invitation, db)


# ---------------------------------------------------------------------------
# Access Requests
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/access-requests", response_model=list[AccessRequestOut])
def list_access_requests(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[AccessRequestOut]:
    """Return pending access requests for a space."""
    space = _get_managed_space(slug, current_user, db)
    requests = (
        db.query(SpaceAccessRequest)
        .filter(SpaceAccessRequest.space_id == space.id, SpaceAccessRequest.status == "pending")
        .order_by(SpaceAccessRequest.created_at.desc())
        .all()
    )
    if not requests:
        return []

    user_ids = [r.user_id for r in requests]
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    from app.models.platform import CreatorProfile
    profiles = {
        cp.user_id: cp
        for cp in db.query(CreatorProfile).filter(CreatorProfile.user_id.in_(user_ids)).all()
    }

    def display_name(u: User) -> str:
        cp = profiles.get(u.id)
        if cp and cp.display_name:
            return cp.display_name
        return u.name or u.email.split("@")[0]

    return [
        AccessRequestOut(
            id=r.id,
            space_id=r.space_id,
            user_id=r.user_id,
            user_display_name=display_name(users[r.user_id]) if r.user_id in users else "Unknown",
            user_email=users[r.user_id].email if r.user_id in users else "",
            status=r.status,
            message=r.message,
            created_at=r.created_at,
        )
        for r in requests
    ]


@router.post("/spaces/{slug}/access-requests/{request_id}/approve", status_code=200)
def approve_access_request(
    slug: str,
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Approve a pending access request — creates membership with learner role."""
    space = _get_managed_space(slug, current_user, db)
    req = (
        db.query(SpaceAccessRequest)
        .filter(SpaceAccessRequest.id == request_id, SpaceAccessRequest.space_id == space.id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Access request not found.")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}.")

    existing = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == req.user_id)
        .first()
    )
    if not existing:
        db.add(SpaceMembership(
            id=str(uuid4()),
            user_id=req.user_id,
            space_id=space.id,
            role=SpaceRole.learner,
            status=SpaceMembershipStatus.active,
            source="joined",
        ))

    req.status = "approved"
    from datetime import datetime as _dt
    req.updated_at = _dt.utcnow()
    db.commit()
    return {"approved": True}


@router.post("/spaces/{slug}/access-requests/{request_id}/decline", status_code=200)
def decline_access_request(
    slug: str,
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Decline a pending access request."""
    space = _get_managed_space(slug, current_user, db)
    req = (
        db.query(SpaceAccessRequest)
        .filter(SpaceAccessRequest.id == request_id, SpaceAccessRequest.space_id == space.id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Access request not found.")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}.")

    req.status = "declined"
    from datetime import datetime as _dt
    req.updated_at = _dt.utcnow()
    db.commit()
    return {"declined": True}


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/pathways", response_model=list[PathwayResponse])
def list_pathways(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    pathways = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id)
        .order_by(Pathway.position)
        .all()
    )
    result = []
    for p in pathways:
        step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == p.id).count()
        result.append({
            "id": p.id,
            "slug": p.slug,
            "title": p.title,
            "description": p.description,
            "practice_body": p.practice_body,
            "cover_image_url": p.cover_image_url,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "access_type": p.access_type,
            "pricing_mode": getattr(p, "pricing_mode", "legacy") or "legacy",
            "price_cents": p.price_cents,
            "currency": p.currency,
            "billing_interval": p.billing_interval,
            "is_sequential": p.is_sequential,
            "pathway_type": (
                p.pathway_type.value if hasattr(p.pathway_type, "value")
                else str(p.pathway_type)
            ),
            "position": p.position,
            "step_count": step_count,
            "updated_at": p.updated_at,
            "created_at": p.created_at,
        })
    return result


@router.get("/spaces/{slug}/pathways/{pathway_slug}", response_model=PathwayResponse)
def get_pathway(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == pathway.id).count()
    return {
        "id": pathway.id,
        "slug": pathway.slug,
        "title": pathway.title,
        "description": pathway.description,
        "practice_body": pathway.practice_body,
        "cover_image_url": pathway.cover_image_url,
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "access_type": pathway.access_type,
        "pricing_mode": getattr(pathway, "pricing_mode", "legacy") or "legacy",
        "price_cents": pathway.price_cents,
        "currency": pathway.currency,
        "billing_interval": pathway.billing_interval,
        "is_sequential": pathway.is_sequential,
        "pathway_type": (
            pathway.pathway_type.value if hasattr(pathway.pathway_type, "value")
            else str(pathway.pathway_type)
        ),
        "position": pathway.position,
        "step_count": step_count,
        "updated_at": pathway.updated_at,
        "created_at": pathway.created_at,
    }


@router.post("/spaces/{slug}/pathways", response_model=PathwayResponse, status_code=201)
def create_pathway(
    slug: str,
    body: PathwayCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    _ensure_creator_write_allowed(current_user, space, db)

    # Enforce plan-level Pathway cap (currently: Community = 5, others uncapped).
    from app.creator.plan_guards import guard_pathway_limit
    guard_pathway_limit(current_user, space, db)

    pslug = body.slug or _pathway_slug(space, body.title, None, db)
    existing = db.query(Pathway).filter(Pathway.space_id == space.id, Pathway.slug == pslug).first()
    if existing:
        pslug = _pathway_slug(space, body.title, None, db)

    max_pos = db.query(Pathway.position).filter(Pathway.space_id == space.id).order_by(Pathway.position.desc()).first()
    position = (max_pos[0] + 1) if max_pos else 0

    pathway = Pathway(
        id=str(uuid4()),
        space_id=space.id,
        slug=pslug,
        title=body.title.strip(),
        description=body.description,
        practice_body=body.practice_body,
        status=body.status,
        is_sequential=body.is_sequential,
        position=position,
        access_type=body.access_type,
        price_cents=body.price_cents,
        currency=body.currency,
        billing_interval=body.billing_interval,
    )
    db.add(pathway)
    db.flush()

    if body.create_channel:
        from app.community.channels import ensure_pathway_channel
        ensure_pathway_channel(
            space_id=space.id,
            pathway_id=pathway.id,
            pathway_title=pathway.title,
            db=db,
            created_by=current_user.id,
        )

    db.commit()
    db.refresh(pathway)
    return {
        **{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "practice_body",
                                             "cover_image_url", "access_type", "pricing_mode", "price_cents",
                                             "currency", "billing_interval", "is_sequential", "position",
                                             "updated_at", "created_at"]},
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "step_count": 0,
    }


@router.patch("/spaces/{slug}/pathways/{pathway_slug}", response_model=PathwayResponse)
def update_pathway(
    slug: str,
    pathway_slug: str,
    body: PathwayUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    _ensure_creator_write_allowed(current_user, space, db)
    pathway = _get_pathway(space, pathway_slug, db)

    updates = body.model_dump(exclude_unset=True)
    for field, val in updates.items():
        if field == "title" and val is not None:
            pathway.title = val.strip()
        elif field in ("description", "practice_body"):
            setattr(pathway, field, (val.strip() or None) if val else None)
        elif field == "status" and val is not None:
            pathway.status = val
        elif field == "is_sequential" and val is not None:
            pathway.is_sequential = val
        elif field == "access_type" and val is not None:
            pathway.access_type = val
        elif field == "pricing_mode" and val is not None:
            pathway.pricing_mode = val
        elif field in ("price_cents", "billing_interval"):
            setattr(pathway, field, val)
        elif field == "currency" and val is not None:
            pathway.currency = val
        elif field == "cover_image_url":
            pathway.cover_image_url = _normalise_banner_image(val)
        elif field == "pathway_type" and val is not None:
            # Type is a hot-switch: no data is migrated or dropped. The
            # frontend surfaces a confirmation when the pathway has
            # enrolments; we don't hard-block here so an operator can
            # correct a mistake even on an active pathway.
            pathway.pathway_type = val

    db.commit()
    db.refresh(pathway)
    step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == pathway.id).count()
    return {
        **{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "practice_body",
                                             "cover_image_url", "access_type", "pricing_mode", "price_cents",
                                             "currency", "billing_interval", "is_sequential", "position",
                                             "updated_at", "created_at"]},
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "pathway_type": (
            pathway.pathway_type.value if hasattr(pathway.pathway_type, "value")
            else str(pathway.pathway_type)
        ),
        "step_count": step_count,
    }


@router.delete("/spaces/{slug}/pathways/{pathway_slug}", status_code=204)
def delete_pathway(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    db.delete(pathway)
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/cover", response_model=PathwayResponse)
async def upload_pathway_cover(
    slug: str,
    pathway_slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    filename = file.filename or "cover.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png"):
        raise HTTPException(status_code=400, detail="Only JPG and PNG images are allowed.")
    data = await file.read()
    if pathway.cover_image_url:
        old_rel = pathway.cover_image_url.removeprefix("/api/uploads/")
        delete_file(old_rel)
    rel_path, _, _ = save_file(data, filename, file.content_type or "image/jpeg", "pathway-covers")
    pathway.cover_image_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(pathway)
    step_count = db.query(PathwayStep).filter(PathwayStep.pathway_id == pathway.id).count()
    return {
        **{c: getattr(pathway, c) for c in ["id", "slug", "title", "description", "practice_body",
                                             "cover_image_url", "access_type", "pricing_mode", "price_cents",
                                             "currency", "billing_interval", "is_sequential", "position",
                                             "updated_at", "created_at"]},
        "status": pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        "step_count": step_count,
    }


@router.post("/spaces/{slug}/pathways/reorder", status_code=204)
def reorder_pathways(
    slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    for i, pid in enumerate(body.ids):
        db.query(Pathway).filter(Pathway.id == pid, Pathway.space_id == space.id).update({"position": i})
    db.commit()


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/pathways/{pathway_slug}/sections", response_model=list[SectionResponse])
def list_sections(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwaySection]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    return (
        db.query(PathwaySection)
        .filter(PathwaySection.pathway_id == pathway.id)
        .order_by(PathwaySection.position)
        .all()
    )


@router.post("/spaces/{slug}/pathways/{pathway_slug}/sections", response_model=SectionResponse, status_code=201)
def create_section(
    slug: str,
    pathway_slug: str,
    body: SectionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwaySection:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    max_pos = (
        db.query(PathwaySection.position)
        .filter(PathwaySection.pathway_id == pathway.id)
        .order_by(PathwaySection.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0
    section = PathwaySection(
        id=str(uuid4()),
        pathway_id=pathway.id,
        title=body.title,
        position=position,
        banner_image_url=_normalise_banner_image(body.banner_image_url),
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@router.patch("/spaces/{slug}/pathways/{pathway_slug}/sections/{section_id}", response_model=SectionResponse)
def update_section(
    slug: str,
    pathway_slug: str,
    section_id: str,
    body: SectionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwaySection:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    section = db.query(PathwaySection).filter(
        PathwaySection.id == section_id, PathwaySection.pathway_id == pathway.id
    ).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    if body.title is not None:
        section.title = body.title
    # banner_image_url: distinguish "not provided" from "explicitly cleared (null)"
    update = body.model_dump(exclude_unset=True)
    if "banner_image_url" in update:
        section.banner_image_url = _normalise_banner_image(update["banner_image_url"])
    db.commit()
    db.refresh(section)
    return section


@router.delete("/spaces/{slug}/pathways/{pathway_slug}/sections/{section_id}", status_code=204)
def delete_section(
    slug: str,
    pathway_slug: str,
    section_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    section = db.query(PathwaySection).filter(
        PathwaySection.id == section_id, PathwaySection.pathway_id == pathway.id
    ).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    # Unlink steps from this section before deleting
    db.query(PathwayStep).filter(PathwayStep.section_id == section_id).update({"section_id": None})
    db.delete(section)
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/sections/reorder", status_code=204)
def reorder_sections(
    slug: str,
    pathway_slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    for i, sid in enumerate(body.ids):
        db.query(PathwaySection).filter(
            PathwaySection.id == sid, PathwaySection.pathway_id == pathway.id
        ).update({"position": i})
    db.commit()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/pathways/{pathway_slug}/steps", response_model=list[StepResponse])
def list_steps(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStep]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    return (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )


@router.get("/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}", response_model=StepResponse)
def get_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStep:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id,
        PathwayStep.slug == step_slug,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")
    return step


@router.post("/spaces/{slug}/pathways/{pathway_slug}/steps", response_model=StepResponse, status_code=201)
def create_step(
    slug: str,
    pathway_slug: str,
    body: StepCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStep:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    sslug = body.slug or _step_slug(pathway, body.title, None, db)
    max_pos = db.query(PathwayStep.position).filter(PathwayStep.pathway_id == pathway.id).order_by(PathwayStep.position.desc()).first()
    position = (max_pos[0] + 1) if max_pos else 0

    section_position: int | None = None
    if body.section_id:
        max_sec_pos = (
            db.query(PathwayStep.section_position)
            .filter(PathwayStep.section_id == body.section_id, PathwayStep.section_position.isnot(None))
            .order_by(PathwayStep.section_position.desc())
            .first()
        )
        section_position = (max_sec_pos[0] + 1) if max_sec_pos else 0

    step = PathwayStep(
        id=str(uuid4()),
        pathway_id=pathway.id,
        slug=sslug,
        title=body.title.strip(),
        content_type=body.content_type,
        content_body=body.content_body,
        content_url=body.content_url,
        estimated_minutes=body.estimated_minutes,
        is_required=body.is_required,
        position=position,
        section_id=body.section_id,
        section_position=section_position,
        reflection_enabled=body.reflection_enabled,
        discussion_enabled=body.discussion_enabled,
        banner_image_url=_normalise_banner_image(body.banner_image_url),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    background_tasks.add_task(trigger_new_step, step.id, current_user.id)
    return step


@router.patch("/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}", response_model=StepResponse)
def update_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStep:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id, PathwayStep.slug == step_slug
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")

    # Use model_fields_set so null values in JSON explicitly clear the field
    update = body.model_dump(exclude_unset=True)
    if "title" in update and update["title"] is not None:
        step.title = update["title"].strip()
    if "content_type" in update and update["content_type"] is not None:
        step.content_type = update["content_type"]
    if "content_body" in update:
        step.content_body = update["content_body"] or None
    if "content_url" in update:
        step.content_url = update["content_url"] or None
    if "estimated_minutes" in update:
        step.estimated_minutes = update["estimated_minutes"]
    if "is_required" in update and update["is_required"] is not None:
        step.is_required = update["is_required"]
    if "reflection_enabled" in update and update["reflection_enabled"] is not None:
        step.reflection_enabled = update["reflection_enabled"]
    if "discussion_enabled" in update and update["discussion_enabled"] is not None:
        step.discussion_enabled = update["discussion_enabled"]
    if "banner_image_url" in update:
        step.banner_image_url = _normalise_banner_image(update["banner_image_url"])
    if "section_id" in update:
        new_section_id = update["section_id"]
        if new_section_id != step.section_id:
            step.section_id = new_section_id
            if new_section_id:
                # Place at end of the new section
                max_sec_pos = (
                    db.query(PathwayStep.section_position)
                    .filter(
                        PathwayStep.section_id == new_section_id,
                        PathwayStep.id != step.id,
                        PathwayStep.section_position.isnot(None),
                    )
                    .order_by(PathwayStep.section_position.desc())
                    .first()
                )
                step.section_position = (max_sec_pos[0] + 1) if max_sec_pos else 0
            else:
                step.section_position = None

    # Drip scheduling — accept the discriminator and only the columns
    # relevant to it. This keeps the schema tolerant of clients that
    # send stale fields when they switch release types.
    if "release_type" in update and update["release_type"] is not None:
        step.release_type = update["release_type"]
    if "release_offset_days" in update:
        step.release_offset_days = update["release_offset_days"]
    if "release_at" in update:
        v = update["release_at"]
        if v is not None and getattr(v, "tzinfo", None) is not None:
            v = v.astimezone(tz=None).replace(tzinfo=None)
        step.release_at = v
    if "release_timezone" in update:
        step.release_timezone = update["release_timezone"] or None
    if "release_previous_state" in update and update["release_previous_state"] is not None:
        step.release_previous_state = update["release_previous_state"]

    db.commit()
    db.refresh(step)
    return step


@router.delete("/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}", status_code=204)
def delete_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id, PathwayStep.slug == step_slug
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")
    db.delete(step)
    db.commit()


# ---------------------------------------------------------------------------
# Manual step releases — the "waiting members" caretaker workflow
# ---------------------------------------------------------------------------


class WaitingMember(BaseModel):
    user_id: str
    display_name: str
    email: str | None = None


class ManualStepEntry(BaseModel):
    step_id: str
    step_slug: str
    step_title: str
    pathway_slug: str
    pathway_title: str
    waiting: list[WaitingMember]


@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/manual-releases",
    response_model=list[ManualStepEntry],
)
def list_manual_release_state(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[ManualStepEntry]:
    """List manual-release steps in this pathway and, for each, the
    enrolled members who have not yet been released. The list stays
    small on purpose — no enrolment metrics, no time-since-enrolled
    scoreboard, just the caretaker's queue of decisions."""
    from app.models.user import User as UserModel
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    steps = (
        db.query(PathwayStep)
        .filter(
            PathwayStep.pathway_id == pathway.id,
            PathwayStep.release_type == "manual",
        )
        .order_by(PathwayStep.position)
        .all()
    )
    if not steps:
        return []

    enrolled_user_ids = {
        row.user_id
        for row in db.query(Enrollment.user_id)
        .filter(Enrollment.pathway_id == pathway.id, Enrollment.status == "active")
        .all()
    }
    if not enrolled_user_ids:
        return [
            ManualStepEntry(
                step_id=s.id, step_slug=s.slug, step_title=s.title,
                pathway_slug=pathway.slug, pathway_title=pathway.title,
                waiting=[],
            )
            for s in steps
        ]

    users_by_id = {
        u.id: u
        for u in db.query(UserModel).filter(UserModel.id.in_(enrolled_user_ids)).all()
    }

    released_by_step: dict[str, set[str]] = {s.id: set() for s in steps}
    for row in db.query(
        PathwayStepManualRelease.step_id, PathwayStepManualRelease.user_id,
    ).filter(PathwayStepManualRelease.step_id.in_({s.id for s in steps})).all():
        released_by_step.setdefault(row.step_id, set()).add(row.user_id)

    entries: list[ManualStepEntry] = []
    for s in steps:
        waiting_ids = enrolled_user_ids - released_by_step[s.id]
        waiting = sorted(
            (
                WaitingMember(
                    user_id=uid,
                    display_name=users_by_id[uid].name or users_by_id[uid].email.split("@")[0],
                    email=users_by_id[uid].email,
                )
                for uid in waiting_ids if uid in users_by_id
            ),
            key=lambda m: (m.display_name or "").lower(),
        )
        entries.append(ManualStepEntry(
            step_id=s.id, step_slug=s.slug, step_title=s.title,
            pathway_slug=pathway.slug, pathway_title=pathway.title,
            waiting=waiting,
        ))
    return entries


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/release-for/{user_id}",
    status_code=204,
)
def release_step_for_member(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Idempotent — releasing a step for the same member twice is a
    no-op (the unique constraint absorbs the duplicate)."""
    import uuid as _uuid
    from sqlalchemy.exc import IntegrityError as _IntegrityError

    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = db.query(PathwayStep).filter(
        PathwayStep.pathway_id == pathway.id, PathwayStep.slug == step_slug
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found.")

    row = PathwayStepManualRelease(
        id=str(_uuid.uuid4()),
        step_id=step.id,
        user_id=user_id,
        released_by=current_user.id,
    )
    db.add(row)
    try:
        db.commit()
    except _IntegrityError:
        db.rollback()  # already released → treat as success


@router.post("/spaces/{slug}/pathways/{pathway_slug}/steps/reorder", status_code=204)
def reorder_steps(
    slug: str,
    pathway_slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Reorder all steps in a flat (no-sections) pathway by global position."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    for i, sid in enumerate(body.ids):
        db.query(PathwayStep).filter(
            PathwayStep.id == sid, PathwayStep.pathway_id == pathway.id
        ).update({"position": i})
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/steps/unsectioned/reorder", status_code=204)
def reorder_unsectioned_steps(
    slug: str,
    pathway_slug: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Reorder unsectioned steps by global position."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    for i, sid in enumerate(body.ids):
        db.query(PathwayStep).filter(
            PathwayStep.id == sid,
            PathwayStep.pathway_id == pathway.id,
            PathwayStep.section_id.is_(None),
        ).update({"position": i})
    db.commit()


@router.post("/spaces/{slug}/pathways/{pathway_slug}/sections/{section_id}/steps/reorder", status_code=204)
def reorder_section_steps(
    slug: str,
    pathway_slug: str,
    section_id: str,
    body: ReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Reorder steps within a section by section_position."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    section = db.query(PathwaySection).filter(
        PathwaySection.id == section_id, PathwaySection.pathway_id == pathway.id
    ).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found.")
    for i, sid in enumerate(body.ids):
        db.query(PathwayStep).filter(
            PathwayStep.id == sid,
            PathwayStep.section_id == section_id,
        ).update({"section_position": i})
    db.commit()


# ---------------------------------------------------------------------------
# Step Resources
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources",
    response_model=list[StepResourceResponse],
)
def list_step_resources(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[StepResource]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    return (
        db.query(StepResource)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position)
        .all()
    )


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources",
    response_model=StepResourceResponse,
    status_code=201,
)
def create_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepResourceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> StepResource:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    max_pos = (
        db.query(StepResource.position)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    resource = StepResource(
        id=str(uuid4()),
        step_id=step.id,
        title=body.title,
        description=body.description,
        resource_type=body.resource_type,
        url=body.url,
        file_name=None,
        file_size=None,
        mime_type=None,
        position=position,
        is_downloadable=False,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources/upload",
    response_model=StepResourceResponse,
    status_code=201,
)
def upload_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    title: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> StepResource:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    try:
        data = file.file.read()
        rel_path, resource_type, size = save_file(
            data=data,
            original_name=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            subdir=f"steps/{step.id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    max_pos = (
        db.query(StepResource.position)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    resource = StepResource(
        id=str(uuid4()),
        step_id=step.id,
        title=title.strip(),
        description=description.strip() if description else None,
        resource_type=resource_type,
        url=rel_path,
        file_name=file.filename,
        file_size=size,
        mime_type=file.content_type,
        position=position,
        is_downloadable=True,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources/{resource_id}",
    response_model=StepResourceResponse,
)
def update_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    resource_id: str,
    body: StepResourceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> StepResource:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    resource = _get_resource(step, resource_id, db)

    update = body.model_dump(exclude_unset=True)
    if "title" in update and update["title"] is not None:
        resource.title = update["title"].strip()
    if "description" in update:
        resource.description = (update["description"] or "").strip() or None
    if "url" in update and update["url"] is not None and resource.file_name is None:
        # Only allow URL edits on link-type resources (not uploaded files)
        resource.url = update["url"].strip() or None

    db.commit()
    db.refresh(resource)
    return resource


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources/{resource_id}",
    status_code=204,
)
def delete_step_resource(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    resource_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    resource = _get_resource(step, resource_id, db)

    # Clean up uploaded file if present
    if resource.url and resource.file_name:
        delete_file(resource.url)

    db.delete(resource)
    db.commit()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/events", response_model=list[EventResponse])
def list_events(
    slug: str,
    scope: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """List Gatherings for a Collective (caretaker view).

    Optional `scope` query param mirrors the member endpoint:
      - 'upcoming' — current + live-in-progress, active only
      - 'archive'  — past (end < now), any status
    Omitting `scope` preserves the historical behaviour of returning
    every Gathering newest-first — used by pages that still show a
    combined list.
    """
    from datetime import datetime as _dt
    space = _get_managed_space(slug, current_user, db)

    query = db.query(Event).filter(Event.space_id == space.id)

    if scope in ("upcoming", "archive"):
        from sqlalchemy import or_
        end_marker = func.coalesce(
            Event.ends_at,
            Event.starts_at + text("INTERVAL '1 hour'"),
        )
        now = _dt.utcnow()
        if scope == "upcoming":
            query = query.filter(Event.status == "active", end_marker > now)
            query = query.order_by(Event.starts_at.asc())
        else:  # archive — past by end-time OR cancelled at any time
            query = query.filter(or_(end_marker <= now, Event.status == "cancelled"))
            query = query.order_by(Event.starts_at.desc())
    else:
        query = query.order_by(Event.starts_at.desc())

    events = query.all()
    event_ids = [e.id for e in events]
    booked_counts: dict[str, int] = {}
    attended_counts: dict[str, int] = {}
    no_show_counts: dict[str, int] = {}
    if event_ids:
        booked_counts = dict(
            db.query(EventBooking.event_id, func.count(EventBooking.id))
            .filter(EventBooking.event_id.in_(event_ids), EventBooking.status == "confirmed")
            .group_by(EventBooking.event_id)
            .all()
        )
        attended_counts = dict(
            db.query(EventBooking.event_id, func.count(EventBooking.id))
            .filter(EventBooking.event_id.in_(event_ids), EventBooking.attendance_status == "attended")
            .group_by(EventBooking.event_id)
            .all()
        )
        no_show_counts = dict(
            db.query(EventBooking.event_id, func.count(EventBooking.id))
            .filter(EventBooking.event_id.in_(event_ids), EventBooking.attendance_status == "no_show")
            .group_by(EventBooking.event_id)
            .all()
        )
    # Stage 3: bulk ticket-sales aggregates for paid Gatherings (no-op
    # cost when no paid events are in the list).
    from app.services.ticket_summary import bulk_ticket_summaries
    summaries = bulk_ticket_summaries(db, [e for e in events if e.booking_access_type == "paid_separately"])
    return [
        _event_to_dict(
            e,
            booked_counts.get(e.id, 0),
            attended_counts.get(e.id, 0),
            no_show_counts.get(e.id, 0),
            ticket_sales=(summaries[e.id].as_dict() if e.id in summaries else None),
        )
        for e in events
    ]


@router.get("/spaces/{slug}/events/{event_id}", response_model=EventResponse)
def get_event(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    booked_count = (
        db.query(func.count(EventBooking.id))
        .filter(EventBooking.event_id == event.id, EventBooking.status == "confirmed")
        .scalar()
    ) or 0
    ticket_sales_dict = None
    if event.booking_access_type == "paid_separately":
        from app.services.ticket_summary import ticket_summary_for
        ticket_sales_dict = ticket_summary_for(db, event).as_dict()
    return _event_to_dict(event, booked_count, ticket_sales=ticket_sales_dict)


def _event_to_dict(
    event: Event,
    booked_count: int = 0,
    attended_count: int = 0,
    no_show_count: int = 0,
    *,
    ticket_sales: dict | None = None,
) -> dict:
    access_type = normalise_access_type(getattr(event, 'booking_access_type', None))
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "location_type": event.location_type.value if hasattr(event.location_type, "value") else str(event.location_type),
        "location_url": event.location_url,
        "recording_url": event.recording_url,
        "is_published": event.is_published,
        "is_public": event.is_public,
        "requires_booking": event.requires_booking,
        "capacity": event.capacity,
        "booking_closes_at": event.booking_closes_at,
        "booking_note": event.booking_note,
        "booked_count": booked_count,
        "attended_count": attended_count,
        "no_show_count": no_show_count,
        "thumbnail_url": event.thumbnail_url,
        "status": event.status if event.status else "active",
        "recurrence_series_id": event.recurrence_series_id,
        "recurrence_label": event.recurrence_label,
        "recurrence_index": event.recurrence_index,
        "recurrence_total": event.recurrence_total,
        "series_id": getattr(event, "series_id", None),
        "created_at": event.created_at,
        # Gatherings 2.0 vocabulary (see services/gathering_types.py).
        # `booking_access_type` is normalised on the way out so legacy
        # rows still speak the current vocabulary.
        "gathering_type": getattr(event, 'gathering_type', 'other') or 'other',
        "attendance_format": getattr(event, 'attendance_format', 'online') or 'online',
        "venue_name": getattr(event, 'venue_name', None),
        "venue_address": getattr(event, 'venue_address', None),
        "access_instructions": getattr(event, 'access_instructions', None),
        "booking_access_type": access_type,
        "booking_required_pathway_id": getattr(event, 'booking_required_pathway_id', None),
        # Stage 3: standalone paid Gathering fields. Both are nullable on
        # non-paid events; the CHECK constraint guarantees published-paid
        # rows are never null.
        "ticket_price_cents": getattr(event, 'ticket_price_cents', None),
        "ticket_currency": getattr(event, 'ticket_currency', None),
        # Aggregate ticket-sales snapshot; only populated for paid events.
        "ticket_sales": ticket_sales if access_type == "paid_separately" else None,
    }


def _validate_ticket_config_or_400(
    access_type: str,
    is_published: bool,
    price_cents: int | None,
    currency: str | None,
) -> tuple[int | None, str | None]:
    """
    Validate ticket_price/currency according to Stage 3 rules:
      - Non-paid access types: force both fields to NULL (defensive —
        prevents stale ticket data leaking onto a free event).
      - Paid draft: allow NULL price/currency (creator saves WIP).
      - Paid + published: require price > 0 and supported currency.

    Raises HTTPException(400) with per-field detail on failure. Returns
    the (possibly cleaned) values to store.
    """
    if access_type != "paid_separately":
        return None, None
    if not is_published:
        # Draft-safe: normalise but don't require values yet.
        if currency is not None:
            try:
                from app.services.ticket_pricing import normalise_currency
                currency = normalise_currency(currency)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail={
                    "code": "invalid_ticket_currency",
                    "field": "ticket_currency",
                    "message": str(exc),
                })
        return price_cents, currency
    # Publish path: both required and must validate.
    from app.services.ticket_pricing import (
        TicketPricingError,
        validate_paid_gathering_price,
    )
    try:
        price, cur = validate_paid_gathering_price(price_cents, currency)
    except TicketPricingError as exc:
        # Attach a field name for the frontend to surface inline
        field = "ticket_price_cents" if price_cents in (None, 0) else "ticket_currency"
        raise HTTPException(status_code=400, detail={
            "code": "invalid_ticket_config",
            "field": field,
            "message": str(exc),
        })
    return price, cur


@router.post("/spaces/{slug}/events", response_model=EventResponse, status_code=201)
def create_event(
    slug: str,
    body: EventCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    _ensure_creator_write_allowed(current_user, space, db)
    ticket_price, ticket_currency = _validate_ticket_config_or_400(
        body.booking_access_type, body.is_published,
        body.ticket_price_cents, body.ticket_currency,
    )
    # Validate optional Series membership — must belong to the same
    # Space. Rejects an id that references someone else's series or
    # a mistyped id early rather than persisting a dangling FK.
    resolved_series_id = _validate_series_id_for_space(body.series_id, space, db)
    # Series-pass invariant: an event with access_type='included_with_series'
    # must belong to a Series. Enforced here so the DB never carries an
    # unresolvable Series-pass gate.
    _enforce_series_pass_invariant(body.booking_access_type, resolved_series_id)

    event = Event(
        id=str(uuid4()),
        space_id=space.id,
        created_by_id=current_user.id,
        title=body.title.strip(),
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        location_type=body.location_type,
        location_url=body.location_url,
        recording_url=body.recording_url,
        is_published=body.is_published,
        is_public=body.is_public,
        requires_booking=body.requires_booking,
        capacity=body.capacity,
        booking_closes_at=body.booking_closes_at,
        booking_note=body.booking_note,
        thumbnail_url=body.thumbnail_url,
        gathering_type=body.gathering_type,
        attendance_format=body.attendance_format,
        venue_name=body.venue_name,
        venue_address=body.venue_address,
        access_instructions=body.access_instructions,
        booking_access_type=body.booking_access_type,
        booking_required_pathway_id=body.booking_required_pathway_id,
        ticket_price_cents=ticket_price,
        ticket_currency=ticket_currency,
        series_id=resolved_series_id,
    )
    db.add(event)
    db.flush()

    if body.create_channel:
        from app.community.channels import ensure_gathering_channel
        ensure_gathering_channel(
            space_id=space.id,
            gathering_id=event.id,
            gathering_title=event.title,
            db=db,
            created_by=current_user.id,
        )

    db.commit()
    db.refresh(event)
    return _event_to_dict(event, 0)


@router.post("/spaces/{slug}/events/bulk", response_model=BulkEventCreateResponse, status_code=201)
def bulk_create_events(
    slug: str,
    body: EventCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> BulkEventCreateResponse:
    """Create a recurring series of individual event records."""
    from datetime import timedelta

    if not body.recurrence:
        raise HTTPException(status_code=400, detail="recurrence is required for bulk creation.")

    space = _get_managed_space(slug, current_user, db)
    rec = body.recurrence
    # Recurrence tag — unique per bulk-create, marks "these rows
    # were generated together". Distinct from the semantic
    # ``series_id`` (below) which links to a first-class Series row.
    recurrence_tag = str(uuid4())
    series_label = rec.series_label
    days_set = set(rec.days_of_week)
    resolved_series_id = _validate_series_id_for_space(body.series_id, space, db)
    # Same invariant as create_event — a bulk-created batch cannot
    # land as ``included_with_series`` without a Series to check
    # passes against. Fail loudly before any rows are generated.
    _enforce_series_pass_invariant(body.booking_access_type, resolved_series_id)

    duration = None
    if body.ends_at:
        duration = body.ends_at - body.starts_at

    start_date = body.starts_at.date()
    start_time = body.starts_at.time()

    dates: list[tuple] = []
    candidate = start_date
    max_search = 365 * 3

    for _ in range(max_search):
        if candidate.weekday() in days_set:
            from datetime import datetime as _dt
            new_start = _dt(candidate.year, candidate.month, candidate.day,
                            start_time.hour, start_time.minute, start_time.second)
            new_end = new_start + duration if duration else None

            if rec.repeat_until and new_start.date() > rec.repeat_until.date():
                break
            dates.append((new_start, new_end))
            if rec.end_after_n and len(dates) >= rec.end_after_n:
                break

        candidate += timedelta(days=1)

    if not dates:
        raise HTTPException(status_code=400, detail="No valid dates generated from recurrence settings.")

    total = len(dates)
    for idx, (new_start, new_end) in enumerate(dates, start=1):
        event = Event(
            id=str(uuid4()),
            space_id=space.id,
            created_by_id=current_user.id,
            title=body.title.strip(),
            description=body.description,
            starts_at=new_start,
            ends_at=new_end,
            location_type=body.location_type,
            location_url=body.location_url,
            recording_url=body.recording_url,
            is_published=body.is_published,
            is_public=body.is_public,
            requires_booking=body.requires_booking,
            capacity=body.capacity,
            booking_closes_at=body.booking_closes_at,
            booking_note=body.booking_note,
            thumbnail_url=body.thumbnail_url,
            gathering_type=body.gathering_type,
            attendance_format=body.attendance_format,
            venue_name=body.venue_name,
            venue_address=body.venue_address,
            access_instructions=body.access_instructions,
            booking_access_type=body.booking_access_type,
            booking_required_pathway_id=body.booking_required_pathway_id,
            recurrence_series_id=recurrence_tag,
            recurrence_label=series_label,
            recurrence_index=idx,
            recurrence_total=total,
            series_id=resolved_series_id,
        )
        db.add(event)

    db.commit()
    # Both names on the response point at the same value — the
    # low-level recurrence UUID stamped on every generated row.
    # ``recurrence_series_id`` is the canonical name; ``series_id``
    # is the deprecated legacy alias kept for wire compat. See
    # BulkEventCreateResponse docstring for the deprecation plan.
    return BulkEventCreateResponse(
        created_count=total,
        recurrence_series_id=recurrence_tag,
        series_id=recurrence_tag,
    )


@router.patch("/spaces/{slug}/events/{event_id}", response_model=EventResponse)
def update_event(
    slug: str,
    event_id: str,
    body: EventUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    _ensure_creator_write_allowed(current_user, space, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    # -----------------------------------------------------------------
    # Stage 3: access-type edit lock.
    #
    # If a paid Gathering has any completed ticket sale, `booking_access_type`
    # cannot be changed away from 'paid_separately' — existing ticket
    # holders must keep their access. Similarly, an active payment hold
    # blocks the change temporarily so we don't invalidate an in-flight
    # Stripe Checkout Session.
    # -----------------------------------------------------------------
    new_access = body.booking_access_type
    if (
        new_access is not None
        and new_access != event.booking_access_type
        and event.booking_access_type == "paid_separately"
    ):
        from app.services.ticket_summary import ticket_summary_for
        summary = ticket_summary_for(db, event)
        if summary.has_completed_ticket_sales:
            raise HTTPException(status_code=409, detail={
                "code": "access_type_locked_by_sales",
                "field": "booking_access_type",
                "message": (
                    "The access type can’t be changed because tickets have "
                    "already been sold. Existing ticket holders must keep "
                    "their access."
                ),
            })
        if summary.has_active_payment_holds:
            raise HTTPException(status_code=409, detail={
                "code": "access_type_locked_by_holds",
                "field": "booking_access_type",
                "message": (
                    "The access type can’t be changed while a purchase is "
                    "in progress. Try again after any pending checkouts "
                    "have expired or been cancelled."
                ),
            })

    for field in ("title", "description", "starts_at", "ends_at", "location_type", "location_url",
                  "recording_url", "is_published", "is_public", "requires_booking", "capacity",
                  "booking_closes_at", "booking_note", "thumbnail_url",
                  "gathering_type", "attendance_format",
                  "venue_name", "venue_address", "access_instructions",
                  "booking_access_type", "booking_required_pathway_id",
                  "ticket_price_cents", "ticket_currency"):
        val = getattr(body, field)
        if val is not None:
            setattr(event, field, val)

    # ``series_id`` uses ``model_fields_set`` so an explicit ``null``
    # detaches the Event from its Series, while omission leaves the
    # attachment untouched. Any non-null value is validated as a
    # Series in this Space before assignment.
    if "series_id" in body.model_fields_set:
        if body.series_id is None:
            event.series_id = None
        else:
            event.series_id = _validate_series_id_for_space(body.series_id, space, db)

    # Series-pass invariant on the RESULTING state. Both fields may
    # have moved in this PATCH — checking the composed result lets a
    # caller change the access type away from Series pass AND clear
    # the series id in the same call. It rejects any combination
    # that would leave the row with an unresolvable Series-pass gate.
    _enforce_series_pass_invariant(event.booking_access_type, event.series_id)

    # After applying updates, validate the ticket configuration against
    # the RESULTING state (post-update). This is what the CHECK constraint
    # will do anyway; catching it here gives a clean field-scoped error.
    ticket_price, ticket_currency = _validate_ticket_config_or_400(
        event.booking_access_type,
        event.is_published,
        event.ticket_price_cents,
        event.ticket_currency,
    )
    event.ticket_price_cents = ticket_price
    event.ticket_currency = ticket_currency

    db.commit()
    db.refresh(event)
    booked_count = (
        db.query(func.count(EventBooking.id))
        .filter(EventBooking.event_id == event.id, EventBooking.status == "confirmed")
        .scalar()
    ) or 0
    ticket_sales_dict = None
    if event.booking_access_type == "paid_separately":
        from app.services.ticket_summary import ticket_summary_for
        ticket_sales_dict = ticket_summary_for(db, event).as_dict()
    return _event_to_dict(event, booked_count, ticket_sales=ticket_sales_dict)


@router.delete("/spaces/{slug}/events/{event_id}", status_code=204)
def delete_event(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    db.delete(event)
    db.commit()


@router.get("/spaces/{slug}/events/{event_id}/bookings", response_model=list[BookedMemberItem])
def list_event_bookings(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    bookings = (
        db.query(EventBooking)
        .filter(EventBooking.event_id == event.id)
        .order_by(EventBooking.booked_at.asc())
        .all()
    )
    user_ids = [b.user_id for b in bookings]
    users_by_id: dict[str, User] = {}
    if user_ids:
        users_by_id = {
            u.id: u
            for u in db.query(User).filter(User.id.in_(user_ids)).all()
        }
    # Stage 3: bulk resolve payment/label metadata so we get one grouped
    # PaymentTransaction lookup regardless of attendee count.
    from app.services.ticket_summary import bulk_attendee_payment_info
    payment_info = bulk_attendee_payment_info(db, list(bookings))
    return [
        {
            "booking_id": b.id,
            "user_id": b.user_id,
            "name": users_by_id[b.user_id].name if b.user_id in users_by_id else None,
            "email": users_by_id[b.user_id].email if b.user_id in users_by_id else "",
            "booked_at": b.booked_at,
            "status": b.status.value if hasattr(b.status, "value") else b.status,
            "source": b.source,
            "note": b.note,
            "attendance_status": b.attendance_status,
            "attendance_marked_at": b.attendance_marked_at,
            **payment_info.get(b.id, {
                "access_source": "Complimentary",
                "amount_paid_cents": None,
                "currency": None,
                "purchased_at": None,
            }),
        }
        for b in bookings
    ]


@router.post("/spaces/{slug}/events/{event_id}/thumbnail", response_model=EventResponse)
async def upload_event_thumbnail(
    slug: str,
    event_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Upload or replace the thumbnail image for a single event."""
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    filename = file.filename or "thumbnail.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(status_code=400, detail="Only JPG, PNG, and WebP images are allowed.")
    data = await file.read()
    if event.thumbnail_url:
        old_rel = event.thumbnail_url.removeprefix("/api/uploads/")
        delete_file(old_rel)
    rel_path, _, _ = save_file(data, filename, file.content_type or "image/jpeg", "event-thumbnails")
    event.thumbnail_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(event)
    booked_count = (
        db.query(func.count(EventBooking.id))
        .filter(EventBooking.event_id == event.id, EventBooking.status == "confirmed")
        .scalar()
    ) or 0
    return _event_to_dict(event, booked_count)


@router.delete("/spaces/{slug}/events/{event_id}/thumbnail", status_code=204)
def remove_event_thumbnail(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Remove the thumbnail image from an event."""
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    if event.thumbnail_url:
        old_rel = event.thumbnail_url.removeprefix("/api/uploads/")
        delete_file(old_rel)
    event.thumbnail_url = None
    db.commit()


@router.post("/spaces/{slug}/events/{event_id}/cancel", response_model=EventResponse)
def cancel_event(
    slug: str,
    event_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Cancel a single event occurrence. Does not affect other events in the series.
    Notifies every confirmed attendee via the notification service.
    TODO: Add cancel entire series endpoint later.
    """
    from app.models.access_pass import AccessPass as _AccessPass
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    if event.status == "cancelled":
        raise HTTPException(status_code=400, detail="Event is already cancelled.")

    # Restore credits for all confirmed bookings — creator cancellation always restores
    confirmed_bookings = (
        db.query(EventBooking)
        .filter(EventBooking.event_id == event.id, EventBooking.status == BookingStatus.confirmed)
        .all()
    )
    had_confirmed_bookings = len(confirmed_bookings) > 0
    now_ts = datetime.utcnow()
    for bk in confirmed_bookings:
        bk.status = BookingStatus.cancelled
        bk.cancelled_at = now_ts
        if bk.access_pass_id and bk.credits_used > 0:
            ap = db.query(_AccessPass).filter(_AccessPass.id == bk.access_pass_id).first()
            if ap:
                ap.used_credits = max(0, ap.used_credits - bk.credits_used)

    event.status = "cancelled"
    db.commit()
    db.refresh(event)

    # Fire attendee-cancellation notifications AFTER the commit so
    # background workers see the flipped statuses. The notifier reads
    # `EventBooking.status='confirmed'` but we intentionally pass the
    # captured recipient list via a nested trigger that re-queries by
    # event_id — those rows are now 'cancelled', so we build the
    # recipient list here from the memoised confirmed bookings.
    if had_confirmed_bookings:
        recipient_ids = [bk.user_id for bk in confirmed_bookings]
        background_tasks.add_task(
            _notify_gathering_cancelled_recipients,
            event_id=event.id,
            recipient_ids=recipient_ids,
            cancelled_by_id=current_user.id,
        )

    booked_count = 0  # all bookings are now cancelled
    return _event_to_dict(event, booked_count)


def _notify_gathering_cancelled_recipients(
    event_id: str, recipient_ids: list[str], cancelled_by_id: str,
) -> None:
    """Background helper — creates one notification per recipient.
    Kept small so the create_notification interaction stays predictable
    and per-recipient failures don't stall the batch.
    """
    from app.core.database import SessionLocal
    from app.services.notification_service import create_notification
    db = SessionLocal()
    try:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            return
        title = "Gathering cancelled"
        message = f"\"{event.title}\" has been cancelled by the caretaker."
        for uid in recipient_ids:
            if uid == cancelled_by_id:
                continue
            try:
                create_notification(
                    db=db,
                    recipient_id=uid,
                    notification_type="gathering_cancelled",
                    title=title,
                    message=message,
                    url=None,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "gathering_cancelled notification failed for user %s", uid
                )
    finally:
        db.close()


@router.post("/spaces/{slug}/events/{event_id}/bookings/manual", response_model=BookedMemberItem)
def manual_book_member(
    slug: str,
    event_id: str,
    body: ManualBookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Manually add a collective member to an event booking.
    TODO: Add manual booking across remaining series sessions later.
    TODO: Send email notification to booked member later.
    """
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    if event.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot book a cancelled event.")

    now = datetime.utcnow()

    # Target user must be an active space member
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == body.user_id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=400,
            detail="User is not an active member of this collective. Invite them as a member first.",
        )

    target_user = db.query(User).filter(User.id == body.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Check capacity
    if event.capacity is not None:
        confirmed = (
            db.query(func.count(EventBooking.id))
            .filter(EventBooking.event_id == event.id, EventBooking.status == "confirmed")
            .scalar()
        ) or 0
        if confirmed >= event.capacity:
            raise HTTPException(status_code=400, detail="Event is at full capacity.")

    # Resolve pass to charge (if use_pass mode)
    access_pass_to_charge: AccessPass | None = None
    if body.use_pass:
        if body.access_pass_id:
            # Specific pass requested — verify it belongs to this member + space
            ap = db.query(AccessPass).filter(
                AccessPass.id == body.access_pass_id,
                AccessPass.user_id == body.user_id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
            ).first()
            if not ap:
                raise HTTPException(status_code=404, detail="Specified pass not found or not active for this member.")
        else:
            # Auto-detect: most recent active pass for this space
            ap = db.query(AccessPass).filter(
                AccessPass.user_id == body.user_id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
            ).order_by(AccessPass.created_at.desc()).first()
            if not ap:
                raise HTTPException(status_code=409, detail="This member has no active pass for this space.")

        # Check total credits
        if ap.total_credits is not None and ap.used_credits >= ap.total_credits:
            raise HTTPException(status_code=409, detail="This member has no remaining sessions on their pass.")

        # Check weekly cap (uses event's starts_at week, same logic as member book_event)
        if ap.credits_per_week is not None:
            event_weekday = event.starts_at.weekday()  # 0=Mon … 6=Sun
            event_week_start = (event.starts_at - timedelta(days=event_weekday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            event_week_end = event_week_start + timedelta(days=7)
            weekly_used = (
                db.query(func.count(EventBooking.id))
                .join(Event, EventBooking.event_id == Event.id)
                .filter(
                    EventBooking.access_pass_id == ap.id,
                    EventBooking.status == BookingStatus.confirmed,
                    Event.starts_at >= event_week_start,
                    Event.starts_at < event_week_end,
                )
                .scalar()
            ) or 0
            if weekly_used >= ap.credits_per_week:
                raise HTTPException(
                    status_code=409,
                    detail=f"This member has reached their weekly limit of {ap.credits_per_week} session(s) for this week.",
                )

        access_pass_to_charge = ap

    # Reactivate cancelled booking or create new
    existing = (
        db.query(EventBooking)
        .filter(EventBooking.event_id == event.id, EventBooking.user_id == body.user_id)
        .first()
    )
    if existing:
        if existing.status == "confirmed":
            raise HTTPException(status_code=400, detail="This member is already booked into this event.")
        existing.status = BookingStatus.confirmed
        existing.booked_at = now
        existing.cancelled_at = None
        existing.source = "creator_pass" if body.use_pass else "creator_manual"
        existing.note = body.note
        existing.access_pass_id = access_pass_to_charge.id if access_pass_to_charge else None
        existing.credits_used = 1 if access_pass_to_charge else 0
        if access_pass_to_charge:
            access_pass_to_charge.used_credits += 1
        db.commit()
        db.refresh(existing)
        booking = existing
    else:
        booking = EventBooking(
            id=str(uuid4()),
            event_id=event.id,
            user_id=body.user_id,
            status=BookingStatus.confirmed,
            booked_at=now,
            source="creator_pass" if body.use_pass else "creator_manual",
            note=body.note,
            access_pass_id=access_pass_to_charge.id if access_pass_to_charge else None,
            credits_used=1 if access_pass_to_charge else 0,
        )
        db.add(booking)
        if access_pass_to_charge:
            access_pass_to_charge.used_credits += 1
        db.commit()
        db.refresh(booking)

    return {
        "booking_id": booking.id,
        "user_id": body.user_id,
        "name": target_user.name,
        "email": target_user.email,
        "booked_at": booking.booked_at,
        "status": "confirmed",
        "source": booking.source,
        "note": body.note,
        "attendance_status": booking.attendance_status,
        "attendance_marked_at": booking.attendance_marked_at,
        "credits_used": booking.credits_used,
        "access_pass_id": booking.access_pass_id,
    }


@router.post("/spaces/{slug}/events/{event_id}/bookings/{booking_id}/cancel", status_code=200)
def cancel_member_booking(
    slug: str,
    event_id: str,
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Creator cancels a member's booking. Record is retained for history.
    TODO: Send cancellation notification to member later.
    """
    from datetime import datetime as _dt

    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    booking = db.query(EventBooking).filter(
        EventBooking.id == booking_id,
        EventBooking.event_id == event.id,
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Booking is already cancelled.")
    now = _dt.utcnow()
    booking.status = BookingStatus.cancelled
    booking.cancelled_at = now

    # Creator cancellation always restores credits — no 24h cutoff applies
    if booking.access_pass_id and booking.credits_used > 0:
        from app.models.access_pass import AccessPass as _AP2
        ap = db.query(_AP2).filter(_AP2.id == booking.access_pass_id).first()
        if ap:
            ap.used_credits = max(0, ap.used_credits - booking.credits_used)

    db.commit()
    return {"booking_id": booking_id, "status": "cancelled"}


@router.patch("/spaces/{slug}/events/{event_id}/bookings/{booking_id}/attendance", status_code=200)
def update_booking_attendance(
    slug: str,
    event_id: str,
    booking_id: str,
    body: AttendanceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Mark a booking as attended, no_show, or reset to pending."""
    from datetime import datetime as _dt
    valid = {"attended", "no_show", "pending"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(sorted(valid))}")
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    booking = db.query(EventBooking).filter(
        EventBooking.id == booking_id,
        EventBooking.event_id == event.id,
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    bstatus = booking.status.value if hasattr(booking.status, "value") else str(booking.status)
    if bstatus == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot mark attendance for a cancelled booking.")
    booking.attendance_status = body.status if body.status != "pending" else None
    booking.attendance_marked_at = _dt.utcnow()
    booking.attendance_marked_by = current_user.id
    db.commit()
    return {"booking_id": booking_id, "attendance_status": booking.attendance_status}


# ---------------------------------------------------------------------------
# Creator member management
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/members", response_model=list[CreatorMemberItem])
def list_creator_members(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[CreatorMemberItem]:
    """Return active space members with email (creator-only)."""
    from app.models.platform import CreatorProfile
    from sqlalchemy import and_

    space = _get_managed_space(slug, current_user, db)
    rows = (
        db.query(SpaceMembership, User, CreatorProfile)
        .join(User, User.id == SpaceMembership.user_id)
        .outerjoin(
            CreatorProfile,
            and_(CreatorProfile.user_id == User.id, CreatorProfile.is_public.is_(True)),
        )
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.status == "active")
        .all()
    )
    result = []
    for membership, user, cp in rows:
        role = membership.role.value if hasattr(membership.role, "value") else str(membership.role)
        display_name = (cp.display_name if cp and cp.display_name else None) or user.name or user.email.split("@")[0]
        result.append(CreatorMemberItem(
            id=user.id,
            display_name=display_name,
            email=user.email,
            space_role=role,
            joined_at=membership.joined_at,
            is_creator=cp is not None,
        ))
    result.sort(key=lambda m: {"creator": 0, "moderator": 1, "learner": 2}.get(m.space_role, 9))
    return result


@router.delete("/spaces/{slug}/members/{user_id}", status_code=200)
def remove_member(
    slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Remove a member from a collective.

    Sets their SpaceMembership to 'removed', revokes manual pathway entitlements,
    and cancels any active access passes in this space.
    Does NOT touch the user account, posts, comments, or memberships in other spaces.
    """
    space = _get_managed_space(slug, current_user, db)

    # Cannot remove yourself
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself from a collective.")

    # Cannot remove the space owner
    if hasattr(space, "creator_id") and space.creator_id and user_id == space.creator_id:
        raise HTTPException(status_code=400, detail="Cannot remove the collective owner.")

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this collective.")

    if membership.status == SpaceMembershipStatus.removed:
        raise HTTPException(status_code=400, detail="Member has already been removed.")

    now = datetime.utcnow()

    # Soft-delete the membership
    membership.status = SpaceMembershipStatus.removed

    # Revoke all active pathway entitlements in this space
    active_entitlements = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == user_id,
            PathwayEntitlement.space_id == space.id,
            PathwayEntitlement.status == EntitlementStatus.active,
        )
        .all()
    )
    for ent in active_entitlements:
        ent.status = EntitlementStatus.revoked
        ent.revoked_by_user_id = current_user.id
        ent.revoked_at = now
        ent.notes = (ent.notes or "") + f" [Revoked on member removal by {current_user.email}]"

    # Cancel active/pending access passes in this space
    active_passes = (
        db.query(AccessPass)
        .filter(
            AccessPass.user_id == user_id,
            AccessPass.space_id == space.id,
            AccessPass.status.in_([AccessPassStatus.active, AccessPassStatus.pending]),
        )
        .all()
    )
    for ap in active_passes:
        ap.status = AccessPassStatus.cancelled
        ap.revoked_by_user_id = current_user.id
        ap.revoked_at = now

    # Cancel future confirmed event bookings in this space.
    # Past bookings are kept as historical record.
    future_bookings = (
        db.query(EventBooking)
        .join(Event, Event.id == EventBooking.event_id)
        .filter(
            EventBooking.user_id == user_id,
            EventBooking.status == BookingStatus.confirmed,
            Event.space_id == space.id,
            Event.starts_at > now,
        )
        .all()
    )
    for booking in future_bookings:
        booking.status = BookingStatus.cancelled
        booking.cancelled_at = now

    db.commit()
    return {"ok": True}


@router.post("/spaces/{slug}/members/add", response_model=AddMemberResponse, status_code=200)
def add_or_invite_member(
    slug: str,
    body: AddMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> AddMemberResponse:
    """Add an existing user directly as a member, or create a draft invitation if not found.

    Result codes:
    - added_as_member: user existed, now an active member
    - already_member: user existed and was already a member
    - pending_invite_created: user not found, draft invitation created (no email sent)
    - invite_already_pending: draft/sent invitation already exists for this email
    """
    from sqlalchemy import func as _func

    space = _get_managed_space(slug, current_user, db)
    email = body.email.strip().lower()

    # Build display name from first/last (fall back to name field or email)
    first = (body.first_name or "").strip()
    last = (body.last_name or "").strip()
    if first or last:
        display_name = f"{first} {last}".strip()
    else:
        display_name = body.name or email

    # Parse role — default to learner for unknown values
    role_map = {"learner": SpaceRole.learner, "moderator": SpaceRole.moderator, "creator": SpaceRole.creator}
    role_enum = role_map.get(body.role, SpaceRole.learner)

    # Check if a user account exists with this email
    user = db.query(User).filter(_func.lower(User.email) == email).first()

    if user:
        # Check if already an active member
        existing = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.space_id == space.id,
                SpaceMembership.user_id == user.id,
                SpaceMembership.status == "active",
            )
            .first()
        )
        if existing:
            return AddMemberResponse(
                result="already_member",
                message="This person is already a member of this collective.",
            )
        # Add as active member — existing users are added directly, no email needed
        membership = SpaceMembership(
            id=str(uuid4()),
            space_id=space.id,
            user_id=user.id,
            role=role_enum,
            status=SpaceMembershipStatus.active,
            source="invited",
        )
        db.add(membership)
        db.commit()
        display = user.name or email
        return AddMemberResponse(
            result="added_as_member",
            message=f"{display} has been added to this collective.",
        )
    else:
        # No account — create draft invitation (sent_at=None, no email sent)
        existing_invite = (
            db.query(SpaceInvitation)
            .filter(SpaceInvitation.space_id == space.id, SpaceInvitation.email == email)
            .first()
        )
        if existing_invite:
            return AddMemberResponse(
                result="invite_already_pending",
                message="An invitation is already pending for this email address.",
            )
        invitation = SpaceInvitation(
            id=str(uuid4()),
            space_id=space.id,
            email=email,
            name=display_name,
            role=role_enum,
            note=body.note,
            invited_by_id=current_user.id,
            token=str(uuid4()),
            payment_option_id=body.payment_option_id,
            payment_status=body.payment_status,
            # sent_at=None → draft invitation, no email sent yet
        )
        db.add(invitation)
        db.commit()
        return AddMemberResponse(
            result="pending_invite_created",
            message=f"Draft invitation created for {display_name}. Use 'Send invite' to email them.",
        )


@router.get("/spaces/{slug}/members/{user_id}/bookings", response_model=list[MemberBookingItem])
def get_member_bookings(
    slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[MemberBookingItem]:
    """Return a member's gathering booking history for this space."""
    space = _get_managed_space(slug, current_user, db)
    rows = (
        db.query(EventBooking, Event)
        .join(Event, Event.id == EventBooking.event_id)
        .filter(
            Event.space_id == space.id,
            EventBooking.user_id == user_id,
        )
        .order_by(Event.starts_at.desc())
        .all()
    )
    return [
        MemberBookingItem(
            booking_id=b.id,
            event_id=e.id,
            event_title=e.title,
            event_starts_at=e.starts_at,
            event_location_type=e.location_type.value if hasattr(e.location_type, "value") else str(e.location_type),
            booking_status=b.status.value if hasattr(b.status, "value") else str(b.status),
            attendance_status=b.attendance_status,
            booked_at=b.booked_at,
        )
        for b, e in rows
    ]


# ---------------------------------------------------------------------------
# Community management
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/community", response_model=list[PostManageResponse])
def list_posts(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    from app.models.user import User as UserModel
    rows = (
        db.query(CommunityPost, UserModel)
        .join(UserModel, UserModel.id == CommunityPost.author_id)
        .filter(CommunityPost.space_id == space.id)
        .order_by(CommunityPost.created_at.desc())
        .all()
    )
    return [
        {
            "id": post.id,
            "post_type": post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
            "title": post.title,
            "body": post.body,
            "image_url": post.image_url,
            "is_pinned": post.is_pinned,
            "is_visible": post.is_visible,
            "created_at": post.created_at,
            "author_name": author.name or author.email.split("@")[0],
        }
        for post, author in rows
    ]


@router.post("/spaces/{slug}/community", response_model=PostManageResponse, status_code=201)
def create_post(
    slug: str,
    body: PostCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    post = CommunityPost(
        id=str(uuid4()),
        space_id=space.id,
        author_id=current_user.id,
        post_type=body.post_type,
        title=body.title,
        body=body.body,
        image_url=body.image_url or None,
        is_pinned=body.is_pinned,
        is_visible=True,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {
        "id": post.id,
        "post_type": post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
        "title": post.title,
        "body": post.body,
        "image_url": post.image_url,
        "is_pinned": post.is_pinned,
        "is_visible": post.is_visible,
        "created_at": post.created_at,
        "author_name": current_user.name or current_user.email.split("@")[0],
    }


@router.patch("/spaces/{slug}/community/{post_id}", response_model=PostManageResponse)
def update_post(
    slug: str,
    post_id: str,
    body: PostUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    _ensure_creator_write_allowed(current_user, space, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    if body.post_type is not None:
        post.post_type = body.post_type
    if body.title is not None:
        post.title = body.title or None
    if body.body is not None:
        post.body = body.body
    if body.is_pinned is not None:
        post.is_pinned = body.is_pinned
    if "image_url" in body.model_fields_set:
        post.image_url = body.image_url or None
    # Reschedule support — only meaningful while the post is still in
    # `scheduled` status. Once published, changing scheduled_for is a
    # no-op (we don't move history around).
    if "scheduled_for" in body.model_fields_set:
        if post.publication_status != "scheduled":
            raise HTTPException(400, detail="Only scheduled posts can be rescheduled.")
        new_time = body.scheduled_for
        if new_time is None:
            raise HTTPException(400, detail="scheduled_for cannot be cleared. Use publish-now instead.")
        if new_time.tzinfo is not None:
            new_time = new_time.astimezone(tz=None).replace(tzinfo=None)
        from datetime import datetime as _dt
        if new_time <= _dt.utcnow():
            raise HTTPException(400, detail="Scheduled time must be in the future.")
        post.scheduled_for = new_time
        if body.scheduling_timezone is not None:
            post.scheduling_timezone = body.scheduling_timezone or None
    db.commit()
    db.refresh(post)
    return _serialize_post_manage(post, db)


def _serialize_post_manage(post: CommunityPost, db: Session) -> dict:
    from app.models.user import User as UserModel
    from app.models.platform import ConversationChannel as _CC
    author = db.get(UserModel, post.author_id)
    channel_name: str | None = None
    channel_slug: str | None = None
    channel_archived = False
    if post.channel_id:
        c = db.get(_CC, post.channel_id)
        if c:
            channel_name = c.name
            channel_slug = c.slug
            channel_archived = c.is_archived
    return {
        "id": post.id,
        "post_type": post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
        "title": post.title,
        "body": post.body,
        "image_url": post.image_url,
        "is_pinned": post.is_pinned,
        "is_visible": post.is_visible,
        "created_at": post.created_at,
        "author_name": author.name or author.email.split("@")[0] if author else "",
        "publication_status": post.publication_status,
        "scheduled_for": post.scheduled_for,
        "scheduling_timezone": post.scheduling_timezone,
        "published_at": post.published_at,
        "channel_id": post.channel_id,
        "channel_slug": channel_slug,
        "channel_name": channel_name,
        "channel_archived": channel_archived,
    }


@router.get("/spaces/{slug}/community/scheduled", response_model=list[PostManageResponse])
def list_scheduled_posts(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """Return the current caretaker's scheduled posts for this collective,
    oldest scheduled first so the next-to-publish sits at the top."""
    space = _get_managed_space(slug, current_user, db)
    posts = (
        db.query(CommunityPost)
        .filter(
            CommunityPost.space_id == space.id,
            CommunityPost.publication_status == "scheduled",
            CommunityPost.is_visible.is_(True),
        )
        .order_by(CommunityPost.scheduled_for.asc().nulls_last())
        .all()
    )
    return [_serialize_post_manage(p, db) for p in posts]


@router.post("/spaces/{slug}/community/{post_id}/publish-now", response_model=PostManageResponse)
def publish_scheduled_post_now(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Skip the schedule and publish immediately.

    Uses the same atomic UPDATE pattern as the background publisher so
    a concurrent scheduler tick can never publish + notify twice.
    """
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    if post.publication_status == "published":
        # Already live — return current state without re-firing anything.
        return _serialize_post_manage(post, db)
    if post.publication_status != "scheduled":
        raise HTTPException(status_code=400, detail="Post is not in a schedulable state.")

    from datetime import datetime as _dt
    from sqlalchemy import text as _text
    now = _dt.utcnow()
    result = db.execute(
        _text(
            "UPDATE community_posts "
            "SET publication_status = 'published', "
            "    published_at = :now, "
            "    notifications_processed_at = :now "
            "WHERE id = :id "
            "  AND publication_status = 'scheduled' "
            "  AND notifications_processed_at IS NULL"
        ),
        {"id": post.id, "now": now},
    )
    db.commit()

    if result.rowcount == 1:
        # We won the race — fire notifications now. Using the shared
        # publisher helper keeps notification dispatch consistent between
        # the manual publish-now path and the background loop.
        from app.services.scheduled_publisher import _dispatch_notifications
        _dispatch_notifications(post.id, post.space_id, post.author_id)

    db.refresh(post)
    return _serialize_post_manage(post, db)


@router.patch("/spaces/{slug}/community/{post_id}/pin", status_code=204)
def toggle_pin(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    _ensure_creator_write_allowed(current_user, space, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    post.is_pinned = not post.is_pinned
    db.commit()


@router.patch("/spaces/{slug}/community/{post_id}/hide", status_code=204)
def hide_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Soft-hide: removes from learner feed but keeps manageable in Creator Studio."""
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    post.is_visible = False
    db.commit()


@router.patch("/spaces/{slug}/community/{post_id}/unhide", status_code=204)
def unhide_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Restore a hidden post to the learner feed."""
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    post.is_visible = True
    db.commit()


@router.delete("/spaces/{slug}/community/{post_id}", status_code=204)
def delete_post(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Hard delete. Use hide/unhide for reversible moderation."""
    space = _get_managed_space(slug, current_user, db)
    post = db.query(CommunityPost).filter(
        CommunityPost.id == post_id, CommunityPost.space_id == space.id
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    db.delete(post)
    db.commit()


# ---------------------------------------------------------------------------
# Media Library
# ---------------------------------------------------------------------------

def _media_usage_counts(db: Session, asset_ids: list[str]) -> dict[str, int]:
    """Single grouped query: count media-asset references across step + about blocks."""
    if not asset_ids:
        return {}
    step_rows = (
        db.query(PathwayStepBlock.media_asset_id, func.count(PathwayStepBlock.id))
        .filter(PathwayStepBlock.media_asset_id.in_(asset_ids))
        .group_by(PathwayStepBlock.media_asset_id)
        .all()
    )
    about_rows = (
        db.query(PathwayAboutBlock.media_asset_id, func.count(PathwayAboutBlock.id))
        .filter(PathwayAboutBlock.media_asset_id.in_(asset_ids))
        .group_by(PathwayAboutBlock.media_asset_id)
        .all()
    )
    counts: dict[str, int] = {}
    for aid, n in step_rows:
        counts[aid] = counts.get(aid, 0) + int(n)
    for aid, n in about_rows:
        counts[aid] = counts.get(aid, 0) + int(n)
    return counts


# ---------------------------------------------------------------------------
# Library — folders + unified list
# ---------------------------------------------------------------------------


def _folder_item_counts(db: Session, space_id: str) -> dict[str, int]:
    """Return ``{folder_id: item_count}`` for every folder in a Space,
    summed across both asset stores.

    Folders with zero items still get a 0 (the caller merges with the
    folder list to render the sidebar).
    """
    media_rows = (
        db.query(CreatorMediaAsset.folder_id, func.count(CreatorMediaAsset.id))
        .filter(
            CreatorMediaAsset.space_id == space_id,
            CreatorMediaAsset.status == "active",
            CreatorMediaAsset.folder_id.isnot(None),
        )
        .group_by(CreatorMediaAsset.folder_id)
        .all()
    )
    resource_rows = (
        db.query(SpaceResource.folder_id, func.count(SpaceResource.id))
        .filter(
            SpaceResource.space_id == space_id,
            SpaceResource.folder_id.isnot(None),
        )
        .group_by(SpaceResource.folder_id)
        .all()
    )
    counts: dict[str, int] = {}
    for fid, n in media_rows:
        counts[fid] = counts.get(fid, 0) + int(n)
    for fid, n in resource_rows:
        counts[fid] = counts.get(fid, 0) + int(n)
    return counts


def _serialise_folder(folder: LibraryFolder, item_count: int) -> dict:
    return {
        "id": folder.id,
        "name": folder.name,
        "position": folder.position,
        "item_count": item_count,
    }


@router.get(
    "/spaces/{slug}/library/folders",
    response_model=list[LibraryFolderResponse],
)
def list_library_folders(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    folders = (
        db.query(LibraryFolder)
        .filter(LibraryFolder.space_id == space.id)
        .order_by(LibraryFolder.position, LibraryFolder.created_at)
        .all()
    )
    counts = _folder_item_counts(db, space.id)
    return [_serialise_folder(f, counts.get(f.id, 0)) for f in folders]


@router.post(
    "/spaces/{slug}/library/folders",
    response_model=LibraryFolderResponse,
    status_code=201,
)
def create_library_folder(
    slug: str,
    body: LibraryFolderCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    # Default position — one past the current max, so new folders land
    # at the bottom of the sidebar rather than the top.
    if body.position is None:
        max_pos = (
            db.query(func.coalesce(func.max(LibraryFolder.position), -1))
            .filter(LibraryFolder.space_id == space.id)
            .scalar()
        )
        position = int(max_pos) + 1
    else:
        position = body.position
    folder = LibraryFolder(
        id=f"flr_{uuid4().hex[:12]}",
        space_id=space.id,
        name=body.name,
        position=position,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return _serialise_folder(folder, 0)


@router.patch(
    "/spaces/{slug}/library/folders/{folder_id}",
    response_model=LibraryFolderResponse,
)
def update_library_folder(
    slug: str,
    folder_id: str,
    body: LibraryFolderUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    folder = db.query(LibraryFolder).filter(
        LibraryFolder.id == folder_id,
        LibraryFolder.space_id == space.id,
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found.")
    if body.name is not None:
        folder.name = body.name
    if body.position is not None:
        folder.position = body.position
    db.commit()
    db.refresh(folder)
    counts = _folder_item_counts(db, space.id)
    return _serialise_folder(folder, counts.get(folder.id, 0))


@router.delete(
    "/spaces/{slug}/library/folders/{folder_id}",
    status_code=204,
)
def delete_library_folder(
    slug: str,
    folder_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    folder = db.query(LibraryFolder).filter(
        LibraryFolder.id == folder_id,
        LibraryFolder.space_id == space.id,
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found.")
    # ON DELETE SET NULL on the child FKs. Contents fall back to
    # "All items" — never deleted with the folder.
    db.delete(folder)
    db.commit()


# ── Unified Library list ────────────────────────────────────────────

_MEDIA_TYPE_TO_LIBRARY: dict[str, str] = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "document": "document",
    "other": "document",
}

# Legacy SpaceResource resource_type values that predate this milestone.
# Anything not 'link' is surfaced as a file-kind item so historical
# content still appears in the Library even before the Phase 2 migration.
_LEGACY_RESOURCE_TYPE_TO_MEDIA: dict[str, str] = {
    "file": "document",
    "guide": "document",
    "template": "document",
    "replay": "video",
    "audio": "audio",
    "video": "video",
    "other": "document",
}


@router.get(
    "/spaces/{slug}/library",
    response_model=LibraryListResponse,
)
def list_library(
    slug: str,
    type: str = "any",           # image | video | audio | document | link | any
    folder: str = "all",         # <folder-id> | none | all
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Return the unified Library — every asset the creator can pick
    from, aggregated across the file store and the link store.

    Filters (all optional):
      * ``type`` — image | video | audio | document | link | any
      * ``folder`` — a folder id, ``none`` (uncategorised), or
        ``all`` (default; every folder + uncategorised)
      * ``q`` — substring match on title / description
      * ``limit`` / ``offset`` — pagination across the merged list
    """
    space = _get_managed_space(slug, current_user, db)

    include_files = type in ("any", "image", "video", "audio", "document")
    include_links = type in ("any", "link")

    q_norm = q.strip().lower()

    # ── Files (CreatorMediaAsset) ───────────────────────────────────
    media_rows: list[CreatorMediaAsset] = []
    if include_files:
        query = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.space_id == space.id,
            CreatorMediaAsset.status == "active",
        )
        if type in ("image", "video", "audio", "document"):
            # 'document' filter accepts both stored media_type=document
            # AND media_type=other, since 'other' is where unfamiliar
            # file types land and the creator's mental model is "it's
            # a file, show it under Documents".
            if type == "document":
                query = query.filter(
                    CreatorMediaAsset.media_type.in_(["document", "other"]),
                )
            else:
                query = query.filter(CreatorMediaAsset.media_type == type)
        if folder == "none":
            query = query.filter(CreatorMediaAsset.folder_id.is_(None))
        elif folder != "all":
            query = query.filter(CreatorMediaAsset.folder_id == folder)
        if q_norm:
            query = query.filter(
                CreatorMediaAsset.title.ilike(f"%{q_norm}%")
                | CreatorMediaAsset.description.ilike(f"%{q_norm}%")
            )
        media_rows = query.all()

    # ── Links + legacy file rows (SpaceResource) ────────────────────
    # New items always have resource_type='link'. Legacy rows with
    # other resource_types are treated as files below.
    resource_rows: list[SpaceResource] = []
    if include_files or include_links:
        query = db.query(SpaceResource).filter(
            SpaceResource.space_id == space.id,
            SpaceResource.status != "archived",
        )
        if type == "link":
            query = query.filter(SpaceResource.resource_type == "link")
        elif type in ("image", "video", "audio", "document"):
            # Legacy file-type rows only.
            legacy_matching = [
                rt for rt, mt in _LEGACY_RESOURCE_TYPE_TO_MEDIA.items()
                if mt == type
            ]
            if not legacy_matching:
                query = query.filter(sa_false())
            else:
                query = query.filter(
                    SpaceResource.resource_type.in_(legacy_matching),
                )
        # type == 'any' → no resource_type filter (we surface both
        # links and legacy files together)
        if folder == "none":
            query = query.filter(SpaceResource.folder_id.is_(None))
        elif folder != "all":
            query = query.filter(SpaceResource.folder_id == folder)
        if q_norm:
            query = query.filter(
                SpaceResource.title.ilike(f"%{q_norm}%")
                | SpaceResource.description.ilike(f"%{q_norm}%")
            )
        resource_rows = query.all()

    # ── Usage counts (folded into the LibraryItem for the "used in N" chip) ──
    resource_ids = [r.id for r in resource_rows]
    resource_usage = _usage_counts_by_resource_id(db, resource_ids)
    media_ids = [a.id for a in media_rows]
    media_usage = _media_usage_counts(db, media_ids)

    # ── Merge + serialise ───────────────────────────────────────────
    items: list[dict] = []
    for a in media_rows:
        media_type_val = (
            a.media_type.value if hasattr(a.media_type, "value")
            else str(a.media_type)
        )
        items.append({
            "kind": "file",
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "folder_id": a.folder_id,
            "used_in_count": media_usage.get(a.id, 0),
            "file": {
                "url": a.file_url,
                "mime_type": a.mime_type,
                "size_bytes": a.file_size_bytes,
                "original_filename": a.original_filename,
                "media_type": _MEDIA_TYPE_TO_LIBRARY.get(media_type_val, "document"),
                "extension": a.extension,
            },
            "link": None,
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        })
    for r in resource_rows:
        rt = r.resource_type
        if rt == "link":
            items.append({
                "kind": "link",
                "id": r.id,
                "title": r.title,
                "description": r.description,
                "folder_id": r.folder_id,
                "used_in_count": resource_usage.get(r.id, 0),
                "file": None,
                "link": {
                    "url": r.url or "",
                    "resource_type": rt,
                },
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            })
        else:
            # Legacy file-type SpaceResource. Presented as a file to
            # the creator so old and new uploads coexist smoothly.
            items.append({
                "kind": "file",
                "id": r.id,
                "title": r.title,
                "description": r.description,
                "folder_id": r.folder_id,
                "used_in_count": resource_usage.get(r.id, 0),
                "file": {
                    "url": r.url or "",
                    "mime_type": None,
                    "size_bytes": r.file_size,
                    "original_filename": r.file_name,
                    "media_type": _LEGACY_RESOURCE_TYPE_TO_MEDIA.get(rt, "document"),
                    "extension": None,
                },
                "link": None,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            })

    # Sort merged list by updated_at desc so the newest edits float up
    # regardless of which store they came from.
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    total = len(items)
    items = items[offset : offset + limit]

    folders = (
        db.query(LibraryFolder)
        .filter(LibraryFolder.space_id == space.id)
        .order_by(LibraryFolder.position, LibraryFolder.created_at)
        .all()
    )
    folder_counts = _folder_item_counts(db, space.id)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "folders": [_serialise_folder(f, folder_counts.get(f.id, 0)) for f in folders],
    }


def _serialise_media(a: CreatorMediaAsset, usage_count: int) -> dict:
    return {
        "id": a.id,
        "space_id": a.space_id,
        "uploaded_by_user_id": a.uploaded_by_user_id,
        "title": a.title,
        "description": a.description,
        "alt_text": a.alt_text,
        "tags": a.tags,
        "original_filename": a.original_filename,
        "stored_filename": a.stored_filename,
        "storage_path": a.storage_path,
        "file_url": a.file_url,
        "mime_type": a.mime_type,
        "media_type": a.media_type.value if hasattr(a.media_type, "value") else str(a.media_type),
        "file_size_bytes": a.file_size_bytes,
        "extension": a.extension,
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "folder_id": a.folder_id,
        "usage_count": usage_count,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


@router.get("/spaces/{slug}/media", response_model=list[MediaAssetResponse])
def list_media(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Return active media assets for the given space, newest first."""
    space = _get_managed_space(slug, current_user, db)
    assets = (
        db.query(CreatorMediaAsset)
        .filter(
            CreatorMediaAsset.space_id == space.id,
            CreatorMediaAsset.status == "active",
        )
        .order_by(CreatorMediaAsset.created_at.desc())
        .all()
    )
    counts = _media_usage_counts(db, [a.id for a in assets])
    return [_serialise_media(a, counts.get(a.id, 0)) for a in assets]


@router.post("/spaces/{slug}/media", response_model=MediaAssetResponse, status_code=201)
async def upload_media(
    slug: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorMediaAsset:
    """
    Upload a file to the media library for the given space.

    Files are organised under uploads/media/{space_slug}/.
    // TODO: Move video storage/streaming to Mux, Cloudflare Stream, S3, or similar before production-scale use.
    // TODO: protect private member resources behind authenticated access checks before production.
    """
    space = _get_managed_space(slug, current_user, db)
    data = await file.read()
    original_name = file.filename or "upload"
    mime = file.content_type or "application/octet-stream"

    try:
        storage_path, file_url, media_type, stored_filename, size = save_media_file(
            data, original_name, mime, space.slug,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ext = pathlib.Path(original_name).suffix.lower()
    used_title = title.strip() if title.strip() else pathlib.Path(original_name).stem

    asset = CreatorMediaAsset(
        id=str(uuid4()),
        space_id=space.id,
        uploaded_by_user_id=current_user.id,
        title=used_title,
        description=description.strip() if description.strip() else None,
        original_filename=original_name,
        stored_filename=stored_filename,
        storage_path=storage_path,
        file_url=file_url,
        mime_type=mime,
        media_type=media_type,
        file_size_bytes=size,
        extension=ext,
        status="active",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialise_media(asset, 0)


@router.patch("/spaces/{slug}/media/{media_id}", response_model=MediaAssetResponse)
def update_media(
    slug: str,
    media_id: str,
    body: MediaAssetUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Update title, description, alt text, or tags of a media asset.

    NEVER modifies the underlying file. NEVER creates a duplicate. Every
    reference to this asset elsewhere (step blocks, about blocks, covers,
    banners) continues to point at the same row and immediately reflects
    the updated metadata.
    """
    space = _get_managed_space(slug, current_user, db)
    asset = db.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.id == media_id,
        CreatorMediaAsset.space_id == space.id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    if body.title is not None:
        asset.title = body.title
    if body.description is not None:
        asset.description = body.description or None
    if body.alt_text is not None:
        asset.alt_text = body.alt_text.strip() or None
    if body.tags is not None:
        # Normalise: strip whitespace around each tag, drop empties, dedupe
        cleaned = [t.strip() for t in body.tags.split(",")]
        deduped: list[str] = []
        for t in cleaned:
            if t and t.lower() not in [d.lower() for d in deduped]:
                deduped.append(t)
        asset.tags = ", ".join(deduped) if deduped else None
    # Folder move — distinguish "omitted" (leave alone) from "sent as
    # null" (move to All items). Explicitly-set folder ids are
    # validated against the space so a caller can't attach an asset
    # to a folder owned by another Collective.
    if "folder_id" in body.model_fields_set:
        if body.folder_id is None:
            asset.folder_id = None
        else:
            target = db.query(LibraryFolder).filter(
                LibraryFolder.id == body.folder_id,
                LibraryFolder.space_id == space.id,
            ).first()
            if not target:
                raise HTTPException(status_code=400, detail="Unknown folder.")
            asset.folder_id = target.id
    db.commit()
    db.refresh(asset)
    counts = _media_usage_counts(db, [asset.id])
    return _serialise_media(asset, counts.get(asset.id, 0))


@router.patch("/spaces/{slug}/media/{media_id}/archive", response_model=MediaAssetResponse)
def archive_media(
    slug: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Soft-archive a media asset. Hides from the active library."""
    space = _get_managed_space(slug, current_user, db)
    asset = db.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.id == media_id,
        CreatorMediaAsset.space_id == space.id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found.")
    asset.status = "archived"
    db.commit()
    db.refresh(asset)
    return _serialise_media(asset, 0)


@router.get("/spaces/{slug}/media/{media_id}/usage", response_model=MediaUsageResponse)
def get_media_usage(
    slug: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Read-only: every place this media asset is referenced.

    Currently covers step blocks (image / audio / file_download) and about
    blocks. Pathway covers and step banners are referenced by URL (not
    media_asset_id) so they're not included here.
    """
    space = _get_managed_space(slug, current_user, db)
    asset = db.query(CreatorMediaAsset).filter(
        CreatorMediaAsset.id == media_id,
        CreatorMediaAsset.space_id == space.id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found.")

    refs: list[MediaUsageReference] = []

    step_rows = (
        db.query(PathwayStepBlock, PathwayStep, Pathway)
        .join(PathwayStep, PathwayStep.id == PathwayStepBlock.step_id)
        .join(Pathway, Pathway.id == PathwayStep.pathway_id)
        .filter(
            PathwayStepBlock.media_asset_id == media_id,
            Pathway.space_id == space.id,
        )
        .all()
    )
    for block, step, pathway in step_rows:
        bt = block.block_type.value if hasattr(block.block_type, "value") else str(block.block_type)
        refs.append(MediaUsageReference(
            kind=f"step_block_{bt}",
            pathway_id=pathway.id,
            pathway_title=pathway.title,
            pathway_slug=pathway.slug,
            step_id=step.id,
            step_title=step.title,
            step_slug=step.slug,
            label=f"{pathway.title} — {step.title} ({bt})",
        ))

    about_rows = (
        db.query(PathwayAboutBlock, Pathway)
        .join(Pathway, Pathway.id == PathwayAboutBlock.pathway_id)
        .filter(
            PathwayAboutBlock.media_asset_id == media_id,
            Pathway.space_id == space.id,
        )
        .all()
    )
    for block, pathway in about_rows:
        bt = block.block_type.value if hasattr(block.block_type, "value") else str(block.block_type)
        refs.append(MediaUsageReference(
            kind=f"about_block_{bt}",
            pathway_id=pathway.id,
            pathway_title=pathway.title,
            pathway_slug=pathway.slug,
            label=f"{pathway.title} (about page · {bt})",
        ))

    return MediaUsageResponse(media_id=media_id, references=refs)


# ---------------------------------------------------------------------------
# Step Blocks
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks",
    response_model=list[StepBlockResponse],
)
def list_step_blocks(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStepBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)
    return (
        db.query(PathwayStepBlock)
        .options(
            selectinload(PathwayStepBlock.media_asset),
            selectinload(PathwayStepBlock.resource),
        )
        .filter(PathwayStepBlock.step_id == step.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )


def _parse_inline_bold(raw: str) -> list[dict]:
    nodes: list[dict] = []
    parts = re.split(r"\*\*(.+?)\*\*", raw)
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 0:
            nodes.append({"type": "text", "text": part})
        else:
            nodes.append({"type": "text", "marks": [{"type": "bold"}], "text": part})
    return nodes or [{"type": "text", "text": ""}]


def _content_body_to_tiptap(content_body: str) -> str:
    chunks = [c.strip() for c in re.split(r"\n\n+", content_body.strip()) if c.strip()]
    nodes: list[dict] = []
    for chunk in chunks:
        if chunk == "---":
            nodes.append({"type": "horizontalRule"})
            continue
        lines = chunk.split("\n")
        if all(ln.startswith("- ") for ln in lines):
            nodes.append({"type": "bulletList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": _parse_inline_bold(ln[2:])}
                ]}
                for ln in lines
            ]})
            continue
        if len(lines) == 1 and re.match(r"^\*\*[^*]+\*\*$", chunk):
            nodes.append({"type": "heading", "attrs": {"level": 3},
                          "content": [{"type": "text", "text": chunk[2:-2]}]})
            continue
        para_text = " ".join(ln.strip() for ln in lines if ln.strip())
        nodes.append({"type": "paragraph", "content": _parse_inline_bold(para_text)})
    if not nodes:
        nodes = [{"type": "paragraph", "content": [{"type": "text", "text": ""}]}]
    return json.dumps({"type": "doc", "content": nodes}, ensure_ascii=False)


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/convert-legacy",
    response_model=list[StepBlockResponse],
    status_code=201,
)
def convert_legacy_content(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStepBlock]:
    """Convert a step's legacy content_body into an editable text block.

    Only acts when content_body is non-empty and the step has no existing blocks.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    existing = (
        db.query(PathwayStepBlock)
        .filter(PathwayStepBlock.step_id == step.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )
    if existing:
        return existing  # Already has blocks — nothing to do

    if not step.content_body or not step.content_body.strip():
        return []  # No legacy content to convert

    tiptap_json = _content_body_to_tiptap(step.content_body)
    block = PathwayStepBlock(
        id=str(uuid4()),
        step_id=step.id,
        block_type="text",  # type: ignore[arg-type]
        position=0,
        content=tiptap_json,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return [block]


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks",
    response_model=StepBlockResponse,
    status_code=201,
)
def create_step_block(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepBlockCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStepBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    # Validate media_asset_id belongs to this space
    if body.media_asset_id:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    # Validate resource_id belongs to this space (so creators can't link to
    # another collective's resources).
    if body.resource_id:
        linked = db.query(SpaceResource).filter(
            SpaceResource.id == body.resource_id,
            SpaceResource.space_id == space.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=404, detail="Resource not found in this space.")

    # Embed blocks: extract iframe src if needed, validate against allowlist.
    # Empty URL is allowed on creation so creators can drop in a stub block
    # and configure it in the edit form.
    embed_url = body.embed_url
    content = body.content
    label = body.label
    caption = body.caption
    if body.block_type == "embed" and embed_url:
        try:
            embed_url = extract_and_validate_embed_url(embed_url)
        except EmbedValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    elif body.block_type == "button":
        # Button validators are URL- and text-required, but only when those
        # fields are actually provided. An empty button block is a valid stub.
        normalised = _normalise_button_fields({
            "embed_url": embed_url,
            "label": label,
            "caption": caption,
            "content": content,
        })
        embed_url = normalised["embed_url"]
        label = normalised["label"]
        caption = normalised["caption"]
        content = normalised["content"]

    # Determine position. When a caller passes an explicit position we
    # shift every existing block at or after that position up by one so
    # the new row lands cleanly in the middle of the sequence. This
    # supports the pathway editor's "insert between" affordance without
    # a follow-up reorder round-trip.
    if body.position is not None:
        position = body.position
        db.query(PathwayStepBlock).filter(
            PathwayStepBlock.step_id == step.id,
            PathwayStepBlock.position >= position,
        ).update(
            {PathwayStepBlock.position: PathwayStepBlock.position + 1},
            synchronize_session=False,
        )
    else:
        max_pos = (
            db.query(func.max(PathwayStepBlock.position))
            .filter(PathwayStepBlock.step_id == step.id)
            .scalar()
        )
        position = (max_pos or -1) + 1

    block = PathwayStepBlock(
        id=str(uuid4()),
        step_id=step.id,
        block_type=body.block_type,
        position=position,
        content=content,
        label=label,
        caption=caption,
        embed_url=embed_url,
        media_asset_id=body.media_asset_id,
        resource_id=body.resource_id,
        container_style=body.container_style,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


# IMPORTANT: Register /blocks/reorder BEFORE /blocks/{block_id} to avoid route conflict
@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks/reorder",
    response_model=list[StepBlockResponse],
)
def reorder_step_blocks(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepBlockReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayStepBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    blocks = {
        b.id: b
        for b in db.query(PathwayStepBlock)
        .filter(PathwayStepBlock.step_id == step.id)
        .all()
    }
    for pos, block_id in enumerate(body.ids):
        if block_id in blocks:
            blocks[block_id].position = pos
    db.commit()

    return (
        db.query(PathwayStepBlock)
        .options(
            selectinload(PathwayStepBlock.media_asset),
            selectinload(PathwayStepBlock.resource),
        )
        .filter(PathwayStepBlock.step_id == step.id)
        .order_by(PathwayStepBlock.position)
        .all()
    )


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks/{block_id}",
    response_model=StepBlockResponse,
)
def update_step_block(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    block_id: str,
    body: StepBlockUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayStepBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    block = db.query(PathwayStepBlock).filter(
        PathwayStepBlock.id == block_id,
        PathwayStepBlock.step_id == step.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found.")

    if body.media_asset_id is not None:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    if body.resource_id is not None:
        linked = db.query(SpaceResource).filter(
            SpaceResource.id == body.resource_id,
            SpaceResource.space_id == space.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=404, detail="Resource not found in this space.")

    patch = body.model_dump(exclude_unset=True)

    # Embed blocks: only validate when the creator has actually entered a URL.
    # Clearing the URL (saving with empty/null) is allowed — the block just
    # won't render until they paste a real one.
    if block.block_type == StepBlockType.embed and patch.get("embed_url"):
        try:
            patch["embed_url"] = extract_and_validate_embed_url(patch["embed_url"])
        except EmbedValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    # Button blocks: _normalise_button_fields skips empty URL/text so a stub
    # button can still be saved while editing in progress.
    if block.block_type == StepBlockType.button:
        _normalise_button_fields(patch)

    for field, value in patch.items():
        setattr(block, field, value)

    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks/{block_id}",
    status_code=204,
)
def delete_step_block(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    step = _get_step(pathway, step_slug, db)

    block = db.query(PathwayStepBlock).filter(
        PathwayStepBlock.id == block_id,
        PathwayStepBlock.step_id == step.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found.")

    db.delete(block)
    db.commit()


# ---------------------------------------------------------------------------
# Pathway About Blocks — CRUD for the pathway-level about/sales page
# ---------------------------------------------------------------------------

@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def list_about_blocks(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    return (
        db.query(PathwayAboutBlock)
        .options(
            selectinload(PathwayAboutBlock.media_asset),
            selectinload(PathwayAboutBlock.resource),
        )
        .filter(PathwayAboutBlock.pathway_id == pathway.id)
        .order_by(PathwayAboutBlock.position)
        .all()
    )


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks",
    response_model=AboutBlockResponse,
    status_code=201,
)
def create_about_block(
    slug: str,
    pathway_slug: str,
    body: AboutBlockCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    if body.media_asset_id:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    if body.resource_id:
        linked = db.query(SpaceResource).filter(
            SpaceResource.id == body.resource_id,
            SpaceResource.space_id == space.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=404, detail="Resource not found in this space.")

    # Embed/Button blocks: only validate provided fields. Empty stubs allowed.
    embed_url = body.embed_url
    content = body.content
    label = body.label
    caption = body.caption
    if body.block_type == "embed" and embed_url:
        try:
            embed_url = extract_and_validate_embed_url(embed_url)
        except EmbedValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    elif body.block_type == "button":
        normalised = _normalise_button_fields({
            "embed_url": embed_url,
            "label": label,
            "caption": caption,
            "content": content,
        })
        embed_url = normalised["embed_url"]
        label = normalised["label"]
        caption = normalised["caption"]
        content = normalised["content"]

    if body.position is not None:
        position = body.position
    else:
        max_pos = (
            db.query(func.max(PathwayAboutBlock.position))
            .filter(PathwayAboutBlock.pathway_id == pathway.id)
            .scalar()
        )
        position = (max_pos or -1) + 1

    block = PathwayAboutBlock(
        id=str(uuid4()),
        pathway_id=pathway.id,
        block_type=body.block_type,
        position=position,
        content=content,
        label=label,
        caption=caption,
        embed_url=embed_url,
        media_asset_id=body.media_asset_id,
        resource_id=body.resource_id,
        container_style=body.container_style,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


# IMPORTANT: /about-blocks/reorder must be registered BEFORE /about-blocks/{block_id}
@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks/reorder",
    response_model=list[AboutBlockResponse],
)
def reorder_about_blocks(
    slug: str,
    pathway_slug: str,
    body: AboutBlockReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    blocks = {
        b.id: b
        for b in db.query(PathwayAboutBlock)
        .filter(PathwayAboutBlock.pathway_id == pathway.id)
        .all()
    }
    for pos, block_id in enumerate(body.ids):
        if block_id in blocks:
            blocks[block_id].position = pos
    db.commit()

    return (
        db.query(PathwayAboutBlock)
        .options(
            selectinload(PathwayAboutBlock.media_asset),
            selectinload(PathwayAboutBlock.resource),
        )
        .filter(PathwayAboutBlock.pathway_id == pathway.id)
        .order_by(PathwayAboutBlock.position)
        .all()
    )


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks/{block_id}",
    response_model=AboutBlockResponse,
)
def update_about_block(
    slug: str,
    pathway_slug: str,
    block_id: str,
    body: AboutBlockUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    block = db.query(PathwayAboutBlock).filter(
        PathwayAboutBlock.id == block_id,
        PathwayAboutBlock.pathway_id == pathway.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="About block not found.")

    if body.media_asset_id is not None:
        asset = db.query(CreatorMediaAsset).filter(
            CreatorMediaAsset.id == body.media_asset_id,
            CreatorMediaAsset.space_id == space.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found in this space.")

    if body.resource_id is not None:
        linked = db.query(SpaceResource).filter(
            SpaceResource.id == body.resource_id,
            SpaceResource.space_id == space.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=404, detail="Resource not found in this space.")

    patch = body.model_dump(exclude_unset=True)

    # Embed/Button: only validate when the creator has actually entered values.
    if block.block_type == StepBlockType.embed and patch.get("embed_url"):
        try:
            patch["embed_url"] = extract_and_validate_embed_url(patch["embed_url"])
        except EmbedValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    if block.block_type == StepBlockType.button:
        _normalise_button_fields(patch)

    for field, value in patch.items():
        setattr(block, field, value)

    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset", "resource"])
    return block


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/about-blocks/{block_id}",
    status_code=204,
)
def delete_about_block(
    slug: str,
    pathway_slug: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    block = db.query(PathwayAboutBlock).filter(
        PathwayAboutBlock.id == block_id,
        PathwayAboutBlock.pathway_id == pathway.id,
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="About block not found.")

    db.delete(block)
    db.commit()


# ---------------------------------------------------------------------------
# Space Resources (collective-level) — Resources v2 (many-to-many pathways)
# ---------------------------------------------------------------------------

def _validate_pathway_ids(space: Space, pathway_ids: list[str], db: Session) -> list[Pathway]:
    """Return Pathway rows for `pathway_ids`, validating they belong to `space`.

    Raises 400 if any id doesn't belong to the space (prevents creator from
    attaching a resource to a pathway in a different collective).
    """
    if not pathway_ids:
        return []
    # Strip duplicates & empties
    cleaned = [pid for pid in {pid for pid in pathway_ids if pid}]
    if not cleaned:
        return []
    rows = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id, Pathway.id.in_(cleaned))
        .all()
    )
    if len(rows) != len(cleaned):
        raise HTTPException(
            status_code=400,
            detail="One or more pathway_ids do not belong to this collective.",
        )
    return rows


def _resolve_library_folder(
    folder_id: str | None, space: Space, db: Session,
) -> str | None:
    """Validate an incoming folder id against the current Collective.

    Returns the folder id on hit, ``None`` when the caller sent null
    or omitted the field. Raises 400 for an unknown or cross-space
    id so a mis-scoped write can't cross Collective boundaries.
    """
    if not folder_id:
        return None
    folder = db.query(LibraryFolder).filter(
        LibraryFolder.id == folder_id,
        LibraryFolder.space_id == space.id,
    ).first()
    if not folder:
        raise HTTPException(status_code=400, detail="Unknown folder.")
    return folder.id


def _legacy_scope_for(pathways: list[Pathway]) -> tuple[str, str | None]:
    """Compute legacy (scope, pathway_id) tuple from the v2 pathway list.

    Kept for back-compat: those columns still get written on every save.
    See SpaceResource docstring.
    """
    if not pathways:
        return ("general", None)
    return ("pathway", pathways[0].id)


def _resolve_pathway_ids(body_pathway_ids: list[str] | None, legacy_scope: str | None, legacy_pathway_id: str | None) -> list[str] | None:
    """Translate a v1-style {scope, pathway_id} or v2-style pathway_ids into a list.

    Returns None if the caller didn't supply anything (no change desired).
    Empty list means "set to General" (clear all pathway attachments).
    """
    if body_pathway_ids is not None:
        return body_pathway_ids
    if legacy_scope is None and legacy_pathway_id is None:
        return None
    if legacy_scope == "general":
        return []
    if legacy_scope == "pathway" and legacy_pathway_id:
        return [legacy_pathway_id]
    return None


def _usage_counts_by_resource_id(db: Session, resource_ids: list[str]) -> dict[str, int]:
    """Single grouped query: count step + about block references per resource."""
    if not resource_ids:
        return {}
    step_rows = (
        db.query(PathwayStepBlock.resource_id, func.count(PathwayStepBlock.id))
        .filter(PathwayStepBlock.resource_id.in_(resource_ids))
        .group_by(PathwayStepBlock.resource_id)
        .all()
    )
    about_rows = (
        db.query(PathwayAboutBlock.resource_id, func.count(PathwayAboutBlock.id))
        .filter(PathwayAboutBlock.resource_id.in_(resource_ids))
        .group_by(PathwayAboutBlock.resource_id)
        .all()
    )
    counts: dict[str, int] = {}
    for rid, n in step_rows:
        counts[rid] = counts.get(rid, 0) + int(n)
    for rid, n in about_rows:
        counts[rid] = counts.get(rid, 0) + int(n)
    return counts


def _serialise_resource(r: SpaceResource, usage_count: int) -> dict:
    """Build a ResourceResponse dict (so we don't need to attach usage_count
    to the ORM object before from_attributes validation).
    """
    return {
        "id": r.id,
        "title": r.title,
        "description": r.description,
        "resource_type": r.resource_type,
        "url": r.url,
        "file_name": r.file_name,
        "file_size": r.file_size,
        "status": r.status,
        "sort_order": r.sort_order,
        "pathways": [
            {"id": p.id, "slug": p.slug, "title": p.title} for p in r.pathways
        ],
        "usage_count": usage_count,
        "scope": r.scope,
        "pathway_id": r.pathway_id,
        "folder_id": r.folder_id,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@router.get("/spaces/{slug}/resources", response_model=list[ResourceResponse])
def list_space_resources(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    resources = (
        db.query(SpaceResource)
        .filter(SpaceResource.space_id == space.id)
        .order_by(SpaceResource.sort_order, SpaceResource.created_at)
        .all()
    )
    counts = _usage_counts_by_resource_id(db, [r.id for r in resources])
    return [_serialise_resource(r, counts.get(r.id, 0)) for r in resources]


@router.post("/spaces/{slug}/resources", response_model=ResourceResponse, status_code=201)
def create_space_resource(
    slug: str,
    body: ResourceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    resolved_ids = _resolve_pathway_ids(body.pathway_ids, body.scope, body.pathway_id) or []
    attached = _validate_pathway_ids(space, resolved_ids, db)
    legacy_scope, legacy_pid = _legacy_scope_for(attached)
    folder_id = _resolve_library_folder(body.folder_id, space, db)
    resource = SpaceResource(
        id=uuid4().hex,
        space_id=space.id,
        created_by_id=current_user.id,
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        resource_type=body.resource_type,
        url=body.url.strip() if body.url else None,
        status=body.status,
        sort_order=body.sort_order,
        folder_id=folder_id,
        scope=legacy_scope,
        pathway_id=legacy_pid,
        pathways=attached,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return _serialise_resource(resource, 0)


@router.post("/spaces/{slug}/resources/upload", response_model=ResourceResponse, status_code=201)
async def upload_space_resource_file(
    slug: str,
    title: str = Form(...),
    description: str | None = Form(None),
    resource_type: str = Form("file"),
    status: str = Form("draft"),
    scope: str = Form("general"),
    pathway_id: str | None = Form(None),
    pathway_ids: str | None = Form(None),  # JSON-encoded list[str] or comma-separated
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    data = await file.read()
    filename = file.filename or "resource"
    try:
        storage_path, file_url, _, stored_filename, file_size = save_media_file(
            data, filename, file.content_type or "application/octet-stream", space.slug
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Parse pathway_ids form field (JSON list preferred, comma-fallback)
    parsed_ids: list[str] | None = None
    if pathway_ids:
        try:
            parsed = json.loads(pathway_ids)
            if isinstance(parsed, list):
                parsed_ids = [str(x) for x in parsed if x]
        except (ValueError, TypeError):
            parsed_ids = [p.strip() for p in pathway_ids.split(",") if p.strip()]

    resolved_ids = _resolve_pathway_ids(parsed_ids, scope, pathway_id) or []
    attached = _validate_pathway_ids(space, resolved_ids, db)
    legacy_scope, legacy_pid = _legacy_scope_for(attached)

    resource = SpaceResource(
        id=uuid4().hex,
        space_id=space.id,
        created_by_id=current_user.id,
        title=title.strip(),
        description=description.strip() if description else None,
        resource_type=resource_type if resource_type in ("link", "file", "replay", "guide", "template", "audio", "video", "other") else "file",
        url=file_url,
        file_name=filename,
        file_size=file_size,
        status=status if status in ("draft", "published", "archived") else "draft",
        sort_order=0,
        scope=legacy_scope,
        pathway_id=legacy_pid,
        pathways=attached,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return _serialise_resource(resource, 0)


@router.patch("/spaces/{slug}/resources/{resource_id}", response_model=ResourceResponse)
def update_space_resource(
    slug: str,
    resource_id: str,
    body: ResourceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    resource = db.query(SpaceResource).filter(
        SpaceResource.id == resource_id,
        SpaceResource.space_id == space.id,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    if body.title is not None:
        resource.title = body.title
    if body.description is not None:
        resource.description = body.description.strip() or None
    if body.resource_type is not None:
        resource.resource_type = body.resource_type
    if body.url is not None:
        resource.url = body.url.strip() or None
    if body.status is not None:
        resource.status = body.status
    if body.sort_order is not None:
        resource.sort_order = body.sort_order

    # Folder move — distinguish "omitted" from "sent as null".
    if "folder_id" in body.model_fields_set:
        if body.folder_id is None:
            resource.folder_id = None
        else:
            resource.folder_id = _resolve_library_folder(body.folder_id, space, db)

    # Pathway assignment: accept v2 list OR legacy scope/pathway_id, then
    # rewrite the join rows + sync legacy columns.
    resolved_ids = _resolve_pathway_ids(body.pathway_ids, body.scope, body.pathway_id)
    if resolved_ids is not None:
        attached = _validate_pathway_ids(space, resolved_ids, db)
        resource.pathways = attached
        legacy_scope, legacy_pid = _legacy_scope_for(attached)
        resource.scope = legacy_scope
        resource.pathway_id = legacy_pid

    db.commit()
    db.refresh(resource)
    counts = _usage_counts_by_resource_id(db, [resource.id])
    return _serialise_resource(resource, counts.get(resource.id, 0))


@router.delete("/spaces/{slug}/resources/{resource_id}", status_code=204)
def delete_space_resource(
    slug: str,
    resource_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    resource = db.query(SpaceResource).filter(
        SpaceResource.id == resource_id,
        SpaceResource.space_id == space.id,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    # If it's an uploaded file, clean up from disk
    if resource.url and resource.url.startswith("/api/uploads/"):
        delete_file(resource.url.removeprefix("/api/uploads/"))
    db.delete(resource)
    db.commit()


@router.get(
    "/spaces/{slug}/resources/{resource_id}/usage",
    response_model=ResourceUsageResponse,
)
def get_resource_usage(
    slug: str,
    resource_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Read-only: every place this resource is referenced from a pathway block.

    Used by the Creator Studio "Used in N places ▼" expander.
    """
    space = _get_managed_space(slug, current_user, db)
    resource = db.query(SpaceResource).filter(
        SpaceResource.id == resource_id,
        SpaceResource.space_id == space.id,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")

    refs: list[ResourceUsageReference] = []

    # Step blocks → step → pathway
    step_block_rows = (
        db.query(PathwayStepBlock, PathwayStep, Pathway)
        .join(PathwayStep, PathwayStep.id == PathwayStepBlock.step_id)
        .join(Pathway, Pathway.id == PathwayStep.pathway_id)
        .filter(
            PathwayStepBlock.resource_id == resource_id,
            Pathway.space_id == space.id,
        )
        .all()
    )
    for _block, step, pathway in step_block_rows:
        refs.append(ResourceUsageReference(
            kind="step_block",
            pathway_id=pathway.id,
            pathway_title=pathway.title,
            pathway_slug=pathway.slug,
            step_id=step.id,
            step_title=step.title,
            step_slug=step.slug,
            href=f"/creator-studio/pathways/{pathway.slug}/steps/{step.slug}",
        ))

    # About blocks → pathway
    about_block_rows = (
        db.query(PathwayAboutBlock, Pathway)
        .join(Pathway, Pathway.id == PathwayAboutBlock.pathway_id)
        .filter(
            PathwayAboutBlock.resource_id == resource_id,
            Pathway.space_id == space.id,
        )
        .all()
    )
    for _block, pathway in about_block_rows:
        refs.append(ResourceUsageReference(
            kind="about_block",
            pathway_id=pathway.id,
            pathway_title=pathway.title,
            pathway_slug=pathway.slug,
            href=f"/creator-studio/pathways/{pathway.slug}/about",
        ))

    return ResourceUsageResponse(resource_id=resource_id, references=refs)


# ---------------------------------------------------------------------------
# Creator Payments
# ---------------------------------------------------------------------------

@router.get("/payments/summary", response_model=CreatorPaymentSummary)
def get_creator_payment_summary(
    current_user: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> CreatorPaymentSummary:
    """
    Earnings summary for the current creator.
    Only includes member purchase transactions (not creator subscription payments).
    Revenue totals are from succeeded transactions only.

    pending_payout_cents = net_creator sum for succeeded transactions where
    payout_status=pending. Updated to 'paid' when Stripe Connect transfers are
    processed.
    # TODO: deduct payout_status=paid rows once Stripe Connect is wired up.
    """
    _MEMBER_TYPES = [
        PaymentTransactionType.member_pathway_purchase,
        PaymentTransactionType.member_collective_purchase,
        PaymentTransactionType.member_pathway_subscription,
        PaymentTransactionType.member_collective_subscription,
    ]
    rows = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.creator_user_id == current_user.id,
            PaymentTransaction.transaction_type.in_([t.value for t in _MEMBER_TYPES]),
        )
        .all()
    )
    succeeded = [r for r in rows if r.status == PaymentTransactionStatus.succeeded]
    return CreatorPaymentSummary(
        total_gross_amount_cents=sum(r.gross_amount_cents for r in succeeded),
        total_platform_fee_cents=sum(r.platform_fee_cents for r in succeeded),
        total_creator_net_amount_cents=sum(r.net_creator_amount_cents or 0 for r in succeeded),
        pending_payout_cents=sum(
            r.net_creator_amount_cents or 0
            for r in succeeded
            if r.payout_status == PayoutStatus.pending
        ),
        succeeded_count=len(succeeded),
        refunded_count=sum(1 for r in rows if r.status in (
            PaymentTransactionStatus.refunded, PaymentTransactionStatus.partially_refunded
        )),
        disputed_count=sum(1 for r in rows if r.status == PaymentTransactionStatus.disputed),
        pending_count=sum(1 for r in rows if r.status == PaymentTransactionStatus.pending),
    )


@router.get("/payments", response_model=list[CreatorPaymentTransactionOut])
def list_creator_payments(
    current_user: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> list[CreatorPaymentTransactionOut]:
    """
    Return member payment transactions for the current creator's spaces/pathways.
    Creator subscription payments are excluded — those live on the Billing page.
    Only returns rows where creator_user_id matches the current user.
    """
    rows = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.creator_user_id == current_user.id,
            # Exclude creator-subscription payments from this view
            PaymentTransaction.transaction_type != PaymentTransactionType.creator_subscription_payment,
        )
        .order_by(PaymentTransaction.created_at.desc())
        .all()
    )
    return [CreatorPaymentTransactionOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Payment Options — CRUD per pathway
# ---------------------------------------------------------------------------

def _get_payment_option(option_id: str, pathway: Pathway, db: Session) -> PaymentOption:
    opt = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == option_id, PaymentOption.pathway_id == pathway.id)
        .first()
    )
    if not opt:
        raise HTTPException(status_code=404, detail="Payment option not found.")
    return opt


def _option_to_dict(opt: PaymentOption) -> dict:
    return {
        "id": opt.id,
        "space_id": opt.space_id,
        "pathway_id": opt.pathway_id,
        # Polymorphic attachment introduced in migration 105. Frontend
        # reads these to distinguish pathway-attached vs series-attached
        # options; the pathway-scoped authoring UI just checks
        # ``attaches_to_kind == 'pathway'`` and hides the switch.
        "attaches_to_kind": opt.attaches_to_kind,
        "attaches_to_id": opt.attaches_to_id,
        "grants_pathway_id": opt.grants_pathway_id,
        "name": opt.name,
        "description": opt.description,
        "payment_type": opt.payment_type.value if hasattr(opt.payment_type, "value") else str(opt.payment_type),
        "status": opt.status.value if hasattr(opt.status, "value") else str(opt.status),
        "term_start_date": opt.term_start_date,
        "term_end_date": opt.term_end_date,
        "sessions_per_week": opt.sessions_per_week,
        "total_sessions": opt.total_sessions,
        "price_per_session_cents": opt.price_per_session_cents,
        "calculated_total_cents": opt.calculated_total_cents,
        "override_total_cents": opt.override_total_cents,
        "effective_price_cents": opt.effective_price_cents,
        "currency": opt.currency,
        "buyer_note": opt.buyer_note,
        "internal_note": opt.internal_note,
        "position": opt.position,
        "created_at": opt.created_at,
        "updated_at": opt.updated_at,
    }


@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options",
    response_model=list[PaymentOptionResponse],
)
def list_payment_options(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    opts = (
        db.query(PaymentOption)
        .filter(PaymentOption.pathway_id == pathway.id)
        .order_by(PaymentOption.position, PaymentOption.created_at)
        .all()
    )
    return [_option_to_dict(o) for o in opts]


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options",
    response_model=PaymentOptionResponse,
    status_code=201,
)
def create_payment_option(
    slug: str,
    pathway_slug: str,
    body: PaymentOptionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    # Validate grants_pathway_id if supplied
    if body.grants_pathway_id:
        gp = db.query(Pathway).filter(Pathway.id == body.grants_pathway_id, Pathway.space_id == space.id).first()
        if not gp:
            raise HTTPException(status_code=400, detail="grants_pathway_id references a pathway not found in this space.")

    max_pos = (
        db.query(PaymentOption.position)
        .filter(PaymentOption.pathway_id == pathway.id)
        .order_by(PaymentOption.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    # Auto-compute calculated_total_cents if not explicitly provided
    calculated_total = body.calculated_total_cents
    if calculated_total is None and body.total_sessions and body.price_per_session_cents:
        calculated_total = body.total_sessions * body.price_per_session_cents

    now = datetime.utcnow()
    opt = PaymentOption(
        id=str(uuid4()),
        space_id=space.id,
        pathway_id=pathway.id,
        # Every option carries an explicit polymorphic attachment
        # since migration 105. This creator surface only ever
        # attaches to a Pathway; series-attached options are
        # authored on a future surface.
        attaches_to_kind="pathway",
        attaches_to_id=pathway.id,
        grants_pathway_id=body.grants_pathway_id,
        name=body.name.strip(),
        description=body.description,
        payment_type=body.payment_type,
        status=body.status,
        term_start_date=body.term_start_date,
        term_end_date=body.term_end_date,
        sessions_per_week=body.sessions_per_week,
        total_sessions=body.total_sessions,
        price_per_session_cents=body.price_per_session_cents,
        calculated_total_cents=calculated_total,
        override_total_cents=body.override_total_cents,
        currency=body.currency.upper(),
        buyer_note=body.buyer_note,
        internal_note=body.internal_note,
        position=position,
        created_at=now,
        updated_at=now,
    )
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return _option_to_dict(opt)


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options/{option_id}",
    response_model=PaymentOptionResponse,
)
def update_payment_option(
    slug: str,
    pathway_slug: str,
    option_id: str,
    body: PaymentOptionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    opt = _get_payment_option(option_id, pathway, db)

    updates = body.model_dump(exclude_unset=True)
    for field, val in updates.items():
        if field == "name" and val is not None:
            setattr(opt, field, val.strip())
        elif field == "currency" and val is not None:
            opt.currency = val.upper()
        elif field == "grants_pathway_id":
            if val:
                gp = db.query(Pathway).filter(Pathway.id == val, Pathway.space_id == space.id).first()
                if not gp:
                    raise HTTPException(status_code=400, detail="grants_pathway_id not found in this space.")
            opt.grants_pathway_id = val
        else:
            setattr(opt, field, val)

    # Recompute calculated_total_cents when session breakdown fields change
    # Only auto-compute if caller didn't explicitly send calculated_total_cents
    if "calculated_total_cents" not in updates:
        total_sess = opt.total_sessions
        price_sess = opt.price_per_session_cents
        if total_sess is not None and price_sess is not None:
            opt.calculated_total_cents = total_sess * price_sess

    opt.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(opt)
    return _option_to_dict(opt)


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options/{option_id}",
    status_code=204,
)
def archive_payment_option(
    slug: str,
    pathway_slug: str,
    option_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Soft-delete: set status to archived. Content and IDs are preserved."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    opt = _get_payment_option(option_id, pathway, db)
    opt.status = "archived"
    opt.updated_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Payment option schedules
# ---------------------------------------------------------------------------

def _get_payment_option_schedule(
    schedule_id: str,
    option: PaymentOption,
    db: Session,
) -> PaymentOptionSchedule:
    sched = (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.id == schedule_id,
            PaymentOptionSchedule.payment_option_id == option.id,
        )
        .first()
    )
    if not sched:
        raise HTTPException(status_code=404, detail="Payment schedule not found.")
    return sched


def _schedule_to_dict(s: PaymentOptionSchedule) -> dict:
    return {
        "id": s.id,
        "payment_option_id": s.payment_option_id,
        "name": s.name,
        "description": s.description,
        "schedule_type": s.schedule_type,
        "status": s.status,
        "total_amount_cents": s.total_amount_cents,
        "upfront_amount_cents": s.upfront_amount_cents,
        "installment_amount_cents": s.installment_amount_cents,
        "installment_count": s.installment_count,
        "interval": s.interval,
        "stripe_interval": s.stripe_interval,
        "stripe_interval_count": s.stripe_interval_count,
        "currency": s.currency,
        "buyer_note": s.buyer_note,
        "internal_note": s.internal_note,
        "position": s.position,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options/{option_id}/schedules",
    response_model=list[PaymentOptionScheduleResponse],
)
def list_payment_option_schedules(
    slug: str,
    pathway_slug: str,
    option_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    _get_payment_option(option_id, pathway, db)  # validates ownership
    schedules = (
        db.query(PaymentOptionSchedule)
        .filter(PaymentOptionSchedule.payment_option_id == option_id)
        .order_by(PaymentOptionSchedule.position, PaymentOptionSchedule.created_at)
        .all()
    )
    return [_schedule_to_dict(s) for s in schedules]


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options/{option_id}/schedules",
    response_model=PaymentOptionScheduleResponse,
    status_code=201,
)
def create_payment_option_schedule(
    slug: str,
    pathway_slug: str,
    option_id: str,
    body: PaymentOptionScheduleCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    _get_payment_option(option_id, pathway, db)  # validates ownership

    max_pos = (
        db.query(PaymentOptionSchedule.position)
        .filter(PaymentOptionSchedule.payment_option_id == option_id)
        .order_by(PaymentOptionSchedule.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    now = datetime.utcnow()
    sched = PaymentOptionSchedule(
        id=str(uuid4()),
        payment_option_id=option_id,
        name=body.name,
        description=body.description,
        schedule_type=body.schedule_type,
        status=body.status,
        total_amount_cents=body.total_amount_cents,
        upfront_amount_cents=body.upfront_amount_cents,
        installment_amount_cents=body.installment_amount_cents,
        installment_count=body.installment_count,
        interval=body.interval,
        stripe_interval=body.stripe_interval,
        stripe_interval_count=body.stripe_interval_count,
        currency=body.currency.upper(),
        buyer_note=body.buyer_note,
        internal_note=body.internal_note,
        position=position,
        created_at=now,
        updated_at=now,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return _schedule_to_dict(sched)


@router.post(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options/{option_id}/schedules/generate",
    response_model=list[PaymentOptionScheduleResponse],
    status_code=201,
)
def generate_payment_option_schedules(
    slug: str,
    pathway_slug: str,
    option_id: str,
    body: GenerateSchedulesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """
    Generate draft pay_in_full, weekly, and fortnightly schedules for this option.
    Skips any schedule_type that already exists (non-archived) for this option.
    """
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    opt = _get_payment_option(option_id, pathway, db)

    total = opt.effective_price_cents
    if not total or total <= 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot generate schedules: payment option has no valid effective price.",
        )

    # Existing non-archived schedule types (avoid duplicating)
    existing_types = {
        r[0]
        for r in db.query(PaymentOptionSchedule.schedule_type)
        .filter(
            PaymentOptionSchedule.payment_option_id == option_id,
            PaymentOptionSchedule.status != "archived",
        )
        .all()
    }

    max_pos_row = (
        db.query(PaymentOptionSchedule.position)
        .filter(PaymentOptionSchedule.payment_option_id == option_id)
        .order_by(PaymentOptionSchedule.position.desc())
        .first()
    )
    next_pos = (max_pos_row[0] + 1) if max_pos_row else 0

    currency = opt.currency or "AUD"
    now = datetime.utcnow()
    created = []

    # --- Pay in full ---
    if "pay_in_full" not in existing_types:
        s = PaymentOptionSchedule(
            id=str(uuid4()),
            payment_option_id=option_id,
            name="Pay in full",
            schedule_type="pay_in_full",
            status="draft",
            total_amount_cents=total,
            currency=currency,
            position=next_pos,
            created_at=now,
            updated_at=now,
        )
        db.add(s)
        created.append(s)
        next_pos += 1

    # --- Weekly ---
    if "recurring_installments" not in existing_types and body.weekly_installment_count > 0:
        weekly_amount = round(total / body.weekly_installment_count)
        s = PaymentOptionSchedule(
            id=str(uuid4()),
            payment_option_id=option_id,
            name=f"Weekly — {body.weekly_installment_count} payments",
            schedule_type="recurring_installments",
            status="draft",
            total_amount_cents=total,
            installment_amount_cents=weekly_amount,
            installment_count=body.weekly_installment_count,
            interval="week",
            stripe_interval="week",
            stripe_interval_count=1,
            currency=currency,
            buyer_note=f"{body.weekly_installment_count} weekly payments of ${weekly_amount / 100:.0f} {currency}",
            position=next_pos,
            created_at=now,
            updated_at=now,
        )
        db.add(s)
        created.append(s)
        next_pos += 1

    # --- Fortnightly ---
    if "recurring_installments" not in existing_types and body.fortnightly_installment_count > 0:
        fort_amount = round(total / body.fortnightly_installment_count)
        s = PaymentOptionSchedule(
            id=str(uuid4()),
            payment_option_id=option_id,
            name=f"Fortnightly — {body.fortnightly_installment_count} payments",
            schedule_type="recurring_installments",
            status="draft",
            total_amount_cents=total,
            installment_amount_cents=fort_amount,
            installment_count=body.fortnightly_installment_count,
            interval="fortnight",
            stripe_interval="week",
            stripe_interval_count=2,
            currency=currency,
            buyer_note=f"{body.fortnightly_installment_count} fortnightly payments of ${fort_amount / 100:.0f} {currency}",
            position=next_pos,
            created_at=now,
            updated_at=now,
        )
        db.add(s)
        created.append(s)

    db.commit()
    for s in created:
        db.refresh(s)
    return [_schedule_to_dict(s) for s in created]


@router.patch(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options/{option_id}/schedules/{schedule_id}",
    response_model=PaymentOptionScheduleResponse,
)
def update_payment_option_schedule(
    slug: str,
    pathway_slug: str,
    option_id: str,
    schedule_id: str,
    body: PaymentOptionScheduleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    opt = _get_payment_option(option_id, pathway, db)
    sched = _get_payment_option_schedule(schedule_id, opt, db)

    updates = body.model_dump(exclude_unset=True)
    for field, val in updates.items():
        if field == "name" and val is not None:
            setattr(sched, field, val.strip())
        elif field == "currency" and val is not None:
            sched.currency = val.upper()
        else:
            setattr(sched, field, val)

    sched.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(sched)
    return _schedule_to_dict(sched)


@router.delete(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-options/{option_id}/schedules/{schedule_id}",
    status_code=204,
)
def archive_payment_option_schedule(
    slug: str,
    pathway_slug: str,
    option_id: str,
    schedule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Soft-delete: set status to archived."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    opt = _get_payment_option(option_id, pathway, db)
    sched = _get_payment_option_schedule(schedule_id, opt, db)
    sched.status = "archived"
    sched.updated_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Member Passes (Phase B)
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/passes", response_model=list[AccessPassAdminOut])
def list_space_passes(
    slug: str,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list:
    """List all AccessPasses for a space. Creator/admin only."""
    from app.models.payment_option import PaymentOption as _PO
    from app.models.platform import Pathway as _Pathway
    from app.models.user import User as _User

    space = _get_managed_space(slug, current_user, db)

    query = db.query(AccessPass).filter(AccessPass.space_id == space.id)
    if status_filter:
        query = query.filter(AccessPass.status == status_filter)
    else:
        # Default: active passes only
        query = query.filter(AccessPass.status == AccessPassStatus.active)

    passes = query.order_by(AccessPass.created_at.desc()).all()

    # Bulk-fetch related records to avoid N+1
    user_ids = {ap.user_id for ap in passes}
    option_ids = {ap.payment_option_id for ap in passes if ap.payment_option_id}
    pathway_ids = {ap.eligible_pathway_id for ap in passes if ap.eligible_pathway_id}

    users = {u.id: u for u in db.query(_User).filter(_User.id.in_(user_ids)).all()} if user_ids else {}
    options = {o.id: o for o in db.query(_PO).filter(_PO.id.in_(option_ids)).all()} if option_ids else {}
    pathways = {p.id: p for p in db.query(_Pathway).filter(_Pathway.id.in_(pathway_ids)).all()} if pathway_ids else {}

    # Booking counts per pass
    from sqlalchemy import case, and_
    booking_counts = (
        db.query(
            EventBooking.access_pass_id,
            func.count(EventBooking.id).label("total_bookings"),
        )
        .filter(
            EventBooking.access_pass_id.in_([ap.id for ap in passes]),
            EventBooking.status == BookingStatus.confirmed,
        )
        .group_by(EventBooking.access_pass_id)
        .all()
    )
    total_bookings_map = {r.access_pass_id: r.total_bookings for r in booking_counts}

    thirty_days_ago = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta as _td
    thirty_days_ago = thirty_days_ago - _td(days=30)
    recent_booking_counts = (
        db.query(
            EventBooking.access_pass_id,
            func.count(EventBooking.id).label("recent_bookings"),
        )
        .filter(
            EventBooking.access_pass_id.in_([ap.id for ap in passes]),
            EventBooking.status == BookingStatus.confirmed,
            EventBooking.booked_at >= thirty_days_ago,
        )
        .group_by(EventBooking.access_pass_id)
        .all()
    )
    recent_bookings_map = {r.access_pass_id: r.recent_bookings for r in recent_booking_counts}

    results = []
    for ap in passes:
        user = users.get(ap.user_id)
        opt = options.get(ap.payment_option_id) if ap.payment_option_id else None
        pathway = pathways.get(ap.eligible_pathway_id) if ap.eligible_pathway_id else None
        results.append(AccessPassAdminOut(
            id=ap.id,
            pass_type=ap.pass_type.value if hasattr(ap.pass_type, "value") else str(ap.pass_type),
            status=ap.status.value if hasattr(ap.status, "value") else str(ap.status),
            valid_from=ap.valid_from,
            valid_until=ap.valid_until,
            total_credits=ap.total_credits,
            used_credits=ap.used_credits,
            remaining_credits=ap.remaining_credits,
            credits_per_week=ap.credits_per_week,
            eligible_pathway_id=ap.eligible_pathway_id,
            option_name=opt.name if opt else None,
            pathway_title=pathway.title if pathway else None,
            created_at=ap.created_at,
            member_name=user.name if user else None,
            member_email=user.email if user else None,
            total_bookings=total_bookings_map.get(ap.id, 0),
            recent_bookings=recent_bookings_map.get(ap.id, 0),
        ))
    return results


@router.post("/spaces/{slug}/passes/grant", response_model=GrantPassResponse, status_code=201)
def grant_pass_manually(
    slug: str,
    body: GrantPassRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> GrantPassResponse:
    """Manually grant an AccessPass to a member. Optionally also grant PathwayEntitlement and record payment."""
    from app.models.access_pass import AccessPass as _AP, AccessPassSource, AccessPassStatus, AccessPassType
    from app.models.payment import PaymentTransaction, PaymentTransactionStatus, PaymentProvider, PayoutStatus
    from app.models.payment_option import PaymentOption as _PO
    from app.models.platform import PathwayEntitlement, EntitlementSource, EntitlementStatus, Pathway as _Pathway
    from datetime import datetime as _dt, date as _date

    space = _get_managed_space(slug, current_user, db)

    if not body.payment_option_id:
        raise HTTPException(
            status_code=400,
            detail="Please select a payment option before granting a pass.",
        )

    # Verify member is in this space
    membership = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == body.user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this space.")

    now = _dt.utcnow()

    # --- Auto-populate from payment option ---
    total_credits = body.total_credits
    credits_per_week = body.credits_per_week
    valid_from = body.valid_from
    valid_until = body.valid_until
    eligible_pathway_id = body.eligible_pathway_id
    payment_option_id = body.payment_option_id

    if payment_option_id:
        opt = db.query(_PO).filter(_PO.id == payment_option_id, _PO.pathway_id.isnot(None)).first()
        if not opt:
            raise HTTPException(status_code=404, detail="Payment option not found.")
        # Verify the option belongs to a pathway in this space
        pathway_check = db.query(_Pathway).filter(_Pathway.id == opt.pathway_id, _Pathway.space_id == space.id).first()
        if not pathway_check:
            raise HTTPException(status_code=403, detail="Payment option does not belong to a pathway in this space.")
        if total_credits is None:
            total_credits = opt.total_sessions
        if credits_per_week is None:
            credits_per_week = opt.sessions_per_week
        if valid_from is None and opt.term_start_date:
            valid_from = opt.term_start_date
        if valid_until is None and opt.term_end_date:
            valid_until = opt.term_end_date
        if eligible_pathway_id is None:
            eligible_pathway_id = opt.pathway_id

    # Verify eligible_pathway_id belongs to this space
    if eligible_pathway_id:
        pathway_obj = db.query(_Pathway).filter(_Pathway.id == eligible_pathway_id, _Pathway.space_id == space.id).first()
        if not pathway_obj:
            raise HTTPException(status_code=404, detail="Pathway not found in this space.")

    # Check for existing active pass for same pathway
    if eligible_pathway_id:
        existing_pass = (
            db.query(_AP)
            .filter(
                _AP.user_id == body.user_id,
                _AP.space_id == space.id,
                _AP.eligible_pathway_id == eligible_pathway_id,
                _AP.status == AccessPassStatus.active,
            )
            .first()
        )
        if existing_pass:
            raise HTTPException(
                status_code=409,
                detail="Member already has an active pass for this pathway.",
            )

    # Map source string to enum
    source_map = {
        "manual": AccessPassSource.manual,
        "bank_transfer": AccessPassSource.manual,
        "cash": AccessPassSource.manual,
        "complimentary": AccessPassSource.free,
        "test": AccessPassSource.manual,
        "admin_grant": AccessPassSource.admin_grant,
    }
    pass_source = source_map.get(body.source, AccessPassSource.manual)

    # Map pass_type string to enum
    pass_type_map = {
        "term_pass": AccessPassType.term_pass,
        "class_pass": AccessPassType.class_pass,
        "pathway_access": AccessPassType.pathway_access,
        "event_ticket": AccessPassType.event_ticket,
    }
    pass_type_enum = pass_type_map.get(body.pass_type, AccessPassType.term_pass)

    valid_from_dt = _dt.combine(valid_from, _dt.min.time()) if valid_from else now
    valid_until_dt = _dt.combine(valid_until, _dt.min.time()) if valid_until else None

    # --- Create AccessPass ---
    access_pass = _AP(
        id=str(uuid4()),
        user_id=body.user_id,
        space_id=space.id,
        payment_option_id=payment_option_id,
        pass_type=pass_type_enum,
        status=AccessPassStatus.active,
        valid_from=valid_from_dt,
        valid_until=valid_until_dt,
        total_credits=total_credits,
        used_credits=0,
        credits_per_week=credits_per_week,
        eligible_pathway_id=eligible_pathway_id,
        grants_pathway_id=eligible_pathway_id,
        source=pass_source,
        notes=body.notes,
        created_at=now,
        updated_at=now,
    )
    db.add(access_pass)
    db.flush()

    # --- Optionally grant PathwayEntitlement ---
    ent_id: str | None = None
    if body.also_grant_pathway_access and eligible_pathway_id:
        existing_ent = (
            db.query(PathwayEntitlement)
            .filter(
                PathwayEntitlement.user_id == body.user_id,
                PathwayEntitlement.pathway_id == eligible_pathway_id,
                PathwayEntitlement.status == EntitlementStatus.active,
            )
            .first()
        )
        if not existing_ent:
            ent = PathwayEntitlement(
                id=str(uuid4()),
                user_id=body.user_id,
                space_id=space.id,
                pathway_id=eligible_pathway_id,
                source=EntitlementSource.manual_grant,
                status=EntitlementStatus.active,
                starts_at=valid_from_dt,
                ends_at=valid_until_dt,
                notes=body.notes,
                granted_by_user_id=current_user.id,
                created_at=now,
                updated_at=now,
            )
            db.add(ent)
            db.flush()
            ent_id = ent.id
            access_pass.pathway_entitlement_id = ent_id
        else:
            ent_id = existing_ent.id
            access_pass.pathway_entitlement_id = ent_id

    # --- Optionally record manual payment ---
    txn_id: str | None = None
    if body.record_payment and body.payment_amount_cents and body.payment_amount_cents > 0:
        pathway_id_for_txn = eligible_pathway_id
        txn = PaymentTransaction(
            id=str(uuid4()),
            transaction_type="member_pathway_purchase",
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.manual,
            payer_user_id=body.user_id,
            creator_user_id=current_user.id,
            space_id=space.id,
            pathway_id=pathway_id_for_txn,
            payment_option_id=payment_option_id,
            currency="AUD",
            gross_amount_cents=body.payment_amount_cents,
            platform_fee_basis_points=0,
            platform_fee_cents=0,
            net_creator_amount_cents=body.payment_amount_cents,
            payout_status=PayoutStatus.not_applicable,
            notes=f"Manual payment — {body.source}" + (f": {body.notes}" if body.notes else ""),
            created_at=now,
            updated_at=now,
        )
        db.add(txn)
        db.flush()
        txn_id = txn.id
        access_pass.payment_transaction_id = txn_id

    db.commit()

    source_label = {
        "bank_transfer": "bank transfer",
        "cash": "cash",
        "complimentary": "complimentary",
        "test": "test",
    }.get(body.source, "manual grant")

    return GrantPassResponse(
        pass_id=access_pass.id,
        entitlement_id=ent_id,
        transaction_id=txn_id,
        message=f"Pass granted ({source_label})." + (" Payment recorded." if txn_id else ""),
    )


@router.get("/spaces/{slug}/members/{user_id}/passes", response_model=list[AccessPassAdminOut])
def get_member_passes(
    slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list:
    """Get a specific member's access passes for this space."""
    from app.models.access_pass import AccessPass as _AP, AccessPassStatus
    from app.models.payment_option import PaymentOption as _PO
    from app.models.platform import Pathway as _Pathway
    from app.models.user import User as _User
    from datetime import timedelta as _td

    space = _get_managed_space(slug, current_user, db)

    membership = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this space.")

    passes = (
        db.query(_AP)
        .filter(_AP.user_id == user_id, _AP.space_id == space.id)
        .order_by(_AP.created_at.desc())
        .all()
    )

    user_obj = db.query(_User).filter(_User.id == user_id).first()
    option_ids = {ap.payment_option_id for ap in passes if ap.payment_option_id}
    pathway_ids = {ap.eligible_pathway_id for ap in passes if ap.eligible_pathway_id}
    options = {o.id: o for o in db.query(_PO).filter(_PO.id.in_(option_ids)).all()} if option_ids else {}
    pathways = {p.id: p for p in db.query(_Pathway).filter(_Pathway.id.in_(pathway_ids)).all()} if pathway_ids else {}

    # Booking counts per pass
    thirty_days_ago = datetime.utcnow() - _td(days=30)
    booking_counts = (
        db.query(EventBooking.access_pass_id, func.count(EventBooking.id).label("total"))
        .filter(EventBooking.access_pass_id.in_([ap.id for ap in passes]), EventBooking.status == BookingStatus.confirmed)
        .group_by(EventBooking.access_pass_id).all()
    )
    recent_counts = (
        db.query(EventBooking.access_pass_id, func.count(EventBooking.id).label("recent"))
        .filter(EventBooking.access_pass_id.in_([ap.id for ap in passes]), EventBooking.status == BookingStatus.confirmed, EventBooking.booked_at >= thirty_days_ago)
        .group_by(EventBooking.access_pass_id).all()
    )
    total_map = {r.access_pass_id: r.total for r in booking_counts}
    recent_map = {r.access_pass_id: r.recent for r in recent_counts}

    results = []
    for ap in passes:
        opt = options.get(ap.payment_option_id) if ap.payment_option_id else None
        pathway = pathways.get(ap.eligible_pathway_id) if ap.eligible_pathway_id else None
        results.append(AccessPassAdminOut(
            id=ap.id,
            pass_type=ap.pass_type.value if hasattr(ap.pass_type, "value") else str(ap.pass_type),
            status=ap.status.value if hasattr(ap.status, "value") else str(ap.status),
            valid_from=ap.valid_from,
            valid_until=ap.valid_until,
            total_credits=ap.total_credits,
            used_credits=ap.used_credits,
            remaining_credits=ap.remaining_credits,
            credits_per_week=ap.credits_per_week,
            eligible_pathway_id=ap.eligible_pathway_id,
            option_name=opt.name if opt else None,
            pathway_title=pathway.title if pathway else None,
            created_at=ap.created_at,
            member_name=user_obj.name if user_obj else None,
            member_email=user_obj.email if user_obj else None,
            total_bookings=total_map.get(ap.id, 0),
            recent_bookings=recent_map.get(ap.id, 0),
        ))
    return results


@router.get("/spaces/{slug}/members/{user_id}/active-pass", response_model=MemberActivePassOut | None)
def get_member_active_pass(
    slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Get the most recent active AccessPass for a member in this space."""
    from app.models.access_pass import AccessPass as _AP, AccessPassStatus as _APS
    from app.models.payment_option import PaymentOption as _PO
    from app.models.platform import Pathway as _Pathway

    space = _get_managed_space(slug, current_user, db)
    membership = db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space.id,
        SpaceMembership.user_id == user_id,
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this space.")

    ap = db.query(_AP).filter(
        _AP.user_id == user_id,
        _AP.space_id == space.id,
        _AP.status == _APS.active,
    ).order_by(_AP.created_at.desc()).first()

    if not ap:
        return None

    opt = db.query(_PO).filter(_PO.id == ap.payment_option_id).first() if ap.payment_option_id else None
    pathway = db.query(_Pathway).filter(_Pathway.id == ap.eligible_pathway_id).first() if ap.eligible_pathway_id else None
    remaining = (ap.total_credits - ap.used_credits) if ap.total_credits is not None else None

    return MemberActivePassOut(
        pass_id=ap.id,
        option_name=opt.name if opt else None,
        pathway_title=pathway.title if pathway else None,
        total_credits=ap.total_credits,
        used_credits=ap.used_credits,
        remaining_credits=remaining,
        credits_per_week=ap.credits_per_week,
        valid_from=ap.valid_from.isoformat() if ap.valid_from else None,
        valid_until=ap.valid_until.isoformat() if ap.valid_until else None,
        status=ap.status.value if hasattr(ap.status, "value") else str(ap.status),
    )


@router.post("/spaces/{slug}/members/{user_id}/bookings/recurring", response_model=RecurringBookingResponse)
def book_recurring_sessions(
    slug: str,
    user_id: str,
    body: RecurringBookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    """Book a member into multiple upcoming sessions at once, respecting pass credits and weekly caps."""
    space = _get_managed_space(slug, current_user, db)

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=400, detail="User is not an active member of this space.")

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Resolve pass once
    ap: AccessPass | None = None
    if body.use_pass:
        if body.access_pass_id:
            ap = db.query(AccessPass).filter(
                AccessPass.id == body.access_pass_id,
                AccessPass.user_id == user_id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
            ).first()
            if not ap:
                raise HTTPException(status_code=404, detail="Specified pass not found or not active for this member.")
        else:
            ap = db.query(AccessPass).filter(
                AccessPass.user_id == user_id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
            ).order_by(AccessPass.created_at.desc()).first()
            if not ap:
                raise HTTPException(status_code=409, detail="This member has no active pass for this space.")

    booked_list: list[dict] = []
    skipped_list: list[dict] = []
    now = datetime.utcnow()

    for event_id in body.event_ids:
        event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
        if not event:
            skipped_list.append({"event_id": event_id, "event_title": "Unknown", "starts_at": "",
                                  "status": "skipped", "reason": "Event not found."})
            continue

        if event.status == "cancelled":
            skipped_list.append({"event_id": event_id, "event_title": event.title,
                                  "starts_at": event.starts_at.isoformat(),
                                  "status": "skipped", "reason": "Event is cancelled."})
            continue

        existing = (
            db.query(EventBooking)
            .filter(EventBooking.event_id == event.id, EventBooking.user_id == user_id)
            .first()
        )
        if existing and existing.status == "confirmed":
            skipped_list.append({"event_id": event_id, "event_title": event.title,
                                  "starts_at": event.starts_at.isoformat(),
                                  "status": "skipped", "reason": "Already booked."})
            continue

        if event.capacity is not None:
            confirmed_count = (
                db.query(func.count(EventBooking.id))
                .filter(EventBooking.event_id == event.id, EventBooking.status == "confirmed")
                .scalar()
            ) or 0
            if confirmed_count >= event.capacity:
                skipped_list.append({"event_id": event_id, "event_title": event.title,
                                      "starts_at": event.starts_at.isoformat(),
                                      "status": "skipped", "reason": "Session is at full capacity."})
                continue

        if body.use_pass and ap:
            db.refresh(ap)  # reflect credits from bookings made earlier in this batch

            if ap.total_credits is not None and ap.used_credits >= ap.total_credits:
                skipped_list.append({"event_id": event_id, "event_title": event.title,
                                      "starts_at": event.starts_at.isoformat(),
                                      "status": "skipped", "reason": "No remaining sessions on pass."})
                continue

            if ap.credits_per_week is not None:
                event_weekday = event.starts_at.weekday()
                event_week_start = (event.starts_at - timedelta(days=event_weekday)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                event_week_end = event_week_start + timedelta(days=7)
                weekly_used = (
                    db.query(func.count(EventBooking.id))
                    .join(Event, EventBooking.event_id == Event.id)
                    .filter(
                        EventBooking.access_pass_id == ap.id,
                        EventBooking.status == BookingStatus.confirmed,
                        Event.starts_at >= event_week_start,
                        Event.starts_at < event_week_end,
                    )
                    .scalar()
                ) or 0
                if weekly_used >= ap.credits_per_week:
                    skipped_list.append({"event_id": event_id, "event_title": event.title,
                                          "starts_at": event.starts_at.isoformat(),
                                          "status": "skipped",
                                          "reason": f"Weekly limit of {ap.credits_per_week} session(s) reached for this week."})
                    continue

        access_pass_to_charge = ap if body.use_pass else None
        if existing:
            existing.status = BookingStatus.confirmed
            existing.booked_at = now
            existing.cancelled_at = None
            existing.source = "creator_pass" if body.use_pass else "creator_manual"
            existing.note = body.note
            existing.access_pass_id = access_pass_to_charge.id if access_pass_to_charge else None
            existing.credits_used = 1 if access_pass_to_charge else 0
            if access_pass_to_charge:
                access_pass_to_charge.used_credits += 1
            db.commit()
            db.refresh(existing)
            booking = existing
        else:
            booking = EventBooking(
                id=str(uuid4()),
                event_id=event.id,
                user_id=user_id,
                status=BookingStatus.confirmed,
                booked_at=now,
                source="creator_pass" if body.use_pass else "creator_manual",
                note=body.note,
                access_pass_id=access_pass_to_charge.id if access_pass_to_charge else None,
                credits_used=1 if access_pass_to_charge else 0,
            )
            db.add(booking)
            if access_pass_to_charge:
                access_pass_to_charge.used_credits += 1
            db.commit()
            db.refresh(booking)

        booked_list.append({"event_id": event_id, "event_title": event.title,
                             "starts_at": event.starts_at.isoformat(),
                             "booking_id": booking.id, "status": "booked"})

    pass_summary: dict | None = None
    if ap:
        db.refresh(ap)
        remaining = (ap.total_credits - ap.used_credits) if ap.total_credits is not None else None
        opt = db.query(PaymentOption).filter(PaymentOption.id == ap.payment_option_id).first() if ap.payment_option_id else None
        pass_summary = {
            "pass_id": ap.id,
            "option_name": opt.name if opt else None,
            "total_credits": ap.total_credits,
            "used_credits": ap.used_credits,
            "remaining_credits": remaining,
            "credits_per_week": ap.credits_per_week,
        }

    return RecurringBookingResponse(
        booked=[RecurringBookingItem(**item) for item in booked_list],
        skipped=[RecurringBookingItem(**item) for item in skipped_list],
        pass_summary=PassSummary(**pass_summary) if pass_summary else None,
    )


# ---------------------------------------------------------------------------
# Manual / Offline Members
# ---------------------------------------------------------------------------

VALID_PAYMENT_STATUSES = {"unpaid", "pending", "paid", "complimentary"}


class ManualMemberCreateRequest(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    pass_label: str | None = None


class ManualMemberUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    pass_label: str | None = None
    payment_option_id: str | None = None
    payment_status: str | None = None


class ManualMemberPathwayItem(BaseModel):
    pathway_id: str
    pathway_title: str
    pathway_slug: str
    grant_id: str
    granted_at: str
    notes: str | None


class ManualMemberResponse(BaseModel):
    id: str
    first_name: str
    last_name: str | None
    display_name: str
    email: str | None
    phone: str | None
    notes: str | None
    pass_label: str | None
    payment_option_id: str | None
    payment_option_name: str | None
    payment_status: str
    status: str
    created_at: str
    updated_at: str


def _manual_member_response(m: ManualMember, db: Session | None = None) -> ManualMemberResponse:
    display = f"{m.first_name} {m.last_name}".strip() if m.last_name else m.first_name
    payment_option_name: str | None = None
    if m.payment_option_id and db is not None:
        from app.models.platform import PaymentOption
        opt = db.query(PaymentOption.name).filter_by(id=m.payment_option_id).scalar()
        payment_option_name = opt
    return ManualMemberResponse(
        id=m.id,
        first_name=m.first_name,
        last_name=m.last_name,
        display_name=display,
        email=m.email,
        phone=m.phone,
        notes=m.notes,
        pass_label=m.pass_label,
        payment_option_id=m.payment_option_id,
        payment_option_name=payment_option_name,
        payment_status=m.payment_status or "unpaid",
        status=m.status.value if hasattr(m.status, "value") else str(m.status),
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat(),
    )


@router.get("/spaces/{slug}/manual-members", response_model=list[ManualMemberResponse])
def list_manual_members(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[ManualMemberResponse]:
    space = _get_managed_space(slug, current_user, db)
    members = (
        db.query(ManualMember)
        .filter(ManualMember.space_id == space.id, ManualMember.status != ManualMemberStatus.converted)
        .order_by(ManualMember.created_at.desc())
        .all()
    )
    return [_manual_member_response(m, db) for m in members]


@router.post("/spaces/{slug}/manual-members", response_model=ManualMemberResponse, status_code=201)
def create_manual_member(
    slug: str,
    body: ManualMemberCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualMemberResponse:
    space = _get_managed_space(slug, current_user, db)
    if not body.first_name.strip():
        raise HTTPException(status_code=422, detail="First name is required.")
    member = ManualMember(
        id=str(uuid4()),
        space_id=space.id,
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip() if body.last_name else None,
        email=body.email.strip().lower() if body.email else None,
        phone=body.phone.strip() if body.phone else None,
        notes=body.notes.strip() if body.notes else None,
        pass_label=body.pass_label.strip() if body.pass_label else None,
        payment_status="unpaid",
        status=ManualMemberStatus.offline,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _manual_member_response(member, db)


@router.patch("/spaces/{slug}/manual-members/{member_id}", response_model=ManualMemberResponse)
def update_manual_member(
    slug: str,
    member_id: str,
    body: ManualMemberUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualMemberResponse:
    space = _get_managed_space(slug, current_user, db)
    member = db.query(ManualMember).filter_by(id=member_id, space_id=space.id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Manual member not found.")
    if body.first_name is not None:
        member.first_name = body.first_name.strip() or member.first_name
    if body.last_name is not None:
        member.last_name = body.last_name.strip() or None
    if body.email is not None:
        member.email = body.email.strip().lower() or None
    if body.phone is not None:
        member.phone = body.phone.strip() or None
    if body.notes is not None:
        member.notes = body.notes.strip() or None
    if body.pass_label is not None:
        member.pass_label = body.pass_label.strip() or None
    if body.payment_option_id is not None:
        # empty string = clear the assignment
        member.payment_option_id = body.payment_option_id.strip() or None
    if body.payment_status is not None:
        if body.payment_status not in VALID_PAYMENT_STATUSES:
            raise HTTPException(status_code=422, detail=f"payment_status must be one of: {', '.join(VALID_PAYMENT_STATUSES)}")
        member.payment_status = body.payment_status
    db.commit()
    db.refresh(member)
    return _manual_member_response(member, db)


@router.delete("/spaces/{slug}/manual-members/{member_id}", status_code=204)
def delete_manual_member(
    slug: str,
    member_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    member = db.query(ManualMember).filter_by(id=member_id, space_id=space.id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Manual member not found.")
    db.delete(member)
    db.commit()


@router.post("/spaces/{slug}/manual-members/{member_id}/promote", response_model=ManualMemberResponse)
def promote_manual_member(
    slug: str,
    member_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualMemberResponse:
    """Promote an offline record to 'managed' so pass/pathway/payment can be assigned."""
    space = _get_managed_space(slug, current_user, db)
    member = db.query(ManualMember).filter_by(id=member_id, space_id=space.id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Manual member not found.")
    if member.status == ManualMemberStatus.offline:
        member.status = ManualMemberStatus.managed
        db.commit()
        db.refresh(member)
    return _manual_member_response(member, db)


@router.get("/spaces/{slug}/manual-members/{member_id}/pathway-access", response_model=list[ManualMemberPathwayItem])
def list_manual_member_pathways(
    slug: str,
    member_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[ManualMemberPathwayItem]:
    space = _get_managed_space(slug, current_user, db)
    member = db.query(ManualMember).filter_by(id=member_id, space_id=space.id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Manual member not found.")
    rows = (
        db.query(ManualMemberPathwayAccess)
        .filter(ManualMemberPathwayAccess.manual_member_id == member_id)
        .order_by(ManualMemberPathwayAccess.created_at)
        .all()
    )
    result = []
    for row in rows:
        pathway = db.query(Pathway).filter_by(id=row.pathway_id).first()
        if not pathway:
            continue
        result.append(ManualMemberPathwayItem(
            pathway_id=row.pathway_id,
            pathway_title=pathway.title,
            pathway_slug=pathway.slug,
            grant_id=row.id,
            granted_at=row.created_at.isoformat(),
            notes=row.notes,
        ))
    return result


class GrantManualMemberPathwayRequest(BaseModel):
    pathway_slug: str
    notes: str | None = None


@router.post("/spaces/{slug}/manual-members/{member_id}/pathway-access", response_model=ManualMemberPathwayItem, status_code=201)
def grant_manual_member_pathway(
    slug: str,
    member_id: str,
    body: GrantManualMemberPathwayRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualMemberPathwayItem:
    space = _get_managed_space(slug, current_user, db)
    member = db.query(ManualMember).filter_by(id=member_id, space_id=space.id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Manual member not found.")
    pathway = db.query(Pathway).filter_by(slug=body.pathway_slug, space_id=space.id).first()
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")
    existing = db.query(ManualMemberPathwayAccess).filter_by(
        manual_member_id=member_id, pathway_id=pathway.id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Pathway access already granted.")
    grant = ManualMemberPathwayAccess(
        id=str(uuid4()),
        manual_member_id=member_id,
        pathway_id=pathway.id,
        granted_by_user_id=current_user.id,
        notes=body.notes.strip() if body.notes else None,
    )
    db.add(grant)
    # Auto-promote to managed if still offline
    if member.status == ManualMemberStatus.offline:
        member.status = ManualMemberStatus.managed
    db.commit()
    db.refresh(grant)
    return ManualMemberPathwayItem(
        pathway_id=pathway.id,
        pathway_title=pathway.title,
        pathway_slug=pathway.slug,
        grant_id=grant.id,
        granted_at=grant.created_at.isoformat(),
        notes=grant.notes,
    )


@router.delete("/spaces/{slug}/manual-members/{member_id}/pathway-access/{pathway_id}", status_code=204)
def revoke_manual_member_pathway(
    slug: str,
    member_id: str,
    pathway_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    member = db.query(ManualMember).filter_by(id=member_id, space_id=space.id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Manual member not found.")
    grant = db.query(ManualMemberPathwayAccess).filter_by(
        manual_member_id=member_id, pathway_id=pathway_id
    ).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Pathway access record not found.")
    db.delete(grant)
    db.commit()


class InviteManagedMemberRequest(BaseModel):
    email: str


@router.post("/spaces/{slug}/manual-members/{member_id}/invite", response_model=ManualMemberResponse)
def invite_managed_member(
    slug: str,
    member_id: str,
    body: InviteManagedMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualMemberResponse:
    """Add email to a managed member and create a SpaceInvitation for them."""
    space = _get_managed_space(slug, current_user, db)
    member = db.query(ManualMember).filter_by(id=member_id, space_id=space.id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Manual member not found.")
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email address is required.")
    # Check if there's already an active member with this email
    from app.models.user import User as UserModel
    existing_user = db.query(UserModel).filter_by(email=email).first()
    if existing_user:
        existing_membership = db.query(SpaceMembership).filter_by(
            user_id=existing_user.id, space_id=space.id
        ).filter(SpaceMembership.status == SpaceMembershipStatus.active).first()
        if existing_membership:
            raise HTTPException(status_code=409, detail="A member with this email already exists in this collective.")
    # Check for duplicate pending invite
    existing_invite = db.query(SpaceInvitation).filter_by(
        email=email, space_id=space.id
    ).first()
    if existing_invite:
        raise HTTPException(status_code=409, detail="An invitation to this email address is already pending.")
    # Update member email + status
    member.email = email
    member.status = ManualMemberStatus.invited
    # Create invitation
    display = f"{member.first_name} {member.last_name}".strip() if member.last_name else member.first_name
    invite = SpaceInvitation(
        id=str(uuid4()),
        space_id=space.id,
        email=email,
        name=display,
        role="learner",
        token=str(uuid4()),
        invited_by_id=current_user.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(member)
    # TODO: Send invitation email when email service is connected.
    return _manual_member_response(member, db)


# ---------------------------------------------------------------------------
# Pathway Unlock Requirements (included_with_offer)
# ---------------------------------------------------------------------------

class PathwayUnlockOptionResponse(BaseModel):
    id: str
    name: str
    payment_type: str


class SetPathwayUnlockRequirementsRequest(BaseModel):
    payment_option_ids: list[str]


@router.get("/spaces/{slug}/pathways/{pathway_slug}/unlock-requirements", response_model=list[PathwayUnlockOptionResponse])
def get_pathway_unlock_requirements(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayUnlockOptionResponse]:
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)
    rows = (
        db.query(PaymentOption)
        .join(PathwayUnlockRequirement, PathwayUnlockRequirement.payment_option_id == PaymentOption.id)
        .filter(PathwayUnlockRequirement.pathway_id == pathway.id)
        .all()
    )
    return [PathwayUnlockOptionResponse(id=r.id, name=r.name, payment_type=r.payment_type.value) for r in rows]


@router.put("/spaces/{slug}/pathways/{pathway_slug}/unlock-requirements", response_model=list[PathwayUnlockOptionResponse])
def set_pathway_unlock_requirements(
    slug: str,
    pathway_slug: str,
    body: SetPathwayUnlockRequirementsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayUnlockOptionResponse]:
    """Replace the full set of payment options that unlock this pathway."""
    space = _get_managed_space(slug, current_user, db)
    pathway = _get_pathway(space, pathway_slug, db)

    # Validate all provided option IDs belong to this space
    valid_options: list[PaymentOption] = []
    for opt_id in body.payment_option_ids:
        opt = db.query(PaymentOption).filter(PaymentOption.id == opt_id, PaymentOption.space_id == space.id).first()
        if not opt:
            raise HTTPException(status_code=404, detail=f"Payment option '{opt_id}' not found in this space.")
        valid_options.append(opt)

    # Delete existing requirements and replace
    db.query(PathwayUnlockRequirement).filter(PathwayUnlockRequirement.pathway_id == pathway.id).delete()
    for opt in valid_options:
        req = PathwayUnlockRequirement(
            id=str(uuid4()),
            pathway_id=pathway.id,
            payment_option_id=opt.id,
        )
        db.add(req)
    db.commit()

    return [PathwayUnlockOptionResponse(id=opt.id, name=opt.name, payment_type=opt.payment_type.value) for opt in valid_options]


@router.get("/spaces/{slug}/payment-options", response_model=list[PathwayUnlockOptionResponse])
def list_space_payment_options(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayUnlockOptionResponse]:
    """All published payment options for this space (used to populate unlock-offer selector)."""
    space = _get_managed_space(slug, current_user, db)
    opts = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.space_id == space.id,
            PaymentOption.status == "published",
        )
        .order_by(PaymentOption.position, PaymentOption.created_at)
        .all()
    )
    return [PathwayUnlockOptionResponse(id=o.id, name=o.name, payment_type=o.payment_type.value) for o in opts]


# ---------------------------------------------------------------------------
# Offer Pages — creator surface (CRUD)
# ---------------------------------------------------------------------------


def _resolve_offer_target(
    target_kind: str, target_id: str, space: Space, db: Session,
) -> tuple[str, str]:
    """Validate an Offer Page target and return ``(kind, title)`` for
    the response snapshot.

    For V1 the only valid kind is ``pathway`` and it must belong to
    the same Collective as the Offer Page. This is where the
    ``target_id`` string is checked; there is no FK constraint on
    the column so future kinds can slot in without a migration.
    """
    if target_kind == "pathway":
        pathway = db.query(Pathway).filter(
            Pathway.id == target_id,
            Pathway.space_id == space.id,
        ).first()
        if not pathway:
            raise HTTPException(
                status_code=400,
                detail="Target pathway not found in this Collective.",
            )
        return ("pathway", pathway.title)
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported target kind: {target_kind!r}.",
    )


def _target_title(kind: str, target_id: str, db: Session) -> str | None:
    """Look up a target's display title for the index list. Returns
    None when the target has since been deleted, which is a valid
    state — the offer row survives so the creator can retarget."""
    if kind == "pathway":
        p = db.query(Pathway).filter(Pathway.id == target_id).first()
        return p.title if p else None
    return None


def _generate_unique_offer_slug(
    space_id: str, base: str, db: Session,
) -> str:
    """Slugify + numeric suffix to guarantee uniqueness per space."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "offer"
    cleaned = cleaned[:120].rstrip("-")
    candidate = cleaned
    n = 2
    while db.query(OfferPage).filter(
        OfferPage.space_id == space_id,
        OfferPage.slug == candidate,
    ).first() is not None:
        suffix = f"-{n}"
        candidate = (cleaned[: 120 - len(suffix)]).rstrip("-") + suffix
        n += 1
    return candidate


def _serialise_offer_page(op: OfferPage) -> dict:
    """Editor-facing shape. ``slug_locked`` is a derived flag —
    permanent once ``published_at`` has ever been set."""
    return {
        "id": op.id,
        "space_id": op.space_id,
        "slug": op.slug,
        "title": op.title,
        "promise": op.promise,
        "hero_image_url": op.hero_image_url,
        "target_kind": op.target_kind,
        "target_id": op.target_id,
        "status": op.status,
        "sections_config": op.sections_config or {},
        "published_at": op.published_at,
        "slug_locked": op.published_at is not None,
        "created_at": op.created_at,
        "updated_at": op.updated_at,
    }


def _serialise_offer_page_summary(op: OfferPage, target_title: str | None) -> dict:
    return {
        "id": op.id,
        "slug": op.slug,
        "title": op.title,
        "hero_image_url": op.hero_image_url,
        "target_kind": op.target_kind,
        "target_id": op.target_id,
        "target_title": target_title,
        "status": op.status,
        "slug_locked": op.published_at is not None,
        "updated_at": op.updated_at,
    }


@router.get(
    "/spaces/{slug}/offers",
    response_model=list[OfferPageSummary],
    summary="List Offer Pages for this Collective",
)
def list_offer_pages(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    rows = (
        db.query(OfferPage)
        .filter(OfferPage.space_id == space.id)
        .order_by(OfferPage.updated_at.desc())
        .all()
    )
    return [
        _serialise_offer_page_summary(op, _target_title(op.target_kind, op.target_id, db))
        for op in rows
    ]


@router.post(
    "/spaces/{slug}/offers",
    response_model=OfferPageResponse,
    status_code=201,
    summary="Create a new Offer Page (starts as draft)",
)
def create_offer_page(
    slug: str,
    body: OfferPageCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    # Community plan → 403. Offer Pages are a commercial surface; the
    # ``paid_offers_enabled`` capability decides who may author them.
    # Platform Owner bypasses. See ``plan_guards.guard_offer_pages_enabled``.
    guard_offer_pages_enabled(current_user, db)
    space = _get_managed_space(slug, current_user, db)
    # Validate target now so we never persist an offer that points at
    # something that doesn't belong to this Collective.
    _resolve_offer_target(body.target_kind, body.target_id, space, db)

    if body.slug:
        # Explicit slug — enforce uniqueness. This is the only place
        # a caller can supply a slug at create time; PATCH slug
        # changes are locked once published (see update handler).
        conflict = db.query(OfferPage).filter(
            OfferPage.space_id == space.id,
            OfferPage.slug == body.slug,
        ).first()
        if conflict:
            raise HTTPException(
                status_code=400,
                detail="An Offer Page with this slug already exists in this Collective.",
            )
        slug_value = body.slug
    else:
        slug_value = _generate_unique_offer_slug(space.id, body.title, db)

    row = OfferPage(
        id=f"ofp_{uuid4().hex[:12]}",
        space_id=space.id,
        slug=slug_value,
        title=body.title,
        target_kind=body.target_kind,
        target_id=body.target_id,
        status="draft",
        sections_config={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialise_offer_page(row)


@router.get(
    "/spaces/{slug}/offers/{offer_slug}",
    response_model=OfferPageResponse,
    summary="Get one Offer Page by slug (owner view — includes drafts)",
)
def get_offer_page(
    slug: str,
    offer_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    row = db.query(OfferPage).filter(
        OfferPage.space_id == space.id,
        OfferPage.slug == offer_slug,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Offer Page not found.")
    return _serialise_offer_page(row)


@router.patch(
    "/spaces/{slug}/offers/{offer_slug}",
    response_model=OfferPageResponse,
    summary="Update an Offer Page (partial)",
)
def update_offer_page(
    slug: str,
    offer_slug: str,
    body: OfferPageUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    guard_offer_pages_enabled(current_user, db)
    space = _get_managed_space(slug, current_user, db)
    row = db.query(OfferPage).filter(
        OfferPage.space_id == space.id,
        OfferPage.slug == offer_slug,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Offer Page not found.")

    sent = body.model_fields_set

    # ── Slug — permanently locked once the page has ever been published.
    if "slug" in sent and body.slug is not None and body.slug != row.slug:
        if row.published_at is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This Offer Page has been published — its slug is "
                    "permanently locked so previously shared links stay "
                    "stable. Create a new Offer Page if you need a "
                    "different URL."
                ),
            )
        conflict = db.query(OfferPage).filter(
            OfferPage.space_id == space.id,
            OfferPage.slug == body.slug,
            OfferPage.id != row.id,
        ).first()
        if conflict:
            raise HTTPException(
                status_code=400,
                detail="An Offer Page with this slug already exists in this Collective.",
            )
        row.slug = body.slug

    # ── Straightforward text fields
    if "title" in sent and body.title is not None:
        row.title = body.title
    if "promise" in sent:
        row.promise = (body.promise or "").strip() or None
    if "hero_image_url" in sent:
        # Empty string clears the image; explicit None also clears.
        val = (body.hero_image_url or "").strip() if body.hero_image_url else None
        row.hero_image_url = val or None

    # ── Sections
    if "sections_config" in sent and body.sections_config is not None:
        # Dump the typed shape so we persist a plain dict — future
        # readers pull the raw dict back out without needing the
        # Pydantic model in the loop.
        row.sections_config = body.sections_config.model_dump()

    # ── Status transitions
    if "status" in sent and body.status is not None:
        row.status = body.status
        if body.status == "published" and row.published_at is None:
            row.published_at = datetime.utcnow()
        # published_at is never cleared — see model docstring.

    db.commit()
    db.refresh(row)
    return _serialise_offer_page(row)


@router.delete(
    "/spaces/{slug}/offers/{offer_slug}",
    status_code=204,
    summary="Delete an Offer Page (draft only; archive published ones instead)",
)
def delete_offer_page(
    slug: str,
    offer_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    guard_offer_pages_enabled(current_user, db)
    space = _get_managed_space(slug, current_user, db)
    row = db.query(OfferPage).filter(
        OfferPage.space_id == space.id,
        OfferPage.slug == offer_slug,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Offer Page not found.")
    # Hard delete is only safe when the page never went public —
    # otherwise the URL might still be shared out there and a
    # subsequent identically-slugged Offer Page would silently
    # capture the old traffic. Force ``archive`` in that case.
    if row.published_at is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This Offer Page has been published — archive it instead "
                "so previously shared links keep resolving to the same "
                "record."
            ),
        )
    db.delete(row)
    db.commit()



# ---------------------------------------------------------------------------
# Gathering Series routes (Step 2 — see _gathering_series_routes.py for
# the CRUD + Payment Option surface). Imported for side effect: the
# module registers its endpoints against the ``router`` above.
# ---------------------------------------------------------------------------

from app.creator import _gathering_series_routes as _gs_routes  # noqa: E402,F401
