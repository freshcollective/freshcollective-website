import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session, selectinload

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment import PaymentTransaction, PaymentTransactionStatus
from app.core.config import settings

from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.creator.schemas import AboutBlockResponse, BlockMediaInfo, StepBlockResponse
from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    BookingStatus,
    Enrollment,
    EntitlementStatus,
    Event,
    EventBooking,
    OfferPage,
    Pathway,
    PathwayAboutBlock,
    PathwayEntitlement,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
    PathwayUnlockRequirement,
    Space,
    SpaceAccessRequest,
    SpaceInvitation,
    SpaceMembership,
    SpaceMemberNotificationPrefs,
    SpaceRole,
    SpaceMembershipStatus,
    SpaceResource,
    space_resource_pathways,
    StepComment,
    StepProgress,
    StepResource,
)
from app.models.user import User
from app.spaces.schemas import (
    AccessRequestOut,
    CompleteStepRequest,
    CompleteStepResponse,
    ContinueResponse,
    EventDetail,
    EventSummary,
    GuideSection,
    GuideStep,
    InviteLookupResponse,
    KnowledgeGuideResponse,
    NotificationPrefsResponse,
    NotificationPrefsUpdate,
    OfferPageTargetSnapshot,
    PathwayProgress,
    PathwaySummary,
    PathwayWithSteps,
    PaymentOptionScheduleSummary,
    PaymentOptionSummary,
    PublicOfferCreator,
    PublicOfferPage,
    PublicPaymentOption,
    PublicPaymentOptionSchedule,
    PublicSpaceCard,
    SaveNotesRequest,
    SaveNotesResponse,
    SectionWithSteps,
    SpaceAccessStatus,
    SpaceResponse,
    SpaceSummary,
    # CollectiveResourceResponse / AggregatedResourcesResponse /
    # PathwayResourceGroup / PathwayResourceItem — retired with the
    # member Resources page. Kept in schemas.py in case a Phase 2
    # analytics feature wants a similar shape; not imported here to
    # avoid dead references.
    StepCommentAuthor,
    StepCommentCreate,
    StepCommentItem,
    StepDetail,
    StepResourceResponse,
    StepSummary,
    BookingResponse,
    SeriesBookingResponse,
    AccessPassOut,
)

from app.models.platform import EventSeries as _EventSeriesModel  # noqa: E402
from app.models.platform import PathwayStepManualRelease  # noqa: E402
from app.services.notification_service import trigger_booking_confirmed, trigger_event_booking_creator  # noqa: E402
from app.services import channel_permissions as channel_perms  # noqa: E402


def _option_supports_finite_member_checkout(option) -> bool:
    """FIP4A — is this PaymentOption's grant bundle fulfillable by
    the current finite-plan checkout path?

    Currently supported grant kinds inside a finite-plan bundle:
      * ``pathway``
      * ``event_series``
    Unsupported:
      * ``gathering`` — standalone-Gathering PaymentOption
        fulfilment is not yet activated in the shared
        ``apply_intent`` path (see
        ``services/purchase_fulfilment.py::resolve_intent_from_grants``).
        A member selecting such a plan would 4xx at
        ``/api/checkout`` — a member-visible dead-end. Hide it.

    Legacy pre-grants options (no ``PaymentOptionGrant`` rows) are
    treated as supported: the legacy resolver handles Pathway /
    Series attachments without needing grant rows. A pathway- or
    series-attached option with no grants still fulfills cleanly.

    Called from :func:`_schedule_is_member_checkoutable` for
    ``recurring_installments`` only. Pay-in-full has never been
    gated on grant-kind because its resolver is broader; leaving
    that unchanged.
    """
    from app.models.payment_option_grant import GRANT_KIND_GATHERING
    grants = list(getattr(option, "grants", []) or [])
    if not grants:
        return True
    for g in grants:
        if getattr(g, "grant_kind", None) == GRANT_KIND_GATHERING:
            return False
    return True


def _schedule_is_member_checkoutable(schedule, option=None) -> bool:
    """Single source of truth for "can a member complete unified
    checkout for this PaymentOptionSchedule today?"

    Pay-in-full (``schedule_type == 'pay_in_full'`` +
    ``status == 'published'``) is always checkoutable — that path
    is proven and always live.

    Recurring instalments (``schedule_type == 'recurring_installments'``)
    are checkoutable when ALL of:

      * ``status == 'published'``
      * ``settings.finite_plan_member_checkout_enabled`` is True
        (production-safety gate; see ``core/config.py``)
      * the schedule row passes
        ``validate_recurring_installments_row`` (structurally
        valid — amount, count, cadence, currency, total-vs-per-
        instalment consistency; see
        ``services/schedule_validation.py``)
      * the PaymentOption's grant bundle is fulfillable by the
        current finite-plan path
        (:func:`_option_supports_finite_member_checkout`). ``option``
        must be passed when the schedule is a finite plan; a caller
        that omits it will fail-closed and the schedule will hide.
        This lets FIP4A refuse to surface a Payment Option that
        would 4xx at ``/api/checkout`` — no member-visible dead
        ends.

    Not checked here (evaluated later, at the unified
    ``POST /api/checkout`` boundary):

      * Member eligibility (auth, no active plan for the same
        Option) — enforced by ``check_no_active_plan`` inside
        ``/api/checkout``. A per-viewer flag isn't returned on the
        list serialiser because the flag is per-Option-and-user;
        we don't want to leak a "you already have this" hint via
        the public shape.

    The member surface must never advertise a payment method the
    backend would refuse. This helper is called at the boundary
    between "backend authoritative" and "frontend renders" — the
    frontend consumes the returned flag and never re-decides.
    """
    if getattr(schedule, "status", None) != "published":
        return False
    schedule_type = getattr(schedule, "schedule_type", None)
    if schedule_type == "pay_in_full":
        return True
    if schedule_type == "recurring_installments":
        from app.core.config import settings
        if not settings.finite_plan_member_checkout_enabled:
            return False
        # Structural validation — same rules FIP2 uses at plan
        # creation. Reuse the row validator so a schedule that
        # would 422 at checkout never shows on the member surface.
        from app.services.schedule_validation import (
            ScheduleValidationError,
            validate_recurring_installments_row,
        )
        try:
            validate_recurring_installments_row(schedule)
        except ScheduleValidationError:
            return False
        # Fail-closed on grant-bundle: if the caller didn't pass
        # the option, we cannot verify grant support and MUST NOT
        # advertise a plan that could 4xx at checkout.
        if option is None:
            return False
        if not _option_supports_finite_member_checkout(option):
            return False
        return True
    return False


def _series_info_for(event, db) -> tuple[str | None, str | None, str | None]:
    """Return ``(title, slug, cover_image_url)`` for the Event's
    semantic Series, or ``(None, None, None)`` when the event isn't
    attached to any Series. Single row lookup — cheap on the detail
    endpoint; the list endpoint bulk-fetches instead."""
    sid = getattr(event, "series_id", None)
    if not sid:
        return None, None, None
    row = (
        db.query(_EventSeriesModel.title, _EventSeriesModel.slug, _EventSeriesModel.cover_image_url)
        .filter(_EventSeriesModel.id == sid)
        .first()
    )
    if row is None:
        return None, None, None
    return row[0], row[1], row[2]


