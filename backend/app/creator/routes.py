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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_creator_user
from app.core.config import settings
from app.core.database import get_db
from app.core.storage import delete_file, save_file, save_media_file
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
    InvitationCreateRequest,
    InvitationResponse,
    BlockMediaInfo,
    MediaAssetResponse,
    MediaAssetUpdateRequest,
    PathwayCreateRequest,
    PathwayResponse,
    PathwayUpdateRequest,
    GenerateSchedulesRequest,
    PaymentOptionCreateRequest,
    PaymentOptionResponse,
    PaymentOptionScheduleCreateRequest,
    PaymentOptionScheduleResponse,
    PaymentOptionScheduleUpdateRequest,
    PaymentOptionUpdateRequest,
    ResourceCreateRequest,
    ResourceResponse,
    ResourceUpdateRequest,
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
    Pathway,
    PathwayAboutBlock,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    Space,
    SpaceAccessRequest,
    SpaceInvitation,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceResource,
    SpaceRole,
    StepProgress,
    StepResource,
)
from app.models.user import User
from app.spaces.schemas import SpaceSummary

router = APIRouter(prefix="/api/creator", tags=["creator"])


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _space_detail_response(space: Space, db: Session) -> dict:
    """Build a SpaceDetail-compatible dict with derived_has_paid_internal_content injected."""
    data = SpaceDetail.model_validate(space).model_dump()
    data['derived_has_paid_internal_content'] = _derived_has_paid_content(space.id, db)
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


def _get_managed_space(slug: str, user: User, db: Session) -> Space:
    """Return the Space if the user owns it or is a creator/moderator."""
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    if user.role == "admin":
        return space  # admins can manage anything

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


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

@router.get("/billing", response_model=CreatorBillingResponse)
def get_creator_billing(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorBillingResponse:
    """Return the creator's current plan, usage, and billing setup status."""

    # Active subscription for this creator
    subscription = (
        db.query(CreatorSubscription)
        .filter(
            CreatorSubscription.user_id == current_user.id,
            CreatorSubscription.status.in_(["active", "trialing"]),
        )
        .first()
    )

    # All active plans ordered cheapest-first (for plan comparison)
    available_plans = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.is_active.is_(True))
        .order_by(CreatorPlan.monthly_price_cents)
        .all()
    )

    # Fall back to the cheapest plan if the creator has no subscription yet
    current_plan = subscription.plan if subscription else (available_plans[0] if available_plans else None)
    if not current_plan:
        raise HTTPException(status_code=500, detail="No creator plans are configured.")

    if not subscription:
        # Create a synthetic placeholder so the response shape is consistent
        from datetime import datetime as dt
        fake_sub = CreatorSubscriptionOut(
            id="",
            status="active",
            starts_at=dt.utcnow(),
            ends_at=None,
            stripe_connected=False,
        )
        sub_out = fake_sub
    else:
        sub_out = CreatorSubscriptionOut(
            id=subscription.id,
            status=subscription.status.value if hasattr(subscription.status, "value") else str(subscription.status),
            starts_at=subscription.starts_at,
            ends_at=subscription.ends_at,
            stripe_connected=False,  # TODO: Stripe billing — set True when stripe_subscription_id is populated
        )

    # Usage: count all non-archived spaces this creator manages
    # (owns directly OR holds creator/moderator membership in).
    # This matches what the Creator Studio sidebar lists so both show the same number.
    # Archived spaces do not count toward the plan limit.
    # Draft collectives count toward creator plan limits because they still occupy creator capacity.
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

    # Usage: count pathways across all creator-managed spaces
    creator_space_ids = list(managed_space_ids)
    pathways_used = (
        db.query(func.count(Pathway.id))
        .filter(Pathway.space_id.in_(creator_space_ids))
        .scalar()
    ) if creator_space_ids else 0

    return CreatorBillingResponse(
        current_plan=CreatorPlanOut.model_validate(current_plan),
        subscription=sub_out,
        usage=CreatorUsage(
            collectives_used=collectives_used,
            pathways_used=pathways_used,
            media_storage_used_mb=None,  # TODO: sum media asset file sizes when tracked
        ),
        available_plans=[CreatorPlanOut.model_validate(p) for p in available_plans],
        payment_setup=CreatorPaymentSetup(
            creator_billing_connected=False,   # Phase 3: True when creator subscription is Stripe-managed
            member_payments_connected=settings.stripe_enabled,  # Phase 1: True when FC platform Stripe is configured
            stripe_connect_connected=False,    # Phase 2+: True when creator's own Stripe Connect account is active
            stripe_test_mode=bool(
                settings.stripe_secret_key
                and settings.stripe_secret_key.startswith("sk_test_")
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

@router.get("/spaces", response_model=list[SpaceSummary])
def list_my_spaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[Space]:
    if current_user.role == "admin":
        return db.query(Space).order_by(Space.name).all()
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
    ))

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
    db.commit()
    db.refresh(space)
    return _space_detail_response(space, db)


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
    return [InvitationResponse.model_validate(inv) for inv in invitations]


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

    # TODO: Send invitation email when email service is connected.
    invitation = SpaceInvitation(
        id=str(uuid4()),
        space_id=space.id,
        email=body.email,
        name=body.name,
        role=body.role,
        note=body.note,
        invited_by_id=current_user.id,
        token=str(uuid4()),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return InvitationResponse.model_validate(invitation)


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
    )
    db.add(step)
    db.commit()
    db.refresh(step)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    events = (
        db.query(Event)
        .filter(Event.space_id == space.id)
        .order_by(Event.starts_at.desc())
        .all()
    )
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
    return [_event_to_dict(e, booked_counts.get(e.id, 0), attended_counts.get(e.id, 0), no_show_counts.get(e.id, 0)) for e in events]


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
    return _event_to_dict(event, booked_count)


def _event_to_dict(event: Event, booked_count: int = 0, attended_count: int = 0, no_show_count: int = 0) -> dict:
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
        "created_at": event.created_at,
        "booking_access_type": getattr(event, 'booking_access_type', 'all_members') or 'all_members',
        "booking_required_pathway_id": getattr(event, 'booking_required_pathway_id', None),
    }


