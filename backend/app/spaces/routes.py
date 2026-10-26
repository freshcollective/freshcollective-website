import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Response
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session, selectinload

from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment import PaymentTransaction, PaymentTransactionStatus
from app.core.config import settings

from app.auth.dependencies import get_current_user, get_optional_user, get_verified_current_user
from app.core.database import get_db
from app.creator.plan_guards import guard_member_allowance
from app.creator.schemas import AboutBlockResponse, BlockMediaInfo, StepBlockResponse
from app.models.payment_option import PaymentOption, PaymentOptionStatus
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    BookingStatus,
    Enrollment,
    EntitlementStatus,
    Event,
    EventBooking,
    Pathway,
    PathwayAboutBlock,
    PathwayEntitlement,
    PathwaySection,
    PathwayStep,
    PathwayStepBlock,
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
from app.services.collective_welcome_emit import (
    emit_collective_welcome as _emit_collective_welcome,
    schedule_welcome as _schedule_welcome,
)
from app.spaces import home_config
from app.spaces import join_policy
from app.spaces import joining_doors
from app.spaces import pathway_pricing
from app.spaces import venue_projection
from app.spaces import area_access, pathway_visibility
from app.services import membership_removal
from app.services import membership_grant
from app.spaces import retained_reservations
from app.spaces import area_policies
from app.spaces.schemas import (
    AccessRequestOut,
    CompleteStepRequest,
    CompleteStepResponse,
    EventDetail,
    EventSummary,
    GuideSection,
    GuideStep,
    InviteLookupResponse,
    KnowledgeGuideResponse,
    NotificationPrefsResponse,
    NotificationPrefsUpdate,
    PathwayProgress,
    PathwaySummary,
    PathwayWithSteps,
    PaymentOptionScheduleSummary,
    PaymentOptionSummary,
    PublicSpaceCard,
    SaveNotesRequest,
    SaveNotesResponse,
    SectionWithSteps,
    DeparturePreview,
    RetainedReservationOut,
    LeaveCollectiveResponse,
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
from app.services.event_permissions import can_book as _can_book_gate_shared
from app.services.gathering_booking_rules import (
    capacity_denial as _capacity_denial,
    confirmed_booking_count as _confirmed_booking_count,
    evaluate_pass_for_event as _evaluate_pass_for_event,
    event_week_bounds as _event_week_bounds,
    occurrence_timing_denial as _occurrence_timing_denial,
)
from app.services.gathering_booking_emit import (  # noqa: E402
    emit_booking_confirmed,
    emit_multi_booking_confirmed,
)
from app.services.notification_service import trigger_event_booking_creator  # noqa: E402
from app.services import channel_permissions as channel_perms  # noqa: E402
from app.services import pathway_payment_options as pathway_options  # noqa: E402


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
    """True when ``user`` holds an active, not-yet-expired AccessPass
    scoped to ``series_id``. Used by the UI to render Reserve vs
    Pass-required.

    This is a series-level ownership check — it deliberately does not
    require ``valid_from <= now``. A member who has purchased a future
    Series (e.g. Term 4 bought in September, pass ``valid_from`` set
    to the 5 October start) legitimately holds the pass and should
    see Reserve. Per-event window enforcement lives in the booking
    commit (``book_event``), which compares the pass window against
    ``event.starts_at``.

    Returns False for anonymous viewers or events without a semantic
    series link.
    """
    if user is None or not series_id:
        return False
    from app.models.access_pass import AccessPass, AccessPassStatus
    hit = (
        db.query(AccessPass.id)
        .filter(
            AccessPass.user_id == user.id,
            AccessPass.eligible_series_id == series_id,
            AccessPass.status == AccessPassStatus.active,
            or_(
                AccessPass.valid_until.is_(None),
                AccessPass.valid_until > now,
            ),
        )
        .first()
    )
    return hit is not None


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

    # Listed Pathways only. This counted ``status != 'archived'``, so a
    # Collective whose only Pathway was a draft advertised "1 pathway"
    # on Explore while its own Pathways tab correctly said "none".
    #
    # These cards are the anonymous public listing, so there is no
    # caretaker to consider: the count is always the non-caretaker one.
    # A creator's own view of their drafts lives in Creator Studio,
    # which counts them separately and deliberately.
    pathway_counts: dict[str, int] = dict(
        db.query(Pathway.space_id, func.count(Pathway.id))
        .filter(
            Pathway.space_id.in_(space_ids),
            Pathway.status.in_(pathway_visibility.LISTED_STATUSES),
        )
        .group_by(Pathway.space_id)
        .all()
    )

    # Minimum price among active paid pathways per space. The rule lives
    # in ``pathway_pricing`` so the Collective detail endpoint returns
    # the same number this listing shows — the public About page used to
    # re-derive its own from ``pathway.price_cents``, which is stale on
    # any payment-options Pathway.
    min_pathway_prices = pathway_pricing.min_paid_price_cents_by_space(
        db, space_ids,
    )

    # Members of the Collective — active learner memberships.
    #
    # This used to count DISTINCT users with an ``Enrollment`` in one of
    # the Collective's Pathways, which is a different question and gave
    # a different answer: EMBODY showed "1 member" on Explore while its
    # own About page showed "4 members". Both were right about what they
    # measured. Only one of them was measuring membership.
    #
    # Enrolment is not how most people belong. A Collective whose
    # Pathways are ``included_with_offer`` grants access through a pass,
    # so members hold a SpaceMembership and may have no Enrollment row
    # at all — the count then reports on whoever happened to start a
    # Pathway, and under-reports the longer a Collective sells access
    # that way.
    #
    # The definition here is the one the public About page and the admin
    # Collectives table already use: active + role=learner. Leaders are
    # counted separately by ``get_space`` and are deliberately NOT folded
    # in — "4 members · 1 leader" is two facts, not one.
    member_counts: dict[str, int] = dict(
        db.query(SpaceMembership.space_id, func.count(SpaceMembership.id))
        .filter(
            SpaceMembership.space_id.in_(space_ids),
            SpaceMembership.status == SpaceMembershipStatus.active,
            SpaceMembership.role == SpaceRole.learner,
        )
        .group_by(SpaceMembership.space_id)
        .all()
    )

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
            join_policy=join_policy.resolve(s.join_policy),
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

    # The rule itself lives in ``services.space_viewer`` so the members
    # directory enforces the same one rather than its own variant —
    # which is how that endpoint came to answer anonymous callers.
    from app.services.space_viewer import resolve_space_viewer
    if resolve_space_viewer(db, current_user, space).qualifies:
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


def _get_listed_pathway_or_404(
    space: Space,
    pathway_slug: str,
    db: Session,
    current_user: "User | None",
) -> Pathway:
    """A Pathway by slug, 404 unless this viewer may see it listed.

    The sibling of ``_get_pathway_or_404`` for the two detail endpoints
    reachable without a membership check. Both looked a Pathway up by
    slug with no status gate, so a draft Pathway's title, description,
    price and full ordered step list were readable by any caller —
    anonymously, in the case of ``/overview``. Discovering the slug was
    the only obstacle, and the public Collective payload used to hand it
    over.

    **404, not 403.** Matching ``_get_space_visible_to``: a draft
    Pathway's existence is itself unreleased information, so the honest
    answer to a stranger is that there is nothing here. A 403 would
    confirm the slug names something real.

    Caretakers are unaffected, which is what keeps the Creator Studio
    Preview flow working on an unpublished Pathway.
    """
    pathway = _get_pathway_or_404(space.id, pathway_slug, db)
    if pathway_visibility.is_listed(pathway):
        return pathway
    if pathway_visibility.viewer_sees_all_pathways(current_user, space, db):
        return pathway
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Pathway not found.",
    )


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


