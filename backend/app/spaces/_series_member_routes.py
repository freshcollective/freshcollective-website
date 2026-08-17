"""Member-facing Gathering Series endpoints (M1).

Appended to ``spaces.routes.router`` so everything sits under the
existing ``/api/spaces`` prefix. Kept in its own module so
``spaces/routes.py`` doesn't grow another 500 lines while we
introduce the new member-facing Series surface.

Wire contract
-------------
    GET  /api/spaces/{slug}/gathering-series
        List published Series in this Collective, with a compact
        access-summary per Series for the current viewer so the
        member Gatherings landing can render one card per Series
        without follow-up round-trips.

    GET  /api/spaces/{slug}/gathering-series/{series_slug}
        Full member detail — identity + rich access summary +
        upcoming Gatherings (compact) + whether purchasable
        Payment Options exist. About blocks + Payment Options
        each have their own endpoint below to keep the payload
        composable and cacheable.

    GET  /api/spaces/{slug}/gathering-series/{series_slug}/about-blocks
        Rich About content authored by the Creator. Reads the
        polymorphic ``pathway_about_blocks`` table with
        ``owner_kind='event_series'`` (migration 113). Same shape
        as the Pathway About endpoint so the shared member
        renderer works verbatim.

    GET  /api/spaces/{slug}/gathering-series/{series_slug}/payment-options
        The Payment Options a member can actually buy today —
        filtered to: status='published', not archived, at least
        one published pay_in_full schedule, no Gathering grants
        (unified checkout refuses those). Draft / recurring /
        subscription / manual schedules are hidden from members
        entirely — Creator Studio surfaces them but they're not
        member choices yet.

Design decisions
----------------
* Reuse: this module never re-implements booking or checkout
  behaviour. The Series detail response describes state; actions
  (reserve, purchase) route through the existing endpoints.
* Access checks: viewer's Series access + remaining allowance is
  computed once (``_series_access_summary``) and returned inline.
  The list-endpoint version is a lightweight variant that skips
  the weekly-usage count so a Space with many Series stays cheap.
* Payment Option filtering: mirrors ``check_option_fulfillable``
  from the unified checkout — an option is only offered to a
  member if it has at least one published pay_in_full schedule
  AND does not carry a Gathering grant (which the unified
  endpoint refuses on purchase).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Iterable

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.creator.schemas import AboutBlockResponse
from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    BookingStatus,
    EventBooking,
    EventSeries,
    Event,
    Pathway,
    PathwayAboutBlock,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
)
from sqlalchemy.orm import selectinload as _selectinload  # noqa: E402
from app.models.user import User
from app.spaces.routes import router, _schedule_is_member_checkoutable


# ---------------------------------------------------------------------------
# Space + Series resolution helpers
# ---------------------------------------------------------------------------


def _get_space(slug: str, db: Session) -> Space:
    sp = db.query(Space).filter(Space.slug == slug).first()
    if not sp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found.")
    return sp


def _get_published_series(space: Space, series_slug: str, db: Session) -> EventSeries:
    series = (
        db.query(EventSeries)
        .filter(
            EventSeries.space_id == space.id,
            EventSeries.slug == series_slug,
            EventSeries.status == "published",
        )
        .first()
    )
    if not series:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gathering Series not found.",
        )
    return series


def _viewer_is_member(user: User | None, space: Space, db: Session) -> bool:
    if user is None:
        return False
    return (
        db.query(SpaceMembership.id)
        .filter(
            SpaceMembership.user_id == user.id,
            SpaceMembership.space_id == space.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SeriesAccessSummary(BaseModel):
    """The viewer's current relationship with the Series.

    Field names are Creator/Member language — no ``AccessPass``,
    ``eligible_series_id`` or ``credits_per_week`` in the wire.
    Only populated when the viewer holds an active pass; ``None``
    fields for anonymous / non-holder viewers.
    """
    has_access: bool = False
    # Human label for what the viewer bought (e.g. "Activate").
    option_name: str | None = None
    # Access window — the Series pass's valid_from / valid_until.
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    # Allowance — mapped from AccessPass credits fields into member
    # vocabulary. All optional because some passes are unlimited.
    gatherings_per_week: int | None = None
    gatherings_total: int | None = None
    gatherings_used: int | None = None
    gatherings_remaining: int | None = None
    # Weekly usage for the calendar week containing "now". Included
    # only when the pass has a weekly allowance so the frontend can
    # render "This week: 1 of 2" without a second call.
    used_this_week: int | None = None


class SeriesGatheringSummary(BaseModel):
    """Compact per-Gathering shape for the Series detail page.

    Only what the member needs to browse + reserve. Full detail
    remains on ``/events/{id}``.
    """
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    location_type: str
    attendance_format: str | None = None
    venue_name: str | None = None
    venue_locality: str | None = None
    thumbnail_url: str | None = None
    booking_access_type: str
    capacity: int | None = None
    booked_count: int = 0
    spots_remaining: int | None = None
    my_booking_status: str | None = None    # 'confirmed' | 'cancelled' | None
    is_past: bool = False


class SeriesSummary(BaseModel):
    """One card on the member Gatherings landing."""
    id: str
    slug: str
    title: str
    description: str | None = None
    cover_image_url: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    # Counts to help the card carry useful metadata without a
    # second fetch. ``upcoming_gathering_count`` excludes past.
    total_gathering_count: int = 0
    upcoming_gathering_count: int = 0
    # Purchasable indicator — used by the card to show "Ways to
    # join" affordances without fetching the full option list.
    has_purchasable_options: bool = False
    # Compact access summary — full detail lives on the Series
    # detail endpoint. Anonymous viewers see ``has_access=False``.
    access: SeriesAccessSummary


class SeriesDetail(SeriesSummary):
    """Full Series member detail — augments ``SeriesSummary`` with
    the upcoming Gatherings list (and past, for archive display).
    About blocks + Payment Options are separate endpoints so the
    payload stays composable."""
    upcoming_gatherings: list[SeriesGatheringSummary] = []
    past_gatherings: list[SeriesGatheringSummary] = []


class MemberPaymentOptionScheduleOut(BaseModel):
    """One payment method attached to a Payment Option, from the
    member's perspective. Shape is deliberately generic so a single
    Payment Option (e.g. Awaken) can carry multiple methods in one
    payload — pay-in-full plus, eventually, finite instalments —
    without a schema change per launch.

    ``is_member_checkoutable`` is the single source of truth for
    "should the member surface offer a CTA for this?" Recurring
    instalment schedules ship with the payload for future readiness
    but are False today; the frontend filters on the flag and never
    on ``schedule_type`` itself. See
    ``app.spaces.routes._schedule_is_member_checkoutable``.
    """
    id: str
    name: str
    schedule_type: str                       # 'pay_in_full' | 'recurring_installments' | 'manual'
    total_amount_cents: int
    installment_amount_cents: int | None = None
    installment_count: int | None = None
    interval: str | None = None
    currency: str
    is_member_checkoutable: bool = False


class MemberPaymentOptionOut(BaseModel):
    """A Payment Option the current viewer can actually purchase.

    Includes each grant's target title so the card can print
    "Includes EMBODY Term 3 2026 · The EMBODY Practice" without a
    per-row lookup. Schedules are already filtered to those a
    member can check out today (published pay_in_full only).
    """
    id: str
    name: str
    description: str | None = None
    # ``allowance_per_week`` / ``allowance_total`` are read from the
    # Series-grant on this option so the card can render "2/week ·
    # 20 total" without inspecting the raw grants payload.
    allowance_per_week: int | None = None
    allowance_total: int | None = None
    included_titles: list[str] = []
    schedules: list[MemberPaymentOptionScheduleOut] = []
    # ``viewer_holds_this_option`` — true when the current viewer
    # already has active access from this exact Payment Option.
    # Lets the UI hide the purchase CTA rather than offer a
    # redundant repurchase (matches the backend duplicate guard).
    viewer_holds_this_option: bool = False


# ---------------------------------------------------------------------------
# Series access summary
# ---------------------------------------------------------------------------


def _find_active_series_pass(
    user: User | None, series_id: str, db: Session, now: datetime,
) -> AccessPass | None:
    if user is None:
        return None
    return (
        db.query(AccessPass)
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
        .order_by(AccessPass.created_at.desc())
        .first()
    )


def _weekly_usage_for(pass_id: str, now: datetime, db: Session) -> int:
    """Count confirmed bookings on this pass within the calendar
    week that contains ``now`` (Monday 00:00 → next Monday 00:00,
    matching the booking endpoint's own weekly bucket)."""
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    week_end = week_start + timedelta(days=7)
    return (
        db.query(func.count(EventBooking.id))
        .join(Event, EventBooking.event_id == Event.id)
        .filter(
            EventBooking.access_pass_id == pass_id,
            EventBooking.status == BookingStatus.confirmed,
            Event.starts_at >= week_start,
            Event.starts_at < week_end,
        )
        .scalar()
    ) or 0


def _series_access_summary(
    user: User | None, series_id: str, db: Session, now: datetime,
    *, include_weekly_usage: bool,
) -> SeriesAccessSummary:
    pass_row = _find_active_series_pass(user, series_id, db, now)
    if pass_row is None:
        return SeriesAccessSummary(has_access=False)
    option_name: str | None = None
    if pass_row.payment_option_id:
        opt = (
            db.query(PaymentOption.name)
            .filter(PaymentOption.id == pass_row.payment_option_id)
            .first()
        )
        option_name = opt[0] if opt else None
    weekly = (
        _weekly_usage_for(pass_row.id, now, db)
        if include_weekly_usage and pass_row.credits_per_week is not None
        else None
    )
    return SeriesAccessSummary(
        has_access=True,
        option_name=option_name,
        valid_from=pass_row.valid_from,
        valid_until=pass_row.valid_until,
        gatherings_per_week=pass_row.credits_per_week,
        gatherings_total=pass_row.total_credits,
        gatherings_used=pass_row.used_credits,
        gatherings_remaining=pass_row.remaining_credits,
        used_this_week=weekly,
    )


# ---------------------------------------------------------------------------
# Purchasable-option filter — shared with the reverse-lookup
# ---------------------------------------------------------------------------


@dataclass
class _PurchasableOption:
    option: PaymentOption
    schedules: list[PaymentOptionSchedule]
    series_grant: PaymentOptionGrant | None
    included_titles: list[str]


def _member_purchasable_options_for_series(
    series: EventSeries, space: Space, db: Session,
) -> list[_PurchasableOption]:
    """Return the Payment Options in this Collective that grant
    access to ``series`` AND are safely purchasable by a member
    today.

    Filters:
      * PaymentOption.status == 'published' (never archived / draft)
      * PaymentOption is in this Collective
      * At least one PaymentOptionGrant of kind='event_series'
        pointing at this Series
      * NO PaymentOptionGrant of kind='gathering' on the option —
        the unified checkout refuses those, so we don't offer them
      * At least one PaymentOptionSchedule with type='pay_in_full'
        AND status='published' — the only schedule shape the
        member checkout runs today. Recurring / manual / subscription
        schedules stay authoring-only (Creator Studio surfaces them).
    """
    # Options that grant this Series.
    q = (
        db.query(PaymentOption)
        .join(PaymentOptionGrant, PaymentOptionGrant.payment_option_id == PaymentOption.id)
        .filter(
            PaymentOption.space_id == space.id,
            PaymentOption.status == "published",
            PaymentOptionGrant.grant_kind == "event_series",
            PaymentOptionGrant.series_id == series.id,
        )
        .distinct()
    )
    candidates: list[PaymentOption] = q.all()
    if not candidates:
        return []

    opt_ids = [o.id for o in candidates]

    # Grants by option — used to (a) exclude options with Gathering
    # grants, (b) pull the Series-grant allowance, (c) resolve
    # included pathway titles.
    grants_by_opt: dict[str, list[PaymentOptionGrant]] = {}
    for g in (
        db.query(PaymentOptionGrant)
        .filter(PaymentOptionGrant.payment_option_id.in_(opt_ids))
        .all()
    ):
        grants_by_opt.setdefault(g.payment_option_id, []).append(g)

    # All published schedules by option — including recurring
    # instalments. The member frontend must never advertise a schedule
    # the backend would refuse, so each schedule ships with the
    # explicit ``is_member_checkoutable`` flag (see the helper in
    # ``routes.py``). Filtering happens on the flag downstream. This
    # keeps the shape multi-schedule ready for the day instalments
    # land without changing the endpoint contract.
    scheds_by_opt: dict[str, list[PaymentOptionSchedule]] = {}
    for s in (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.payment_option_id.in_(opt_ids),
            PaymentOptionSchedule.status == "published",
        )
        .order_by(PaymentOptionSchedule.position, PaymentOptionSchedule.created_at)
        .all()
    ):
        scheds_by_opt.setdefault(s.payment_option_id, []).append(s)

    # Pathway titles for included-list rendering.
    pathway_ids = {
        g.pathway_id
        for gs in grants_by_opt.values()
        for g in gs
        if g.grant_kind == "pathway" and g.pathway_id
    }
    pathway_titles = (
        {p_id: title for (p_id, title) in db.query(Pathway.id, Pathway.title).filter(Pathway.id.in_(pathway_ids)).all()}
        if pathway_ids else {}
    )

    out: list[_PurchasableOption] = []
    for opt in candidates:
        grants = grants_by_opt.get(opt.id, [])
        # Refuse anything with a Gathering grant — unified checkout
        # refuses those, so member should never see them as buyable.
        if any(g.grant_kind == "gathering" for g in grants):
            continue
        # Must have at least one schedule the member can actually
        # complete checkout for. Draft rows are already filtered out
        # by the query; ``_schedule_is_member_checkoutable`` also
        # rejects recurring_installments today. Options whose only
        # published schedules are recurring-instalment-only stay
        # hidden until the Commerce milestone flips the helper.
        pubs = scheds_by_opt.get(opt.id, [])
        if not any(_schedule_is_member_checkoutable(s, opt) for s in pubs):
            continue
        # The Series-grant carries the allowance we display.
        series_grant = next(
            (g for g in grants if g.grant_kind == "event_series" and g.series_id == series.id),
            None,
        )
        included = [series.title]
        for g in grants:
            if g.grant_kind == "pathway" and g.pathway_id in pathway_titles:
                included.append(pathway_titles[g.pathway_id])
        out.append(_PurchasableOption(
            option=opt,
            schedules=pubs,
            series_grant=series_grant,
            included_titles=included,
        ))
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _count_upcoming(series_id: str, db: Session, now: datetime) -> int:
    return (
        db.query(func.count(Event.id))
        .filter(
            Event.series_id == series_id,
            Event.is_published.is_(True),
            Event.status == "active",
            or_(
                Event.ends_at.is_(None) & (Event.starts_at >= now),
                Event.ends_at > now,
            ),
        )
        .scalar()
    ) or 0