def _viewer_has_series_pass(user, series_id: str | None, db, now) -> bool:
    """True when ``user`` holds a valid, in-window AccessPass scoped
    to ``series_id``. Mirrors the booking-endpoint eligibility rule
    so the UI can render Reserve vs Pass-required without a
    speculative POST. Returns False for anonymous viewers or events
    without a semantic series link."""
    if user is None or not series_id:
        return False
    from app.models.access_pass import AccessPass, AccessPassStatus
    hit = (
        db.query(AccessPass.id)
        .filter(
            AccessPass.user_id == user.id,
            AccessPass.eligible_series_id == series_id,
            AccessPass.status == AccessPassStatus.active,
            AccessPass.valid_from <= now,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .first()
    )
    return hit is not None


def _emit_booking_confirmed(db, background_tasks, *, event, booker) -> None:
    """M5c: emit gathering.booking.confirmed alongside the legacy
    trigger. Kept as a helper so the two call sites (upsert + fresh
    booking) share one place to bundle the payload.
    """
    from app.comms import Source, emit as comms_emit
    from app.comms.rollout import schedule_routing_if_needed
    ev = comms_emit(
        db,
        event_type="gathering.booking.confirmed",
        source_type=Source.CREATOR,
        source_id=event.creator_id if getattr(event, "creator_id", None) else booker.id,
        actor_user_id=booker.id,
        subject_type="gathering", subject_id=event.id,
        context={
            "space_id": event.space_id,
            "collective_name": getattr(event, "collective_name", None),
        },
        payload={
            "booker_id": booker.id,
            "gathering_title": getattr(event, "title", None),
            "gathering_starts_at": (
                event.starts_at.isoformat() if getattr(event, "starts_at", None) else None
            ),
        },
    )
    db.commit()
    schedule_routing_if_needed(background_tasks, ev, "gathering.booking.confirmed")
from app.services.pathway_release import (  # noqa: E402
    Availability,
    PreviousStepState,
    StepRule,
    compute_availability,
)

router = APIRouter(prefix="/api/spaces", tags=["spaces"])
me_router = APIRouter(prefix="/api/me", tags=["me"])
public_router = APIRouter(prefix="/api/public", tags=["public"])


# ---------------------------------------------------------------------------
# Public (unauthenticated) discovery endpoint
# ---------------------------------------------------------------------------

def _public_space_query(db: Session):
    """The single source of truth for "which Spaces may be shown on
    a public surface". Any change here rewires both the list endpoint
    and the single-slug endpoint below in lock-step.

    Predicates (kept identical to the historical list filter so no
    caller sees a regression):
      * ``status == 'active'``     — never surface drafts / archived
      * ``is_public == true``      — private Collectives are invisible
      * ``auto_grant_role IS NULL``— hides operational Spaces such as
                                     World Builders, whose membership
                                     is managed automatically.
    """
    return db.query(Space).filter(
        Space.status == "active",
        Space.is_public.is_(True),
        Space.auto_grant_role.is_(None),
    )


@public_router.get("/spaces", response_model=list[PublicSpaceCard])
def list_public_spaces(db: Session = Depends(get_db)) -> list[PublicSpaceCard]:
    """Return all public active spaces with aggregated counts — no auth required."""
    spaces = _public_space_query(db).order_by(Space.created_at).all()
    return hydrate_public_space_cards(spaces, db)


@public_router.get("/spaces/{slug}", response_model=PublicSpaceCard)
def get_public_space(slug: str, db: Session = Depends(get_db)) -> PublicSpaceCard:
    """Return a single publicly-visible Collective by slug — no auth.

    Uses the same filter as :func:`list_public_spaces` so any Collective
    that would not appear in the list is *not* addressable here either
    (returns 404). Prevents an unlisted Collective (draft, private, or
    auto-grant) from being surfaced through the single-slug route.

    Hydration goes through ``hydrate_public_space_cards`` so the
    returned shape is byte-for-byte the same as an entry in the list
    response — no private membership, creator-contact, unpublished
    pricing or admin fields are exposed.
    """
    space = _public_space_query(db).filter(Space.slug == slug).one_or_none()
    if space is None:
        raise HTTPException(status_code=404, detail="Collective not found.")
    cards = hydrate_public_space_cards([space], db)
    # Hydration always returns exactly one card for a single input row;
    # a defensive index guard would only mask a bug.
    return cards[0]


def hydrate_public_space_cards(
    spaces: list[Space], db: Session,
) -> list[PublicSpaceCard]:
    """Project a list of Space rows into ``PublicSpaceCard`` payloads.

    Extracted so other public surfaces (e.g. ``GET /api/places/{slug}``)
    can render Collectives with exactly the same shape and aggregations
    the Explore Collectives listing uses — the frontend re-uses the
    same card component on both pages, so any drift here would ripple
    into visual inconsistency.

    Caller is responsible for filtering (status / is_public / etc.);
    this helper just does the aggregate hydration.
    """
    if not spaces:
        return []

    space_ids = [s.id for s in spaces]

    pathway_counts: dict[str, int] = dict(
        db.query(Pathway.space_id, func.count(Pathway.id))
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status != "archived",
        )
        .group_by(Pathway.space_id)
        .all()
    )

    # Minimum price among active paid pathways per space.
    # - Legacy pathways (pricing_mode='legacy'): use pathway.price_cents.
    # - Payment-options pathways (pricing_mode='payment_options'): use minimum
    #   effective price from PUBLISHED options only (draft/archived excluded).
    #   effective_price_cents = COALESCE(override_total_cents, calculated_total_cents)
    _paid_access_types = ('one_time', 'subscription')
    min_pathway_prices: dict[str, int] = {}

    # Legacy pathway prices
    legacy_rows = (
        db.query(Pathway.space_id, func.min(Pathway.price_cents))
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status == "active",
            Pathway.access_type.in_(_paid_access_types),
            Pathway.pricing_mode == "legacy",
            Pathway.price_cents.isnot(None),
            Pathway.price_cents > 0,
        )
        .group_by(Pathway.space_id)
        .all()
    )
    for space_id, min_cents in legacy_rows:
        if min_cents is not None:
            min_pathway_prices[space_id] = int(min_cents)

    # Payment-options pathway prices — derived from published options only
    from sqlalchemy import case as sa_case
    effective_price_expr = func.coalesce(
        PaymentOption.override_total_cents,
        PaymentOption.calculated_total_cents,
    )
    options_rows = (
        db.query(Pathway.space_id, func.min(effective_price_expr))
        .join(PaymentOption, PaymentOption.pathway_id == Pathway.id)
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status == "active",
            Pathway.pricing_mode == "payment_options",
            PaymentOption.status == "published",
            effective_price_expr.isnot(None),
            effective_price_expr > 0,
        )
        .group_by(Pathway.space_id)
        .all()
    )
    for space_id, min_cents in options_rows:
        if min_cents is not None:
            existing = min_pathway_prices.get(space_id)
            min_pathway_prices[space_id] = int(min_cents) if existing is None else min(existing, int(min_cents))

    member_counts: dict[str, int] = dict(
        db.query(Pathway.space_id, func.count(func.distinct(Enrollment.user_id)))
        .join(Enrollment, Enrollment.pathway_id == Pathway.id)
        .filter(Pathway.space_id.in_(space_ids))
        .group_by(Pathway.space_id)
        .all()
    )

    upcoming_event_space_ids: set[str] = {
        r[0] for r in db.query(Event.space_id)
        .filter(
            Event.space_id.in_(space_ids),
            Event.is_published.is_(True),
            Event.starts_at >= datetime.utcnow(),
        )
        .distinct()
        .all()
    }

    creator_ids = [s.creator_id for s in spaces if s.creator_id]
    creator_names: dict[str, str | None] = {}
    if creator_ids:
        rows = db.query(User.id, User.name).filter(User.id.in_(creator_ids)).all()
        creator_names = {r.id: r.name for r in rows}

    # Atlas artwork per collective — falls back to `cover_image_url` when
    # the collective is legacy or unassigned.
    from app.models.platform import Location  # local import to keep top imports flat
    location_ids = [s.location_id for s in spaces if s.location_id]
    location_art: dict[str, tuple[str | None, str | None]] = {}
    if location_ids:
        locs = (
            db.query(Location.id, Location.hero_artwork_url, Location.thumbnail_artwork_url)
            .filter(Location.id.in_(location_ids))
            .all()
        )
        location_art = {row.id: (row.hero_artwork_url, row.thumbnail_artwork_url) for row in locs}

    return [
        PublicSpaceCard(
            id=s.id,
            slug=s.slug,
            name=s.name,
            tagline=s.tagline,
            description=s.description,
            cover_image_url=s.cover_image_url,
            is_public=s.is_public,
            pathway_count=pathway_counts.get(s.id, 0),
            member_count=member_counts.get(s.id, 0),
            creator_name=creator_names.get(s.creator_id) if s.creator_id else None,
            has_upcoming_event=s.id in upcoming_event_space_ids,
            themes=s.themes or [],
            pricing_type=s.pricing_type or 'free',
            pricing_amount_cents=s.pricing_amount_cents,
            pricing_currency=s.pricing_currency or 'AUD',
            pricing_note=s.pricing_note,
            has_paid_internal_content=s.has_paid_internal_content or False,
            included_access_summary=s.included_access_summary,
            paid_content_summary=s.paid_content_summary,
            derived_has_paid_internal_content=s.id in min_pathway_prices,
            min_paid_pathway_price_cents=min_pathway_prices.get(s.id),
            location_hero_artwork_url=location_art.get(s.location_id or "", (None, None))[0] if s.location_id else None,
            location_thumbnail_artwork_url=location_art.get(s.location_id or "", (None, None))[1] if s.location_id else None,
        )
        for s in spaces
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_space_or_404(slug: str, db: Session) -> Space:
    space = db.query(Space).filter(Space.slug == slug, Space.status == "active").first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _get_space_by_slug_or_404(slug: str, db: Session) -> Space:
    """Slug lookup that does NOT filter by public status. Use only from
    endpoints that gate access with a per-user membership check, so a
    member of a draft, coming-soon, or archived collective can still
    manage their own state (notification prefs, membership record, etc.).

    ``_get_space_or_404`` remains the correct choice for public read
    paths — do not converge them.
    """
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _user_manages_space(user: "User | None", space: Space, db: Session) -> bool:
    """True when the caller is entitled to see a non-active collective —
    admins, the collective's owner, or an active creator/moderator
    SpaceMembership. Used only by read paths that surface a preview to
    the manager (Preview button flow). Public/anonymous callers can
    never satisfy this predicate."""
    if user is None:
        return False
    if user.role == "admin":
        return True
    if space.creator_id == user.id:
        return True
    mem = (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .first()
    )
    return mem is not None


def _get_space_visible_to(slug: str, db: Session, current_user: "User | None") -> Space:
    """Same as ``_get_space_or_404`` for public callers, but additionally
    permits any status when the caller manages the collective. Used by
    the pathway read endpoints reached from the Creator Studio Preview
    button so a draft collective's owner can preview it end-to-end
    without weakening public 404 behaviour."""
    space = db.query(Space).filter(Space.slug == slug).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    if space.status != "active" and not _user_manages_space(current_user, space, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return space


def _get_member_space(slug: str, current_user: "User", db: Session) -> Space:
    """Space lookup that requires the caller to have a qualifying
    relationship with the Space. Used by endpoints that return
    space-scoped data which a non-member has no legitimate business
    seeing (SEC-004: ``list_pathways_progress`` was previously readable
    by any authenticated caller, leaking draft/archived pathways and
    letting strangers enumerate private link-only Collectives).

    Qualifying relationships:

      * ``current_user.role == "admin"`` — platform admin retains
        cross-Collective read access here (out of scope for SEC-005-E).
      * The caller owns the Space (``space.creator_id == user.id``).
      * The caller has an active ``SpaceMembership`` — any role
        (``learner``, ``moderator``, ``creator``).

    SEC-005-E: platform ``User.role == "creator"`` is no longer a
    global bypass. A platform creator with no relationship to this
    Collective is refused; access requires ownership or an active
    ``SpaceMembership``, matching the sibling ``_check_pathway_access``
    and ``_compute_pathway_access`` semantics.

    Non-members receive **404 Not Found**, not 403. Matches the privacy
    stance of ``_get_space_visible_to``: refusing to acknowledge a
    Space's existence to callers who cannot see it (relevant for
    private / link-only Collectives such as World Builders).
    """
    space = db.query(Space).filter(Space.slug == slug).first()
    if space is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    # Platform admin — preserved cross-Collective oversight.
    if current_user.role == "admin":
        return space

    # Space owner.
    if space.creator_id == current_user.id:
        return space

    # Active membership (any role).
    membership = (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    if membership is not None:
        return space

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")


def _get_pathway_or_404(space_id: str, pathway_slug: str, db: Session) -> Pathway:
    pathway = (
        db.query(Pathway)
        .filter(Pathway.space_id == space_id, Pathway.slug == pathway_slug)
        .first()
    )
    if not pathway:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pathway not found.")
    return pathway


def _get_step_or_404(pathway_id: str, step_slug: str, db: Session) -> PathwayStep:
    step = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway_id, PathwayStep.slug == step_slug)
        .first()
    )
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found.")
    return step


def _completed_step_ids(user_id: str, step_ids: list[str], db: Session) -> set[str]:
    """Return the subset of step_ids the user has completed (completed_at IS NOT NULL)."""
    records = (
        db.query(StepProgress.step_id)
        .filter(
            StepProgress.user_id == user_id,
            StepProgress.step_id.in_(step_ids),
            StepProgress.completed_at.isnot(None),
        )
        .all()
    )
    return {r.step_id for r in records}


def _hydrate_step_availability(
    steps_in_display_order: list["PathwayStep"],
    pathway_id: str,
    user_id: str,
    db: Session,
) -> dict[str, Availability]:
    """Batch-compute per-step availability for one user against a pathway.

    `steps_in_display_order` must be the caller's authoritative view
    order — the release engine's AFTER_PREVIOUS rule uses the immediately
    preceding entry in this list as the prerequisite.

    Callers with no `user_id` (public / unauthenticated) should skip
    this and hand every step the default open Availability.
    """
    if not steps_in_display_order:
        return {}

    step_ids = [s.id for s in steps_in_display_order]

    # Per-user context, fetched in three cheap queries.
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == user_id, Enrollment.pathway_id == pathway_id)
        .first()
    )
    enrolled_at = enrollment.enrolled_at if enrollment else None

    manual_ids: set[str] = {
        row.step_id
        for row in db.query(PathwayStepManualRelease.step_id)
        .filter(
            PathwayStepManualRelease.step_id.in_(step_ids),
            PathwayStepManualRelease.user_id == user_id,
        )
        .all()
    }

    progress_by_step: dict[str, StepProgress] = {
        p.step_id: p
        for p in db.query(StepProgress)
        .filter(StepProgress.user_id == user_id, StepProgress.step_id.in_(step_ids))
        .all()
    }

    now = datetime.utcnow()
    result: dict[str, Availability] = {}
    for idx, step in enumerate(steps_in_display_order):
        prev = None
        if idx > 0:
            prev_step = steps_in_display_order[idx - 1]
            prev_progress = progress_by_step.get(prev_step.id)
            prev = PreviousStepState(
                completed_at=prev_progress.completed_at if prev_progress else None,
                has_progress_record=prev_progress is not None,
            )
        rule = StepRule(
            release_type=step.release_type or "immediate",
            release_offset_days=step.release_offset_days,
            release_at=step.release_at,
            release_timezone=step.release_timezone,
            release_previous_state=step.release_previous_state or "completed",
        )
        result[step.id] = compute_availability(
            rule=rule,
            enrolled_at=enrolled_at,
            previous=prev,
            manually_released=step.id in manual_ids,
            now=now,
        )
    return result


def _availability_to_schema(step: "PathwayStep", av: Availability) -> "StepAvailability":
    """Convert engine dataclass + step's release columns into the wire schema."""
    from app.spaces.schemas import StepAvailability as _StepAvailabilitySchema
    return _StepAvailabilitySchema(
        is_locked=av.is_locked,
        reason=av.reason,
        unlocks_at=av.unlocks_at,
        message=av.message,
        release_type=step.release_type or "immediate",
        release_offset_days=step.release_offset_days,
        release_at=step.release_at,
        release_timezone=step.release_timezone,
        release_previous_state=step.release_previous_state or "completed",
    )


def _ensure_enrollment(user_id: str, pathway_id: str, db: Session) -> None:
    """Create an active enrollment if one does not already exist."""
    exists = (
        db.query(Enrollment.id)
        .filter(Enrollment.user_id == user_id, Enrollment.pathway_id == pathway_id)
        .first()
    )
    if not exists:
        db.add(Enrollment(
            id=str(uuid.uuid4()),
            user_id=user_id,
            pathway_id=pathway_id,
            status="active",
        ))
        db.flush()


def _compute_pathway_access(user: "User | None", pathway: Pathway, space: Space, db: Session) -> bool:
    """
    Return True if user has access to this pathway; False otherwise.
    Accepts None for unauthenticated visitors — they never have access to paid/included pathways.

    SEC-005-E: platform ``User.role == "creator"`` no longer grants
    global pathway access. Manager-level access (draft / archived /
    coming_soon / paid pathways bypass) now requires platform admin,
    Space ownership, or an active creator/moderator ``SpaceMembership``.
    """
    if user is None:
        p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
        access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
        if p_status in ("draft", "archived", "coming_soon"):
            return False
        return access_type == "free"
    if user.role == "admin":
        return True
    if space.creator_id == user.id:
        return True
    space_role = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .first()
    )
    if space_role:
        return True
    p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
    access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")
    if p_status in ("draft", "archived", "coming_soon"):
        return False
    if access_type == "free":
        return True
    if access_type == "included":
        mem = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == "active",
            )
            .first()
        )
        return mem is not None
    if access_type == "included_with_offer":
        unlock_option_ids = [
            row.payment_option_id
            for row in db.query(PathwayUnlockRequirement.payment_option_id)
            .filter(PathwayUnlockRequirement.pathway_id == pathway.id)
            .all()
        ]
        if not unlock_option_ids:
            return False
        pass_row = (
            db.query(AccessPass.id)
            .filter(
                AccessPass.user_id == user.id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
                AccessPass.payment_option_id.in_(unlock_option_ids),
            )
            .first()
        )
        return pass_row is not None

    # one_time or subscription — requires active PathwayEntitlement that hasn't expired
    now = datetime.utcnow()
    ent = (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None) | (PathwayEntitlement.ends_at > now)),
        )
        .first()
    )
    return ent is not None


def _check_pathway_access(
    user: User,
    pathway: Pathway,
    space: Space,
    db: Session,
) -> None:
    """
    Raise HTTP 403 if the user does not have access to this pathway.

    Access rules (SEC-005-E — narrowed):
      - platform admin → always allowed
      - Space owner → always allowed
      - active SpaceMembership(role in creator/moderator) → always allowed
      - draft/archived pathway → denied to everyone else
      - coming_soon pathway → denied (About page is separate, not gated here)
      - free pathway (active) → allowed
      - included pathway (active) → allowed for space members
      - one_time/subscription pathway → requires active PathwayEntitlement row

    Platform ``User.role == "creator"`` is no longer a global bypass;
    a platform creator with no ownership or per-Collective membership
    is treated as an ordinary caller here.
    """
    # Platform admin — preserved cross-Collective oversight.
    if user.role == "admin":
        return

    # Space owner — legitimate authority even without a matching
    # ``SpaceMembership`` row (defends legacy Collectives).
    if space.creator_id == user.id:
        return

    # Space creators and moderators always have access
    space_role = (
        db.query(SpaceMembership.role)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.role.in_(["creator", "moderator"]),
            SpaceMembership.status == "active",
        )
        .first()
    )
    if space_role:
        return

    p_status = pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status)
    access_type = pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type or "free")

    if p_status in ("draft", "archived"):
        raise HTTPException(status_code=403, detail="This pathway is not available.")
    if p_status == "coming_soon":
        raise HTTPException(status_code=403, detail="This pathway is coming soon.")

    if access_type == "free":
        return

    if access_type == "included":
        mem = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == "active",
            )
            .first()
        )
        if mem:
            return
        raise HTTPException(status_code=403, detail="This pathway is included with space membership.")

    if access_type == "included_with_offer":
        unlock_option_ids = [
            row.payment_option_id
            for row in db.query(PathwayUnlockRequirement.payment_option_id)
            .filter(PathwayUnlockRequirement.pathway_id == pathway.id)
            .all()
        ]
        if unlock_option_ids:
            pass_row = (
                db.query(AccessPass.id)
                .filter(
                    AccessPass.user_id == user.id,
                    AccessPass.space_id == space.id,
                    AccessPass.status == AccessPassStatus.active,
                    AccessPass.payment_option_id.in_(unlock_option_ids),
                )
                .first()
            )
            if pass_row:
                return
        raise HTTPException(status_code=403, detail="Access to this pathway is included with a paid offer.")

    # one_time / subscription — require an active entitlement that hasn't expired
    now = datetime.utcnow()
    entitlement = (
        db.query(PathwayEntitlement.id)
        .filter(
            PathwayEntitlement.user_id == user.id,
            PathwayEntitlement.pathway_id == pathway.id,
            PathwayEntitlement.status == EntitlementStatus.active,
            (PathwayEntitlement.ends_at.is_(None) | (PathwayEntitlement.ends_at > now)),
        )
        .first()
    )
    if entitlement:
        return

    raise HTTPException(
        status_code=403,
        detail="Access to this pathway requires a purchase or manual grant.",
    )


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

@router.get("", response_model=list[SpaceSummary])
def list_spaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Space]:
    return (
        db.query(Space)
        .filter(Space.status == "active")
        .order_by(Space.name)
        .all()
    )