# Canonical Pathway-access predicate — sourced from the shared
# ``app.services.pathway_access`` module so every surface (Pathway
# page, Pathway Conversation channels, mention autocomplete) evaluates
# the same rule against the same access sources. This delegate
# preserves the private ``_compute_pathway_access`` name for
# backward compatibility with in-module callers.
from app.services.pathway_access import compute_pathway_access as _compute_pathway_access  # noqa: E402
from app.services.pathway_access import (  # noqa: E402
    RETIRED_STATUS as _RETIRED_STATUS,
    has_active_pathway_entitlement as _has_active_pathway_entitlement,
    included_with_offer_unlocked as _included_with_offer_unlocked,
    retains_acquired_access as _retains_acquired_access,
)


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
      - draft pathway → denied to everyone else
      - coming_soon pathway → denied (About page is separate, not gated here)
      - archived pathway → denied UNLESS the caller holds a durable
        record of having acquired it, and then the ordinary rule for
        its access type still has to pass as well
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

    if p_status == "draft":
        raise HTTPException(status_code=403, detail="This pathway is not available.")
    if p_status == "coming_soon":
        raise HTTPException(status_code=403, detail="This pathway is coming soon.")

    # Archived. Mirror of the same branch in
    # ``services.pathway_access.compute_pathway_access`` — kept in
    # lockstep by sharing the predicate rather than by matching the
    # query by hand, which is how the three surfaces drifted before.
    #
    # An EXTRA condition, not a replacement: the access-type rules
    # below still run, so an archived ``included_with_offer`` Pathway
    # still needs active membership and an archived ``one_time`` one
    # still needs a live entitlement. Nobody gains anything by a
    # Pathway being archived.
    if p_status == _RETIRED_STATUS and not _retains_acquired_access(
        db, user_id=user.id, space_id=space.id, pathway_id=pathway.id,
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "This pathway has been archived and is no longer "
                "available."
            ),
        )

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
        # Mirror of ``services.pathway_access.compute_pathway_access``
        # for the ``included_with_offer`` branch — kept in lockstep so
        # the HTTP-raising and bool-returning helpers can never
        # diverge. Both now call the same helpers, so "in lockstep" is
        # enforced by sharing the query rather than by matching it by
        # hand. Either an AccessPass on an including Option or an
        # active PathwayEntitlement for this Pathway unlocks it; active
        # membership is still required here, at the call site.
        member_row = (
            db.query(SpaceMembership.id)
            .filter(
                SpaceMembership.user_id == user.id,
                SpaceMembership.space_id == space.id,
                SpaceMembership.status == "active",
            )
            .first()
        )
        if member_row is not None and _included_with_offer_unlocked(
            db, user_id=user.id, space_id=space.id, pathway_id=pathway.id,
        ):
            return
        raise HTTPException(status_code=403, detail="Access to this pathway is included with a paid offer.")

    # one_time / subscription — require an active entitlement that hasn't expired
    if _has_active_pathway_entitlement(
        db, user_id=user.id, pathway_id=pathway.id,
    ):
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




def _private_no_store(response: Response) -> None:
    """Mark a viewer-specific payload uncacheable.

    ``/api/spaces/{slug}`` now differs between a visitor, a member and
    an entitled member — ``area_access`` and ``home_tiles`` are
    resolved per viewer. One person's set of open doorways must never
    be served to another from a shared cache.

    A route dependency rather than a ``Response`` parameter so the
    handler stays an ordinary function that tests and internal callers
    can invoke directly.
    """
    response.headers["Cache-Control"] = "private, max-age=0, no-store"
    response.headers["Vary"] = "Cookie"