@router.post("/spaces/{slug}/events", response_model=EventResponse, status_code=201)
def create_event(
    slug: str,
    body: EventCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
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
        booking_access_type=body.booking_access_type,
        booking_required_pathway_id=body.booking_required_pathway_id,
    )
    db.add(event)
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
    series_id = str(uuid4())
    series_label = rec.series_label
    days_set = set(rec.days_of_week)

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
            booking_access_type=body.booking_access_type,
            booking_required_pathway_id=body.booking_required_pathway_id,
            recurrence_series_id=series_id,
            recurrence_label=series_label,
            recurrence_index=idx,
            recurrence_total=total,
        )
        db.add(event)

    db.commit()
    return BulkEventCreateResponse(created_count=total, series_id=series_id)


@router.patch("/spaces/{slug}/events/{event_id}", response_model=EventResponse)
def update_event(
    slug: str,
    event_id: str,
    body: EventUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    event = db.query(Event).filter(Event.id == event_id, Event.space_id == space.id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    for field in ("title", "description", "starts_at", "ends_at", "location_type", "location_url",
                  "recording_url", "is_published", "is_public", "requires_booking", "capacity",
                  "booking_closes_at", "booking_note", "thumbnail_url",
                  "booking_access_type", "booking_required_pathway_id"):
        val = getattr(body, field)
        if val is not None:
            setattr(event, field, val)

    db.commit()
    db.refresh(event)
    booked_count = (
        db.query(func.count(EventBooking.id))
        .filter(EventBooking.event_id == event.id, EventBooking.status == "confirmed")
        .scalar()
    ) or 0
    return _event_to_dict(event, booked_count)


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Cancel a single event occurrence. Does not affect other events in the series.
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
    booked_count = 0  # all bookings are now cancelled
    return _event_to_dict(event, booked_count)


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


@router.post("/spaces/{slug}/members/add", response_model=AddMemberResponse, status_code=200)
def add_or_invite_member(
    slug: str,
    body: AddMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> AddMemberResponse:
    """Add an existing user directly as a member, or create an invitation if not found.

    Result codes:
    - added_as_member: user existed, now an active member
    - already_member: user existed and was already a member
    - invite_created: user not found, invitation record created
    - invite_already_pending: invitation already exists for this email
    """
    from sqlalchemy import func as _func

    space = _get_managed_space(slug, current_user, db)
    email = body.email.strip().lower()

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
        # Add as active member
        membership = SpaceMembership(
            id=str(uuid4()),
            space_id=space.id,
            user_id=user.id,
            role=role_enum,
            status=SpaceMembershipStatus.active,
        )
        db.add(membership)
        db.commit()
        display = user.name or email
        return AddMemberResponse(
            result="added_as_member",
            message=f"{display} has been added to this collective.",
        )
    else:
        # No account — create or detect pending invitation
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
            name=body.name,
            role=role_enum,
            note=body.note,
            invited_by_id=current_user.id,
            token=str(uuid4()),
        )
        db.add(invitation)
        db.commit()
        return AddMemberResponse(
            result="invite_created",
            message=f"No account found for {email}. An invitation has been created — share the invite link with them.",
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
    db.commit()
    db.refresh(post)
    from app.models.user import User as UserModel
    author = db.get(UserModel, post.author_id)
    return {
        "id": post.id,
        "post_type": post.post_type.value if hasattr(post.post_type, "value") else str(post.post_type),
        "title": post.title,
        "body": post.body,
        "is_pinned": post.is_pinned,
        "is_visible": post.is_visible,
        "created_at": post.created_at,
        "author_name": author.name or author.email.split("@")[0] if author else "",
    }


@router.patch("/spaces/{slug}/community/{post_id}/pin", status_code=204)
def toggle_pin(
    slug: str,
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
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

@router.get("/spaces/{slug}/media", response_model=list[MediaAssetResponse])
def list_media(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[CreatorMediaAsset]:
    """Return active media assets for the given space, newest first."""
    space = _get_managed_space(slug, current_user, db)
    return (
        db.query(CreatorMediaAsset)
        .filter(
            CreatorMediaAsset.space_id == space.id,
            CreatorMediaAsset.status == "active",
        )
        .order_by(CreatorMediaAsset.created_at.desc())
        .all()
    )


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
    return asset


@router.patch("/spaces/{slug}/media/{media_id}", response_model=MediaAssetResponse)
def update_media(
    slug: str,
    media_id: str,
    body: MediaAssetUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorMediaAsset:
    """Update title or description of a media asset."""
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
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/spaces/{slug}/media/{media_id}/archive", response_model=MediaAssetResponse)
def archive_media(
    slug: str,
    media_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> CreatorMediaAsset:
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
    return asset


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
        .options(selectinload(PathwayStepBlock.media_asset))
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

    # Determine position
    if body.position is not None:
        position = body.position
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
        content=body.content,
        label=body.label,
        caption=body.caption,
        embed_url=body.embed_url,
        media_asset_id=body.media_asset_id,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
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
        .options(selectinload(PathwayStepBlock.media_asset))
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

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(block, field, value)

    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
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
        .options(selectinload(PathwayAboutBlock.media_asset))
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
        content=body.content,
        label=body.label,
        caption=body.caption,
        embed_url=body.embed_url,
        media_asset_id=body.media_asset_id,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
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
        .options(selectinload(PathwayAboutBlock.media_asset))
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

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(block, field, value)

    db.commit()
    db.refresh(block)
    db.refresh(block, ["media_asset"])
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
# Space Resources (collective-level)
# ---------------------------------------------------------------------------

@router.get("/spaces/{slug}/resources", response_model=list[ResourceResponse])
def list_space_resources(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    return (
        db.query(SpaceResource)
        .filter(SpaceResource.space_id == space.id)
        .order_by(SpaceResource.sort_order, SpaceResource.created_at)
        .all()
    )


@router.post("/spaces/{slug}/resources", response_model=ResourceResponse, status_code=201)
def create_space_resource(
    slug: str,
    body: ResourceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
):
    space = _get_managed_space(slug, current_user, db)
    scope = body.scope if body.scope in ("general", "pathway") else "general"
    pathway_id = body.pathway_id if scope == "pathway" else None
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
        scope=scope,
        pathway_id=pathway_id,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.post("/spaces/{slug}/resources/upload", response_model=ResourceResponse, status_code=201)
async def upload_space_resource_file(
    slug: str,
    title: str = Form(...),
    description: str | None = Form(None),
    resource_type: str = Form("file"),
    status: str = Form("draft"),
    scope: str = Form("general"),
    pathway_id: str | None = Form(None),
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

    _scope = scope if scope in ("general", "pathway") else "general"
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
        status=status if status in ("draft", "published") else "draft",
        sort_order=0,
        scope=_scope,
        pathway_id=pathway_id if _scope == "pathway" else None,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


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
    if body.scope is not None and body.scope in ("general", "pathway"):
        resource.scope = body.scope
    # Update pathway_id — always sync based on current scope after update
    new_scope = body.scope if body.scope in ("general", "pathway") else resource.scope
    if new_scope == "general":
        resource.pathway_id = None
    elif body.pathway_id is not None:
        resource.pathway_id = body.pathway_id
    db.commit()
    db.refresh(resource)
    return resource


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
        valid_until=ap.valid_until.isoformat() if ap.valid_until else None,
        status=ap.status.value if hasattr(ap.status, "value") else str(ap.status),
    )