@router.get("/{slug}", response_model=SpaceResponse)
def get_space(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> SpaceResponse:
    # Managers of a collective can see it via the space overview even when
    # it's draft/archived, so the Creator Studio Preview flow works
    # end-to-end (the SpaceLayout hits this endpoint before any pathway
    # page renders). Public / non-manager callers still get 404.
    space = (
        db.query(Space)
        .options(selectinload(Space.pathways))
        .filter(Space.slug == slug)
        .first()
    )
    if not space or (
        space.status != "active" and not _user_manages_space(current_user, space, db)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    if not space.is_public and current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    # Authoritative aggregate counts. These MUST be sourced from a
    # DB aggregate, never from a privacy-filtered directory list on
    # the frontend — otherwise ordinary-member sidebars silently
    # show 0 members whenever the Space has ``show_member_directory=False``
    # (the ``/api/spaces/{slug}/members`` endpoint hides learner
    # rows from learner-role callers in that case). Sidebar / stats
    # UI must consume these fields, not compute ``members.length``.
    learner_count = (
        db.query(func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role == SpaceRole.learner,
        )
        .scalar()
    ) or 0
    leader_count = (
        db.query(func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role.in_((SpaceRole.creator, SpaceRole.moderator)),
        )
        .scalar()
    ) or 0
    # Atlas v1.2 — hydrate Location + Colour Palette for downstream theming.
    from app.models.platform import Location, ColourStory, AtmosphereOption
    location_dict = None
    if space.location_id:
        loc = db.query(Location).filter(Location.id == space.location_id).first()
        if loc:
            location_dict = {
                "id": loc.id,
                "key": loc.key,
                "name": loc.name,
                "description": loc.description,
                "hero_artwork_url": loc.hero_artwork_url,
                "thumbnail_artwork_url": loc.thumbnail_artwork_url,
            }
    palette_dict = None
    if space.colour_story_key:
        cs = db.query(ColourStory).filter(ColourStory.key == space.colour_story_key).first()
        if cs:
            palette_dict = {"key": cs.key, "name": cs.name, "palette": cs.palette}
    atmo_keys = list(space.atmosphere_keys or [])
    atmo_labels: list[str] = []
    if atmo_keys:
        rows = (
            db.query(AtmosphereOption.key, AtmosphereOption.name)
            .filter(AtmosphereOption.key.in_(atmo_keys))
            .all()
        )
        name_by_key = {r.key: r.name for r in rows}
        # Preserve the creator-authored order and drop any keys that no
        # longer resolve (e.g. an atmosphere_option was archived).
        atmo_labels = [name_by_key[k] for k in atmo_keys if k in name_by_key]
    resp = SpaceResponse.model_validate(space)
    return resp.model_copy(update={
        "learner_count": learner_count,
        "leader_count": leader_count,
        "location": location_dict,
        "colour_palette": palette_dict,
        "colour_palette_key": space.colour_story_key,
        "atmosphere_keys": atmo_keys,
        "atmosphere_labels": atmo_labels,
        "identity_statement": space.identity_statement,
        "welcome_message": space.welcome_message,
    })


# ---------------------------------------------------------------------------
# Member access: join, request-access, my-access
# ---------------------------------------------------------------------------

@router.get("/{slug}/my-access", response_model=SpaceAccessStatus)
def get_my_access(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpaceAccessStatus:
    """Return the current user's access state for this Space."""
    space = _get_space_visible_to(slug, db, current_user)

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.status == "active",
        )
        .first()
    )

    request = (
        db.query(SpaceAccessRequest)
        .filter(
            SpaceAccessRequest.space_id == space.id,
            SpaceAccessRequest.user_id == current_user.id,
            SpaceAccessRequest.status == "pending",
        )
        .first()
    )

    invite = (
        db.query(SpaceInvitation)
        .filter(
            SpaceInvitation.space_id == space.id,
            SpaceInvitation.email == current_user.email.lower(),
        )
        .first()
    )

    return SpaceAccessStatus(
        is_member=membership is not None,
        membership_role=(
            membership.role.value if membership and hasattr(membership.role, "value")
            else str(membership.role) if membership else None
        ),
        has_pending_request=request is not None,
        has_pending_invite=invite is not None,
    )


@router.post("/{slug}/join", status_code=201)
def join_space(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Join a public Space as a learner."""
    space = _get_space_or_404(slug, db)

    # Community Care — a frozen collective cannot accept new members
    # or renewals while the freeze is in place.
    from app.community_care.shared import is_space_closed, is_space_frozen
    if is_space_closed(space):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This collective has been closed.",
        )
    if is_space_frozen(space):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This collective is temporarily paused by Fresh Collective.",
        )

    if space.auto_grant_role is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this collective is managed automatically by Fresh Collective and cannot be joined manually.",
        )

    if not space.is_public:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This collective is private. Request access instead.")

    existing = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == current_user.id)
        .first()
    )
    if existing:
        return {"joined": True, "already_member": True}

    db.add(SpaceMembership(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        space_id=space.id,
        role=SpaceRole.learner,
        status=SpaceMembershipStatus.active,
        source="joined",
    ))
    db.commit()
    return {"joined": True, "already_member": False}


@router.post("/{slug}/request-access", status_code=201)
def request_access(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Submit an access request to a private Space."""
    space = _get_space_or_404(slug, db)

    if space.is_public:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This collective is public. Use the join endpoint instead.")

    existing_member = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == current_user.id,
                SpaceMembership.status == "active")
        .first()
    )
    if existing_member:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="You are already a member of this collective.")

    existing_request = (
        db.query(SpaceAccessRequest)
        .filter(SpaceAccessRequest.space_id == space.id, SpaceAccessRequest.user_id == current_user.id)
        .first()
    )
    if existing_request:
        if existing_request.status == "pending":
            return {"requested": True, "already_pending": True}
        # Allow re-requesting if previously declined
        existing_request.status = "pending"
        existing_request.updated_at = datetime.utcnow()
        db.commit()
        return {"requested": True, "already_pending": False}

    db.add(SpaceAccessRequest(
        id=str(uuid.uuid4()),
        space_id=space.id,
        user_id=current_user.id,
        status="pending",
    ))
    db.commit()
    return {"requested": True, "already_pending": False}


# ---------------------------------------------------------------------------
# Invite acceptance (token-based)
# ---------------------------------------------------------------------------

invites_router = APIRouter(prefix="/api/invites", tags=["invites"])