@router.get(
    "/{slug}",
    response_model=SpaceResponse,
    dependencies=[Depends(_private_no_store)],
)
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
    # Upcoming-gathering signals for the member Home. Same eligibility
    # the member Gatherings list uses for what is still attendable:
    # published, active, future. One COUNT and one MIN rather than
    # loading rows the Home would only measure and discard.
    _gathering_window = [
        Event.space_id == space.id,
        Event.is_published.is_(True),
        Event.status == "active",
        Event.starts_at > datetime.utcnow(),
    ]
    upcoming_gathering_count = (
        db.query(func.count(Event.id)).filter(*_gathering_window).scalar() or 0
    )
    next_gathering_starts_at = (
        db.query(func.min(Event.starts_at)).filter(*_gathering_window).scalar()
    )

    creator_name = None
    if space.creator_id:
        creator_row = (
            db.query(User.name).filter(User.id == space.creator_id).first()
        )
        creator_name = creator_row[0] if creator_row else None

    # One resolution per request, reused by the tiles below and
    # returned so the client's nav and Home render from the same
    # answer instead of each deciding for itself.
    areas = area_access.resolve_area_access(db, space, current_user)

    # This payload is now viewer-specific: ``area_access``,
    # ``home_tiles`` and the counts differ between a visitor, a member
    # and an entitled member. It must never land in a shared cache
    # where one person's resolved doorways could be served to another.

    resp = SpaceResponse.model_validate(space)
    # ``pathways`` comes from the ORM relationship, which is
    # unfiltered — so before this, an anonymous caller received every
    # draft and archived Pathway in full, title and all, and the
    # Collective's own page counted them. The About page never rendered
    # a draft title, but the payload carried it, which is the part a
    # reader of the API could see.
    #
    # Filtered here rather than on the relationship: other readers of
    # ``space.pathways`` — Creator Studio among them — legitimately
    # need every row, and narrowing the relationship would quietly
    # change all of them.
    _sees_all = pathway_visibility.viewer_sees_all_pathways(
        current_user, space, db,
    )
    listed_pathways = (
        resp.pathways
        if _sees_all
        else [p for p in resp.pathways if pathway_visibility.is_listed(p)]
    )
    return resp.model_copy(update={
        "pathways": listed_pathways,
        "area_access": sorted(areas.reachable),
        "creator_name": creator_name,
        "join_policy": join_policy.resolve(space.join_policy),
        "joining_options": joining_doors.list_joining_doors(db, space),
        "home_tiles": home_config.resolve(
            space.home_config,
            show_member_directory=space.show_member_directory,
            reachable_areas=areas.reachable,
        ),
        "upcoming_gathering_count": int(upcoming_gathering_count),
        "next_gathering_starts_at": next_gathering_starts_at,
        "learner_count": learner_count,
        "leader_count": leader_count,
        "location": location_dict,
        "colour_palette": palette_dict,
        "colour_palette_key": space.colour_story_key,
        "atmosphere_keys": atmo_keys,
        "atmosphere_labels": atmo_labels,
        "identity_statement": space.identity_statement,
        "welcome_message": space.welcome_message,
        # Same derivation the Explore listing uses, so the two surfaces
        # cannot quote different prices for the same Collective.
        "min_paid_pathway_price_cents":
            pathway_pricing.min_paid_price_cents_for_space(db, space.id),
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


# ---------------------------------------------------------------------------
# Leaving — a member ending their own membership
# ---------------------------------------------------------------------------
#
# Two endpoints, deliberately. The preview is what lets the confirmation
# dialog state consequences instead of reciting a generic warning, and
# the same refusals are evaluated in both so the dialog never offers an
# action the DELETE would reject.
#
# Neither takes a user id. That is the authorisation model, not an
# omission: there is no parameter through which one member could name
# another, so "cannot remove somebody else" is a property of the route's
# shape rather than a check that could be forgotten. Creator-initiated
# removal keeps its own endpoint, its own ``user_id`` and its own
# creator guard.


def _resolve_own_membership(
    slug: str, db: Session, current_user: User,
) -> tuple[Space, SpaceMembership | None, str | None]:
    """The caller's own membership of this Collective, and why they may
    not leave it — ``None`` when they may.

    Shared by the preview and the DELETE so the two cannot disagree
    about who is allowed to go.
    """
    space = _get_space_visible_to(slug, db, current_user)

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
    )
    if membership is None:
        return space, None, "not_a_member"

    # The owner cannot leave their own Collective, and neither can a
    # caretaker leave through this door. Stepping back from running a
    # place is a different operation with different consequences for the
    # place — who owns it, who moderates it, what happens to its
    # members — and quietly turning it into "remove my membership row"
    # would strand a Collective with nobody managing it. Mirrors the
    # creator endpoint's refusal to remove the owner.
    if space.creator_id and space.creator_id == current_user.id:
        return space, membership, "caretaker_role"
    if membership.role in membership_removal.CARETAKER_ROLES:
        return space, membership, "caretaker_role"

    # World Builders and friends: membership here is computed from
    # platform eligibility, not chosen. ``creator_eligibility`` would
    # set the row straight back to ``active`` on its next run, so
    # offering to leave would be offering something that silently
    # undoes itself. ``membership_grant`` declines to touch these
    # Collectives for the same reason.
    if space.auto_grant_role is not None:
        return space, membership, "auto_managed_collective"

    if membership_removal.live_payment_plan_count(
        db, user_id=current_user.id, space_id=space.id,
    ):
        return space, membership, "live_payment_plan"

    return space, membership, None


@me_router.get(
    "/retained-reservations",
    response_model=list[RetainedReservationOut],
)
def list_retained_reservations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RetainedReservationOut]:
    """Upcoming Gatherings the caller paid for in Collectives they left.

    The "practical way to locate it" half of the paid-reservation
    exception. Without this, keeping the reservation reachable would
    depend on the former member still having the Gathering's URL.

    Scoped to the caller by ``current_user`` with no addressable
    parameter, like the departure endpoints — there is no shape of this
    request that returns somebody else's reservations.

    Empty for everybody who has not left a Collective holding a paid
    booking, which is almost everybody; the surface that renders it
    shows nothing at all in that case.
    """
    rows = retained_reservations.list_retained(
        db, user_id=current_user.id, now=datetime.utcnow(),
    )
    return [
        RetainedReservationOut(
            event_id=r.event_id,
            event_title=r.event_title,
            starts_at=r.starts_at,
            ends_at=r.ends_at,
            space_slug=r.space_slug,
            space_name=r.space_name,
            booking_id=r.booking_id,
        )
        for r in rows
    ]


