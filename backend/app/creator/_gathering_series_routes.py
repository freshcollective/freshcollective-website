"""Gathering Series creator routes — appended to ``creator.routes.router``.

Kept in its own module purely for readability: ``creator/routes.py`` is
already ~7,600 lines. The router itself is imported and mutated here so
FastAPI still exposes the endpoints under the same ``/api/creator``
prefix as every other creator route.

Endpoints:

    GET     /spaces/{slug}/gathering-series
    POST    /spaces/{slug}/gathering-series
    GET     /spaces/{slug}/gathering-series/{series_slug}
    PATCH   /spaces/{slug}/gathering-series/{series_slug}
    DELETE  /spaces/{slug}/gathering-series/{series_slug}

    GET     /spaces/{slug}/gathering-series/{series_slug}/payment-options
    POST    /spaces/{slug}/gathering-series/{series_slug}/payment-options
    PATCH   /spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}
    DELETE  /spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}

The event <-> series attachment is handled through the existing event
PATCH endpoint (``series_id`` in ``EventUpdateRequest``) rather than a
dedicated attach/detach route — one code path for all edits, one
validation helper, one 404/permission story.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.creator.routes import (
    _event_to_dict,
    _get_gathering_series,
    _get_managed_space,
    _normalise_button_fields,
    _option_to_dict,
    _schedule_to_dict,
    _unique_slug,
    get_creator_user,
    router,
)
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockReorderRequest,
    AboutBlockResponse,
    AboutBlockUpdateRequest,
    GatheringSeriesCreateRequest,
    GatheringSeriesResponse,
    GatheringSeriesSummary,
    GatheringSeriesUpdateRequest,
    GenerateSchedulesRequest,
    PaymentOptionResponse,
    PaymentOptionScheduleCreateRequest,
    PaymentOptionScheduleResponse,
    PaymentOptionScheduleUpdateRequest,
    SeriesPaymentOptionCreateRequest,
    SeriesPaymentOptionUpdateRequest,
)
from app.services.embed_validator import (
    EmbedValidationError,
    extract_and_validate_embed_url,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    CreatorMediaAsset,
    Event,
    EventSeries,
    PathwayAboutBlock,
    SpaceResource,
    StepBlockType,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.user import User

from sqlalchemy import func
from sqlalchemy.orm import selectinload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _slugify(title: str) -> str:
    base = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)
    return base or "series"


def _generate_unique_series_slug(space_id: str, title: str, db: Session) -> str:
    base = _slugify(title)[:100]
    existing = {
        row[0]
        for row in db.query(EventSeries.slug)
        .filter(EventSeries.space_id == space_id)
        .all()
    }
    return _unique_slug(base, list(existing))


def _series_to_dict(series: EventSeries) -> dict:
    return {
        "id": series.id,
        "space_id": series.space_id,
        "slug": series.slug,
        "title": series.title,
        "description": series.description,
        "starts_at": series.starts_at,
        "ends_at": series.ends_at,
        "status": series.status,
        "cover_image_url": series.cover_image_url,
        "published_at": series.published_at,
        "created_at": series.created_at,
        "updated_at": series.updated_at,
    }


def _series_summary(
    series: EventSeries, *, gathering_count: int, payment_option_count: int,
) -> dict:
    return {
        "id": series.id,
        "slug": series.slug,
        "title": series.title,
        "starts_at": series.starts_at,
        "ends_at": series.ends_at,
        "status": series.status,
        "cover_image_url": series.cover_image_url,
        "gathering_count": gathering_count,
        "payment_option_count": payment_option_count,
        "published_at": series.published_at,
        "updated_at": series.updated_at,
    }


# ---------------------------------------------------------------------------
# Series CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/spaces/{slug}/gathering-series",
    response_model=list[GatheringSeriesSummary],
    summary="List Gathering Series for a Collective",
)
def list_gathering_series(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    from sqlalchemy import func as _sqfn
    space = _get_managed_space(slug, current_user, db)
    rows = (
        db.query(EventSeries)
        .filter(EventSeries.space_id == space.id)
        .order_by(EventSeries.starts_at.desc())
        .all()
    )
    if not rows:
        return []
    ids = [s.id for s in rows]
    ev_counts = dict(
        db.query(Event.series_id, _sqfn.count(Event.id))
        .filter(Event.series_id.in_(ids))
        .group_by(Event.series_id)
        .all()
    )
    po_counts = dict(
        db.query(PaymentOption.attaches_to_id, _sqfn.count(PaymentOption.id))
        .filter(
            PaymentOption.attaches_to_kind == "event_series",
            PaymentOption.attaches_to_id.in_(ids),
            PaymentOption.status != PaymentOptionStatus.archived,
        )
        .group_by(PaymentOption.attaches_to_id)
        .all()
    )
    return [
        _series_summary(
            s,
            gathering_count=ev_counts.get(s.id, 0),
            payment_option_count=po_counts.get(s.id, 0),
        )
        for s in rows
    ]


@router.post(
    "/spaces/{slug}/gathering-series",
    response_model=GatheringSeriesResponse,
    status_code=201,
    summary="Create a new Gathering Series (draft)",
)
def create_gathering_series(
    slug: str,
    body: GatheringSeriesCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)

    if body.ends_at is not None and body.ends_at <= body.starts_at:
        raise HTTPException(
            status_code=400,
            detail="End date must be after the start date.",
        )

    if body.slug:
        conflict = (
            db.query(EventSeries)
            .filter(EventSeries.space_id == space.id, EventSeries.slug == body.slug)
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=400,
                detail="A Gathering Series with this slug already exists.",
            )
        slug_value = body.slug
    else:
        slug_value = _generate_unique_series_slug(space.id, body.title, db)

    row = EventSeries(
        id=f"es_{uuid4().hex[:12]}",
        space_id=space.id,
        slug=slug_value,
        title=body.title,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        status="draft",
        cover_image_url=body.cover_image_url,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _series_to_dict(row)


@router.get(
    "/spaces/{slug}/gathering-series/{series_slug}",
    response_model=GatheringSeriesResponse,
    summary="Get one Gathering Series",
)
def get_gathering_series(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    return _series_to_dict(_get_gathering_series(space, series_slug, db))


@router.patch(
    "/spaces/{slug}/gathering-series/{series_slug}",
    response_model=GatheringSeriesResponse,
    summary="Update a Gathering Series (partial)",
)
def update_gathering_series(
    slug: str,
    series_slug: str,
    body: GatheringSeriesUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    row = _get_gathering_series(space, series_slug, db)
    sent = body.model_fields_set

    if "title" in sent and body.title is not None:
        row.title = body.title
    if "description" in sent:
        row.description = (body.description or "").strip() or None
    if "cover_image_url" in sent:
        v = (body.cover_image_url or "").strip() if body.cover_image_url else None
        row.cover_image_url = v or None
    if "starts_at" in sent and body.starts_at is not None:
        row.starts_at = body.starts_at
    # ``ends_at`` uses model_fields_set so ``null`` explicitly turns
    # a finite series ongoing without a separate endpoint.
    if "ends_at" in sent:
        row.ends_at = body.ends_at
    if row.ends_at is not None and row.ends_at <= row.starts_at:
        raise HTTPException(
            status_code=400,
            detail="End date must be after the start date.",
        )
    if "status" in sent and body.status is not None:
        # Stamp published_at the first time the Series transitions to
        # 'published' — never cleared. Enables the delete-vs-archive
        # lifecycle rule (never-published drafts can be hard-deleted;
        # once-public Series are archived instead).
        if body.status == "published" and row.published_at is None:
            row.published_at = datetime.utcnow()
        row.status = body.status

    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _series_to_dict(row)


@router.delete(
    "/spaces/{slug}/gathering-series/{series_slug}",
    status_code=204,
    summary=(
        "Delete a Gathering Series — allowed only when it has never "
        "been published and has no historical AccessPass references. "
        "Attached Gatherings are auto-detached (not deleted)."
    ),
)
def delete_gathering_series(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Lifecycle rule (see step-2 polish):

    A draft Series that has never been meaningfully used is
    permanently deletable. Anything that has ever been publicly
    seen — or that has any AccessPass row scoped to it — must be
    archived instead so historical booking / entitlement records
    keep a resolvable target. Attached Gatherings are auto-detached
    on delete (their ``series_id`` is set to NULL); the Gatherings
    themselves are never removed.
    """
    # Local imports keep the module import graph light; AccessPass
    # is only touched on this rare code path.
    from app.models.access_pass import AccessPass

    space = _get_managed_space(slug, current_user, db)
    row = _get_gathering_series(space, series_slug, db)

    # Published-ever → archive-only. The frontend surfaces "Archive"
    # rather than "Delete" for this state; this backend refusal is a
    # defence-in-depth check.
    if row.published_at is not None or row.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                "This Gathering Series has been published or is no longer "
                "a draft. Archive it instead so previously shared links "
                "and any Series passes keep resolving to the same record."
            ),
        )

    # Any AccessPass ever scoped to this Series (regardless of status)
    # blocks hard-delete. Losing the target would orphan the pass's
    # ``eligible_series_id`` reference — a data-integrity risk we
    # refuse to take even on a draft Series.
    pass_ref = (
        db.query(AccessPass.id)
        .filter(AccessPass.eligible_series_id == row.id)
        .first()
    )
    if pass_ref:
        raise HTTPException(
            status_code=409,
            detail=(
                "Historical passes are scoped to this Series. Archive it "
                "instead so those records keep a valid reference."
            ),
        )

    # Active (non-archived) Payment Options must be resolved first —
    # they belong to the Series and archiving them is a Creator choice,
    # not an automatic side effect of Series deletion.
    active_options = (
        db.query(PaymentOption.id)
        .filter(
            PaymentOption.attaches_to_kind == "event_series",
            PaymentOption.attaches_to_id == row.id,
            PaymentOption.status != PaymentOptionStatus.archived,
        )
        .first()
    )
    if active_options:
        raise HTTPException(
            status_code=409,
            detail=(
                "This Gathering Series has active Payment Options. "
                "Archive them first."
            ),
        )

    # Auto-detach attached Gatherings. The events themselves are not
    # deleted — Series membership is a semantic tag, not ownership.
    (
        db.query(Event)
        .filter(Event.series_id == row.id)
        .update({Event.series_id: None}, synchronize_session=False)
    )

    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Attached Gatherings — list only (attach/detach is done via the existing
# event PATCH ``series_id`` field so there's one code path per change).
# ---------------------------------------------------------------------------


@router.get(
    "/spaces/{slug}/gathering-series/{series_slug}/gatherings",
    summary="List Gatherings attached to this Series",
)
def list_series_gatherings(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    events = (
        db.query(Event)
        .filter(Event.series_id == series.id)
        .order_by(Event.starts_at.asc())
        .all()
    )
    # Reuse the shared serialiser so the shape matches every other
    # events endpoint; booking counts are zeroed here (not needed on
    # this surface — the events list page has richer aggregates).
    return [_event_to_dict(e, 0) for e in events]


# ---------------------------------------------------------------------------
# Series-attached Payment Options
# ---------------------------------------------------------------------------


def _get_series_option(
    option_id: str, series: EventSeries, db: Session,
) -> PaymentOption:
    opt = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.id == option_id,
            PaymentOption.attaches_to_kind == "event_series",
            PaymentOption.attaches_to_id == series.id,
        )
        .first()
    )
    if not opt:
        raise HTTPException(status_code=404, detail="Payment option not found.")
    return opt