@invites_router.get("/{token}", response_model=InviteLookupResponse)
def get_invite_by_token(
    token: str,
    db: Session = Depends(get_db),
) -> InviteLookupResponse:
    """Look up an invite by token — public endpoint (no auth required)."""
    invite = (
        db.query(SpaceInvitation)
        .filter(SpaceInvitation.token == token)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or already used.")

    space = db.query(Space).filter(Space.id == invite.space_id).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    return InviteLookupResponse(
        id=invite.id,
        space_id=invite.space_id,
        space_name=space.name,
        space_slug=space.slug,
        email=invite.email,
        name=invite.name,
        role=invite.role.value if hasattr(invite.role, "value") else str(invite.role),
    )


@invites_router.post("/{token}/accept", status_code=201)
def accept_invite(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Accept a space invite by token. Caller must be logged in."""
    invite = (
        db.query(SpaceInvitation)
        .filter(SpaceInvitation.token == token)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found or already used.")

    if current_user.email.lower() != invite.email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invite was sent to a different email address. Please log in with that account.",
        )

    space = db.query(Space).filter(Space.id == invite.space_id).first()
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")

    existing = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == current_user.id)
        .first()
    )
    if not existing:
        role_value = invite.role.value if hasattr(invite.role, "value") else str(invite.role)
        db.add(SpaceMembership(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            space_id=space.id,
            role=role_value,
            status=SpaceMembershipStatus.active,
            source="invited",
        ))

    # Delete the invite — consumed
    db.delete(invite)
    db.commit()
    return {"accepted": True, "space_slug": space.slug}


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

@router.get("/{slug}/pathways", response_model=list[PathwaySummary])
def list_pathways(
    slug: str,
    db: Session = Depends(get_db),
    current_user: "User | None" = Depends(get_optional_user),
) -> list[PathwaySummary]:
    space = _get_space_visible_to(slug, db, current_user)
    # SEC-005-E — manager visibility (see draft/archived pathways) now
    # requires admin, ownership, or active creator/moderator membership.
    # ``is_caretaker`` centralises this predicate and returns False for
    # anonymous callers.
    is_space_manager = channel_perms.is_caretaker(current_user, space, db)

    query = db.query(Pathway).filter(Pathway.space_id == space.id)
    if not is_space_manager:
        # Anonymous visitors and regular members only see published pathways (active + coming_soon)
        query = query.filter(Pathway.status.in_(["active", "coming_soon"]))

    pathways = query.order_by(Pathway.position).all()

    pathway_ids = [p.id for p in pathways]
    step_counts: dict[str, int] = {}
    if pathway_ids:
        step_counts = dict(
            db.query(PathwayStep.pathway_id, func.count(PathwayStep.id))
            .filter(PathwayStep.pathway_id.in_(pathway_ids))
            .group_by(PathwayStep.pathway_id)
            .all()
        )

    # Bulk-fetch unlock offer names for included_with_offer pathways
    unlock_offer_names_by_pathway: dict[str, list[str]] = {}
    if pathway_ids:
        rows = (
            db.query(PathwayUnlockRequirement.pathway_id, PaymentOption.name)
            .join(PaymentOption, PaymentOption.id == PathwayUnlockRequirement.payment_option_id)
            .filter(PathwayUnlockRequirement.pathway_id.in_(pathway_ids))
            .all()
        )
        for pid, name in rows:
            unlock_offer_names_by_pathway.setdefault(pid, []).append(name)

    result = []
    for p in pathways:
        has_access = _compute_pathway_access(current_user, p, space, db)
        result.append(PathwaySummary(
            id=p.id,
            slug=p.slug,
            title=p.title,
            description=p.description,
            cover_image_url=p.cover_image_url,
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            position=p.position,
            access_type=p.access_type.value if hasattr(p.access_type, "value") else str(p.access_type or "free"),
            pricing_mode=getattr(p, "pricing_mode", "legacy") or "legacy",
            price_cents=p.price_cents,
            currency=p.currency,
            billing_interval=p.billing_interval,
            pathway_type=(
                p.pathway_type.value if hasattr(p.pathway_type, "value")
                else str(p.pathway_type or "guided_experience")
            ),
            user_has_access=has_access,
            step_count=step_counts.get(p.id, 0),
            unlock_offer_names=unlock_offer_names_by_pathway.get(p.id, []),
        ))
    return result


@router.get("/{slug}/pathways-progress", response_model=list[PathwayProgress])
def list_pathways_progress(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PathwayProgress]:
    """All pathways for a space, each annotated with this user's
    completion stats.

    SEC-004: authorisation gate matches ``list_pathways`` — the caller
    must have a qualifying relationship with the Space (member,
    manager, owner, or platform admin/creator role), and non-managers
    see only pathways with ``status in ('active', 'coming_soon')``.
    Draft / archived pathways remain visible only to managers, mirroring
    the visibility rule enforced in ``list_pathways`` above.
    """
    space = _get_member_space(slug, current_user, db)

    # SEC-005-E — same predicate as ``list_pathways`` above so both
    # endpoints stay in sync. Includes platform admin, Space owner,
    # and active creator/moderator SpaceMembership.
    is_space_manager = channel_perms.is_caretaker(current_user, space, db)

    query = db.query(Pathway).filter(Pathway.space_id == space.id)
    if not is_space_manager:
        query = query.filter(Pathway.status.in_(["active", "coming_soon"]))
    pathways = query.order_by(Pathway.position).all()
    pathway_ids = [p.id for p in pathways]
    if not pathway_ids:
        return []

    step_counts: dict[str, int] = dict(
        db.query(PathwayStep.pathway_id, func.count(PathwayStep.id))
        .filter(PathwayStep.pathway_id.in_(pathway_ids))
        .group_by(PathwayStep.pathway_id)
        .all()
    )

    completed_counts: dict[str, int] = dict(
        db.query(PathwayStep.pathway_id, func.count(PathwayStep.id))
        .join(StepProgress, StepProgress.step_id == PathwayStep.id)
        .filter(
            PathwayStep.pathway_id.in_(pathway_ids),
            StepProgress.user_id == current_user.id,
            StepProgress.completed_at.isnot(None),
        )
        .group_by(PathwayStep.pathway_id)
        .all()
    )

    return [
        PathwayProgress(
            id=p.id,
            slug=p.slug,
            title=p.title,
            description=p.description,
            cover_image_url=p.cover_image_url,
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            position=p.position,
            step_count=step_counts.get(p.id, 0),
            completed_count=completed_counts.get(p.id, 0),
            access_type=p.access_type.value if hasattr(p.access_type, "value") else str(p.access_type),
            price_cents=p.price_cents,
            currency=p.currency,
            billing_interval=p.billing_interval,
        )
        for p in pathways
    ]


@router.get("/{slug}/events", response_model=list[EventSummary])
def list_events(
    slug: str,
    scope: str = "upcoming",
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[EventSummary]:
    """Published events for a space, with per-user booking state.

    `scope` (additive query param, defaults to 'upcoming'):
      - 'upcoming' — current + live-in-progress Gatherings. Excludes
                     cancelled + archived. Ordered soonest first.
      - 'archive'  — past Gatherings whose end time has passed. Includes
                     historical cancelled rows so members can revisit
                     the record. Ordered newest first.

    A Gathering is "past" when `COALESCE(ends_at, starts_at + 1h)` is
    in the past — the same 60-min fallback the detail page uses when
    ends_at is absent.
    """
    space = _get_space_or_404(slug, db)

    scope = scope if scope in ("upcoming", "archive") else "upcoming"

    # Determine if caller is a member (affects event visibility and booking access)
    is_member = False
    if current_user:
        membership = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
        is_member = bool(membership)

    now = datetime.utcnow()

    # Non-members (and anon users) only see public events; members see all
    # published. Paid-separately Gatherings are always visible externally
    # so ticket sales pages can be linked to and discovered — same rule
    # as the single-event visibility check in `get_event` above.
    base_visibility = [
        Event.space_id == space.id,
        Event.is_published.is_(True),
    ]
    if not (is_member or (current_user is not None and space.is_public)):
        base_visibility.append(
            or_(Event.is_public.is_(True), Event.booking_access_type == "paid_separately")
        )

    # end_marker = COALESCE(ends_at, starts_at + 1h) — the moment a
    # Gathering falls out of "current" and into the archive. Written
    # as SQL so filtering + ordering stay index-friendly.
    end_marker = func.coalesce(Event.ends_at, Event.starts_at + text("INTERVAL '1 hour'"))

    if scope == "upcoming":
        # Live-in-progress Gatherings stay on the main list: end > now
        # is the correct fence, not starts_at > now.
        scope_filters = [
            Event.status == "active",
            end_marker > now,
        ]
        order_by = Event.starts_at.asc()
    else:  # archive
        # Archive contains every Gathering that no longer belongs on
        # the current schedule: past by end-time OR cancelled at any
        # time. Future cancelled rows would otherwise be invisible.
        scope_filters = [
            or_(end_marker <= now, Event.status == "cancelled"),
        ]
        order_by = Event.starts_at.desc()

    events_q = db.query(Event).filter(*base_visibility, *scope_filters)
    events = events_q.order_by(order_by).all()

    # Bulk-fetch confirmed booking counts for all events in one query
    event_ids = [e.id for e in events]
    booked_counts: dict[str, int] = {}
    if event_ids:
        rows = (
            db.query(EventBooking.event_id, func.count(EventBooking.id))
            .filter(
                EventBooking.event_id.in_(event_ids),
                EventBooking.status == BookingStatus.confirmed,
            )
            .group_by(EventBooking.event_id)
            .all()
        )
        booked_counts = dict(rows)

    # Fetch current user's bookings if logged in
    user_bookings: dict[str, str] = {}  # event_id -> status
    if current_user:
        user_rows = (
            db.query(EventBooking.event_id, EventBooking.status)
            .filter(
                EventBooking.event_id.in_(event_ids),
                EventBooking.user_id == current_user.id,
            )
            .all()
        )
        user_bookings = {r.event_id: r.status.value for r in user_rows}

    # Bulk-fetch host display names. Single query keyed on creator id
    # keeps the list endpoint from doing N per-event lookups.
    host_ids = {e.created_by_id for e in events if e.created_by_id}
    host_names: dict[str, str] = {}
    if host_ids:
        rows = db.query(User.id, User.name).filter(User.id.in_(host_ids)).all()
        host_names = {uid: (name or '').strip() for uid, name in rows}

    # Bulk-fetch Series titles for events with semantic series_id.
    # One query on ids → dict lookup per row. Enables the member-side
    # "Included with {series_title}" copy without an N+1 fetch.
    from app.models.platform import EventSeries as _EventSeries
    series_ids = {getattr(e, 'series_id', None) for e in events}
    series_ids.discard(None)
    series_titles: dict[str, str] = {}
    series_slugs: dict[str, str] = {}
    series_covers: dict[str, str | None] = {}
    series_offer_slugs: dict[str, str] = {}
    if series_ids:
        rows = db.query(
            _EventSeries.id, _EventSeries.title, _EventSeries.slug,
            _EventSeries.cover_image_url,
        ).filter(_EventSeries.id.in_(series_ids)).all()
        series_titles = {sid: t for sid, t, _sl, _c in rows}
        series_slugs = {sid: sl for sid, _t, sl, _c in rows}
        series_covers = {sid: c for sid, _t, _sl, c in rows}
        # Bulk-lookup the published Offer Page (if any) targeting each
        # Series in the batch so member Gathering cards can eventually
        # send a "Buy series pass" CTA to the right public URL without
        # a per-event round-trip. Only ``published`` pages count — a
        # draft/archived page must not leak into the member API.
        offer_rows = (
            db.query(OfferPage.target_id, OfferPage.slug)
            .filter(
                OfferPage.space_id == space.id,
                OfferPage.target_kind == "event_series",
                OfferPage.target_id.in_(series_ids),
                OfferPage.status == "published",
            )
            .all()
        )
        # If a Series has multiple published Offer Pages (edge case),
        # last write wins — the frontend only needs *a* slug. Ordering
        # is intentionally unspecified.
        series_offer_slugs = {sid: sl for sid, sl in offer_rows}

    # Bulk-check the viewer's active AccessPasses for these series so
    # the booking UI can distinguish "has pass → Reserve" from "no
    # pass → explain requirement". Same window rule as the booking
    # endpoint: status active AND valid_from <= now AND (valid_until
    # NULL OR valid_until > now).
    user_series_pass_ids: set[str] = set()
    if current_user and series_ids:
        pass_rows = (
            db.query(AccessPass.eligible_series_id)
            .filter(
                AccessPass.user_id == current_user.id,
                AccessPass.eligible_series_id.in_(series_ids),
                AccessPass.status == AccessPassStatus.active,
                AccessPass.valid_from <= now,
                or_(
                    AccessPass.valid_until.is_(None),
                    AccessPass.valid_until > now,
                ),
            )
            .all()
        )
        user_series_pass_ids = {r[0] for r in pass_rows if r[0]}

    # Bulk-check pathway entitlements for the current user.
    # Collect unique required pathway IDs from pathway-gated events.
    # Post-079 vocabulary uses 'included_with_pathway'; the
    # normaliser handles any legacy rows still carrying old strings.
    from app.services.gathering_types import normalise_access_type as _norm_access
    required_pathway_ids = {
        e.booking_required_pathway_id
        for e in events
        if _norm_access(getattr(e, 'booking_access_type', None)) == 'included_with_pathway'
        and e.booking_required_pathway_id
    }
    user_pathway_access: set[str] = set()
    if current_user and required_pathway_ids:
        ent_rows = (
            db.query(PathwayEntitlement.pathway_id)
            .filter(
                PathwayEntitlement.user_id == current_user.id,
                PathwayEntitlement.pathway_id.in_(required_pathway_ids),
                PathwayEntitlement.status == EntitlementStatus.active,
            )
            .all()
        )
        user_pathway_access = {r.pathway_id for r in ent_rows}
        # Creators/moderators always have pathway access
        if membership and getattr(membership, 'role', None) in (SpaceRole.creator, SpaceRole.moderator):
            user_pathway_access = required_pathway_ids

    # Bulk-fetch active AccessPass remaining credits per pathway for the current user
    # Used to populate pass_credits_remaining on each event (member-facing credit display)
    user_pass_credits: dict[str, int | None] = {}  # pathway_id → remaining credits (None = unlimited)
    if current_user and required_pathway_ids:
        pass_rows = (
            db.query(AccessPass)
            .filter(
                AccessPass.user_id == current_user.id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
                AccessPass.eligible_pathway_id.in_(required_pathway_ids),
                or_(
                    AccessPass.valid_until.is_(None),
                    AccessPass.valid_until > now,
                ),
            )
            .all()
        )
        for ap in pass_rows:
            if ap.eligible_pathway_id:
                user_pass_credits[ap.eligible_pathway_id] = ap.remaining_credits

    result = []
    for e in events:
        booked = booked_counts.get(e.id, 0)
        spots_remaining = (e.capacity - booked) if e.capacity is not None else None
        my_status = user_bookings.get(e.id)  # 'confirmed' | 'cancelled' | None
        booking_closed = bool(e.booking_closes_at and e.booking_closes_at <= now)
        is_full = e.capacity is not None and booked >= e.capacity
        event_access_type = _norm_access(getattr(e, 'booking_access_type', None))
        required_pid = getattr(e, 'booking_required_pathway_id', None)
        # Only pathway-gated events actually depend on entitlement.
        # Everything else answers "does the user have access to the
        # required pathway" with True since no pathway is required.
        has_pathway_access = (
            event_access_type != 'included_with_pathway'
            or required_pid is None
            or required_pid in user_pathway_access
        )
        # Bookings for 'paid_separately' or 'invitation_only' aren't
        # supported in this phase — surface as un-bookable so the UI
        # can render the correct "coming soon" / "invite required"
        # message instead of a booking button.
        access_supports_booking = event_access_type in (
            'free', 'included_with_collective', 'included_with_pathway',
            'included_with_series',
        )
        # Credits remaining on the user's active AccessPass for this pathway (None = no pass or unlimited)
        pass_credits_remaining: int | None = (
            user_pass_credits.get(required_pid) if required_pid else None
        )
        # If user has an AccessPass with zero credits remaining, they cannot book
        credits_exhausted = (
            pass_credits_remaining is not None and pass_credits_remaining <= 0
        )
        # For ``included_with_series`` events, a valid Series pass is
        # required. Without it the booking endpoint would 403 — so we
        # mirror that here so the list and detail views agree on
        # ``can_book`` (list previously said True for any member,
        # producing a misleading "Reserve" CTA that the detail page
        # correctly refused).
        e_series_id = getattr(e, 'series_id', None)
        has_required_series_pass = (
            event_access_type != 'included_with_series'
            or (e_series_id is not None and e_series_id in user_series_pass_ids)
        )
        can_book = (
            e.requires_booking
            and is_member
            and access_supports_booking
            and has_pathway_access
            and has_required_series_pass
            and not credits_exhausted
            and my_status != "confirmed"
            and not booking_closed
            and not is_full
        )
        can_cancel = (
            e.requires_booking
            and is_member
            and my_status == "confirmed"
        )
        result.append(EventSummary(
            id=e.id,
            title=e.title,
            description=e.description,
            starts_at=e.starts_at,
            ends_at=e.ends_at,
            location_type=e.location_type.value if hasattr(e.location_type, "value") else str(e.location_type),
            requires_booking=e.requires_booking,
            capacity=e.capacity,
            booked_count=booked,
            spots_remaining=spots_remaining,
            booking_closes_at=e.booking_closes_at,
            booking_note=e.booking_note,
            my_booking_status=my_status,
            can_book=can_book,
            can_cancel_booking=can_cancel,
            recurrence_series_id=e.recurrence_series_id,
            recurrence_label=e.recurrence_label,
            recurrence_index=e.recurrence_index,
            recurrence_total=e.recurrence_total,
            series_id=getattr(e, 'series_id', None),
            series_title=series_titles.get(getattr(e, 'series_id', None)) if getattr(e, 'series_id', None) else None,
            series_slug=series_slugs.get(getattr(e, 'series_id', None)) if getattr(e, 'series_id', None) else None,
            series_cover_image_url=series_covers.get(getattr(e, 'series_id', None)) if getattr(e, 'series_id', None) else None,
            series_offer_page_slug=series_offer_slugs.get(getattr(e, 'series_id', None)) if getattr(e, 'series_id', None) else None,
            user_has_series_pass=(getattr(e, 'series_id', None) in user_series_pass_ids) if getattr(e, 'series_id', None) else False,
            is_public=e.is_public,
            thumbnail_url=e.thumbnail_url,
            status=e.status if e.status else "active",
            booking_access_type=event_access_type,
            booking_required_pathway_id=required_pid,
            user_has_pathway_access=has_pathway_access,
            pass_credits_remaining=pass_credits_remaining,
            gathering_type=getattr(e, 'gathering_type', 'other') or 'other',
            attendance_format=getattr(e, 'attendance_format', 'online') or 'online',
            venue_name=getattr(e, 'venue_name', None),
            venue_locality=getattr(e, 'venue_locality', None),
            host_name=host_names.get(e.created_by_id) or None,
            recording_url=e.recording_url,
            # Stage 4: standalone paid Gathering fields for the member LIST
            # endpoint. Same trust boundary as get_event — never expose
            # aggregate revenue, hold counts, or Stripe identifiers here.
            ticket_price_cents=getattr(e, 'ticket_price_cents', None),
            ticket_currency=getattr(e, 'ticket_currency', None),
            sales_enabled=bool(settings.standalone_gathering_sales_enabled),
        ))
    return result


@router.post("/{slug}/events/{event_id}/book", response_model=BookingResponse)
def book_event(
    slug: str,
    event_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingResponse:
    """Book a spot at a gathering. Members only. Enforces capacity and cutoff time."""
    space = _get_space_or_404(slug, db)

    # Community Care — a frozen collective cannot accept new bookings.
    from app.community_care.shared import is_space_closed, is_space_frozen
    if is_space_closed(space):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This collective has been closed.",
        )
    if is_space_frozen(space):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This collective is temporarily paused by Fresh Collective.",
        )

    # Must be an active member
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member to book.")

    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id, Event.is_published.is_(True))
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gathering not found.")
    if not event.requires_booking:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering does not require booking.")
    if getattr(event, 'status', 'active') == 'cancelled':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering has been cancelled.")

    # Central access gate — handles new (included_with_*, free,
    # paid_separately, invitation_only) and legacy vocabulary.
    # Returns a machine-readable reason so we surface the right
    # HTTP status. Standalone paid checkout is intentionally
    # blocked here until the ticket infrastructure lands.
    from app.services.event_permissions import can_book as _can_book_gate
    from app.services.gathering_types import normalise_access_type as _norm_access
    gate = _can_book_gate(current_user, event, space, db)
    if not gate.allowed:
        status_code = (
            status.HTTP_401_UNAUTHORIZED if gate.reason == "auth_required"
            else status.HTTP_501_NOT_IMPLEMENTED if gate.reason == "paid_separately_pending"
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=status_code, detail=gate.message)

    event_access_type = _norm_access(getattr(event, 'booking_access_type', None))
    required_pid = getattr(event, 'booking_required_pathway_id', None)
    is_privileged = getattr(membership, 'role', None) in (SpaceRole.creator, SpaceRole.moderator)

    now = datetime.utcnow()

    # --- AccessPass credit check (Phase B) ---
    # Layered on top of the existing pathway access check.
    #
    # Two eligibility mechanisms are honoured, keyed off the event's
    # ``booking_access_type`` — NOT off the mere presence of a
    # ``series_id``. A Series may exist purely for grouping /
    # presentation of ``free`` or ``included_with_collective`` events;
    # only ``included_with_series`` opts a Gathering in to term-pass
    # enforcement.
    #
    #   1. ``included_with_pathway`` — legacy. An AccessPass with
    #      ``eligible_pathway_id`` matching the event's
    #      ``booking_required_pathway_id`` authorises booking.
    #   2. ``included_with_series`` — new (migration 105). An
    #      AccessPass with ``eligible_series_id`` matching the
    #      event's ``series_id`` authorises booking. This is what a
    #      term-pass buyer holds.
    #
    # Validity window: BOTH ends are enforced (``valid_from <= now``
    # AND (``valid_until IS NULL OR valid_until > now``)). Without the
    # ``valid_from`` check a future-term pass would be usable early —
    # e.g. buying Term 4 during Term 3 would let the buyer immediately
    # book Term 3 events using the Term 4 pass. That is the behaviour
    # this branch prevents.
    #
    # ``included_with_series`` events with no matching pass are
    # rejected here (no legacy lenient fallback): "the term hasn't
    # started" and "I never bought a pass" are both correctly a
    # booking denial. ``included_with_pathway`` events keep the
    # legacy lenient fallback because a member may hold a manual
    # PathwayEntitlement without a term pass.
    #
    # Creators and moderators bypass all credit checks.
    access_pass_to_charge: AccessPass | None = None
    event_series_id: str | None = getattr(event, 'series_id', None)
    is_series_gated = event_access_type == 'included_with_series'
    is_pathway_gated = event_access_type == 'included_with_pathway' and bool(required_pid)

    credit_check_applies = not is_privileged and (is_pathway_gated or is_series_gated)

    if credit_check_applies:
        match_conditions = []
        if is_pathway_gated:
            match_conditions.append(AccessPass.eligible_pathway_id == required_pid)
        if is_series_gated and event_series_id is not None:
            match_conditions.append(AccessPass.eligible_series_id == event_series_id)

        candidate_pass = None
        if match_conditions:
            candidate_pass = (
                db.query(AccessPass)
                .filter(
                    AccessPass.user_id == current_user.id,
                    AccessPass.status == AccessPassStatus.active,
                    or_(*match_conditions),
                    AccessPass.valid_from <= now,
                    or_(
                        AccessPass.valid_until.is_(None),
                        AccessPass.valid_until > now,
                    ),
                )
                .order_by(AccessPass.created_at.desc())
                .first()
            )

        # A series-gated event with no matching pass is a hard 403 —
        # no legacy manual-entitlement fallback exists for term-scoped
        # bookings. A pathway-gated event keeps the fallback because a
        # member may hold a manual PathwayEntitlement without a pass.
        if candidate_pass is None and is_series_gated and not is_pathway_gated:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This session is part of a term. You need an active term "
                    "pass to book it (or the term may not have started yet)."
                ),
            )

        if candidate_pass is not None:
            # Hard enforce: total credits exhausted
            if (
                candidate_pass.total_credits is not None
                and candidate_pass.used_credits >= candidate_pass.total_credits
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You have no remaining sessions on your current pass.",
                )

            # Hard enforce: weekly cap
            # Uses the EVENT's starts_at week, not the booking creation time.
            # This allows a member to book sessions in multiple future weeks on
            # the same day, while still preventing two sessions in the same event week.
            if candidate_pass.credits_per_week is not None:
                # Determine the Monday of the week the target event falls in
                event_weekday = event.starts_at.weekday()  # 0=Mon … 6=Sun
                event_week_start = (event.starts_at - timedelta(days=event_weekday)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                event_week_end = event_week_start + timedelta(days=7)
                weekly_used = (
                    db.query(func.count(EventBooking.id))
                    .join(Event, EventBooking.event_id == Event.id)
                    .filter(
                        EventBooking.access_pass_id == candidate_pass.id,
                        EventBooking.status == BookingStatus.confirmed,
                        Event.starts_at >= event_week_start,
                        Event.starts_at < event_week_end,
                    )
                    .scalar()
                ) or 0
                if weekly_used >= candidate_pass.credits_per_week:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"You have reached your weekly limit of "
                            f"{candidate_pass.credits_per_week} session(s)."
                        ),
                    )

            access_pass_to_charge = candidate_pass
        # else: no AccessPass found → legacy/manual path, booking proceeds without credit tracking

    if event.starts_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering has already started.")
    if event.booking_closes_at and event.booking_closes_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking has closed for this gathering.")

    # Check capacity
    if event.capacity is not None:
        confirmed = (
            db.query(func.count(EventBooking.id))
            .filter(EventBooking.event_id == event.id, EventBooking.status == BookingStatus.confirmed)
            .scalar()
        )
        if confirmed >= event.capacity:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering is fully booked.")

    # Reactivate cancelled booking or create new
    existing = (
        db.query(EventBooking)
        .filter(EventBooking.event_id == event.id, EventBooking.user_id == current_user.id)
        .first()
    )
    if existing:
        if existing.status == BookingStatus.confirmed:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already booked.")
        existing.status = BookingStatus.confirmed
        existing.booked_at = now
        existing.cancelled_at = None
        existing.access_pass_id = access_pass_to_charge.id if access_pass_to_charge else None
        existing.credits_used = 1 if access_pass_to_charge else 0
        if access_pass_to_charge:
            access_pass_to_charge.used_credits += 1
        db.commit()
        db.refresh(existing)
        background_tasks.add_task(trigger_event_booking_creator, event.id, current_user.id)
        background_tasks.add_task(trigger_booking_confirmed, event.id, current_user.id)
        return BookingResponse(status="confirmed", booking_id=existing.id)

    booking = EventBooking(
        id=str(uuid.uuid4()),
        event_id=event.id,
        user_id=current_user.id,
        status=BookingStatus.confirmed,
        booked_at=now,
        access_pass_id=access_pass_to_charge.id if access_pass_to_charge else None,
        credits_used=1 if access_pass_to_charge else 0,
    )
    db.add(booking)
    if access_pass_to_charge:
        access_pass_to_charge.used_credits += 1
    db.commit()
    db.refresh(booking)
    background_tasks.add_task(trigger_event_booking_creator, event.id, current_user.id)
    background_tasks.add_task(trigger_booking_confirmed, event.id, current_user.id)
    return BookingResponse(status="confirmed", booking_id=booking.id)


@router.post("/{slug}/events/{event_id}/cancel-booking", response_model=BookingResponse)
def cancel_booking(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingResponse:
    """Cancel the current user's booking for a gathering."""
    space = _get_space_or_404(slug, db)
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gathering not found.")

    booking = (
        db.query(EventBooking)
        .filter(
            EventBooking.event_id == event.id,
            EventBooking.user_id == current_user.id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .first()
    )
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active booking found.")

    now = datetime.utcnow()
    booking.status = BookingStatus.cancelled
    booking.cancelled_at = now

    # Credit restoration: restore if cancelling more than 24h before gathering start
    if booking.access_pass_id and booking.credits_used > 0:
        access_pass = db.query(AccessPass).filter(AccessPass.id == booking.access_pass_id).first()
        if access_pass:
            hours_until = (event.starts_at - now).total_seconds() / 3600
            if hours_until > 24:
                access_pass.used_credits = max(0, access_pass.used_credits - booking.credits_used)

    db.commit()
    return BookingResponse(status="cancelled", booking_id=booking.id)


# ---------------------------------------------------------------------------
# Standalone paid Gathering — Stripe Checkout Session creation
#
# POST /api/spaces/{slug}/events/{event_id}/checkout
#
# Creates (or reuses) a capacity hold, then a Stripe-hosted Checkout
# Session for the ticket. Actual access is granted only when the Stripe
# webhook fires — see `app/services/gathering_tickets.fulfil_ticket_purchase`.
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field, HttpUrl  # noqa: E402
import stripe as _stripe  # noqa: E402
from app.services import gathering_tickets as _gt  # noqa: E402
from app.checkout.routes import _resolve_fee_bps as _resolve_fee_bps_for_ticket  # noqa: E402


class GatheringCheckoutRequest(BaseModel):
    success_url: HttpUrl = Field(..., description="Where Stripe returns the buyer on success.")
    cancel_url: HttpUrl = Field(..., description="Where Stripe returns the buyer on cancel.")


class GatheringCheckoutResponse(BaseModel):
    checkout_url: str
    transaction_id: str
    reused: bool = Field(
        False,
        description="True when we returned an existing in-flight Checkout URL "
                    "rather than creating a new Session.",
    )


def _map_ticket_error(exc: _gt.TicketCheckoutError) -> HTTPException:
    return HTTPException(status_code=exc.http_status,
                         detail={"code": exc.code, "message": exc.message})


@router.post(
    "/{slug}/events/{event_id}/checkout",
    response_model=GatheringCheckoutResponse,
)
def create_gathering_ticket_checkout(
    slug: str,
    event_id: str,
    body: GatheringCheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GatheringCheckoutResponse:
    """
    Stripe-hosted Checkout for a standalone paid Gathering ticket.

    Trust boundary: **every** price, currency, and user identity is
    loaded from the database. The request body only carries the
    caller-provided success/cancel URLs. See services/gathering_tickets.py
    for the invariants this endpoint enforces.
    """
    try:
        _gt.ensure_sales_enabled_or_raise()
    except _gt.TicketCheckoutError as exc:
        raise _map_ticket_error(exc)

    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "stripe_not_configured",
                    "message": "Stripe is not configured on this environment."},
        )

    # 1. Load + validate the trusted offer
    try:
        offer = _gt.load_and_validate_offer(db, slug, event_id)
    except _gt.TicketCheckoutError as exc:
        raise _map_ticket_error(exc)

    # 2. Fast path: user already has a live hold — return the existing
    #    Session URL rather than creating a new one.
    active = _gt._existing_active_hold(db, offer.event.id, current_user.id)
    if active is not None and active.payment_transaction_id:
        txn = db.get(PaymentTransaction, active.payment_transaction_id)
        if txn and txn.status == PaymentTransactionStatus.pending and txn.provider_checkout_url:
            return GatheringCheckoutResponse(
                checkout_url=txn.provider_checkout_url,
                transaction_id=txn.id,
                reused=True,
            )
        # Hold exists but no URL recorded (crash between txn insert and
        # Stripe response). Fall through: create a fresh Session and
        # UPDATE-reuse the row via `create_or_reuse_hold`.

    # 3. Resolve creator fee — same helper as pathway checkout
    fee_bps, plan_id, sub_id = _resolve_fee_bps_for_ticket(offer.space.creator_id, db)

    # 4. Create (or UPDATE-reuse) the hold + pending transaction, in one lock.
    try:
        outcome = _gt.create_or_reuse_hold(
            db,
            offer=offer,
            buyer=current_user,
            fee_bps=fee_bps,
            creator_plan_id=plan_id,
            creator_subscription_id=sub_id,
            hold_ttl_minutes=settings.gathering_checkout_expiry_minutes,
        )
    except _gt.TicketCheckoutError as exc:
        raise _map_ticket_error(exc)

    # 5. Create the Stripe Checkout Session. If this fails, we roll back
    #    the hold+txn so no dangling capacity is consumed.
    _stripe.api_key = settings.stripe_secret_key
    session_lifetime_seconds = settings.gathering_checkout_expiry_minutes * 60
    try:
        session = _stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            customer_email=current_user.email,
            # Naive datetime.utcnow().timestamp() treats the value as local
            # time — on a non-UTC host (this dev box is Australia/Melbourne)
            # that puts the epoch several hours off and Stripe rejects the
            # request as `expires_at is in the past`. Mark the value as UTC
            # explicitly before converting to an epoch integer.
            expires_at=int(
                (datetime.utcnow() + timedelta(seconds=session_lifetime_seconds))
                .replace(tzinfo=timezone.utc)
                .timestamp()
            ),
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": offer.currency.lower(),
                    "unit_amount": offer.price_cents,
                    "product_data": {
                        "name": offer.event.title,
                        "description": (
                            f"Ticket for {offer.event.title} "
                            f"— {offer.space.name}"
                        )[:500],
                    },
                },
            }],
            success_url=str(body.success_url),
            cancel_url=str(body.cancel_url),
            metadata={
                "purchase_type":    "standalone_gathering",
                "transaction_id":   outcome.transaction.id,
                "event_id":         offer.event.id,
                "space_id":         offer.space.id,
                "payer_user_id":    current_user.id,
                "creator_user_id":  offer.space.creator_id or "",
                "platform_fee_bps": str(fee_bps),
                "creator_plan_id":  plan_id or "",
            },
            payment_intent_data={
                "metadata": {
                    "purchase_type":  "standalone_gathering",
                    "transaction_id": outcome.transaction.id,
                    "event_id":       offer.event.id,
                    "payer_user_id":  current_user.id,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 — Stripe errors are broad
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail={"code": "stripe_error",
                    "message": "Could not open Stripe Checkout. Please try again."},
        ) from exc

    # 6. Persist Stripe refs onto the pending PaymentTransaction.
    outcome.transaction.provider_checkout_session_id = session.id
    outcome.transaction.provider_checkout_url = session.url

    db.commit()
    return GatheringCheckoutResponse(
        checkout_url=session.url,
        transaction_id=outcome.transaction.id,
        reused=False,
    )


# NOTE for future maintainers: refunds / dispute revocation are NOT
# implemented. A manual Stripe refund does NOT release the seat or
# revoke the AccessPass — this is a documented MVP gap.


@router.get("/{slug}/my-passes", response_model=list[AccessPassOut])
def get_my_passes(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list:
    """Return the current user's active AccessPasses for this space."""
    space = _get_space_visible_to(slug, db, current_user)
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member.")

    now = datetime.utcnow()
    passes = (
        db.query(AccessPass)
        .filter(
            AccessPass.user_id == current_user.id,
            AccessPass.space_id == space.id,
            AccessPass.status == AccessPassStatus.active,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .order_by(AccessPass.created_at.desc())
        .all()
    )

    from app.models.payment_option import PaymentOption as _PO
    results = []
    for ap in passes:
        opt_name = None
        if ap.payment_option_id:
            opt = db.query(_PO).filter(_PO.id == ap.payment_option_id).first()
            if opt:
                opt_name = opt.name
        results.append(AccessPassOut(
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
            option_name=opt_name,
            pathway_title=None,
            created_at=ap.created_at,
        ))
    return results


@router.get("/{slug}/events/{event_id}", response_model=EventDetail)
def get_event(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> dict:
    """Return a single published event by ID within a space, with booking state."""
    space = _get_space_or_404(slug, db)
    event = (
        db.query(Event)
        .filter(
            Event.id == event_id,
            Event.space_id == space.id,
            Event.is_published.is_(True),
        )
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    # Non-members can only see public events. The membership row is
    # kept alongside the boolean so the caretaker check further down
    # can read its role without a second query.
    membership: SpaceMembership | None = None
    if current_user:
        membership = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
    is_member = membership is not None
    # Paid-separately Gatherings are effectively-public for the purpose of
    # this visibility check — non-members with the URL must be able to see
    # the price + purchase panel. Members-only events (any other access
    # type) still require `is_public=True` to be visible externally.
    _paid_event = getattr(event, 'booking_access_type', None) == 'paid_separately'
    if not is_member and not event.is_public and not _paid_event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    now = datetime.utcnow()
    is_past = bool(event.ends_at and event.ends_at < now) or (not event.ends_at and event.starts_at < now)

    booked_count = 0
    my_booking_status = None
    is_paid_event = getattr(event, 'booking_access_type', None) == 'paid_separately'
    if event.requires_booking:
        # For paid Gatherings, capacity math must include non-expired
        # `pending_payment` holds so a member can't see "1 remaining"
        # while another buyer holds that seat inside Stripe Checkout.
        # Free/included/pathway/invitation events never generate holds,
        # so the confirmed-only count is unchanged for them.
        if is_paid_event:
            booked_count = int(db.execute(text("""
                SELECT COUNT(*) FROM event_bookings
                WHERE event_id = :e
                  AND (status = 'confirmed'
                       OR (status = 'pending_payment' AND hold_expires_at > timezone('UTC', NOW())))
            """), {"e": event.id}).scalar_one())
        else:
            booked_count = (
                db.query(func.count(EventBooking.id))
                .filter(EventBooking.event_id == event.id, EventBooking.status == BookingStatus.confirmed)
                .scalar()
            ) or 0
        if current_user:
            my_row = (
                db.query(EventBooking)
                .filter(EventBooking.event_id == event.id, EventBooking.user_id == current_user.id)
                .first()
            )
            if my_row:
                my_booking_status = my_row.status.value if hasattr(my_row.status, "value") else my_row.status

    spots_remaining = None
    if event.capacity is not None:
        spots_remaining = max(0, event.capacity - booked_count)

    event_status = getattr(event, 'status', 'active') or 'active'
    is_cancelled = event_status == 'cancelled'

    # Pathway access restriction
    from app.services.gathering_types import normalise_access_type as _norm_access
    event_access_type = _norm_access(getattr(event, 'booking_access_type', None))
    required_pid = getattr(event, 'booking_required_pathway_id', None)
    user_has_pathway_access = True
    if event_access_type == 'included_with_pathway' and required_pid and current_user:
        # Creators/moderators always have access
        if is_member and (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        ):
            user_has_pathway_access = True
        else:
            ent = (
                db.query(PathwayEntitlement)
                .filter(
                    PathwayEntitlement.user_id == current_user.id,
                    PathwayEntitlement.pathway_id == required_pid,
                    PathwayEntitlement.status == EntitlementStatus.active,
                )
                .first()
            )
            user_has_pathway_access = bool(ent)

    # 'paid_separately' / 'invitation_only' access types don't yet
    # support in-app booking (ticket sales + invites are follow-ups).
    # ``included_with_series`` DOES: the booking endpoint validates a
    # matching AccessPass at commit time; here we let the request
    # reach the endpoint so the client can render a Reserve CTA that
    # will either succeed (pass holder) or fail with a clear
    # "Series pass required" message rather than the CTA never
    # rendering at all.
    access_supports_booking = event_access_type in (
        'free', 'included_with_collective', 'included_with_pathway',
        'included_with_series',
    )
    # For ``included_with_series`` events a valid Series pass is
    # required — surface that in ``can_book`` so the list and detail
    # views agree. Without this the detail would show a "Reserve"
    # CTA that the booking endpoint would reject.
    event_series_id_for_pass = getattr(event, 'series_id', None)
    has_required_series_pass = (
        event_access_type != 'included_with_series'
        or _viewer_has_series_pass(current_user, event_series_id_for_pass, db, now)
    )
    booking_open = (
        event.requires_booking
        and not is_past
        and not is_cancelled
        and is_member
        and access_supports_booking
        and user_has_pathway_access
        and has_required_series_pass
        and (event.booking_closes_at is None or event.booking_closes_at > now)
    )
    can_book = booking_open and my_booking_status != "confirmed" and (spots_remaining is None or spots_remaining > 0)
    can_cancel_booking = bool(not is_past and not is_cancelled and my_booking_status == "confirmed")

    # Sensitive detail visibility — confirmed attendees + caretakers
    # see meeting URL, full venue address, and arrival instructions.
    # Everyone else sees only the venue name as a rough locator.
    # SEC-005-E: caretaker is now admin OR Space owner OR active
    # creator/moderator membership. Platform ``creator`` role alone
    # no longer surfaces sensitive event detail for other creators'
    # gatherings.
    is_caretaker = channel_perms.is_caretaker(current_user, space, db)
    has_confirmed_booking = my_booking_status == "confirmed"
    show_sensitive = bool(is_caretaker or has_confirmed_booking)

    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "location_type": event.location_type.value if hasattr(event.location_type, "value") else str(event.location_type),
        "location_url": event.location_url if show_sensitive else None,
        # Replay: visible to caretakers, active members, AND paid-ticket
        # holders (confirmed booking). Same shape as `show_sensitive` but
        # additionally allows any active member of the Collective — the
        # existing pre-Stage-4 behaviour for included-with-collective
        # Gatherings, preserved here.
        "recording_url": event.recording_url if (show_sensitive or is_member) else None,
        "requires_booking": event.requires_booking,
        "capacity": event.capacity,
        "booked_count": booked_count,
        "spots_remaining": spots_remaining,
        "booking_closes_at": event.booking_closes_at,
        "booking_note": event.booking_note,
        "my_booking_status": my_booking_status,
        "can_book": can_book,
        "can_cancel_booking": can_cancel_booking,
        "recurrence_series_id": event.recurrence_series_id,
        "recurrence_label": event.recurrence_label,
        "recurrence_index": event.recurrence_index,
        "recurrence_total": event.recurrence_total,
        # Semantic series membership + title lookup for the public
        # "Included with {Series title}" copy. Single ID lookup; N+1
        # is not a concern for a per-Event detail page.
        "series_id": getattr(event, 'series_id', None),
        **(lambda t: {"series_title": t[0], "series_slug": t[1], "series_cover_image_url": t[2]})(_series_info_for(event, db)),
        "series_offer_page_slug": (
            (db.query(OfferPage.slug)
                .filter(
                    OfferPage.space_id == space.id,
                    OfferPage.target_kind == "event_series",
                    OfferPage.target_id == event.series_id,
                    OfferPage.status == "published",
                )
                .scalar())
            if getattr(event, 'series_id', None) else None
        ),
        "user_has_series_pass": _viewer_has_series_pass(
            current_user, getattr(event, 'series_id', None), db, now,
        ),
        "is_public": event.is_public,
        "thumbnail_url": event.thumbnail_url,
        "status": event_status,
        "booking_access_type": event_access_type,
        "booking_required_pathway_id": required_pid,
        "user_has_pathway_access": user_has_pathway_access,
        # Gatherings 2.0 vocabulary + safe venue exposure.
        "gathering_type": getattr(event, 'gathering_type', 'other') or 'other',
        "attendance_format": getattr(event, 'attendance_format', 'online') or 'online',
        "venue_name": getattr(event, 'venue_name', None),
        "venue_address": getattr(event, 'venue_address', None) if show_sensitive else None,
        # Member-safe locality (suburb + region). Explicit Creator-
        # controlled column since migration 114 — always exposed.
        # The full ``venue_address`` above stays behind the attendee
        # gate; the two fields are independent.
        "venue_locality": getattr(event, 'venue_locality', None),
        "access_instructions": getattr(event, 'access_instructions', None) if show_sensitive else None,
        "host_name": (
            (db.query(User.name).filter(User.id == event.created_by_id).scalar() or '').strip() or None
            if event.created_by_id else None
        ),
        # Stage 4: standalone paid Gathering fields for members.
        # Ticket price + currency are null for non-paid events. `sales_enabled`
        # mirrors the feature flag so the member UI can render "Ticket sales
        # aren't open yet" rather than a Buy button that would 503.
        # Never exposes Stripe identifiers, aggregate revenue, hold counts,
        # or completed-sale flags — those are creator-only.
        "ticket_price_cents": getattr(event, 'ticket_price_cents', None),
        "ticket_currency": getattr(event, 'ticket_currency', None),
        "sales_enabled": bool(settings.standalone_gathering_sales_enabled),
    }


@router.post("/{slug}/events/series/{series_id}/book", response_model=SeriesBookingResponse)
def book_series(
    slug: str,
    series_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeriesBookingResponse:
    """Book all future bookable sessions in a recurrence series. Skips full/closed/already-booked."""
    space = _get_space_or_404(slug, db)
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be a member to book.")

    now = datetime.utcnow()
    events = (
        db.query(Event)
        .filter(
            Event.space_id == space.id,
            Event.recurrence_series_id == series_id,
            Event.is_published.is_(True),
            Event.requires_booking.is_(True),
            Event.status == "active",
            Event.starts_at > now,
        )
        .order_by(Event.starts_at)
        .all()
    )
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No upcoming bookable sessions in this series.")

    event_ids = [e.id for e in events]
    confirmed_counts: dict[str, int] = dict(
        db.query(EventBooking.event_id, func.count(EventBooking.id))
        .filter(EventBooking.event_id.in_(event_ids), EventBooking.status == BookingStatus.confirmed)
        .group_by(EventBooking.event_id)
        .all()
    )
    existing_bookings: dict[str, "EventBooking"] = {
        b.event_id: b
        for b in db.query(EventBooking).filter(
            EventBooking.event_id.in_(event_ids),
            EventBooking.user_id == current_user.id,
        ).all()
    }

    booked = 0
    already_booked = 0
    skipped_full = 0
    skipped_closed = 0

    for e in events:
        existing = existing_bookings.get(e.id)
        if existing and existing.status == BookingStatus.confirmed:
            already_booked += 1
            continue
        if e.booking_closes_at and e.booking_closes_at <= now:
            skipped_closed += 1
            continue
        confirmed = confirmed_counts.get(e.id, 0)
        if e.capacity is not None and confirmed >= e.capacity:
            skipped_full += 1
            continue

        if existing:
            existing.status = BookingStatus.confirmed
            existing.booked_at = now
            existing.cancelled_at = None
        else:
            db.add(EventBooking(
                id=str(uuid.uuid4()),
                event_id=e.id,
                user_id=current_user.id,
                status=BookingStatus.confirmed,
                booked_at=now,
            ))
        booked += 1

    db.commit()
    return SeriesBookingResponse(
        booked=booked,
        already_booked=already_booked,
        skipped_full=skipped_full,
        skipped_closed=skipped_closed,
        total_in_series=len(events),
    )


@router.get("/{slug}/events/{event_id}/calendar.ics")
def download_ics(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Download an iCalendar (.ics) file for a gathering. Available for public events or members."""
    from fastapi.responses import Response

    space = _get_space_or_404(slug, db)
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id, Event.is_published.is_(True))
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    is_member = False
    if current_user:
        is_member = bool(
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == current_user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == SpaceMembershipStatus.active,
            )
            .first()
        )
    if not is_member and not event.is_public:
        raise HTTPException(status_code=404, detail="Event not found.")
    if getattr(event, 'status', 'active') == 'cancelled':
        raise HTTPException(status_code=410, detail="This event has been cancelled.")

    def fmt_ics_dt(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")

    starts = fmt_ics_dt(event.starts_at)
    if event.ends_at:
        ends = fmt_ics_dt(event.ends_at)
    else:
        from datetime import timedelta
        ends = fmt_ics_dt(event.starts_at + timedelta(hours=1))

    location = event.location_url or ""
    description = (event.description or "").replace("\n", "\\n")
    event_url = f"https://fresh.community/spaces/{slug}/events/{event.id}"
    uid = f"{event.id}@fresh.community"

    ics = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Fresh Collective//Gatherings//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART:{starts}",
        f"DTEND:{ends}",
        f"SUMMARY:{event.title}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{location}",
        f"URL:{event_url}",
        "END:VEVENT",
        "END:VCALENDAR",
    ])

    safe_title = "".join(c for c in event.title if c.isalnum() or c in " -_").strip().replace(" ", "-")
    filename = f"{safe_title or 'gathering'}.ics"
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Space Resources (member-facing) — RETIRED.
#
# Members no longer browse a raw list of resources. Creators surface
# resources through Pathways instead (Guided Experiences or Knowledge
# Guides), embedding Library items as ``resource`` blocks. The member
# ``/api/spaces/{slug}/resources`` endpoint has been removed; any
# stale client hitting it now sees a 404. The underlying
# ``SpaceResource`` table is unchanged — it powers the creator-only
# Library alongside ``CreatorMediaAsset``.

@router.get("/{slug}/pathways/{pathway_slug}", response_model=PathwaySummary)
def get_pathway(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PathwaySummary:
    space = _get_space_or_404(slug, db)
    p = _get_pathway_or_404(space.id, pathway_slug, db)
    unlock_offer_names = [
        row.name
        for row in db.query(PaymentOption.name)
        .join(PathwayUnlockRequirement, PathwayUnlockRequirement.payment_option_id == PaymentOption.id)
        .filter(PathwayUnlockRequirement.pathway_id == p.id)
        .all()
    ]
    return PathwaySummary(
        id=p.id,
        slug=p.slug,
        title=p.title,
        description=p.description,
        cover_image_url=p.cover_image_url,
        status=p.status.value if hasattr(p.status, "value") else str(p.status),
        position=p.position,
        access_type=p.access_type.value if hasattr(p.access_type, "value") else str(p.access_type or "free"),
        pricing_mode=getattr(p, "pricing_mode", "legacy") or "legacy",
        price_cents=p.price_cents,
        currency=p.currency,
        billing_interval=p.billing_interval,
        pathway_type=(
            p.pathway_type.value if hasattr(p.pathway_type, "value")
            else str(p.pathway_type or "guided_experience")
        ),
        user_has_access=_compute_pathway_access(current_user, p, space, db),
        step_count=db.query(func.count(PathwayStep.id)).filter(PathwayStep.pathway_id == p.id).scalar() or 0,
        unlock_offer_names=unlock_offer_names,
    )


@router.get("/{slug}/pathways/{pathway_slug}/overview", response_model=PathwayWithSteps)
def get_pathway_overview(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: "User | None" = Depends(get_optional_user),
) -> PathwayWithSteps:
    """Pathway detail with ordered steps and this user's completion state."""
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)

    steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )

    step_ids = [s.id for s in steps]
    completed = _completed_step_ids(current_user.id, step_ids, db) if current_user else set()

    # Drip-release availability for this member; skipped when unauthenticated.
    availability_by_id: dict[str, Availability] = (
        _hydrate_step_availability(steps, pathway.id, current_user.id, db)
        if current_user else {}
    )

    step_summaries = [
        StepSummary(
            id=s.id,
            slug=s.slug,
            title=s.title,
            content_type=s.content_type.value if hasattr(s.content_type, "value") else str(s.content_type),
            estimated_minutes=s.estimated_minutes,
            is_required=s.is_required,
            position=s.position,
            is_completed=s.id in completed,
            banner_image_url=s.banner_image_url,
            availability=_availability_to_schema(
                s, availability_by_id.get(s.id, Availability(False, None, None, None)),
            ),
        )
        for s in steps
    ]

    # Build section groupings (only if pathway has sections defined)
    db_sections = (
        db.query(PathwaySection)
        .filter(PathwaySection.pathway_id == pathway.id)
        .order_by(PathwaySection.position)
        .all()
    )
    summary_by_id = {s.id: s for s in step_summaries}
    sections = []
    for sec in db_sections:
        sec_steps = (
            db.query(PathwayStep)
            .filter(PathwayStep.section_id == sec.id)
            .order_by(PathwayStep.section_position.nulls_last(), PathwayStep.position)
            .all()
        )
        sections.append(SectionWithSteps(
            id=sec.id,
            slug=_section_slug(sec),
            title=sec.title,
            position=sec.position,
            steps=[summary_by_id[s.id] for s in sec_steps if s.id in summary_by_id],
            banner_image_url=sec.banner_image_url,
        ))

    user_has_access = _compute_pathway_access(current_user, pathway, space, db)

    published_options = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.pathway_id == pathway.id,
            PaymentOption.status == "published",
        )
        .order_by(PaymentOption.position)
        .all()
    )

    # Fetch published schedules for each option in one query
    opt_ids = [o.id for o in published_options]
    schedules_by_opt: dict[str, list[PaymentOptionSchedule]] = {oid: [] for oid in opt_ids}
    if opt_ids:
        pub_schedules = (
            db.query(PaymentOptionSchedule)
            .filter(
                PaymentOptionSchedule.payment_option_id.in_(opt_ids),
                PaymentOptionSchedule.status == "published",
            )
            .order_by(PaymentOptionSchedule.position)
            .all()
        )
        for s in pub_schedules:
            schedules_by_opt[s.payment_option_id].append(s)

    option_summaries = [
        PaymentOptionSummary(
            id=opt.id,
            name=opt.name,
            description=opt.description,
            payment_type=opt.payment_type.value if hasattr(opt.payment_type, "value") else str(opt.payment_type),
            status=opt.status.value if hasattr(opt.status, "value") else str(opt.status),
            term_start_date=opt.term_start_date,
            term_end_date=opt.term_end_date,
            sessions_per_week=opt.sessions_per_week,
            total_sessions=opt.total_sessions,
            price_per_session_cents=opt.price_per_session_cents,
            calculated_total_cents=opt.calculated_total_cents,
            override_total_cents=opt.override_total_cents,
            effective_price_cents=opt.effective_price_cents,
            currency=opt.currency,
            buyer_note=opt.buyer_note,
            position=opt.position,
            schedules=[
                PaymentOptionScheduleSummary(
                    id=s.id,
                    name=s.name,
                    description=s.description,
                    schedule_type=s.schedule_type,
                    status=s.status,
                    total_amount_cents=s.total_amount_cents,
                    installment_amount_cents=s.installment_amount_cents,
                    installment_count=s.installment_count,
                    # Prefer the creator-authored human ``interval``
                    # ('weekly' / 'fortnightly' / 'monthly'); fall back
                    # to the Stripe-compatible ``stripe_interval``
                    # ('week' / 'month') when the human field wasn't
                    # populated (older rows / operator-created test
                    # data). The frontend humanises either shape via
                    # ``lib/paymentPlan.humanCadence`` so members never
                    # see the generic "recurring" fallback when we
                    # actually know the cadence.
                    interval=s.interval or s.stripe_interval,
                    currency=s.currency,
                    buyer_note=s.buyer_note,
                    position=s.position,
                    is_member_checkoutable=_schedule_is_member_checkoutable(s, opt),
                )
                for s in schedules_by_opt.get(opt.id, [])
            ],
        )
        for opt in published_options
    ]

    return PathwayWithSteps(
        id=pathway.id,
        slug=pathway.slug,
        title=pathway.title,
        description=pathway.description,
        cover_image_url=pathway.cover_image_url,
        status=pathway.status.value if hasattr(pathway.status, "value") else str(pathway.status),
        step_count=len(steps),
        completed_count=len(completed),
        steps=step_summaries,
        sections=sections,
        access_type=pathway.access_type.value if hasattr(pathway.access_type, "value") else str(pathway.access_type),
        pricing_mode=getattr(pathway, "pricing_mode", "legacy") or "legacy",
        price_cents=pathway.price_cents,
        currency=pathway.currency,
        billing_interval=pathway.billing_interval,
        pathway_type=(
            pathway.pathway_type.value if hasattr(pathway.pathway_type, "value")
            else str(pathway.pathway_type or "guided_experience")
        ),
        user_has_access=user_has_access,
        payment_options=option_summaries,
        member_plan_state=_pathway_member_plan_state(current_user, pathway.id, db),
    )


def _pathway_member_plan_state(current_user, pathway_id: str, db):
    """FIP4B1 — surface a payment-plan recovery banner state on the
    pathway detail response when the current viewer holds a finite
    plan for this pathway that needs their attention."""
    if current_user is None:
        return None
    from app.services.member_plan_state import (
        build_member_plan_state, find_recovery_plan_for_pathway,
    )
    plan = find_recovery_plan_for_pathway(db, user=current_user, pathway_id=pathway_id)
    if plan is None:
        return None
    return build_member_plan_state(db, plan)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@router.get("/{slug}/pathways/{pathway_slug}/steps", response_model=list[StepSummary])
def list_steps(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StepSummary]:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)

    steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )

    step_ids = [s.id for s in steps]
    completed = _completed_step_ids(current_user.id, step_ids, db)

    availability_by_id = _hydrate_step_availability(steps, pathway.id, current_user.id, db)

    return [
        StepSummary(
            id=s.id,
            slug=s.slug,
            title=s.title,
            content_type=s.content_type.value if hasattr(s.content_type, "value") else str(s.content_type),
            estimated_minutes=s.estimated_minutes,
            is_required=s.is_required,
            position=s.position,
            is_completed=s.id in completed,
            banner_image_url=s.banner_image_url,
            availability=_availability_to_schema(
                s, availability_by_id.get(s.id, Availability(False, None, None, None)),
            ),
        )
        for s in steps
    ]