@router.get(
    "/{slug}/my-membership/departure",
    response_model=DeparturePreview,
)
def preview_leaving_collective(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeparturePreview:
    """What leaving this Collective would mean for the caller.

    Read-only. Changes nothing, and is safe to call on a Collective the
    caller is not a member of — it answers ``can_leave=False`` with
    ``blocked_reason='not_a_member'`` rather than 404, because the
    Membership page may render a stale card.
    """
    space, membership, blocked = _resolve_own_membership(
        slug, db, current_user,
    )
    if membership is None:
        return DeparturePreview(can_leave=False, blocked_reason=blocked)

    consequences = membership_removal.summarise_departure(
        db,
        user_id=current_user.id,
        space_id=space.id,
        now=datetime.utcnow(),
    )
    return DeparturePreview(
        can_leave=blocked is None,
        blocked_reason=blocked,
        live_payment_plans=consequences.live_payment_plans,
        active_passes=consequences.active_passes,
        unused_credits=consequences.unused_credits,
        future_bookings=consequences.future_bookings,
        purchased_future_bookings=consequences.purchased_future_bookings,
        purchased_pathways=consequences.purchased_pathways,
        membership_gated_paid_pathways=(
            consequences.membership_gated_paid_pathways
        ),
        offerings_retained=consequences.offerings_retained,
    )


@router.delete(
    "/{slug}/my-membership",
    response_model=LeaveCollectiveResponse,
)
def leave_collective(
    slug: str,
    db: Session = Depends(get_db),
    # Verified account required, matching every other member-initiated
    # state change (SEC-009).
    current_user: User = Depends(get_verified_current_user),
) -> LeaveCollectiveResponse:
    """End the caller's own membership of this Collective.

    Takes nothing but the Collective. Ends one membership, in one
    Collective, for the person making the request.

    What it does **not** do, and why
    -------------------------------

    It makes no payment change of any kind — no Stripe call, no refund,
    no schedule alteration, no cancelled booking, no cancelled pass. A
    member walking out is not consent to forfeit what they bought, and
    the reverse — taking access away while a card keeps being charged —
    is the one outcome nobody would choose. So where a live payment plan
    exists this refuses with 409 rather than pick either side of that
    conflict; the member is sent to the creator, who has the plan-cancel
    operation that talks to Stripe properly.

    Offerings in Your Collection are untouched here and by design: their
    entitlement row, and nothing else, authorises a download.
    """
    space, membership, blocked = _resolve_own_membership(
        slug, db, current_user,
    )

    if blocked == "not_a_member" or membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of this collective.",
        )
    if blocked == "caretaker_role":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You manage this collective, so you cannot leave it as a "
                "member. Transfer or close it from Creator Studio instead."
            ),
        )
    if blocked == "auto_managed_collective":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Membership of this collective is managed automatically "
                "and cannot be left here."
            ),
        )
    if blocked == "live_payment_plan":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You have a payment plan in progress for this collective. "
                "Please contact the collective's creator to settle or "
                "cancel it before leaving, so you are not charged for "
                "access you no longer have."
            ),
        )
    if blocked is not None:  # pragma: no cover — defensive
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot leave.",
        )

    now = datetime.utcnow()
    retained = membership_removal.summarise_departure(
        db, user_id=current_user.id, space_id=space.id, now=now,
    ).offerings_retained

    membership_removal.end_membership(
        db,
        membership=membership,
        space=space,
        actor_user_id=current_user.id,
        now=now,
        # Recorded as the member's own decision, which is what makes
        # rejoining through the ordinary Join flow safe. A voluntary
        # departure carries no reason and can never carry a block —
        # ``RemovalDecision`` refuses to construct one that does.
        decision=membership_removal.RemovalDecision(
            kind=membership_removal.REMOVAL_VOLUNTARY,
        ),
        # The member chose to go; they did not choose to lose what they
        # paid for. See the table in ``services.membership_removal``.
        revoke_purchased_access=False,
        cancel_passes=False,
        cancel_future_bookings=False,
        note="Revoked when the member left the collective",
    )
    db.commit()

    return LeaveCollectiveResponse(
        left=True,
        space_name=space.name,
        offerings_retained=retained,
    )


@router.post("/{slug}/join", status_code=201)
def join_space(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),  # SEC-009
    # Routing dispatches to the email provider inline, so the
    # welcome is handed to FastAPI to run after the response
    # rather than made part of it. Defaulted for the tests that
    # call this function directly with no request context.
    background_tasks: BackgroundTasks = None,
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

    # Purchase-required Collectives have no free door. Enforced here
    # rather than by hiding the button: the endpoint is the boundary,
    # and a hidden button is a suggestion. The code is stable so the
    # client can branch on it without reading the sentence.
    if not join_policy.allows_free_join(space.join_policy):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": join_policy.REASON_PURCHASE_REQUIRED,
                "message": (
                    "Membership of this collective comes with a purchase. "
                    "Choose an option to join."
                ),
            },
        )

    existing = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == space.id, SpaceMembership.user_id == current_user.id)
        .first()
    )
    if existing is not None:
        existing_status = (
            existing.status.value
            if hasattr(existing.status, "value") else str(existing.status)
        )
        if existing_status == SpaceMembershipStatus.active.value:
            return {"joined": True, "already_member": True}

        # Rejoining. This used to be the same branch as "already a
        # member": the query had no status filter, so a ``removed`` row
        # produced ``already_member: true`` — a success for a join that
        # happened to nobody. The person stayed removed and was told
        # they were in.
        #
        # Who may come back is ``membership_grant.may_rejoin``, shared
        # with the purchase path so a refusal at one door is not a way
        # in through the other. It requires a recorded *voluntary*
        # departure, so a creator's removal, an admin's revocation and
        # a historical removal of unknown provenance all stay refused.
        if (
            existing_status == SpaceMembershipStatus.removed.value
            and membership_grant.may_rejoin(existing)
        ):
            # Allowance is re-checked, because the Collective may have
            # filled up while they were away — rejoining is subject to
            # the same requirements as joining, which is what was
            # promised.
            guard_member_allowance(space, db)
            membership_grant.reactivate(existing, now=datetime.utcnow())
            db.commit()
            # No second welcome: the Collective's welcome is a
            # first-arrival moment, and ``_emit_collective_welcome``
            # would dedupe it anyway.
            return {"joined": True, "already_member": False, "rejoined": True}

        # Removed and not by their own choice — or paused. Refused, and
        # deliberately without saying which: "ask the creative" is the
        # same next step either way, and spelling out that a specific
        # person was removed by a creator discloses a moderation
        # decision through a join button.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Your membership of this collective is not active. Please "
                "contact the collective's creator if you would like to "
                "rejoin."
            ),
        )

    # Plan enforcement: the owning creator's member allowance. Checked
    # here, after the already-a-member return above, so an existing
    # member is never turned away from a Collective they are already in.
    guard_member_allowance(space, db)

    db.add(SpaceMembership(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        space_id=space.id,
        role=SpaceRole.learner,
        status=SpaceMembershipStatus.active,
        source="joined",
    ))
    # First-time membership → the Collective's welcome. Emitted inside
    # this transaction, routed after the commit below. The
    # already-a-member return above means a repeat press cannot reach
    # here, and the dedupe key would refuse a second one anyway.
    _welcome = _emit_collective_welcome(
        db, space=space, member=current_user, join_source="joined",
    )
    db.commit()
    _schedule_welcome(_welcome, background_tasks)
    return {"joined": True, "already_member": False}