def _validate_series_grants_pathway(
    pathway_id: str | None, space_id: str, db: Session,
) -> str | None:
    """When set, ``grants_pathway_id`` must reference a Pathway in
    the same Space. Return the id verbatim; raise 400 otherwise.
    Null passes through unchanged."""
    if not pathway_id:
        return None
    from app.models.platform import Pathway
    p = (
        db.query(Pathway)
        .filter(Pathway.id == pathway_id, Pathway.space_id == space_id)
        .first()
    )
    if not p:
        raise HTTPException(
            status_code=400,
            detail="Included Pathway must belong to this Collective.",
        )
    return p.id


@router.get(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options",
    response_model=list[PaymentOptionResponse],
    summary="List Payment Options for a Gathering Series",
)
def list_series_payment_options(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    opts = (
        db.query(PaymentOption)
        .filter(
            PaymentOption.attaches_to_kind == "event_series",
            PaymentOption.attaches_to_id == series.id,
        )
        .order_by(PaymentOption.position, PaymentOption.created_at)
        .all()
    )
    return [_option_to_dict(o) for o in opts]


@router.post(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options",
    response_model=PaymentOptionResponse,
    status_code=201,
    summary="Create a Payment Option attached to a Gathering Series",
)
def create_series_payment_option(
    slug: str,
    series_slug: str,
    body: SeriesPaymentOptionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)

    grants_pw = _validate_series_grants_pathway(body.grants_pathway_id, space.id, db)

    max_pos = (
        db.query(PaymentOption.position)
        .filter(
            PaymentOption.attaches_to_kind == "event_series",
            PaymentOption.attaches_to_id == series.id,
        )
        .order_by(PaymentOption.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    calculated_total = body.calculated_total_cents
    if calculated_total is None and body.total_sessions and body.price_per_session_cents:
        calculated_total = body.total_sessions * body.price_per_session_cents

    now = datetime.utcnow()
    opt = PaymentOption(
        id=str(uuid4()),
        space_id=space.id,
        pathway_id=None,  # series-attached options are not scoped to a pathway
        attaches_to_kind="event_series",
        attaches_to_id=series.id,
        grants_pathway_id=grants_pw,
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
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}",
    response_model=PaymentOptionResponse,
    summary="Update a series-attached Payment Option (partial)",
)
def update_series_payment_option(
    slug: str,
    series_slug: str,
    option_id: str,
    body: SeriesPaymentOptionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    opt = _get_series_option(option_id, series, db)
    sent = body.model_fields_set

    scalar_fields = (
        "name", "description", "payment_type", "status", "term_start_date",
        "term_end_date", "sessions_per_week", "total_sessions",
        "price_per_session_cents", "calculated_total_cents",
        "override_total_cents", "currency", "buyer_note", "internal_note",
    )
    for field in scalar_fields:
        if field in sent:
            val = getattr(body, field)
            if field == "currency" and val is not None:
                val = val.upper()
            setattr(opt, field, val)

    # ``grants_pathway_id`` — model_fields_set so explicit null
    # removes the included Pathway grant, versus omission leaving
    # it unchanged.
    if "grants_pathway_id" in sent:
        opt.grants_pathway_id = _validate_series_grants_pathway(
            body.grants_pathway_id, space.id, db,
        )

    # If the caller cleared calculated_total_cents but session breakdown
    # is present, recompute it — mirrors pathway PO update behaviour.
    if (
        opt.calculated_total_cents is None
        and opt.total_sessions
        and opt.price_per_session_cents
    ):
        opt.calculated_total_cents = opt.total_sessions * opt.price_per_session_cents

    opt.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(opt)
    return _option_to_dict(opt)


@router.delete(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}",
    status_code=204,
    summary="Archive a series-attached Payment Option",
)
def delete_series_payment_option(
    slug: str,
    series_slug: str,
    option_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    opt = _get_series_option(option_id, series, db)
    # Soft-delete via status — matches the pathway PO delete path
    # (see PaymentOptionsSection on the frontend which treats
    # 'archived' as the terminal state, not a hard row delete).
    opt.status = PaymentOptionStatus.archived
    opt.updated_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Payment Option Schedules (series-scoped)
#
# Payment Options describe WHAT the member receives; schedules describe
# HOW they pay for it. A single Payment Option can carry multiple
# schedules (Pay in full, Weekly × N, Fortnightly × N …) — regardless
# of which the member picks, the resulting AccessPass entitlement is
# identical. The schedule affects only the Stripe cadence.
#
# These endpoints mirror the pathway-scoped equivalents in
# ``routes.py`` — same request/response schemas, same serialiser,
# same generate helper. Reuse over duplication.
# ---------------------------------------------------------------------------


def _get_series_option_schedule(
    schedule_id: str, option: PaymentOption, db: Session,
) -> PaymentOptionSchedule:
    row = (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.id == schedule_id,
            PaymentOptionSchedule.payment_option_id == option.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Payment schedule not found.")
    return row


@router.get(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}/schedules",
    response_model=list[PaymentOptionScheduleResponse],
    summary="List payment schedules for a series-attached Payment Option",
)
def list_series_option_schedules(
    slug: str,
    series_slug: str,
    option_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    _get_series_option(option_id, series, db)  # ownership check
    rows = (
        db.query(PaymentOptionSchedule)
        .filter(PaymentOptionSchedule.payment_option_id == option_id)
        .order_by(PaymentOptionSchedule.position, PaymentOptionSchedule.created_at)
        .all()
    )
    return [_schedule_to_dict(s) for s in rows]


@router.post(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}/schedules",
    response_model=PaymentOptionScheduleResponse,
    status_code=201,
    summary="Add a payment schedule to a series-attached Payment Option",
)
def create_series_option_schedule(
    slug: str,
    series_slug: str,
    option_id: str,
    body: PaymentOptionScheduleCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    _get_series_option(option_id, series, db)

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
        currency=(body.currency or "AUD").upper(),
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
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}/schedules/generate",
    response_model=list[PaymentOptionScheduleResponse],
    status_code=201,
    summary=(
        "Generate default draft schedules (pay in full + weekly + "
        "fortnightly) for a series-attached Payment Option."
    ),
)
def generate_series_option_schedules(
    slug: str,
    series_slug: str,
    option_id: str,
    body: GenerateSchedulesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """Generate draft ``pay_in_full`` + weekly + fortnightly schedules.

    For a fixed-term Series a reasonable weekly instalment count is
    the number of *weeks in the term* — same duration as the term,
    same amount split evenly. We default to the caller-supplied count
    (matches the pathway-side helper) but round the per-payment
    amount off ``opt.effective_price_cents`` so the maths adds up.
    """
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    opt = _get_series_option(option_id, series, db)

    total = opt.effective_price_cents
    if not total or total <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot generate schedules: this Payment Option has no "
                "total price yet. Set a price first."
            ),
        )

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

    currency = (opt.currency or "AUD").upper()
    now = datetime.utcnow()
    created: list[PaymentOptionSchedule] = []

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

    if "recurring_installments" not in existing_types and body.weekly_installment_count > 0:
        n = body.weekly_installment_count
        per = round(total / n)
        s = PaymentOptionSchedule(
            id=str(uuid4()),
            payment_option_id=option_id,
            name=f"Weekly \u2014 {n} payments",
            schedule_type="recurring_installments",
            status="draft",
            total_amount_cents=total,
            installment_amount_cents=per,
            installment_count=n,
            interval="week",
            stripe_interval="week",
            stripe_interval_count=1,
            currency=currency,
            buyer_note=f"{n} weekly payments of ${per / 100:.0f} {currency}",
            position=next_pos,
            created_at=now,
            updated_at=now,
        )
        db.add(s)
        created.append(s)
        next_pos += 1

    db.commit()
    for s in created:
        db.refresh(s)
    return [_schedule_to_dict(s) for s in created]


@router.patch(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}/schedules/{schedule_id}",
    response_model=PaymentOptionScheduleResponse,
    summary="Update a payment schedule (partial)",
)
def update_series_option_schedule(
    slug: str,
    series_slug: str,
    option_id: str,
    schedule_id: str,
    body: PaymentOptionScheduleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    opt = _get_series_option(option_id, series, db)
    sched = _get_series_option_schedule(schedule_id, opt, db)

    sent = body.model_fields_set
    for field in (
        "name", "description", "schedule_type", "status",
        "total_amount_cents", "upfront_amount_cents",
        "installment_amount_cents", "installment_count",
        "interval", "stripe_interval", "stripe_interval_count",
        "currency", "buyer_note", "internal_note",
    ):
        if field in sent:
            v = getattr(body, field)
            if field == "currency" and v is not None:
                v = v.upper()
            setattr(sched, field, v)

    sched.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(sched)
    return _schedule_to_dict(sched)


@router.delete(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-options/{option_id}/schedules/{schedule_id}",
    status_code=204,
    summary="Archive a payment schedule",
)
def delete_series_option_schedule(
    slug: str,
    series_slug: str,
    option_id: str,
    schedule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    opt = _get_series_option(option_id, series, db)
    sched = _get_series_option_schedule(schedule_id, opt, db)
    # Soft-delete via status — mirrors the pathway schedule delete
    # path so future consumers don't need special-case logic.
    sched.status = "archived"
    sched.updated_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Series About Blocks — mirrors the Pathway About Block endpoints
#
# Both surfaces write to the same ``pathway_about_blocks`` table via
# the polymorphic ``owner_kind`` / ``owner_id`` columns introduced in
# migration 113. Series rows carry ``owner_kind='event_series'`` and
# leave the legacy ``pathway_id`` column NULL. All request/response
# schemas + block-type validators + embed / button normalisation are
# reused as-is from the pathway endpoints.
# ---------------------------------------------------------------------------


_SERIES_OWNER_KIND = "event_series"


def _series_about_blocks_query(series: EventSeries, db: Session):
    return (
        db.query(PathwayAboutBlock)
        .options(
            selectinload(PathwayAboutBlock.media_asset),
            selectinload(PathwayAboutBlock.resource),
        )
        .filter(
            PathwayAboutBlock.owner_kind == _SERIES_OWNER_KIND,
            PathwayAboutBlock.owner_id == series.id,
        )
        .order_by(PathwayAboutBlock.position)
    )


@router.get(
    "/spaces/{slug}/gathering-series/{series_slug}/about-blocks",
    response_model=list[AboutBlockResponse],
)
def list_series_about_blocks(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)
    return _series_about_blocks_query(series, db).all()


@router.post(
    "/spaces/{slug}/gathering-series/{series_slug}/about-blocks",
    response_model=AboutBlockResponse,
    status_code=201,
)
def create_series_about_block(
    slug: str,
    series_slug: str,
    body: AboutBlockCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)

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
            .filter(
                PathwayAboutBlock.owner_kind == _SERIES_OWNER_KIND,
                PathwayAboutBlock.owner_id == series.id,
            )
            .scalar()
        )
        position = (max_pos or -1) + 1

    block = PathwayAboutBlock(
        id=str(uuid4()),
        owner_kind=_SERIES_OWNER_KIND,
        owner_id=series.id,
        pathway_id=None,   # Series-owned rows leave the legacy FK NULL.
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
    "/spaces/{slug}/gathering-series/{series_slug}/about-blocks/reorder",
    response_model=list[AboutBlockResponse],
)
def reorder_series_about_blocks(
    slug: str,
    series_slug: str,
    body: AboutBlockReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[PathwayAboutBlock]:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)

    blocks = {
        b.id: b
        for b in db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.owner_kind == _SERIES_OWNER_KIND,
            PathwayAboutBlock.owner_id == series.id,
        )
        .all()
    }
    for pos, block_id in enumerate(body.ids):
        if block_id in blocks:
            blocks[block_id].position = pos
    db.commit()

    return _series_about_blocks_query(series, db).all()


@router.patch(
    "/spaces/{slug}/gathering-series/{series_slug}/about-blocks/{block_id}",
    response_model=AboutBlockResponse,
)
def update_series_about_block(
    slug: str,
    series_slug: str,
    block_id: str,
    body: AboutBlockUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> PathwayAboutBlock:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)

    block = (
        db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.id == block_id,
            PathwayAboutBlock.owner_kind == _SERIES_OWNER_KIND,
            PathwayAboutBlock.owner_id == series.id,
        )
        .first()
    )
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
    "/spaces/{slug}/gathering-series/{series_slug}/about-blocks/{block_id}",
    status_code=204,
)
def delete_series_about_block(
    slug: str,
    series_slug: str,
    block_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    series = _get_gathering_series(space, series_slug, db)

    block = (
        db.query(PathwayAboutBlock)
        .filter(
            PathwayAboutBlock.id == block_id,
            PathwayAboutBlock.owner_kind == _SERIES_OWNER_KIND,
            PathwayAboutBlock.owner_id == series.id,
        )
        .first()
    )
    if not block:
        raise HTTPException(status_code=404, detail="About block not found.")

    db.delete(block)
    db.commit()