@router.get("/{slug}/pathways/{pathway_slug}/steps/{step_slug}", response_model=StepDetail)
def get_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StepDetail:
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    # Compute availability for this member. If the step is locked, hide
    # the body but return the availability info as structured JSON so the
    # frontend can render a calm "Waiting" panel rather than a 404.
    all_steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )
    availability_by_id = _hydrate_step_availability(all_steps, pathway.id, current_user.id, db)
    availability = availability_by_id.get(step.id, Availability(False, None, None, None))

    progress = (
        db.query(StepProgress)
        .filter(
            StepProgress.user_id == current_user.id,
            StepProgress.step_id == step.id,
        )
        .first()
    )

    # Section banner / title — populated for EVERY step that belongs to a
    # section, so the member step page can show a consistent week-level banner
    # across all lessons in the section. Steps outside any section get None.
    section_banner_image_url: str | None = None
    section_title: str | None = None
    if step.section_id:
        section = db.query(PathwaySection).filter(PathwaySection.id == step.section_id).first()
        if section:
            section_banner_image_url = section.banner_image_url
            section_title = section.title

    availability_schema = _availability_to_schema(step, availability)
    # Strip the reading body from locked steps so the frontend can't
    # accidentally leak content by rendering a hidden div.
    if availability.is_locked:
        content_body = None
        content_url = None
    else:
        content_body = step.content_body
        content_url = step.content_url

    return StepDetail(
        id=step.id,
        slug=step.slug,
        title=step.title,
        content_type=step.content_type.value if hasattr(step.content_type, "value") else str(step.content_type),
        content_body=content_body,
        content_url=content_url,
        estimated_minutes=step.estimated_minutes,
        is_required=step.is_required,
        position=step.position,
        is_completed=progress is not None and progress.completed_at is not None,
        reflection_text=progress.reflection_text if progress else None,
        reflection_enabled=step.reflection_enabled,
        discussion_enabled=step.discussion_enabled,
        banner_image_url=step.banner_image_url,
        section_banner_image_url=section_banner_image_url,
        section_title=section_title,
        availability=availability_schema,
    )


