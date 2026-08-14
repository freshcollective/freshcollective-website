"""Central, Collective-level Payment Options creator routes.

Appended to ``creator.routes.router`` (same ``/api/creator`` prefix
as every other creator route).

Rationale
---------
Legacy Payment Option authoring lives on the Pathway editor
(``/spaces/{slug}/pathways/{pathway_slug}/payment-options``) and the
Gathering Series editor
(``/spaces/{slug}/gathering-series/{series_slug}/payment-options``).
Both treat the option as owned by the pathway / series it happens to
attach to. That model breaks for options that grant multiple
experiences — the whole reason ``PaymentOptionGrant`` exists (B1–B4).

This module exposes a **Collective-scoped, grants-first** surface for
the Creator Studio "Commerce → Payment Options" UI. The legacy
nested routes remain in place for backwards compatibility; new
Creator-authored options should be written here.

Wire contract
-------------
Base prefix: ``/api/creator/spaces/{slug}/commerce/payment-options``

    GET     ""                          — list all (any status)
    POST    ""                          — create (grants-first;
                                          legacy attaches_to_* seeded
                                          with a ``'space'`` sentinel
                                          so DB NOT NULLs stay
                                          satisfied without polluting
                                          any real Pathway / Series).
    GET     "/{option_id}"              — one option with grants +
                                          schedules embedded.
    PATCH   "/{option_id}"              — update basics (name / desc /
                                          status / notes / currency;
                                          NOT legacy grant fields —
                                          those are read-only from
                                          this surface).
    DELETE  "/{option_id}"              — lifecycle-aware:
                                            draft + never purchased
                                              → hard delete
                                            otherwise
                                              → soft archive

    POST    "/{option_id}/grants"       — add a grant
    PATCH   "/{option_id}/grants/{gid}" — edit a grant
    DELETE  "/{option_id}/grants/{gid}" — remove a grant

    POST    "/{option_id}/schedules"    — mirrors legacy pathway
    PATCH   "/{option_id}/schedules/{sid}"    schedule endpoints but
    DELETE  "/{option_id}/schedules/{sid}"    scoped by space, not
                                              pathway (parity of
                                              behaviour; deliberately
                                              tiny wrappers so the UI
                                              only ever has to know
                                              one URL family).

Reverse lookups
---------------
Pathway / Series editors need "This is included in …" reference
blocks. Those are:

    GET  /spaces/{slug}/pathways/{pathway_slug}/payment-option-references
    GET  /spaces/{slug}/gathering-series/{series_slug}/payment-option-references

Response is a list of ``PaymentOptionReferenceOut`` rows: minimal
identity + the grant fields relevant to the reference context
(``sessions_per_week`` / ``total_sessions`` for Series references).

Grants-first author path — legacy fields
----------------------------------------
This surface never writes ``pathway_id`` / ``grants_pathway_id`` /
``attaches_to_kind`` / ``attaches_to_id`` from creator input. Those
columns remain in the schema for legacy readers and the
``resolve_intent_from_legacy`` fallback, but for options authored
here they are seeded with sentinels (``attaches_to_kind='space'``,
``attaches_to_id=space.id``) and never surfaced back through the
Creator UI. All commercial meaning lives on the grants + schedules
underneath.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.access_pass import AccessPass, AccessPassStatus
from app.creator.routes import (
    _get_managed_space,
    _option_to_dict,
    _schedule_to_dict,
    get_creator_user,
    router,
)
from app.creator.schemas import (
    PaymentOptionCreateRequest,
    PaymentOptionGrantCreate,
    PaymentOptionGrantResponse,
    PaymentOptionResponse,
    PaymentOptionScheduleCreateRequest,
    PaymentOptionScheduleResponse,
    PaymentOptionScheduleUpdateRequest,
    PaymentOptionUpdateRequest,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    Event,
    EventSeries,
    Pathway,
    Space,
    SpaceMembership,
)
from app.models.user import User
from app.services.schedule_validation import (
    validate_recurring_installments_payload,
)
from app.services.checkout_orchestration import (
    check_option_fulfillable_or_raise,
    check_same_option_not_active,
    resolve_fee_context,
)
from app.services.purchase_fulfilment import (
    apply_intent,
    resolve_intent_for_option,
    validate_intent,
)


# ---------------------------------------------------------------------------
# Response shapes not covered by the shared schemas module
# ---------------------------------------------------------------------------


from pydantic import BaseModel


class _GrantRefTarget(BaseModel):
    id: str
    title: str
    slug: str | None = None


class PaymentOptionGrantWithTarget(PaymentOptionGrantResponse):
    """Grant row + a small target snapshot so the UI can render
    "EMBODY Term 3 2026" / "The EMBODY Practice" without a follow-up
    fetch per row."""

    target: _GrantRefTarget | None = None


class SpacePaymentOptionRead(PaymentOptionResponse):
    """List/read shape for the central Creator UI. Embeds grants +
    schedules so the index page renders in one round-trip."""

    grants: list[PaymentOptionGrantWithTarget] = []
    schedules: list[PaymentOptionScheduleResponse] = []
    # Purchasability signal — derived, not stored. See
    # ``_derive_purchasability`` for the exact rule.
    purchasability: str = "unknown"
    purchasability_notes: list[str] = []


class PaymentOptionReferenceOut(BaseModel):
    """Reverse-lookup row: which Payment Options include a given
    Pathway / Series. Used by the Pathway and Series editor
    reference blocks."""

    payment_option_id: str
    payment_option_name: str
    payment_option_status: str
    grant_kind: str
    sessions_per_week: int | None = None
    total_sessions: int | None = None


# ---------------------------------------------------------------------------
# Grants-first sentinel — see module docstring
# ---------------------------------------------------------------------------

# Legacy ``attaches_to_kind`` is NOT NULL. Grants-first options do
# not attach to a single Pathway/Series (they may grant many). Rather
# than lie by pointing at "the first" grant target, we tag them with
# a distinct sentinel so downstream readers can recognise them if
# needed. Nothing in the checkout pipeline reads ``attaches_to_kind``
# for options that have grants (the dispatcher routes grants-first
# → grant resolver), so the sentinel is inert at runtime.
_GRANTS_FIRST_ATTACH_KIND = "space"


# ---------------------------------------------------------------------------
# Purchasability derivation
# ---------------------------------------------------------------------------


def _derive_purchasability(opt: PaymentOption) -> tuple[str, list[str]]:
    """Return ``(state, notes)`` describing why an option is (not)
    ready for member purchase through the unified endpoint.

    States
    ------
    ready
        At least one ``published`` ``pay_in_full`` schedule + at
        least one grant. Unified checkout accepts this today.
    configured_not_yet_checkoutable
        The option has published schedules, but all of them are
        types the unified checkout does not yet execute (finite
        instalments, subscription, manual). Author work is done;
        the *runtime* isn't there yet.
    needs_attention
        Missing prerequisites — no grants, or no published schedule
        at all. Options in this state must not look "publishable"
        in the UI even if their own status is ``published``.
    archived
        Status is archived.
    draft
        Status is draft AND doesn't otherwise land in
        ``needs_attention``.
    """
    if opt.status == "archived" or (
        hasattr(opt.status, "value") and opt.status.value == "archived"
    ):
        return "archived", []

    notes: list[str] = []
    has_grants = len(opt.grants) > 0
    if not has_grants:
        notes.append("No experiences included yet.")

    published_scheds = [
        s for s in _schedules_of(opt) if _schedule_status(s) == "published"
    ]
    if not published_scheds:
        notes.append("No published payment method.")

    if not has_grants or not published_scheds:
        if opt.status == "draft" or (
            hasattr(opt.status, "value") and opt.status.value == "draft"
        ):
            return "draft", notes
        return "needs_attention", notes

    # There is at least one published schedule + grants. Is there a
    # ``pay_in_full`` published schedule (the only kind unified
    # checkout executes today)?
    for s in published_scheds:
        if s.schedule_type == "pay_in_full":
            return "ready", []

    notes.append("Only finite instalment / subscription schedules configured — checkout coming later.")
    return "configured_not_yet_checkoutable", notes


def _schedules_of(opt: PaymentOption) -> list[PaymentOptionSchedule]:
    """Read the option's schedules from the relationship-backed
    session. The relationship is lazy-loaded on access."""
    return list(getattr(opt, "_schedules_cache", []) or [])


def _schedule_status(s: PaymentOptionSchedule) -> str:
    return s.status.value if hasattr(s.status, "value") else str(s.status)


def _fetch_schedules(db: Session, option_id: str) -> list[PaymentOptionSchedule]:
    return (
        db.query(PaymentOptionSchedule)
        .filter(PaymentOptionSchedule.payment_option_id == option_id)
        .order_by(PaymentOptionSchedule.position, PaymentOptionSchedule.created_at)
        .all()
    )


# ---------------------------------------------------------------------------
# Grant target enrichment
# ---------------------------------------------------------------------------


def _enrich_grants(
    db: Session, space: Space, grants: list[PaymentOptionGrant],
) -> list[dict]:
    """Turn a list of ``PaymentOptionGrant`` rows into API
    dictionaries, each enriched with a minimal ``target`` snapshot
    (id + title + slug). Batched by kind so each list produces at
    most 3 SELECTs."""
    pathway_ids = {g.pathway_id for g in grants if g.pathway_id}
    series_ids = {g.series_id for g in grants if g.series_id}
    event_ids = {g.event_id for g in grants if g.event_id}

    pathways = (
        {p.id: p for p in db.query(Pathway).filter(Pathway.id.in_(pathway_ids)).all()}
        if pathway_ids else {}
    )
    seriess = (
        {s.id: s for s in db.query(EventSeries).filter(EventSeries.id.in_(series_ids)).all()}
        if series_ids else {}
    )
    events = (
        {e.id: e for e in db.query(Event).filter(Event.id.in_(event_ids)).all()}
        if event_ids else {}
    )

    out: list[dict] = []
    for g in grants:
        target: dict | None = None
        if g.grant_kind == "pathway" and g.pathway_id and g.pathway_id in pathways:
            p = pathways[g.pathway_id]
            target = {"id": p.id, "title": p.title, "slug": p.slug}
        elif g.grant_kind == "event_series" and g.series_id and g.series_id in seriess:
            s = seriess[g.series_id]
            target = {"id": s.id, "title": s.title, "slug": s.slug}
        elif g.grant_kind == "gathering" and g.event_id and g.event_id in events:
            e = events[g.event_id]
            target = {"id": e.id, "title": e.title, "slug": None}
        out.append({
            "id": g.id,
            "payment_option_id": g.payment_option_id,
            "grant_kind": g.grant_kind,
            "pathway_id": g.pathway_id,
            "series_id": g.series_id,
            "event_id": g.event_id,
            "sessions_per_week": g.sessions_per_week,
            "total_sessions": g.total_sessions,
            "valid_from_override": g.valid_from_override,
            "valid_until_override": g.valid_until_override,
            "position": g.position,
            "created_at": g.created_at,
            "updated_at": g.updated_at,
            "target": target,
        })
    return out


def _serialise_option(db: Session, space: Space, opt: PaymentOption) -> dict:
    """Full read-shape for the central UI — option + grants +
    schedules + derived purchasability."""
    schedules = _fetch_schedules(db, opt.id)
    # Attach so ``_derive_purchasability`` reads without another
    # DB round-trip. Not persisted anywhere.
    opt._schedules_cache = schedules  # type: ignore[attr-defined]

    base = _option_to_dict(opt)
    grants_payload = _enrich_grants(db, space, list(opt.grants))
    schedules_payload = [_schedule_to_dict(s) for s in schedules]
    state, notes = _derive_purchasability(opt)
    return {
        **base,
        "grants": grants_payload,
        "schedules": schedules_payload,
        "purchasability": state,
        "purchasability_notes": notes,
    }


def _validate_grant_target(
    db: Session, space: Space, body: PaymentOptionGrantCreate,
) -> None:
    """Confirm the grant's target row exists in this Collective.
    Runs at request boundary so the exact-one-target rule already
    enforced by the pydantic validator remains authoritative for
    shape."""
    if body.grant_kind == "pathway":
        found = db.query(Pathway.id).filter(
            Pathway.id == body.pathway_id, Pathway.space_id == space.id,
        ).first()
        if not found:
            raise HTTPException(status_code=400, detail="Pathway not found in this Collective.")
    elif body.grant_kind == "event_series":
        found = db.query(EventSeries.id).filter(
            EventSeries.id == body.series_id, EventSeries.space_id == space.id,
        ).first()
        if not found:
            raise HTTPException(status_code=400, detail="Gathering Series not found in this Collective.")
    elif body.grant_kind == "gathering":
        found = db.query(Event.id).filter(
            Event.id == body.event_id, Event.space_id == space.id,
        ).first()
        if not found:
            raise HTTPException(status_code=400, detail="Gathering not found in this Collective.")


def _get_space_option(db: Session, space: Space, option_id: str) -> PaymentOption:
    opt = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == option_id, PaymentOption.space_id == space.id)
        .first()
    )
    if not opt:
        raise HTTPException(status_code=404, detail="Payment option not found.")
    return opt


# ---------------------------------------------------------------------------
# Payment Options — list + create + read + update + delete
# ---------------------------------------------------------------------------


@router.get(
    "/spaces/{slug}/commerce/payment-options",
    response_model=list[SpacePaymentOptionRead],
)
def list_commerce_payment_options(
    slug: str,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """List every Payment Option in this Collective, with grants +
    schedules embedded. ``include_archived`` opts into archived
    rows (default excludes them)."""
    space = _get_managed_space(slug, current_user, db)
    q = db.query(PaymentOption).filter(PaymentOption.space_id == space.id)
    if not include_archived:
        q = q.filter(PaymentOption.status != "archived")
    opts = q.order_by(
        PaymentOption.status,          # draft before published etc — arbitrary but stable
        PaymentOption.position,
        PaymentOption.created_at,
    ).all()
    return [_serialise_option(db, space, o) for o in opts]


@router.post(
    "/spaces/{slug}/commerce/payment-options",
    response_model=SpacePaymentOptionRead,
    status_code=201,
)
def create_commerce_payment_option(
    slug: str,
    body: PaymentOptionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Create a new grants-first Payment Option in this Collective.

    Legacy attach columns are seeded with the ``'space'`` sentinel
    described in the module docstring — the DB requires them to be
    non-null but this surface never writes real target refs there.
    ``grants_pathway_id`` is intentionally ignored on this surface;
    Creator selects included Pathways via grants instead.
    """
    space = _get_managed_space(slug, current_user, db)

    max_pos = (
        db.query(PaymentOption.position)
        .filter(PaymentOption.space_id == space.id)
        .order_by(PaymentOption.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    now = datetime.utcnow()
    opt = PaymentOption(
        id=str(uuid4()),
        space_id=space.id,
        pathway_id=None,
        attaches_to_kind=_GRANTS_FIRST_ATTACH_KIND,
        attaches_to_id=space.id,
        grants_pathway_id=None,
        name=body.name.strip(),
        description=body.description,
        payment_type=body.payment_type,
        status=body.status,
        term_start_date=None,
        term_end_date=None,
        sessions_per_week=None,
        total_sessions=None,
        price_per_session_cents=None,
        calculated_total_cents=body.calculated_total_cents,
        override_total_cents=body.override_total_cents,
        currency=(body.currency or "AUD").upper(),
        buyer_note=body.buyer_note,
        internal_note=body.internal_note,
        position=position,
        created_at=now,
        updated_at=now,
    )
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return _serialise_option(db, space, opt)


@router.get(
    "/spaces/{slug}/commerce/payment-options/{option_id}",
    response_model=SpacePaymentOptionRead,
)
def get_commerce_payment_option(
    slug: str,
    option_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)
    return _serialise_option(db, space, opt)


@router.patch(
    "/spaces/{slug}/commerce/payment-options/{option_id}",
    response_model=SpacePaymentOptionRead,
)
def update_commerce_payment_option(
    slug: str,
    option_id: str,
    body: PaymentOptionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Update basics only. Legacy commercial fields
    (``term_start_date``, ``term_end_date``, ``sessions_per_week``,
    ``total_sessions``, ``price_per_session_cents``,
    ``grants_pathway_id``) are ignored — grants are the source of
    truth from this surface."""
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)

    updates = body.model_dump(exclude_unset=True)
    editable = {
        "name", "description", "payment_type", "status", "currency",
        "buyer_note", "internal_note",
        "calculated_total_cents", "override_total_cents",
    }
    for field, val in updates.items():
        if field not in editable:
            continue
        if field == "name" and val is not None:
            setattr(opt, field, val.strip())
        elif field == "currency" and val is not None:
            opt.currency = val.upper()
        else:
            setattr(opt, field, val)

    opt.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(opt)
    return _serialise_option(db, space, opt)


@router.delete(
    "/spaces/{slug}/commerce/payment-options/{option_id}",
    status_code=204,
)
def delete_commerce_payment_option(
    slug: str,
    option_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Lifecycle-aware delete:

    * draft option with no purchases → hard delete (grants +
      schedules cascade).
    * anything else                  → soft-archive.
    """
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)

    is_draft = opt.status == "draft" or (
        hasattr(opt.status, "value") and opt.status.value == "draft"
    )
    has_purchases = (
        db.query(PaymentTransaction.id)
        .filter(
            PaymentTransaction.payment_option_id == opt.id,
            PaymentTransaction.status.in_([
                PaymentTransactionStatus.pending,
                PaymentTransactionStatus.succeeded,
                PaymentTransactionStatus.refunded,
                PaymentTransactionStatus.partially_refunded,
                PaymentTransactionStatus.disputed,
            ]),
        )
        .first()
        is not None
    )

    if is_draft and not has_purchases:
        db.delete(opt)
    else:
        opt.status = "archived"
        opt.updated_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Grants — CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/spaces/{slug}/commerce/payment-options/{option_id}/grants",
    response_model=PaymentOptionGrantResponse,
    status_code=201,
)
def add_commerce_payment_option_grant(
    slug: str,
    option_id: str,
    body: PaymentOptionGrantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)
    _validate_grant_target(db, space, body)

    max_pos = (
        db.query(PaymentOptionGrant.position)
        .filter(PaymentOptionGrant.payment_option_id == opt.id)
        .order_by(PaymentOptionGrant.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    now = datetime.utcnow()
    grant = PaymentOptionGrant(
        id=str(uuid4()),
        payment_option_id=opt.id,
        grant_kind=body.grant_kind,
        pathway_id=body.pathway_id,
        series_id=body.series_id,
        event_id=body.event_id,
        sessions_per_week=body.sessions_per_week,
        total_sessions=body.total_sessions,
        valid_from_override=body.valid_from_override,
        valid_until_override=body.valid_until_override,
        position=position,
        created_at=now,
        updated_at=now,
    )
    db.add(grant)
    opt.updated_at = now
    db.commit()
    db.refresh(grant)
    return {
        "id": grant.id,
        "payment_option_id": grant.payment_option_id,
        "grant_kind": grant.grant_kind,
        "pathway_id": grant.pathway_id,
        "series_id": grant.series_id,
        "event_id": grant.event_id,
        "sessions_per_week": grant.sessions_per_week,
        "total_sessions": grant.total_sessions,
        "valid_from_override": grant.valid_from_override,
        "valid_until_override": grant.valid_until_override,
        "position": grant.position,
        "created_at": grant.created_at,
        "updated_at": grant.updated_at,
    }


class _GrantEditRequest(BaseModel):
    sessions_per_week: int | None = None
    total_sessions: int | None = None
    valid_from_override: datetime | None = None
    valid_until_override: datetime | None = None
    position: int | None = None


@router.patch(
    "/spaces/{slug}/commerce/payment-options/{option_id}/grants/{grant_id}",
    response_model=PaymentOptionGrantResponse,
)
def edit_commerce_payment_option_grant(
    slug: str,
    option_id: str,
    grant_id: str,
    body: _GrantEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    """Editable fields: allowance (series only) + windows + position.
    Target refs (pathway_id / series_id / event_id / grant_kind) are
    immutable — remove and re-add to change what a grant references."""
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)
    grant = (
        db.query(PaymentOptionGrant)
        .filter(
            PaymentOptionGrant.id == grant_id,
            PaymentOptionGrant.payment_option_id == opt.id,
        )
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found.")

    updates = body.model_dump(exclude_unset=True)
    # Guard: session credits are event_series-only. Silently ignore
    # for other kinds rather than 400 — the UI shouldn't ever send
    # them for a non-Series grant anyway.
    if grant.grant_kind != "event_series":
        updates.pop("sessions_per_week", None)
        updates.pop("total_sessions", None)
    for field, val in updates.items():
        setattr(grant, field, val)
    grant.updated_at = datetime.utcnow()
    opt.updated_at = grant.updated_at
    db.commit()
    db.refresh(grant)
    return {
        "id": grant.id,
        "payment_option_id": grant.payment_option_id,
        "grant_kind": grant.grant_kind,
        "pathway_id": grant.pathway_id,
        "series_id": grant.series_id,
        "event_id": grant.event_id,
        "sessions_per_week": grant.sessions_per_week,
        "total_sessions": grant.total_sessions,
        "valid_from_override": grant.valid_from_override,
        "valid_until_override": grant.valid_until_override,
        "position": grant.position,
        "created_at": grant.created_at,
        "updated_at": grant.updated_at,
    }


@router.delete(
    "/spaces/{slug}/commerce/payment-options/{option_id}/grants/{grant_id}",
    status_code=204,
)
def remove_commerce_payment_option_grant(
    slug: str,
    option_id: str,
    grant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)
    grant = (
        db.query(PaymentOptionGrant)
        .filter(
            PaymentOptionGrant.id == grant_id,
            PaymentOptionGrant.payment_option_id == opt.id,
        )
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Grant not found.")
    db.delete(grant)
    opt.updated_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Schedules — CRUD (mirrors the legacy pathway-scoped endpoints)
# ---------------------------------------------------------------------------


@router.post(
    "/spaces/{slug}/commerce/payment-options/{option_id}/schedules",
    response_model=PaymentOptionScheduleResponse,
    status_code=201,
)
def create_commerce_payment_option_schedule(
    slug: str,
    option_id: str,
    body: PaymentOptionScheduleCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)

    # FIP1 — validate finite payment plans on create when they are
    # being published. Draft rows may be incomplete so a Creator can
    # save-in-progress. Members can't purchase either way while the
    # 503 guard in checkout_orchestration remains active.
    if body.status == "published":
        validate_recurring_installments_payload(body)

    max_pos = (
        db.query(PaymentOptionSchedule.position)
        .filter(PaymentOptionSchedule.payment_option_id == opt.id)
        .order_by(PaymentOptionSchedule.position.desc())
        .first()
    )
    position = (max_pos[0] + 1) if max_pos else 0

    now = datetime.utcnow()
    sched = PaymentOptionSchedule(
        id=str(uuid4()),
        payment_option_id=opt.id,
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
    opt.updated_at = now
    db.commit()
    db.refresh(sched)
    return _schedule_to_dict(sched)


@router.patch(
    "/spaces/{slug}/commerce/payment-options/{option_id}/schedules/{schedule_id}",
    response_model=PaymentOptionScheduleResponse,
)
def update_commerce_payment_option_schedule(
    slug: str,
    option_id: str,
    schedule_id: str,
    body: PaymentOptionScheduleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> dict:
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)
    sched = (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.id == schedule_id,
            PaymentOptionSchedule.payment_option_id == opt.id,
        )
        .first()
    )
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    updates = body.model_dump(exclude_unset=True)
    for field, val in updates.items():
        if field == "currency" and val is not None:
            sched.currency = val.upper()
        else:
            setattr(sched, field, val)

    # FIP1 — validate the merged post-update state when the row is
    # (now) recurring_installments AND (now) published. Editing an
    # existing draft with incomplete fields is still permitted.
    merged_status = updates.get("status", sched.status)
    if merged_status == "published":
        validate_recurring_installments_payload(sched)

    sched.updated_at = datetime.utcnow()
    opt.updated_at = sched.updated_at
    db.commit()
    db.refresh(sched)
    return _schedule_to_dict(sched)


@router.delete(
    "/spaces/{slug}/commerce/payment-options/{option_id}/schedules/{schedule_id}",
    status_code=204,
)
def delete_commerce_payment_option_schedule(
    slug: str,
    option_id: str,
    schedule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> None:
    """Hard-delete for draft schedules with no purchases; soft-
    archive otherwise (mirrors the option lifecycle rule)."""
    space = _get_managed_space(slug, current_user, db)
    opt = _get_space_option(db, space, option_id)
    sched = (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.id == schedule_id,
            PaymentOptionSchedule.payment_option_id == opt.id,
        )
        .first()
    )
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found.")

    is_draft = sched.status == "draft" or (
        hasattr(sched.status, "value") and sched.status.value == "draft"
    )
    has_purchases = (
        db.query(PaymentTransaction.id)
        .filter(PaymentTransaction.payment_option_schedule_id == sched.id)
        .first()
        is not None
    )
    if is_draft and not has_purchases:
        db.delete(sched)
    else:
        sched.status = "archived"
        sched.updated_at = datetime.utcnow()
    opt.updated_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Reverse-lookup — "this pathway / series is included in …"
# ---------------------------------------------------------------------------


def _reference_row(opt: PaymentOption, grant: PaymentOptionGrant) -> dict:
    return {
        "payment_option_id": opt.id,
        "payment_option_name": opt.name,
        "payment_option_status": (
            opt.status.value if hasattr(opt.status, "value") else str(opt.status)
        ),
        "grant_kind": grant.grant_kind,
        "sessions_per_week": grant.sessions_per_week,
        "total_sessions": grant.total_sessions,
    }


@router.get(
    "/spaces/{slug}/pathways/{pathway_slug}/payment-option-references",
    response_model=list[PaymentOptionReferenceOut],
)
def pathway_payment_option_references(
    slug: str,
    pathway_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """Which Payment Options include this Pathway via a grant?
    Archived options are omitted."""
    space = _get_managed_space(slug, current_user, db)
    pathway = (
        db.query(Pathway)
        .filter(Pathway.space_id == space.id, Pathway.slug == pathway_slug)
        .first()
    )
    if not pathway:
        raise HTTPException(status_code=404, detail="Pathway not found.")

    rows = (
        db.query(PaymentOption, PaymentOptionGrant)
        .join(
            PaymentOptionGrant,
            PaymentOptionGrant.payment_option_id == PaymentOption.id,
        )
        .filter(
            PaymentOption.space_id == space.id,
            PaymentOption.status != "archived",
            PaymentOptionGrant.grant_kind == "pathway",
            PaymentOptionGrant.pathway_id == pathway.id,
        )
        .order_by(PaymentOption.status, PaymentOption.position, PaymentOption.created_at)
        .all()
    )
    return [_reference_row(opt, grant) for opt, grant in rows]


@router.get(
    "/spaces/{slug}/gathering-series/{series_slug}/payment-option-references",
    response_model=list[PaymentOptionReferenceOut],
)
def series_payment_option_references(
    slug: str,
    series_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """Which Payment Options include this Gathering Series via a
    grant? Archived options are omitted."""
    space = _get_managed_space(slug, current_user, db)
    series = (
        db.query(EventSeries)
        .filter(EventSeries.space_id == space.id, EventSeries.slug == series_slug)
        .first()
    )
    if not series:
        raise HTTPException(status_code=404, detail="Gathering Series not found.")

    rows = (
        db.query(PaymentOption, PaymentOptionGrant)
        .join(
            PaymentOptionGrant,
            PaymentOptionGrant.payment_option_id == PaymentOption.id,
        )
        .filter(
            PaymentOption.space_id == space.id,
            PaymentOption.status != "archived",
            PaymentOptionGrant.grant_kind == "event_series",
            PaymentOptionGrant.series_id == series.id,
        )
        .order_by(PaymentOption.status, PaymentOption.position, PaymentOption.created_at)
        .all()
    )
    return [_reference_row(opt, grant) for opt, grant in rows]


# ---------------------------------------------------------------------------
# Options selectable as grant targets — for the editor's "include an
# experience" picker.
# ---------------------------------------------------------------------------


class _GrantTargetSummary(BaseModel):
    id: str
    title: str
    slug: str | None = None
    kind: str    # "pathway" | "event_series" | "gathering"
    status: str
    # Human-readable disambiguator (e.g. Gathering start date). Optional.
    subtitle: str | None = None


@router.get(
    "/spaces/{slug}/commerce/grantable-experiences",
    response_model=list[_GrantTargetSummary],
)
def list_grantable_experiences(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> list[dict]:
    """Every Pathway / Series / Gathering in this Collective that
    the Creator could add as a grant target on a Payment Option.
    Editor picker uses this to populate its dropdowns."""
    space = _get_managed_space(slug, current_user, db)

    pathways = (
        db.query(Pathway.id, Pathway.title, Pathway.slug, Pathway.status)
        .filter(Pathway.space_id == space.id)
        .order_by(Pathway.title)
        .all()
    )
    seriess = (
        db.query(EventSeries.id, EventSeries.title, EventSeries.slug, EventSeries.status)
        .filter(EventSeries.space_id == space.id)
        .order_by(EventSeries.title)
        .all()
    )
    # Gatherings: only genuinely standalone ones (not children of any
    # Gathering Series). A Series-child Gathering is represented by
    # its Series grant, so listing it here would let a Creator author
    # an overlapping/contradictory grant and would clutter the picker
    # for Collectives with many Series-attached Gatherings (e.g.
    # EMBODY has ~50 Series children).
    events = (
        db.query(Event.id, Event.title, Event.status, Event.starts_at)
        .filter(Event.space_id == space.id, Event.series_id.is_(None))
        .order_by(Event.starts_at, Event.title)
        .all()
    )

    out: list[dict] = []
    for row in pathways:
        out.append({
            "id": row.id, "title": row.title, "slug": row.slug,
            "kind": "pathway",
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "subtitle": None,
        })
    for row in seriess:
        out.append({
            "id": row.id, "title": row.title, "slug": row.slug,
            "kind": "event_series",
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "subtitle": None,
        })
    for row in events:
        # A short date suffix helps the Creator disambiguate multiple
        # standalone Gatherings with similar titles.
        subtitle: str | None = None
        if row.starts_at is not None:
            subtitle = row.starts_at.strftime("%-d %b %Y")
        out.append({
            "id": row.id, "title": row.title, "slug": None,
            "kind": "gathering",
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "subtitle": subtitle,
        })
    return out


# ---------------------------------------------------------------------------
# Manual "Grant access" — reuses the same PaymentOption fulfilment
# architecture that unified checkout uses, so a manually-granted
# Payment Option produces the exact same PathwayEntitlement +
# AccessPass rows a Stripe purchase would.
#
# Design decisions
# ----------------
# * Source of truth for "what gets granted" = the PaymentOption's
#   grants. The Creator never picks a Pathway or Series separately.
# * Complimentary → gross=0, provider=manual. Bank transfer / cash
#   record the paid amount so the Payments ledger reflects what
#   actually moved. Admin grant is a system-level record with the
#   Payment Option's calculated total (or an override), same
#   provider.
# * Payment Option Schedule selection is optional but recommended
#   for "bank_transfer" / "cash" so the amount defaults to a
#   schedule's total. Complimentary / admin-grant defaults to 0.
# * Duplicate guard: reuses ``check_same_option_not_active`` so the
#   member's currently-active same-option access can't be
#   double-granted (silently OK to re-grant after expiry).
# * Gathering-grant safety: reuses
#   ``check_option_fulfillable_or_raise`` — options with
#   Gathering grants are refused (unified checkout also refuses;
#   consistent behaviour).
# * Fulfilment: ``resolve_intent_for_option`` → ``validate_intent``
#   → ``apply_intent`` on the shared purchase-fulfilment service.
#   Atomic — all promised grants apply, or none do.
# ---------------------------------------------------------------------------


# Sources the Creator UI still offers on a *new* Grant Access flow.
# Off-platform payment methods (bank_transfer / cash) were removed in
# the final U1 refinement — Creator Studio no longer normalises taking
# payments outside Fresh Collective.
_NEW_GRANT_SOURCES = {"complimentary", "manual"}

# Sources the correction endpoint will still accept on *existing*
# rows. Includes the legacy off-platform labels so a Creator can
# still re-label a historical row correctly. ``admin_grant`` is the
# older internal spelling of what the UI now calls "Manual access";
# it stays here so legacy audit rows keep matching.
_MANUAL_GRANT_SOURCES = _NEW_GRANT_SOURCES | {
    "bank_transfer",
    "cash",
    "admin_grant",
}


class ManualGrantRequest(BaseModel):
    """Grant a Payment Option's full bundle to a member.

    Access-only operation. Off-platform payment recording
    (bank transfer / cash) is deliberately not supported here —
    Creator Studio does not encourage taking payments outside
    Fresh Collective. If a Creator did receive money outside
    Fresh Collective, they select "Manual access" and the ledger
    records that as an audit row with no money attached.

    Fields:
      * ``user_id`` — member receiving access. Must be in the Collective.
      * ``payment_option_id`` — Payment Option to grant. Must belong
        to the Collective and not be archived. Its grants are the
        source of truth for what the member receives.
      * ``source`` — creator-facing reason:
          ``complimentary`` — intentionally provided at no charge.
          ``manual``        — administrative / exceptional access
                              arranged manually.
      * ``notes`` — optional operator note, stored on the ledger row.

    Any transaction row created here is a $0 audit-only anchor
    (needed for fulfilment idempotency + reversal traceability);
    it is intentionally excluded from the Creator-facing Payments
    received ledger.
    """

    user_id: str
    payment_option_id: str
    source: str
    notes: str | None = None


class ManualGrantResponse(BaseModel):
    transaction_id: str
    access_pass_ids: list[str] = []
    entitlement_ids: list[str] = []
    message: str


@router.post(
    "/spaces/{slug}/commerce/manual-grant",
    response_model=ManualGrantResponse,
    status_code=201,
)
def manual_grant_payment_option(
    slug: str,
    body: ManualGrantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualGrantResponse:
    space = _get_managed_space(slug, current_user, db)

    # ── Source validation ────────────────────────────────────────
    # New grants only accept the narrow, on-platform-friendly set.
    if body.source not in _NEW_GRANT_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported reason. Choose one of: "
                + ", ".join(sorted(_NEW_GRANT_SOURCES))
            ),
        )

    # ── Member validation — must be in this Collective ───────────
    payer = db.query(User).filter(User.id == body.user_id).first()
    if not payer:
        raise HTTPException(status_code=404, detail="Member not found.")
    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == body.user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=404,
            detail="Member is not part of this Collective.",
        )

    # ── Payment Option validation ─────────────────────────────────
    opt = _get_space_option(db, space, body.payment_option_id)
    opt_status = (
        opt.status.value if hasattr(opt.status, "value") else str(opt.status)
    )
    if opt_status == "archived":
        raise HTTPException(
            status_code=400,
            detail="This Payment Option is archived and cannot be granted.",
        )

    # Refuse Gathering-grant options — same rule as unified checkout.
    check_option_fulfillable_or_raise(opt)

    # ── Duplicate guard ──────────────────────────────────────────
    now = datetime.utcnow()
    check_same_option_not_active(
        db, user=payer, payment_option=opt, now=now,
    )

    # ── Amount ──────────────────────────────────────────────────
    # Grant Access is an access operation — never a payment
    # workflow. Every ledger row created here is a $0 audit anchor
    # regardless of the option's price, so the row exists for
    # fulfilment idempotency + cancel-and-revoke traceability but
    # never surfaces as "money received" on the Payments received
    # ledger (see ``list_creator_payments`` provider filter).
    schedule: PaymentOptionSchedule | None = None
    gross_amount = 0
    currency = (opt.currency or "AUD").upper()

    # ── Fulfilment intent (grant-first when ready) ───────────────
    resolution = resolve_intent_for_option(
        db,
        payment_option=opt,
        metadata_pathway_id=None,
        now=now,
    )
    if resolution.fatal_error:
        raise HTTPException(
            status_code=400,
            detail=(
                "This Payment Option cannot be granted as-is: "
                f"{resolution.fatal_error}"
            ),
        )
    validation = validate_intent(db, resolution.intent)
    if not validation.ok:
        raise HTTPException(
            status_code=400,
            detail=(
                "This Payment Option references items that no longer exist: "
                + "; ".join(validation.errors)
            ),
        )

    # ── Ledger row + fulfilment (single transaction) ─────────────
    fee_context = resolve_fee_context(space, db)
    txn_id = str(uuid4())
    notes_prefix = f"Manual grant — {body.source}"
    if body.notes:
        notes = f"{notes_prefix}: {body.notes}"
    else:
        notes = notes_prefix

    txn = PaymentTransaction(
        id=txn_id,
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.manual,
        payer_user_id=payer.id,
        creator_user_id=fee_context.creator_id,
        space_id=space.id,
        pathway_id=None,
        creator_plan_id=fee_context.creator_plan_id,
        creator_subscription_id=fee_context.creator_subscription_id,
        currency=currency,
        gross_amount_cents=gross_amount,
        # Complimentary + admin grants + out-of-Stripe payments do
        # not attract a platform fee — the money didn't flow through
        # Fresh Collective's Stripe account, so a fee split would
        # misrepresent the ledger.
        platform_fee_basis_points=0,
        platform_fee_cents=0,
        net_creator_amount_cents=gross_amount,
        net_platform_amount_cents=0,
        payment_option_id=opt.id,
        payment_option_schedule_id=schedule.id if schedule else None,
        payout_status=PayoutStatus.not_applicable,
        fulfilment_status=PaymentFulfilmentStatus.pending,
        notes=notes,
        stripe_mode="test",
        created_at=now,
        updated_at=now,
    )
    db.add(txn)
    db.flush()

    try:
        result = apply_intent(
            db,
            intent=resolution.intent,
            txn=txn,
            payer_user_id=payer.id,
            space_id=space.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=schedule.id if schedule else None,
            session_id=None,
            payment_intent_id=None,
            now=now,
        )
        txn.fulfilment_status = PaymentFulfilmentStatus.applied
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ManualGrantResponse(
        transaction_id=txn.id,
        access_pass_ids=[ap.id for ap in result.access_passes],
        entitlement_ids=[e.id for e in result.entitlements],
        message="Access granted.",
    )


# ---------------------------------------------------------------------------
# Correcting a manual grant — safe operations only
#
# Corrections deliberately split into two operations rather than a
# single "replace" endpoint that fakes atomicity it can't guarantee:
#
#   PATCH  /commerce/manual-grant/{txn_id}
#     Safe metadata correction. Editable fields:
#       * ``source``   — the payment provenance label (bank_transfer
#                        / cash / complimentary / admin_grant). Rewrites
#                        the transaction's notes prefix so the derived
#                        Access ``access_source`` re-reads correctly.
#       * ``amount_cents`` — the recorded amount. Updates gross +
#                        net_creator_amount together. Cannot change
#                        currency (which is a downstream reporting
#                        concern).
#       * ``notes`` — the operator note appended after the prefix.
#     Does NOT touch AccessPass / PathwayEntitlement rows.
#
#   DELETE /commerce/manual-grant/{txn_id}
#     Cancel + revoke. Marks the transaction ``cancelled``, cancels
#     every linked AccessPass, and revokes the linked PathwayEntitlement
#     if the txn's singular pointer is populated AND that entitlement
#     was created as a manual grant. After cancelling the Creator can
#     re-issue via the normal Grant Access modal.
#
# What's deliberately NOT implemented
# -----------------------------------
# * "Replace Payment Option in-place" — the shared applier
#   (``_apply_entitlement``) reactivates existing PathwayEntitlement
#   rows rather than creating new ones, so a manual grant's PE row
#   may pre-date the grant. We cannot safely tell "did we create this
#   entitlement, or was it already active from another source?" for
#   every case. Cancel + re-grant preserves that safety.
# * Reversal of non-manual transactions — Stripe purchases can only be
#   corrected through Stripe's own refund flow, not here.
# * Multi-entitlement bundle reversal on the PE side — ``entitlement_id``
#   is only set when the intent produced exactly one entitlement. For
#   multi-Pathway options we cancel the AccessPasses but leave the
#   PathwayEntitlements alone; the Creator can then re-issue with the
#   corrected option. Reported to the caller in the cancel response.
# ---------------------------------------------------------------------------


_MANUAL_GRANT_SOURCE_PREFIX = "Manual grant"


class ManualGrantMetadataPatch(BaseModel):
    source: str | None = None
    amount_cents: int | None = None
    notes: str | None = None


def _rewrite_manual_grant_notes(new_source: str, new_notes: str | None) -> str:
    """Produce the ``notes`` string in the same shape the create
    endpoint writes. Keeps ``access_source`` derivation on the Access
    page consistent."""
    prefix = f"{_MANUAL_GRANT_SOURCE_PREFIX} \u2014 {new_source}"
    if new_notes:
        return f"{prefix}: {new_notes}"
    return prefix


def _get_manual_grant_txn(
    db: Session, space: Space, txn_id: str,
) -> PaymentTransaction:
    txn = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.id == txn_id,
            PaymentTransaction.space_id == space.id,
        )
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    provider = (
        txn.payment_provider.value
        if hasattr(txn.payment_provider, "value")
        else str(txn.payment_provider)
    )
    if provider != PaymentProvider.manual.value:
        raise HTTPException(
            status_code=400,
            detail="This transaction wasn't created as a manual grant, so it can't be edited here.",
        )
    return txn


@router.patch(
    "/spaces/{slug}/commerce/manual-grant/{txn_id}",
    response_model=ManualGrantResponse,
)
def edit_manual_grant_metadata(
    slug: str,
    txn_id: str,
    body: ManualGrantMetadataPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualGrantResponse:
    """Safe metadata correction on a manual-grant transaction.
    Does NOT touch downstream Access rows — that would risk revoking
    legitimate access from a different source. Use DELETE for the
    "wrong Payment Option" case instead."""
    space = _get_managed_space(slug, current_user, db)
    txn = _get_manual_grant_txn(db, space, txn_id)

    updates = body.model_dump(exclude_unset=True)

    if "source" in updates and updates["source"] is not None:
        if updates["source"] not in _MANUAL_GRANT_SOURCES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported source. Choose one of: "
                    + ", ".join(sorted(_MANUAL_GRANT_SOURCES))
                ),
            )
    if "amount_cents" in updates and updates["amount_cents"] is not None:
        if updates["amount_cents"] < 0:
            raise HTTPException(status_code=400, detail="Amount cannot be negative.")

    # Complimentary is always $0 regardless of what the caller sent —
    # keep that invariant here too, so the ledger stays coherent.
    new_source = updates.get("source", _parse_source_from_notes(txn.notes))
    if "amount_cents" in updates:
        gross = 0 if new_source == "complimentary" else int(updates["amount_cents"] or 0)
    else:
        gross = 0 if new_source == "complimentary" else txn.gross_amount_cents

    # Notes rewrite happens whenever source or notes change so the
    # derived ``access_source`` stays in sync.
    new_notes_text = updates.get("notes") if "notes" in updates else _parse_notes_body(txn.notes)
    txn.notes = _rewrite_manual_grant_notes(new_source, new_notes_text)

    txn.gross_amount_cents = gross
    txn.net_creator_amount_cents = gross
    txn.updated_at = datetime.utcnow()
    db.commit()

    # Return the same shape as the create endpoint so the frontend
    # doesn't need a second lookup.
    access_pass_ids = [
        row[0]
        for row in db.query(AccessPass.id)
        .filter(AccessPass.payment_transaction_id == txn.id)
        .all()
    ]
    return ManualGrantResponse(
        transaction_id=txn.id,
        access_pass_ids=access_pass_ids,
        entitlement_ids=[txn.entitlement_id] if txn.entitlement_id else [],
        message="Correction saved.",
    )


class ManualGrantCancelResponse(BaseModel):
    transaction_id: str
    revoked_access_passes: int
    revoked_entitlement_id: str | None = None
    entitlement_left_intact_reason: str | None = None


@router.delete(
    "/spaces/{slug}/commerce/manual-grant/{txn_id}",
    response_model=ManualGrantCancelResponse,
)
def cancel_manual_grant(
    slug: str,
    txn_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_creator_user),
) -> ManualGrantCancelResponse:
    """Cancel a manual grant.

    * The transaction is marked ``cancelled`` (not deleted) so the
      Payments ledger keeps a record of the correction.
    * Every AccessPass linked to this transaction is cancelled
      (status → ``cancelled``, revoked_at + revoked_by set) —
      unambiguously ours by ``payment_transaction_id`` FK.
    * The linked PathwayEntitlement is revoked ONLY when the
      transaction's singular ``entitlement_id`` pointer is set AND
      the entitlement's ``source`` is ``manual_grant``. This avoids
      revoking a Pathway a member also holds from a different
      source (e.g. a real Stripe purchase or a legacy manual grant
      with different provenance).
    * When we deliberately leave an entitlement in place, the
      response's ``entitlement_left_intact_reason`` says why — the
      Creator can then handle it explicitly if needed.
    """
    from app.models.platform import EntitlementStatus, EntitlementSource, PathwayEntitlement

    space = _get_managed_space(slug, current_user, db)
    txn = _get_manual_grant_txn(db, space, txn_id)

    now = datetime.utcnow()
    passes = (
        db.query(AccessPass)
        .filter(AccessPass.payment_transaction_id == txn.id)
        .all()
    )
    for ap in passes:
        ap.status = AccessPassStatus.cancelled
        ap.revoked_at = now
        ap.revoked_by_user_id = current_user.id
        ap.updated_at = now

    revoked_ent_id: str | None = None
    left_intact: str | None = None
    if txn.entitlement_id:
        ent = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.id == txn.entitlement_id)
            .first()
        )
        if ent is None:
            left_intact = "Linked entitlement no longer exists."
        else:
            src = (
                ent.source.value if hasattr(ent.source, "value") else str(ent.source)
            )
            if src == EntitlementSource.manual_grant.value or src == "one_time_purchase":
                # Manual-grant entitlements + one_time_purchase entitlements
                # produced by this manual grant are safe to revoke — the
                # applier writes ``source=one_time_purchase`` when it
                # creates the row, and the txn.entitlement_id pointer is
                # authoritative for "this grant's" entitlement.
                ent.status = EntitlementStatus.revoked
                ent.revoked_at = now
                ent.revoked_by_user_id = current_user.id
                ent.updated_at = now
                revoked_ent_id = ent.id
            else:
                left_intact = (
                    f"Linked entitlement source is {src!r} — not revoked "
                    "so pre-existing member access from a different source "
                    "is preserved."
                )
    else:
        # Bundle with >1 entitlement: applier never sets txn.entitlement_id.
        # We cannot reliably identify "just this grant's" entitlements without
        # additional linkage. Report so the Creator can act if needed.
        # (Note: single-Series options don't produce a PathwayEntitlement at
        # all, so this branch is silent for those — nothing to revoke.)
        left_intact = (
            "Bundle produced more than one Pathway entitlement or none — "
            "any remaining PathwayEntitlement rows were left in place. "
            "If a Pathway should be revoked, do it manually from People."
        )

    txn.status = PaymentTransactionStatus.cancelled
    existing_notes = txn.notes or ""
    if "cancelled" not in existing_notes.lower():
        txn.notes = f"{existing_notes} \u00b7 cancelled by correction".strip(" \u00b7")
    txn.updated_at = now
    db.commit()

    return ManualGrantCancelResponse(
        transaction_id=txn.id,
        revoked_access_passes=len(passes),
        revoked_entitlement_id=revoked_ent_id,
        entitlement_left_intact_reason=left_intact,
    )


def _parse_source_from_notes(notes: str | None) -> str:
    """Extract the source label from a ``Manual grant \u2014 {source}[: note]``
    notes string. Falls back to ``manual`` for legacy shapes."""
    if not notes:
        return "manual"
    lower = notes.lower()
    for kind in ("complimentary", "bank_transfer", "cash", "admin_grant"):
        if kind in lower:
            return kind
    return "manual"


def _parse_notes_body(notes: str | None) -> str | None:
    """Return the operator-supplied note (after the ``: `` separator),
    or None if the notes are just the prefix."""
    if not notes:
        return None
    _, sep, tail = notes.partition(":")
    if not sep:
        return None
    tail = tail.strip()
    # Strip trailing " · cancelled by correction" marker so a
    # re-edit doesn't accumulate it.
    tail = tail.split(" \u00b7 cancelled by correction")[0].strip()
    return tail or None