def _count_total(series_id: str, db: Session) -> int:
    return (
        db.query(func.count(Event.id))
        .filter(
            Event.series_id == series_id,
            Event.is_published.is_(True),
            Event.status == "active",
        )
        .scalar()
    ) or 0


@router.get("/{slug}/gathering-series", response_model=list[SeriesSummary])
def list_member_gathering_series(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[SeriesSummary]:
    """Published Series in this Collective for the member landing.

    Anonymous viewers see the same list (Series are Collective-
    scoped and inherit the Space's own visibility). Each row
    carries a compact access summary so the landing cards can
    render "You have Activate access" without a second call.

    Weekly-usage count is deliberately omitted here to keep the
    list cheap when a Collective has many Series — it's only
    populated on the detail endpoint.
    """
    space = _get_space(slug, db)
    now = datetime.utcnow()

    series_rows = (
        db.query(EventSeries)
        .filter(
            EventSeries.space_id == space.id,
            EventSeries.status == "published",
        )
        .order_by(EventSeries.starts_at.desc())
        .all()
    )
    if not series_rows:
        return []

    # Bulk-check purchasable options presence — one SELECT rather
    # than one per Series. Materialise `EXISTS` per series_id.
    series_ids = [s.id for s in series_rows]
    purchasable_ids: set[str] = set()
    for (sid,) in (
        db.query(PaymentOptionGrant.series_id)
        .join(PaymentOption, PaymentOption.id == PaymentOptionGrant.payment_option_id)
        .filter(
            PaymentOption.space_id == space.id,
            PaymentOption.status == "published",
            PaymentOptionGrant.grant_kind == "event_series",
            PaymentOptionGrant.series_id.in_(series_ids),
        )
        .distinct()
        .all()
    ):
        if sid:
            purchasable_ids.add(sid)

    out: list[SeriesSummary] = []
    for series in series_rows:
        # The list-side purchasable indicator is deliberately a
        # lightweight EXISTS on Series-grants alone. It ignores the
        # published-pay_in_full-schedule filter that the detail
        # endpoint applies — mainly so the landing card can still
        # invite the member to "See ways to join" and let the
        # detail page speak authoritatively. In practice for
        # published Series this is a strict subset check anyway.
        access = _series_access_summary(
            current_user, series.id, db, now, include_weekly_usage=False,
        )
        out.append(SeriesSummary(
            id=series.id,
            slug=series.slug,
            title=series.title,
            description=series.description,
            cover_image_url=series.cover_image_url,
            starts_at=series.starts_at,
            ends_at=series.ends_at,
            total_gathering_count=_count_total(series.id, db),
            upcoming_gathering_count=_count_upcoming(series.id, db, now),
            has_purchasable_options=(series.id in purchasable_ids),
            access=access,
        ))
    return out


def _gathering_summary(
    ev: Event, user: User | None, db: Session, now: datetime,
) -> SeriesGatheringSummary:
    booked = (
        db.query(func.count(EventBooking.id))
        .filter(
            EventBooking.event_id == ev.id,
            EventBooking.status == BookingStatus.confirmed,
        )
        .scalar()
    ) or 0
    my_status: str | None = None
    if user is not None:
        my = (
            db.query(EventBooking.status)
            .filter(
                EventBooking.event_id == ev.id,
                EventBooking.user_id == user.id,
            )
            .order_by(EventBooking.booked_at.desc())
            .first()
        )
        if my is not None:
            my_status = my[0].value if hasattr(my[0], "value") else str(my[0])
    spots_remaining = (
        max(0, (ev.capacity or 0) - booked) if ev.capacity is not None else None
    )
    is_past = bool(ev.ends_at and ev.ends_at < now) or (
        not ev.ends_at and ev.starts_at < now
    )
    return SeriesGatheringSummary(
        id=ev.id,
        title=ev.title,
        starts_at=ev.starts_at,
        ends_at=ev.ends_at,
        location_type=ev.location_type.value if hasattr(ev.location_type, "value") else str(ev.location_type),
        attendance_format=getattr(ev, "attendance_format", None),
        venue_name=getattr(ev, "venue_name", None),
        venue_locality=getattr(ev, "venue_locality", None),
        thumbnail_url=ev.thumbnail_url,
        booking_access_type=(
            ev.booking_access_type.value if hasattr(ev.booking_access_type, "value")
            else str(getattr(ev, "booking_access_type", "included_with_collective"))
        ),
        capacity=ev.capacity,
        booked_count=booked,
        spots_remaining=spots_remaining,
        my_booking_status=my_status,
        is_past=is_past,
    )


@router.get(
    "/{slug}/gathering-series/{series_slug}",
    response_model=SeriesDetail,
)
def get_member_gathering_series(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> SeriesDetail:
    """Full member detail for a Series — identity + access +
    upcoming Gatherings + past Gatherings (compact)."""
    space = _get_space(slug, db)
    series = _get_published_series(space, series_slug, db)
    now = datetime.utcnow()

    access = _series_access_summary(
        current_user, series.id, db, now, include_weekly_usage=True,
    )

    # Same visibility filter as the count / list endpoints:
    # published + not cancelled. Cancelled events never render on
    # the member Series page (the Creator archive still surfaces
    # them via a separate creator-side endpoint).
    events = (
        db.query(Event)
        .filter(
            Event.series_id == series.id,
            Event.is_published.is_(True),
            Event.status == "active",
        )
        .order_by(Event.starts_at.asc())
        .all()
    )
    upcoming: list[SeriesGatheringSummary] = []
    past: list[SeriesGatheringSummary] = []
    for ev in events:
        summary = _gathering_summary(ev, current_user, db, now)
        (past if summary.is_past else upcoming).append(summary)

    # Purchasable-option presence — mirrors the list endpoint but
    # here we care about the *stricter* rule (needs a published
    # pay_in_full schedule) so the frontend knows whether to render
    # the "Ways to join" section at all.
    has_purchasable = bool(
        _member_purchasable_options_for_series(series, space, db)
    )

    return SeriesDetail(
        id=series.id,
        slug=series.slug,
        title=series.title,
        description=series.description,
        cover_image_url=series.cover_image_url,
        starts_at=series.starts_at,
        ends_at=series.ends_at,
        total_gathering_count=len(events),
        upcoming_gathering_count=len(upcoming),
        has_purchasable_options=has_purchasable,
        access=access,
        upcoming_gatherings=upcoming,
        past_gatherings=past,
    )


@router.get(
    "/{slug}/gathering-series/{series_slug}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def get_member_series_about_blocks(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[PathwayAboutBlock]:
    """Rich About blocks for the member Series page. Reads the
    polymorphic ``pathway_about_blocks`` table with
    ``owner_kind='event_series'``. Same response shape as the
    Pathway About endpoint so the shared frontend renderer works
    verbatim.

    Anonymous readers see the same content — Series About is
    presentational, no member-only content lives here today.
    """
    space = _get_space(slug, db)
    series = _get_published_series(space, series_slug, db)
    from sqlalchemy.orm import selectinload
    return (
        db.query(PathwayAboutBlock)
        .options(
            selectinload(PathwayAboutBlock.media_asset),
            selectinload(PathwayAboutBlock.resource),
        )
        .filter(
            PathwayAboutBlock.owner_kind == "event_series",
            PathwayAboutBlock.owner_id == series.id,
        )
        .order_by(PathwayAboutBlock.position)
        .all()
    )


@router.get(
    "/{slug}/gathering-series/{series_slug}/payment-options",
    response_model=list[MemberPaymentOptionOut],
)
def list_member_series_payment_options(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[MemberPaymentOptionOut]:
    """The Payment Options a member can currently buy for this
    Series. See ``_member_purchasable_options_for_series`` for
    the exact filter."""
    space = _get_space(slug, db)
    series = _get_published_series(space, series_slug, db)
    now = datetime.utcnow()

    # Which options does the current viewer already actively hold?
    # Used to hide the CTA on options they already own.
    held_option_ids: set[str] = set()
    if current_user is not None:
        for (oid,) in (
            db.query(AccessPass.payment_option_id)
            .filter(
                AccessPass.user_id == current_user.id,
                AccessPass.space_id == space.id,
                AccessPass.status == AccessPassStatus.active,
                AccessPass.payment_option_id.isnot(None),
                or_(
                    AccessPass.valid_until.is_(None),
                    AccessPass.valid_until > now,
                ),
            )
            .distinct()
            .all()
        ):
            if oid:
                held_option_ids.add(oid)

    out: list[MemberPaymentOptionOut] = []
    for po in _member_purchasable_options_for_series(series, space, db):
        allowance_per_week = po.series_grant.sessions_per_week if po.series_grant else None
        allowance_total = po.series_grant.total_sessions if po.series_grant else None
        out.append(MemberPaymentOptionOut(
            id=po.option.id,
            name=po.option.name,
            description=po.option.description,
            allowance_per_week=allowance_per_week,
            allowance_total=allowance_total,
            included_titles=po.included_titles,
            schedules=[
                MemberPaymentOptionScheduleOut(
                    id=s.id,
                    name=s.name,
                    schedule_type=s.schedule_type,
                    total_amount_cents=s.total_amount_cents or 0,
                    installment_amount_cents=s.installment_amount_cents,
                    installment_count=s.installment_count,
                    # Prefer human ``interval`` when set; fall back to
                    # ``stripe_interval`` so the frontend's
                    # ``humanCadence`` helper produces "weekly" /
                    # "fortnightly" / "monthly" rather than the generic
                    # "recurring" fallback.
                    interval=s.interval or s.stripe_interval,
                    currency=s.currency or "AUD",
                    is_member_checkoutable=_schedule_is_member_checkoutable(s, po.option),
                )
                for s in po.schedules
            ],
            viewer_holds_this_option=po.option.id in held_option_ids,
        ))
    return out


# ---------------------------------------------------------------------------
# Member-side Event About blocks (M1 refinement)
#
# The Creator writes rich About content via the creator-side CRUD in
# ``_event_about_routes.py``. Members read it via this endpoint,
# which enforces the same event visibility rules the Event detail
# endpoint uses (published + is_public or member of Space).
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/events/{event_id}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def get_member_event_about_blocks(
    slug: str,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> list[PathwayAboutBlock]:
    """Rich About blocks for an individual Gathering. Same visibility
    rules as ``get_event``: published Events are readable to members;
    public-ish paid or public Events are readable to anyone with the
    URL. Content itself is presentational — no attendee-gated fields."""
    space = _get_space(slug, db)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gathering not found.")

    # Visibility parity with ``get_event``: paid-separately events
    # are effectively-public (buyers with the URL must see the About);
    # everything else requires membership when not is_public.
    is_paid = getattr(event, 'booking_access_type', None) == 'paid_separately'
    if not event.is_public and not is_paid:
        if current_user is None or not _viewer_is_member(current_user, space, db):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gathering not found.")

    return (
        db.query(PathwayAboutBlock)
        .options(
            _selectinload(PathwayAboutBlock.media_asset),
            _selectinload(PathwayAboutBlock.resource),
        )
        .filter(
            PathwayAboutBlock.owner_kind == "event",
            PathwayAboutBlock.owner_id == event.id,
        )
        .order_by(PathwayAboutBlock.position)
        .all()
    )