def _reject_if_knowledge_guide(pathway: Pathway) -> None:
    """Guard endpoints that don't apply to Knowledge Guide pathways.

    Knowledge Guides deliberately have no progress or completion — the
    frontend never renders "Mark complete", so a request landing here
    is either stale client state or a scripted call. Refuse it rather
    than silently creating a meaningless StepProgress row.
    """
    ptype = getattr(pathway, "pathway_type", None)
    ptype_val = ptype.value if hasattr(ptype, "value") else str(ptype or "")
    if ptype_val == "knowledge_guide":
        raise HTTPException(
            status_code=409,
            detail="Knowledge Guide pathways do not track step completion.",
        )


@router.post(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/complete",
    response_model=CompleteStepResponse,
)
def complete_step(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: CompleteStepRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompleteStepResponse:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _reject_if_knowledge_guide(pathway)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    _ensure_enrollment(current_user.id, pathway.id, db)

    # A locked step cannot be marked complete — a caretaker (or the
    # release schedule) has to open it first. Enforced at the API even
    # though the frontend hides the button, so a scripted request can't
    # sneak past the gate.
    all_steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )
    availability_by_id = _hydrate_step_availability(
        all_steps, pathway.id, current_user.id, db,
    )
    if availability_by_id.get(step.id, Availability(False, None, None, None)).is_locked:
        raise HTTPException(status_code=403, detail="This step is not yet available.")

    progress = (
        db.query(StepProgress)
        .filter(
            StepProgress.user_id == current_user.id,
            StepProgress.step_id == step.id,
        )
        .first()
    )

    if progress:
        progress.completed_at = datetime.utcnow()
        if body.reflection_text is not None:
            progress.reflection_text = body.reflection_text
    else:
        db.add(StepProgress(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            step_id=step.id,
            completed_at=datetime.utcnow(),
            reflection_text=body.reflection_text,
        ))

    db.commit()
    return CompleteStepResponse(is_completed=True)