@router.post("/{slug}/request-access", status_code=201)
def request_access(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
    # Routing dispatches to the email provider inline, so the
    # welcome is handed to FastAPI to run after the response
    # rather than made part of it. Defaulted for the tests that
    # call this function directly with no request context.
    background_tasks: BackgroundTasks = None,
) -> dict:
    """Accept a space invite by token.

    SEC-009: caller must be authenticated AND email-verified. Per
    product policy, invitation acceptance does NOT auto-verify — an
    unverified invited user must complete verification first (their
    dashboard shows the "please verify" banner + resend). Requiring
    a verified email before we bind the account to a Collective
    keeps membership provenance clean regardless of who typed the
    email at signup time.

    The underlying invitation stays valid until it's consumed;
    verification isn't a token replacement, just a precondition.
    """
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
    _welcome = None
    if existing is not None:
        # A third membership door, and it had the same bug ``join_space``
        # did: the lookup above has no status filter, so a ``removed``
        # row made this skip the INSERT, delete the invitation and
        # return ``accepted: true`` — consuming the invite and joining
        # nobody.
        #
        # Same rule as the other two doors, read from the same place, so
        # an invitation cannot be a way around a refusal at Join or at
        # checkout. An invitation is not authority to overturn a
        # creator's block: the creator lifts the block, and then the
        # invitation works.
        existing_status = (
            existing.status.value
            if hasattr(existing.status, "value") else str(existing.status)
        )
        if existing_status == SpaceMembershipStatus.removed.value:
            if not membership_grant.may_rejoin(existing):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Your membership of this collective is not active. "
                        "Please contact the collective's creator."
                    ),
                )
            role_value = (
                invite.role.value if hasattr(invite.role, "value")
                else str(invite.role)
            )
            if role_value == SpaceRole.learner.value:
                guard_member_allowance(space, db)
            membership_grant.reactivate(existing, now=datetime.utcnow())
            existing.role = role_value
    if not existing:
        role_value = invite.role.value if hasattr(invite.role, "value") else str(invite.role)
        # An invitation does not exempt the Collective from its plan's
        # member allowance — otherwise the cap could be bypassed simply
        # by inviting past it. Caretaker roles (creator / moderator) are
        # not members for allowance purposes, so only learners count.
        if role_value == SpaceRole.learner.value:
            guard_member_allowance(space, db)
        db.add(SpaceMembership(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            space_id=space.id,
            role=role_value,
            status=SpaceMembershipStatus.active,
            source="invited",
        ))
        # Accepting is the moment a person actually becomes a member —
        # issuing the invitation is not, and must not welcome anybody.
        # Inside the ``if not existing`` branch, so somebody who was
        # already a member and merely consumes a stray invite is not
        # welcomed a second time.
        _welcome = _emit_collective_welcome(
            db, space=space, member=current_user, join_source="invited",
        )

    # Delete the invite — consumed
    db.delete(invite)
    db.commit()
    _schedule_welcome(_welcome, background_tasks)
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
    # The Pathways doorway only. Individual Pathway about / offer /
    # checkout pages stay reachable regardless — a person must be able
    # to get to the page where access is bought without already
    # holding it.
    area_access.require_area(db, space, current_user, area_policies.AREA_PATHWAYS)
    # SEC-005-E — manager visibility (see draft/archived pathways) now
    # requires admin, ownership, or active creator/moderator membership.
    # ``is_caretaker`` centralises this predicate and returns False for
    # anonymous callers.
    is_space_manager = channel_perms.is_caretaker(current_user, space, db)

    query = db.query(Pathway).filter(Pathway.space_id == space.id)
    # The rule this endpoint has always applied, now shared so the
    # public counts cannot drift from it. Access is NOT filtered here:
    # ``has_access`` below is computed per row, so a paid or
    # members-only published Pathway is listed and renders locked.
    _listed = pathway_visibility.listed_pathway_filter(is_space_manager)
    if _listed is not None:
        # One personal exception: an archived Pathway this caller still
        # holds. Archiving no longer revokes a purchase, and a Pathway
        # that is open to a member but absent from their list is open
        # in name only.
        #
        # Personal, not public. The ids are resolved for this user, so
        # an anonymous caller adds nothing (there is no user to ask
        # about) and a member holding nothing gets an empty set. Every
        # genuinely public surface — the Explore counts,
        # ``hydrate_public_space_cards``, the anonymous
        # ``SpaceResponse`` payload — reads
        # ``pathway_visibility`` directly and still excludes archived
        # Pathways outright.
        _retained: set[str] = set()
        if current_user is not None:
            from app.services.pathway_access import (
                retained_archived_pathway_ids,
            )
            _retained = retained_archived_pathway_ids(
                db, user_id=current_user.id, space_id=space.id,
            )
        if _retained:
            query = query.filter(_listed | Pathway.id.in_(_retained))
        else:
            query = query.filter(_listed)

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

    # Bulk-fetch unlock offer names for included_with_offer pathways.
    # Sourced from PaymentOptionGrant (the single source of truth for
    # "which Options include this Pathway"). Draft Options are
    # excluded — they're not sold, so listing them as unlock offers
    # would mislead members.
    unlock_offer_names_by_pathway: dict[str, list[str]] = {}
    if pathway_ids:
        from app.models.payment_option_grant import PaymentOptionGrant as _POG
        rows = (
            db.query(_POG.pathway_id, PaymentOption.name)
            .join(PaymentOption, PaymentOption.id == _POG.payment_option_id)
            .filter(
                _POG.grant_kind == "pathway",
                _POG.pathway_id.in_(pathway_ids),
                PaymentOption.status.in_([
                    PaymentOptionStatus.published,
                    PaymentOptionStatus.archived,
                ]),
            )
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
    # Was a fourth hand-written copy of the status list. Same rule, read
    # from one place so it cannot drift from the tab or the counts.
    _listed = pathway_visibility.listed_pathway_filter(is_space_manager)
    if _listed is not None:
        query = query.filter(_listed)
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
    # Area policy decides whether this doorway answers at all. What a
    # member may then *book* inside it is unchanged — see book_event.
    area_access.require_area(db, space, current_user, area_policies.AREA_GATHERINGS)

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
        #
        # Deliberately does NOT include ``archived`` the way the creator
        # archive now does. Archiving is how a Creator takes something
        # off the member-facing schedule; a future archived Gathering
        # appearing in a member's archive would be new exposure, not a
        # repair. A *past* archived one already qualifies here on
        # ``end_marker``, which is the member-relevant history.
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
    if series_ids:
        rows = db.query(
            _EventSeries.id, _EventSeries.title, _EventSeries.slug,
            _EventSeries.cover_image_url,
        ).filter(_EventSeries.id.in_(series_ids)).all()
        series_titles = {sid: t for sid, t, _sl, _c in rows}
        series_slugs = {sid: sl for sid, _t, sl, _c in rows}
        series_covers = {sid: c for sid, _t, _sl, c in rows}

    # Bulk-check the viewer's active AccessPasses for these series so
    # the booking UI can distinguish "has pass → Reserve" from "no
    # pass → explain requirement". Same window rule as the booking
    # endpoint: series-level ownership check — status active AND
    # (valid_until NULL OR valid_until > now). Deliberately no
    # ``valid_from`` filter here: a member who has purchased a future
    # Series (pass ``valid_from`` in the future) legitimately holds
    # the pass. Per-event window enforcement happens in ``book_event``
    # against ``event.starts_at``, which is what actually determines
    # whether a given session is inside the pass window.
    user_series_pass_ids: set[str] = set()
    if current_user and series_ids:
        pass_rows = (
            db.query(AccessPass.eligible_series_id)
            .filter(
                AccessPass.user_id == current_user.id,
                AccessPass.eligible_series_id.in_(series_ids),
                AccessPass.status == AccessPassStatus.active,
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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

    # Row-locked for the duration of the booking decision. Two members
    # racing for the last seat now serialise here instead of both
    # counting the same confirmed total and both inserting. The bulk
    # "regular sessions" path takes the same lock, ordered by id, so
    # the two paths cannot oversell against each other either.
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.space_id == space.id, Event.is_published.is_(True))
        .with_for_update()
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

    # --- Entitlement check ---
    #
    # The decision lives in ``services.gathering_booking_rules`` so
    # that "Reserve your regular sessions" evaluates twenty
    # occurrences with the same rules this endpoint applies to one.
    # The behaviour is unchanged by the move: the reasons, the
    # messages and the status codes below are the ones this endpoint
    # has always returned, and the privilege nuances (bypass refusal,
    # never bypass consumption) are preserved verbatim there.
    #
    # Evaluated before the timing checks that follow, deliberately —
    # a member without a pass gets "you need a term pass" rather than
    # "this has already started", which is the more useful answer and
    # the order this endpoint already had.
    pass_decision = _evaluate_pass_for_event(
        db, user=current_user, event=event, is_privileged=is_privileged,
        # Locked: the occurrence row above stops two members racing for
        # the last seat, but the allowance is a property of the *pass*,
        # so two requests from the same member for two different
        # sessions would otherwise both see headroom and both spend it.
        lock_pass=True,
    )
    if pass_decision.denial is not None:
        raise HTTPException(
            status_code=pass_decision.denial.http_status,
            detail=pass_decision.denial.message,
        )
    access_pass_to_charge: AccessPass | None = pass_decision.charge

    if event.starts_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This gathering has already started.")
    if event.booking_closes_at and event.booking_closes_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking has closed for this gathering.")

    # Check capacity — shared with the bulk reserve path.
    capacity_problem = _capacity_denial(
        event, _confirmed_booking_count(db, event.id),
    )
    if capacity_problem is not None:
        raise HTTPException(
            status_code=capacity_problem.http_status,
            detail=capacity_problem.message,
        )

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
        # Comms — member booking confirmation. Replaces the legacy
        # trigger, which has stood down for this topic since
        # ``gatherings`` went live and left members with no email.
        emit_booking_confirmed(
            db, booking=existing, background_tasks=background_tasks,
        )
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
    emit_booking_confirmed(
        db, booking=booking, background_tasks=background_tasks,
    )
    return BookingResponse(status="confirmed", booking_id=booking.id)


@router.post("/{slug}/events/{event_id}/cancel-booking", response_model=BookingResponse)
def cancel_booking(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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
    #
    # A SoldOut refusal may be stale: holds now keep their seats past
    # their window until something positively resolves them (invariant
    # I2), so the seat a buyer is being refused may belong to a checkout
    # that quietly died. On the first refusal we verify those holds
    # against Stripe — OUTSIDE the Event lock, because a lock spanning a
    # network call would queue every other buyer of this Gathering behind
    # it — and then try exactly once more.
    #
    # One retry. If the second attempt still refuses, the holds are
    # genuinely live or genuinely unverifiable, and looping would spend
    # longer reaching the same answer.
    def _take_hold():
        return _gt.create_or_reuse_hold(
            db,
            offer=offer,
            buyer=current_user,
            fee_bps=fee_bps,
            creator_plan_id=plan_id,
            creator_subscription_id=sub_id,
            hold_ttl_minutes=settings.gathering_checkout_expiry_minutes,
        )

    try:
        try:
            outcome = _take_hold()
        except _gt.SoldOut:
            db.rollback()
            if not _gt.sweep_stale_holds(db, event_id=offer.event.id):
                raise
            outcome = _take_hold()
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

    # 6. Persist Stripe refs, and adopt Stripe's OWN expiry as canonical.
    #
    # The hold above was given a provisional, deliberately generous
    # expiry. Stripe enforces a minimum Session lifetime from its own
    # clock and may normalise what we asked for, so whatever it returns is
    # the truth — and writing that exact instant into the hold is what
    # makes the two impossible to disagree about. Two independently
    # computed timestamps was the original defect: the Session outlived
    # the hold by the gap between their calculations, and the seat was
    # sellable while still payable.
    outcome.transaction.provider_checkout_session_id = session.id
    outcome.transaction.provider_checkout_url = session.url

    session_expires_at = getattr(session, "expires_at", None)
    if session_expires_at:
        # Stripe reports a Unix timestamp; the column is naive UTC, as
        # every timestamp in this schema is.
        outcome.booking.hold_expires_at = datetime.fromtimestamp(
            int(session_expires_at), tz=timezone.utc,
        ).replace(tzinfo=None)

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

    # Normally a child of the Gatherings area — never more reachable
    # than the list it belongs to, or the list becomes a formality.
    #
    # The one exception: somebody holding a paid, confirmed booking for
    # THIS Gathering. A member who leaves keeps the reservation they
    # bought, and before this the area gate made that reservation
    # unreachable — intact in the database and invisible to its owner.
    #
    # Scoped to the reservation, not to the Collective. The resolver is
    # untouched, so the Gatherings list, the Pathways, the Channels and
    # the member directory all still refuse them; this opens one
    # Gathering to one person who paid for it. See
    # ``spaces.retained_reservations``.
    #
    # Loaded before the gate because the exception needs the event row
    # to ask the question. A non-existent Gathering still 404s first, so
    # the reordering tells an unauthorised caller nothing new.
    _paid_reservation = retained_reservations.find_purchased_booking(
        db, user_id=current_user.id if current_user else None, event=event,
    )
    if _paid_reservation is None:
        area_access.require_area(
            db, space, current_user, area_policies.AREA_GATHERINGS,
        )

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
    if (
        not is_member
        and not event.is_public
        and not _paid_event
        # A pass-funded reservation on a members-only Gathering: bought,
        # confirmed, and the holder has since left. Without this the
        # area exception above would be undone three lines later.
        and _paid_reservation is None
    ):
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
            # The authoritative count, not a copy of it. This used to
            # embed its own clock-based predicate, which after the
            # oversell fix meant member-facing availability disagreed
            # with the gate that actually allocates seats: a seat could
            # read "1 left" and then be refused on click. One function,
            # one answer — see invariant I2 in ``gathering_tickets``.
            booked_count = _gt.capacity_used(db, event.id)
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
    # A former member reading this page through the paid-reservation
    # exception may not book. ``book_event`` would refuse them anyway —
    # it keeps its own area gate and membership checks, and the
    # exception is deliberately not a caller — so without this the
    # payload would advertise a button that fails. Which is also the
    # honest answer after they cancel: coming back needs rejoining,
    # not a second pass through this page.
    if _paid_reservation is not None and not is_member:
        can_book = False
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
        # Public half, shared rule: locality first, never the
        # address. The sensitive fields above and below keep their
        # own attendee gate.
        **venue_projection.public_venue_fields(event),
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),  # SEC-009
) -> SeriesBookingResponse:
    """Book every remaining bookable session in a recurrence group.

    The recurrence group is a different thing from a Gathering Series:
    it is the "these rows were created together" tag a bulk create
    leaves behind, and this endpoint is reached from a Gathering's own
    page ("reserve the whole run"). It stays, and its response shape
    stays, because two surfaces consume it.

    What changed, and why it had to
    -------------------------------
    This endpoint used to check only Collective membership. It applied
    no access gate and no term-pass allowance, which made it a way
    around both: a member could reserve ``included_with_series``
    sessions without ever buying a term pass, and a pass holder's
    bookings were created with no ``access_pass_id``, so their weekly
    and total allowances were neither charged nor enforced. Capacity
    was counted but not locked.

    It now runs every occurrence through
    ``services.gathering_booking_rules`` — the same decisions the
    single-booking endpoint and "Reserve your regular sessions" apply.
    Legitimate existing behaviour is preserved exactly: ``free`` and
    ``included_with_collective`` sessions still book on membership
    alone, caretakers are still never refused, and the counting
    response is unchanged apart from one added field.
    """
    space = _get_space_or_404(slug, db)

    # A frozen or closed Collective accepts no bookings. The single
    # endpoint has refused this since Community Care shipped; this one
    # did not, which was the same omission in a quieter place.
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
    # Locked in id order, so two overlapping bulk requests cannot
    # deadlock and neither can oversell the last place. Ordered by
    # ``starts_at`` afterwards in Python, because the member-facing
    # ordering and the lock ordering are different concerns.
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
        .order_by(Event.id)
        .with_for_update()
        .all()
    )
    events.sort(key=lambda e: e.starts_at)
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No upcoming bookable sessions in this series.")

    event_ids = [e.id for e in events]
    existing_bookings: dict[str, "EventBooking"] = {
        b.event_id: b
        for b in db.query(EventBooking).filter(
            EventBooking.event_id.in_(event_ids),
            EventBooking.user_id == current_user.id,
        ).all()
    }

    is_privileged = getattr(membership, "role", None) in (
        SpaceRole.creator, SpaceRole.moderator,
    )
    if current_user.role == "admin" or space.creator_id == current_user.id:
        is_privileged = True

    booked = 0
    already_booked = 0
    created_bookings: list[EventBooking] = []
    skipped_full = 0
    skipped_closed = 0
    # New: an occurrence the member is not entitled to reserve. It used
    # to be booked anyway. Counted separately rather than folded into
    # ``skipped_closed``, because "you need a term pass" and "booking
    # has closed" are not the same news.
    skipped_unavailable = 0

    # Allowance consumed by this operation but not yet committed — a
    # pass allowing two a week cannot pay for five Mondays just because
    # none of them is in the database yet.
    pending_weekly: dict[datetime, int] = {}
    pending_total = 0
    pending_seats: dict[str, int] = {}

    for e in events:
        existing = existing_bookings.get(e.id)
        if existing and existing.status == BookingStatus.confirmed:
            already_booked += 1
            continue

        timing = _occurrence_timing_denial(e, now)
        if timing is not None:
            if timing.reason == "booking_closed":
                skipped_closed += 1
            else:
                skipped_unavailable += 1
            continue

        gate = _can_book_gate_shared(current_user, e, space, db)
        if not gate.allowed:
            skipped_unavailable += 1
            continue

        seats = pending_seats.get(e.id, 0)
        if _capacity_denial(
            e, _confirmed_booking_count(db, e.id), pending=seats,
        ) is not None:
            skipped_full += 1
            continue

        decision = _evaluate_pass_for_event(
            db, user=current_user, event=e, is_privileged=is_privileged,
            pending_weekly=pending_weekly, pending_total=pending_total,
            lock_pass=True,
        )
        if decision.denial is not None:
            skipped_unavailable += 1
            continue
        charge = decision.charge

        if existing:
            existing.status = BookingStatus.confirmed
            existing.booked_at = now
            existing.cancelled_at = None
            existing.access_pass_id = charge.id if charge else None
            existing.credits_used = 1 if charge else 0
            created_bookings.append(existing)
        else:
            fresh = EventBooking(
                id=str(uuid.uuid4()),
                event_id=e.id,
                user_id=current_user.id,
                status=BookingStatus.confirmed,
                booked_at=now,
                access_pass_id=charge.id if charge else None,
                credits_used=1 if charge else 0,
            )
            db.add(fresh)
            created_bookings.append(fresh)
        booked += 1
        pending_seats[e.id] = seats + 1
        if charge is not None:
            charge.used_credits += 1
            week_start, _ = _event_week_bounds(e)
            pending_weekly[week_start] = pending_weekly.get(week_start, 0) + 1
            pending_total += 1

    db.commit()

    # Comms — ONE summary for the whole action. Booking a Series creates
    # one EventBooking per occurrence; emailing each would be a flood
    # for a single click. Only the bookings actually created or
    # reactivated are reported — already-booked and skipped occurrences
    # are not news to the member.
    if created_bookings:
        series_row = None
        series_fk = next(
            (e.series_id for e in events if getattr(e, "series_id", None)), None,
        )
        if series_fk:
            series_row = (
                db.query(_EventSeriesModel)
            .filter(_EventSeriesModel.id == series_fk)
            .first()
            )
        emit_multi_booking_confirmed(
            db,
            user_id=current_user.id,
            bookings=created_bookings,
            space=space,
            scope=f"series:{series_id}",
            operation_at=now,
            series=series_row,
            added_by_creator=False,
            background_tasks=background_tasks,
        )

    return SeriesBookingResponse(
        booked=booked,
        already_booked=already_booked,
        skipped_full=skipped_full,
        skipped_closed=skipped_closed,
        skipped_unavailable=skipped_unavailable,
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
    # Same paid-reservation exception as ``get_event``: the calendar
    # entry is part of "what you need to turn up to the thing you
    # bought". Holder-scoped and event-scoped, like the other two.
    _holds_paid_reservation = retained_reservations.find_purchased_booking(
        db, user_id=current_user.id if current_user else None, event=event,
    ) is not None
    if not is_member and not event.is_public and not _holds_paid_reservation:
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
    p = _get_listed_pathway_or_404(space, pathway_slug, db, current_user)
    from app.models.payment_option_grant import PaymentOptionGrant as _POG_single
    unlock_offer_names = [
        row.name
        for row in db.query(PaymentOption.name)
        .join(_POG_single, _POG_single.payment_option_id == PaymentOption.id)
        .filter(
            _POG_single.grant_kind == "pathway",
            _POG_single.pathway_id == p.id,
            PaymentOption.status.in_([
                PaymentOptionStatus.published,
                PaymentOptionStatus.archived,
            ]),
        )
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
    pathway = _get_listed_pathway_or_404(space, pathway_slug, db, current_user)

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

    # Grants-first: an Option authored in the Payment Options editor
    # leaves ``pathway_id`` NULL and links through PaymentOptionGrant,
    # so asking the legacy column alone returned nothing for it.
    published_options = pathway_options.published_options_for_pathway(
        db, pathway.id,
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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

    Public — locked and anonymous visitors can view the About page as a
    preview/sales page. That is the point of this endpoint and it is
    unchanged: a published Pathway sells itself to strangers, and
    ``has_access`` elsewhere decides whether they may open its steps.

    **Listed Pathways only.** A draft has nothing to sell yet, and its
    About blocks are the sales copy a creator is still writing. This
    endpoint took the same unfiltered ``_get_pathway_or_404`` the two
    detail endpoints did, so it was the fourth anonymous way to read an
    unpublished Pathway — verified against production, which returned
    the draft's heading and body to an unauthenticated caller after the
    other three were closed.
    """
    space = _get_space_visible_to(slug, db, current_user)
    pathway = _get_listed_pathway_or_404(space, pathway_slug, db, current_user)
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
    current_user: User = Depends(get_verified_current_user),  # SEC-009
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
# Member-facing Gathering Series endpoints (M1). Imported here for the
# side effect of registering the endpoints on ``router`` — mirrors the
# ``_gathering_series_routes`` / ``_space_payment_options_routes``
# pattern used on the creator side.
# ---------------------------------------------------------------------------

from app.spaces import _series_member_routes as _series_member_routes  # noqa: E402,F401

# ---------------------------------------------------------------------------
# "Reserve your regular sessions" — same side-effect registration. Kept
# after the Series member routes because it resolves the same Series by
# slug and reads naturally as an extension of them.
# ---------------------------------------------------------------------------

from app.spaces import _regular_sessions_routes as _regular_sessions_routes  # noqa: E402,F401

# ---------------------------------------------------------------------------
# Exercise responses — same side-effect registration. A member's private
# writing against one Exercise block, shaped like the step-reflection
# endpoint above it because it is the same kind of thing at a finer
# grain.
# ---------------------------------------------------------------------------

from app.spaces import _exercise_response_routes as _exercise_response_routes  # noqa: E402,F401