@router.patch(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/notes",
    response_model=SaveNotesResponse,
)
def save_notes(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: SaveNotesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SaveNotesResponse:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    progress = (
        db.query(StepProgress)
        .filter(
            StepProgress.user_id == current_user.id,
            StepProgress.step_id == step.id,
        )
        .first()
    )

    if progress:
        progress.reflection_text = body.reflection_text
    else:
        # Create a draft progress record (completed_at stays NULL)
        db.add(StepProgress(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            step_id=step.id,
            completed_at=None,
            reflection_text=body.reflection_text,
        ))

    db.commit()
    return SaveNotesResponse(saved=True)


@router.get(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/resources",
    response_model=list[StepResourceResponse],
)
def list_step_resources(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StepResource]:
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)
    return (
        db.query(StepResource)
        .filter(StepResource.step_id == step.id)
        .order_by(StepResource.position)
        .all()
    )


@router.get(
    "/{slug}/pathways/{pathway_slug}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def list_pathway_about_blocks(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: "User | None" = Depends(get_optional_user),
) -> list[PathwayAboutBlock]:
    """Return about-page blocks for a pathway.

    Public — locked and anonymous visitors can view the About page as a preview/sales page.
    """
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
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


@router.get(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/blocks",
    response_model=list[StepBlockResponse],
)
def list_step_blocks(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PathwayStepBlock]:
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)
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


# ---------------------------------------------------------------------------
# Knowledge Guide — continuous document view
# ---------------------------------------------------------------------------

@router.get(
    "/{slug}/pathways/{pathway_slug}/guide",
    response_model=KnowledgeGuideResponse,
)
def get_knowledge_guide(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeGuideResponse:
    """Return every section, step, and block for a Knowledge Guide in
    one round trip so the frontend can render a single continuous
    document without per-step network calls.

    Refuses (409) for Guided Experience pathways so a stale client
    doesn't get half-loaded content — those pathways use the existing
    per-step endpoints.
    """
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)

    ptype = getattr(pathway, "pathway_type", None)
    ptype_val = ptype.value if hasattr(ptype, "value") else str(ptype or "")
    if ptype_val != "knowledge_guide":
        raise HTTPException(
            status_code=409,
            detail="This endpoint is only valid for Knowledge Guide pathways.",
        )

    # One query for every step in the pathway; a second for every
    # block. Both bounded by pathway_id so the payload can't be
    # inflated by another Collective's data.
    steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(
            PathwayStep.section_id.nulls_first(),
            PathwayStep.section_position.nulls_last(),
            PathwayStep.position,
        )
        .all()
    )

    step_ids = [s.id for s in steps]
    blocks_by_step: dict[str, list[PathwayStepBlock]] = {sid: [] for sid in step_ids}
    if step_ids:
        block_rows = (
            db.query(PathwayStepBlock)
            .options(
                selectinload(PathwayStepBlock.media_asset),
                selectinload(PathwayStepBlock.resource),
            )
            .filter(PathwayStepBlock.step_id.in_(step_ids))
            .order_by(PathwayStepBlock.position)
            .all()
        )
        for b in block_rows:
            blocks_by_step.setdefault(b.step_id, []).append(b)

    def _serialize_step(step: PathwayStep) -> GuideStep:
        return GuideStep(
            id=step.id,
            slug=step.slug,
            title=step.title,
            blocks=[
                StepBlockResponse.model_validate(b).model_dump(mode="json")
                for b in blocks_by_step.get(step.id, [])
            ],
        )

    # Section-less steps land in `orphan_steps` so a KG author who has
    # not yet organised into chapters still gets a usable document.
    orphan_steps = [_serialize_step(s) for s in steps if s.section_id is None]

    db_sections = (
        db.query(PathwaySection)
        .filter(PathwaySection.pathway_id == pathway.id)
        .order_by(PathwaySection.position)
        .all()
    )
    steps_by_section: dict[str, list[PathwayStep]] = {sec.id: [] for sec in db_sections}
    for s in steps:
        if s.section_id and s.section_id in steps_by_section:
            steps_by_section[s.section_id].append(s)

    sections = [
        GuideSection(
            id=sec.id,
            slug=_section_slug(sec),
            title=sec.title,
            banner_image_url=sec.banner_image_url,
            steps=[_serialize_step(s) for s in steps_by_section.get(sec.id, [])],
        )
        for sec in db_sections
    ]

    return KnowledgeGuideResponse(
        id=pathway.id,
        slug=pathway.slug,
        title=pathway.title,
        description=pathway.description,
        cover_image_url=pathway.cover_image_url,
        pathway_type="knowledge_guide",
        orphan_steps=orphan_steps,
        sections=sections,
    )


def _section_slug(section: PathwaySection) -> str:
    """Sections don't carry a slug column; derive a stable, URL-safe
    anchor from ``title`` + ``id`` so the frontend can hash-navigate to
    a chapter without a database round trip. The id suffix guards
    against title collisions within a pathway.
    """
    import re
    base = re.sub(r"[^a-z0-9]+", "-", (section.title or "").lower()).strip("-")
    if not base:
        base = "chapter"
    return f"{base}-{section.id[:8]}"


# ---------------------------------------------------------------------------
# Me — continue journey
# ---------------------------------------------------------------------------

@me_router.get("/continue", response_model=ContinueResponse | None)
def get_continue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContinueResponse | None:
    """Return the user's most relevant next step, defaulting to REAL Journey."""
    # Always anchor to REAL Journey as the primary pathway
    pathway = (
        db.query(Pathway)
        .join(Space)
        .filter(Space.slug == "the-natural-leader-hub", Pathway.slug == "real-journey")
        .first()
    )
    if not pathway:
        return None

    steps = (
        db.query(PathwayStep)
        .filter(PathwayStep.pathway_id == pathway.id)
        .order_by(PathwayStep.position)
        .all()
    )
    if not steps:
        return None

    step_ids = [s.id for s in steps]
    completed = _completed_step_ids(current_user.id, step_ids, db)
    all_complete = len(completed) >= len(steps)

    next_step = next((s for s in steps if s.id not in completed), steps[-1])

    return ContinueResponse(
        space_slug="the-natural-leader-hub",
        pathway_slug=pathway.slug,
        pathway_title=pathway.title,
        step_slug=next_step.slug,
        step_title=next_step.title,
        all_complete=all_complete,
    )


# ---------------------------------------------------------------------------
# Step Comments — Questions & discussion
# ---------------------------------------------------------------------------

@router.get(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/comments",
    response_model=list[StepCommentItem],
)
def list_step_comments(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StepCommentItem]:
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    comments = (
        db.query(StepComment)
        .filter(StepComment.step_id == step.id, StepComment.is_visible.is_(True))
        .order_by(StepComment.created_at.asc())
        .all()
    )

    # Batch-load authors
    from app.models.user import User as UserModel
    author_ids = list({c.author_id for c in comments})
    authors = {
        u.id: u
        for u in db.query(UserModel).filter(UserModel.id.in_(author_ids)).all()
    }

    return [
        StepCommentItem(
            id=c.id,
            body=c.body,
            author=StepCommentAuthor(
                id=c.author_id,
                name=authors[c.author_id].name if c.author_id in authors else None,
                email=authors[c.author_id].email if c.author_id in authors else "",
            ),
            created_at=c.created_at,
        )
        for c in comments
    ]


@router.post(
    "/{slug}/pathways/{pathway_slug}/steps/{step_slug}/comments",
    response_model=StepCommentItem,
    status_code=201,
)
def create_step_comment(
    slug: str,
    pathway_slug: str,
    step_slug: str,
    body: StepCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StepCommentItem:
    space = _get_space_or_404(slug, db)
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    _check_pathway_access(current_user, pathway, space, db)
    step = _get_step_or_404(pathway.id, step_slug, db)

    comment = StepComment(
        id=str(uuid.uuid4()),
        step_id=step.id,
        author_id=current_user.id,
        body=body.body,
        is_visible=True,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    return StepCommentItem(
        id=comment.id,
        body=comment.body,
        author=StepCommentAuthor(
            id=current_user.id,
            name=current_user.name,
            email=current_user.email,
        ),
        created_at=comment.created_at,
    )

# ---------------------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------------------

_NOTIF_DEFAULTS = dict(
    weekly_digest_email=True,
    daily_digest_email=False,
    admin_broadcast_email=True,
    gathering_reminder_email=True,
    new_post_email=False,
    comment_reply_email=True,
    pathway_comment_email=True,
    new_pathway_email=True,
    push_enabled=False,
    push_gathering_reminders=False,
    push_replies=False,
    push_announcements=False,
)


def _prefs_response(space: Space, prefs: "SpaceMemberNotificationPrefs | None") -> NotificationPrefsResponse:
    if prefs is None:
        return NotificationPrefsResponse(
            space_id=space.id,
            space_slug=space.slug,
            space_name=space.name,
            **_NOTIF_DEFAULTS,  # type: ignore[arg-type]
        )
    return NotificationPrefsResponse(
        space_id=space.id,
        space_slug=space.slug,
        space_name=space.name,
        weekly_digest_email=prefs.weekly_digest_email,
        daily_digest_email=prefs.daily_digest_email,
        admin_broadcast_email=prefs.admin_broadcast_email,
        gathering_reminder_email=prefs.gathering_reminder_email,
        new_post_email=prefs.new_post_email,
        comment_reply_email=prefs.comment_reply_email,
        pathway_comment_email=prefs.pathway_comment_email,
        new_pathway_email=prefs.new_pathway_email,
        push_enabled=prefs.push_enabled,
        push_gathering_reminders=prefs.push_gathering_reminders,
        push_replies=prefs.push_replies,
        push_announcements=prefs.push_announcements,
    )


def _require_membership(space_id: str, user_id: str, db: Session) -> None:
    m = db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space_id,
        SpaceMembership.user_id == user_id,
        SpaceMembership.status == "active",
    ).first()
    if not m:
        raise HTTPException(status_code=403, detail="You are not a member of this collective.")


@router.get("/{slug}/notification-settings", response_model=NotificationPrefsResponse)
def get_notification_settings(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPrefsResponse:
    # Use the slug-only lookup so members of draft / coming-soon /
    # archived collectives can still manage their own preferences.
    # Access is fully gated by _require_membership below.
    space = _get_space_by_slug_or_404(slug, db)
    _require_membership(space.id, current_user.id, db)
    prefs = db.query(SpaceMemberNotificationPrefs).filter(
        SpaceMemberNotificationPrefs.user_id == current_user.id,
        SpaceMemberNotificationPrefs.space_id == space.id,
    ).first()
    return _prefs_response(space, prefs)


@router.patch("/{slug}/notification-settings", response_model=NotificationPrefsResponse)
def update_notification_settings(
    slug: str,
    payload: NotificationPrefsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPrefsResponse:
    # See get_notification_settings above — same slug-only lookup so
    # members of non-active collectives can still save preferences.
    space = _get_space_by_slug_or_404(slug, db)
    _require_membership(space.id, current_user.id, db)

    prefs = db.query(SpaceMemberNotificationPrefs).filter(
        SpaceMemberNotificationPrefs.user_id == current_user.id,
        SpaceMemberNotificationPrefs.space_id == space.id,
    ).first()

    if prefs is None:
        import uuid as _uuid
        prefs = SpaceMemberNotificationPrefs(
            id=str(_uuid.uuid4()),
            user_id=current_user.id,
            space_id=space.id,
            **_NOTIF_DEFAULTS,
        )
        db.add(prefs)
        db.flush()

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(prefs, field, value)

    db.commit()
    db.refresh(prefs)
    return _prefs_response(space, prefs)


# ---------------------------------------------------------------------------
# Offer Pages — public read
#
# One public endpoint. Only ``published`` Offer Pages are exposed to
# non-owners; ``draft`` and ``archived`` return 404. Owners
# (creators/moderators of the Collective, or admins) see every status
# through the same URL — mirrors the pathway About page's preview
# behaviour so we don't need a separate ``?preview=1`` mode.
# ---------------------------------------------------------------------------


def _viewer_owns_space(user: "User | None", space: Space, db: Session) -> bool:
    """True when the viewer can preview draft / archived Offer Pages.

    Site admins always qualify. Otherwise the viewer must hold an
    active creator or moderator membership on the Collective.
    """
    if user is None:
        return False
    if user.role == "admin":
        return True
    return db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space.id,
        SpaceMembership.user_id == user.id,
        SpaceMembership.status == SpaceMembershipStatus.active,
        SpaceMembership.role.in_([SpaceRole.creator, SpaceRole.moderator]),
    ).first() is not None


def _build_series_payment_options(series_id: str, db: Session) -> list[PublicPaymentOption]:
    """Return published PaymentOptions attached to a Series, each
    with its published PaymentOptionSchedules nested. Order matches
    the creator-configured ``position`` on each level."""
    options = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.attaches_to_kind == "event_series",
            PaymentOption.attaches_to_id == series_id,
            PaymentOption.status == "published",
        )
        .order_by(PaymentOption.position, PaymentOption.created_at)
        .all()
    )
    if not options:
        return []
    opt_ids = [o.id for o in options]
    schedule_rows = (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.payment_option_id.in_(opt_ids),
            PaymentOptionSchedule.status == "published",
        )
        .order_by(PaymentOptionSchedule.position, PaymentOptionSchedule.created_at)
        .all()
    )
    options_by_id = {o.id: o for o in options}
    by_option: dict[str, list[PublicPaymentOptionSchedule]] = {}
    for s in schedule_rows:
        by_option.setdefault(s.payment_option_id, []).append(
            PublicPaymentOptionSchedule(
                id=s.id,
                name=s.name,
                description=s.description,
                schedule_type=s.schedule_type,
                total_amount_cents=s.total_amount_cents,
                upfront_amount_cents=s.upfront_amount_cents,
                installment_amount_cents=s.installment_amount_cents,
                installment_count=s.installment_count,
                # See the pathway serializer's ``interval`` comment.
                interval=s.interval or s.stripe_interval,
                currency=s.currency,
                buyer_note=s.buyer_note,
                is_member_checkoutable=_schedule_is_member_checkoutable(
                    s, options_by_id.get(s.payment_option_id),
                ),
            )
        )
    return [
        PublicPaymentOption(
            id=o.id,
            name=o.name,
            description=o.description,
            payment_type=(
                o.payment_type.value if hasattr(o.payment_type, "value")
                else str(o.payment_type)
            ),
            sessions_per_week=o.sessions_per_week,
            total_sessions=o.total_sessions,
            price_per_session_cents=o.price_per_session_cents,
            effective_price_cents=o.effective_price_cents,
            currency=o.currency,
            buyer_note=o.buyer_note,
            schedules=by_option.get(o.id, []),
        )
        for o in options
    ]


def _build_offer_creator(space: Space, db: Session) -> "PublicOfferCreator | None":
    """Resolve the personal Creator identity behind the Space.

    Preference order:
      1. Public ``CreatorProfile`` fields.
      2. ``User.name`` for the Space's creator.
      3. ``None`` — omit the "Meet your guide" section entirely.

    Never falls back to ``Space.name`` / tagline / description /
    logo. The Collective is not the Creator (e.g. Collective EMBODY,
    Creator Lindsey). A future "About this Collective" section will
    represent Collective identity separately.
    """
    if not space.creator_id:
        return None
    from app.models.platform import CreatorProfile
    u_row = db.query(User.name).filter(User.id == space.creator_id).first()
    user_name = (u_row[0] if u_row and u_row[0] else "").strip() or None
    profile = (
        db.query(CreatorProfile)
        .filter(CreatorProfile.user_id == space.creator_id)
        .first()
    )
    if profile and profile.is_public:
        display = (profile.display_name or "").strip() or user_name
        if not display:
            return None
        return PublicOfferCreator(
            display_name=display,
            tagline=profile.profile_tagline,
            bio=profile.bio,
            avatar_url=profile.avatar_url,
            website_url=profile.website_url,
        )
    if not user_name:
        return None
    return PublicOfferCreator(display_name=user_name)


def _build_target_snapshot(
    row: OfferPage, space: Space, viewer: "User | None", db: Session,
) -> tuple[OfferPageTargetSnapshot, bool]:
    """Resolve an Offer Page's target and return ``(snapshot, has_access)``.

    Returns None-shaped snapshot fields when the target has since
    been deleted so the frontend can render an honest "unavailable"
    state instead of crashing on a missing reference. Access lookup
    reuses the existing pathway helper so entitlement / enrolment /
    admin all behave identically to the pathway landing page.
    """
    if row.target_kind == "pathway":
        pathway = db.query(Pathway).filter(
            Pathway.id == row.target_id,
            Pathway.space_id == space.id,
        ).first()
        if not pathway:
            # Target deleted — surface an empty snapshot so the
            # public renderer can show an "Unavailable" state
            # without crashing. Access defaults to False.
            return (
                OfferPageTargetSnapshot(
                    kind="pathway",
                    id=row.target_id,
                    slug="",
                    title="(Unavailable)",
                ),
                False,
            )
        access_type = (
            pathway.access_type.value
            if hasattr(pathway.access_type, "value")
            else str(pathway.access_type or "free")
        )
        checkout_path = (
            f"/spaces/{space.slug}/pathways/{pathway.slug}/checkout"
            if access_type in ("one_time", "subscription", "included_with_offer")
            else None
        )
        has_access = _compute_pathway_access(viewer, pathway, space, db)
        return (
            OfferPageTargetSnapshot(
                kind="pathway",
                id=pathway.id,
                slug=pathway.slug,
                title=pathway.title,
                description=pathway.description,
                cover_image_url=pathway.cover_image_url,
                access_type=access_type,
                price_cents=pathway.price_cents,
                currency=pathway.currency,
                billing_interval=pathway.billing_interval,
                checkout_path=checkout_path,
                enter_path=f"/spaces/{space.slug}/pathways/{pathway.slug}",
            ),
            has_access,
        )
    if row.target_kind == "event_series":
        series = db.query(_EventSeriesModel).filter(
            _EventSeriesModel.id == row.target_id,
            _EventSeriesModel.space_id == space.id,
        ).first()
        if not series:
            return (
                OfferPageTargetSnapshot(
                    kind="event_series",
                    id=row.target_id,
                    slug="",
                    title="(Unavailable)",
                ),
                False,
            )
        now = datetime.utcnow()
        has_access = _viewer_has_series_pass(viewer, series.id, db, now)
        return (
            OfferPageTargetSnapshot(
                kind="event_series",
                id=series.id,
                slug=series.slug,
                title=series.title,
                description=series.description,
                cover_image_url=series.cover_image_url,
                # Series pricing lives on PaymentOptions — no single
                # price / access_type / checkout_path applies here.
                starts_at=series.starts_at,
                ends_at=series.ends_at,
                enter_path=f"/spaces/{space.slug}/gatherings",
                payment_options=_build_series_payment_options(series.id, db),
            ),
            has_access,
        )
    if row.target_kind == "gathering":
        event = db.query(Event).filter(
            Event.id == row.target_id,
            Event.space_id == space.id,
        ).first()
        if not event:
            return (
                OfferPageTargetSnapshot(
                    kind="gathering",
                    id=row.target_id,
                    slug="",
                    title="(Unavailable)",
                ),
                False,
            )
        has_access = False
        if viewer is not None:
            confirmed = (
                db.query(EventBooking.id)
                .filter(
                    EventBooking.event_id == event.id,
                    EventBooking.user_id == viewer.id,
                    EventBooking.status == BookingStatus.confirmed,
                )
                .first()
            )
            has_access = confirmed is not None
        access_type = getattr(event, "booking_access_type", None)
        return (
            OfferPageTargetSnapshot(
                kind="gathering",
                id=event.id,
                # Events have no public slug — use id as the stable
                # routing key so the frontend can build a link even
                # when a public event URL isn't wired up yet.
                slug=event.id,
                title=event.title,
                description=event.description,
                cover_image_url=event.thumbnail_url,
                access_type=access_type,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                ticket_price_cents=getattr(event, "ticket_price_cents", None),
                ticket_currency=getattr(event, "ticket_currency", None),
                enter_path=f"/spaces/{space.slug}/events/{event.id}",
            ),
            has_access,
        )
    # Unknown kind — surface an empty snapshot so the renderer can
    # show an "Unavailable" state without crashing.
    return (
        OfferPageTargetSnapshot(
            kind=row.target_kind,
            id=row.target_id,
            slug="",
            title="(Unavailable)",
        ),
        False,
    )


@router.get(
    "/{slug}/offers/{offer_slug}",
    response_model=PublicOfferPage,
    summary="Public read of an Offer Page (owners see drafts)",
)
def get_public_offer_page(
    slug: str,
    offer_slug: str,
    db: Session = Depends(get_db),
    current_user: "User | None" = Depends(get_optional_user),
):
    # Space visibility mirrors the pathway About endpoint —
    # unlisted collectives are still reachable by direct URL.
    space = _get_space_visible_to(slug, db, current_user)

    row = db.query(OfferPage).filter(
        OfferPage.space_id == space.id,
        OfferPage.slug == offer_slug,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Offer Page not found.")

    # Only ``published`` is publicly visible. Owners see every
    # status (draft + archived) through the same URL so we never
    # need a separate preview mode.
    if row.status != "published":
        if not _viewer_owns_space(current_user, space, db):
            raise HTTPException(status_code=404, detail="Offer Page not found.")

    # Future — plan-downgrade handling for commercial pages.
    #
    # Product intent: when a Creator's plan lapses back to Community,
    # their previously-published Offer Pages should become publicly
    # unavailable (returning 404 here, or a soft "temporarily
    # unavailable" state) WITHOUT deleting the underlying rows, and
    # should restore automatically if the paid plan is reactivated.
    # This is not implemented yet — today the only plan gate is
    # write-side (``guard_paid_offers_enabled`` at create / update),
    # so a page published on Creator will keep serving after a
    # downgrade until we add a runtime read-side check here (and a
    # matching handler on subscription-lapsed webhooks). Track when
    # commercial content downgrade policy is decided.

    target_snapshot, has_access = _build_target_snapshot(
        row, space, current_user, db,
    )
    return PublicOfferPage(
        id=row.id,
        slug=row.slug,
        title=row.title,
        promise=row.promise,
        hero_image_url=row.hero_image_url,
        status=row.status,
        sections_config=row.sections_config or {},
        target=target_snapshot,
        creator=_build_offer_creator(space, db),
        user_has_target_access=has_access,
    )


# ---------------------------------------------------------------------------
# Member-facing Gathering Series endpoints (M1). Imported here for the
# side effect of registering the endpoints on ``router`` — mirrors the
# ``_gathering_series_routes`` / ``_space_payment_options_routes``
# pattern used on the creator side.
# ---------------------------------------------------------------------------

from app.spaces import _series_member_routes as _series_member_routes  # noqa: E402,F401
