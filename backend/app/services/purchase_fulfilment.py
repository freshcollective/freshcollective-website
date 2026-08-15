"""Successful-purchase fulfilment — shared service.

Owns the side-effects of a successful ``PaymentTransaction``:
creation/reactivation of ``PathwayEntitlement`` rows, creation of
``AccessPass`` rows, auto-join of the buyer into the target
``Space`` as a learner, and (future) confirmation of standalone
Gathering bookings.

Atomicity contract
------------------
A Payment Option may promise multiple experiences (multiple
Pathways, multiple Series, and — later — Gatherings). The shared
service is atomic on that bundle:

    resolve → validate → apply

Every FK target referenced by the intent is checked against the
DB **before any writes**. If any required target is missing, the
service refuses to apply the bundle and returns ``FulfilmentResult
(status=blocked)``. If validation passes, the applier proceeds; if
any write raises during apply the caller is expected to roll back
the whole transaction (writes are batched into a single
in-memory session; the caller commits or rolls back exactly once).

There is deliberately **no partial-fulfilment path**: the pre-B3
webhook committed half a bundle when the second half failed, which
is an operational hazard we do not want to bake into the shared
service. Callers get either "everything, applied" or "nothing, and
here's why".

Boundary between resolvers
--------------------------
Two entrypoints today:

    resolve_intent_from_legacy(...) -> FulfilmentResolution
        Reads the legacy ``PaymentOption`` fields
        (``attaches_to_kind`` / ``attaches_to_id`` /
        ``grants_pathway_id`` / ``sessions_per_week`` /
        ``total_sessions`` / ``term_start_date`` /
        ``term_end_date``). This is the resolver B3 ships and the
        webhook exclusively uses.

    validate_intent(db, intent) -> ValidationResult
        Confirms every ``EntitlementIntent.pathway_id``,
        ``AccessPassIntent.eligible_pathway_id`` /
        ``eligible_series_id`` / ``grants_pathway_id``,
        and ``BookingIntent.event_id`` refers to a row that
        exists in the DB right now.

    apply_intent(intent, ...) -> FulfilmentResult
        Writes the entitlement / AccessPass / membership rows.
        Assumes validation has already passed — an unexpected
        integrity error during apply must roll back the whole
        transaction (the caller's responsibility). Never inspects
        ``PaymentOption`` or grants.

B4 will add ``resolve_intent_from_grants`` alongside the legacy
resolver; the applier and the intent shape stay unchanged.

Not in scope for B3
-------------------
Free-checkout short-circuit, unified ``/api/checkout``, subscription
renewal, standalone-Gathering ticket flow (``BookingIntent`` exists
as a placeholder but the resolver never populates one — the
existing pending-payment/capacity-hold system in
``services/gathering_tickets.py`` remains authoritative for those
purchases; see B7 in the roadmap).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment import PaymentTransaction
from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES,
    GRANT_KIND_GATHERING,
    GRANT_KIND_PATHWAY,
)
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Event,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    SpaceMembership,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalised intents — resolver output; applier input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntitlementIntent:
    """A PathwayEntitlement to create or reactivate on purchase.

    ``starts_at``
        ``None`` (default) → the applier uses ``NOW()`` at
        fulfilment time. This is the historical behaviour — the
        pre-B3 webhook and the legacy resolver both always used
        ``NOW()``, including for bundled Pathway grants attached
        to a future-term Series pass (the "immediate access"
        rule).

        Non-``None`` → the applier uses this timestamp as the
        entitlement's ``starts_at``. Enables PaymentOptionGrant
        rows carrying ``valid_from_override`` to express delayed
        activation.

    ``ends_at``
        ``None`` → the entitlement is perpetual (no ``ends_at``
        stored). Non-``None`` → pins the end.
    """

    pathway_id: str
    ends_at: datetime | None
    starts_at: datetime | None = None


@dataclass(frozen=True)
class AccessPassIntent:
    """An AccessPass to create on purchase (term_pass only today).

    Note on ``grants_pathway_id``: this is a **legacy shadow
    relationship**. In the pre-B3 webhook and today's legacy
    resolver, a Series-attached option with a bundled Pathway
    populates BOTH a separate PathwayEntitlement AND
    ``AccessPass.grants_pathway_id`` pointing at the same
    pathway. The AccessPass field is redundant — the entitlement
    is the authoritative record — but it stays populated so
    legacy readers keep working. In the grants architecture
    (B4+), a bundled Pathway is expressed by a separate
    ``EntitlementIntent`` in the same ``FulfilmentIntent`` and
    the applier no longer requires this field to be set. The
    field remains in the intent shape and is written to the row
    unchanged; it is not the source of truth for anything new.
    """

    pass_type: AccessPassType
    valid_from: datetime
    valid_until: datetime | None
    total_credits: int | None
    credits_per_week: int | None
    eligible_pathway_id: str | None
    eligible_series_id: str | None
    # Legacy shadow — see class docstring.
    grants_pathway_id: str | None = None


@dataclass(frozen=True)
class BookingIntent:
    """An EventBooking to confirm on purchase.

    Placeholder for standalone-Gathering ``PaymentOption``
    fulfilment. The legacy resolver never populates a
    BookingIntent in B3 — standalone paid Gathering purchases
    continue to flow through ``services/gathering_tickets.py``'s
    pending-payment / capacity-hold system. When the standalone-
    Gathering PaymentOption path is activated, this intent type +
    a matching applier helper are the target shape.
    """

    event_id: str


@dataclass(frozen=True)
class FulfilmentIntent:
    """Everything a successful purchase should produce, in a
    resolver-agnostic shape. Every collection defaults to empty.
    """

    entitlements: tuple[EntitlementIntent, ...] = ()
    access_passes: tuple[AccessPassIntent, ...] = ()
    bookings: tuple[BookingIntent, ...] = ()


@dataclass(frozen=True)
class FulfilmentResolution:
    """What the resolver produced.

    ``intent`` is the collection of side-effects to apply.
    ``fatal_error``, when set, indicates the resolver detected a
    condition that means the purchase cannot be fulfilled — the
    caller should mark the txn's ``fulfilment_status='blocked'``
    and return.

    No singular ``resolved_series`` field: the multi-experience
    target architecture explicitly allows a Payment Option to
    grant multiple Series, so a singular Series pointer here would
    embed an incorrect assumption in the source-independent
    contract. Legacy resolvers that need Series context for their
    own logging keep it as an internal detail — see
    ``resolve_intent_from_legacy`` below for an example.
    """

    intent: FulfilmentIntent = field(default_factory=FulfilmentIntent)
    fatal_error: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    """Output of ``validate_intent``.

    ``errors`` lists every missing target the applier would trip
    over. Empty → the intent may be applied. Non-empty → the
    applier must not run.
    """

    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class FulfilmentResult:
    """What the applier produced.

    ``status`` is the terminal outcome from the shared service's
    point of view. ``entitlements`` / ``access_passes`` contain
    the rows the applier touched.

    There is deliberately no ``partial_error`` field: pre-write
    validation prevents partial application, and any error during
    apply must roll back the whole transaction.
    """

    status: "FulfilmentStatus"
    entitlements: list[PathwayEntitlement] = field(default_factory=list)
    access_passes: list[AccessPass] = field(default_factory=list)
    membership_created: bool = False
    # When status is not ``applied``, ``reason`` explains why — a
    # concatenation of resolver fatal_error / validation errors /
    # any operational note. Consumed by the webhook for logs and
    # by tests for assertions.
    reason: str | None = None


class FulfilmentStatus:
    """String constants used on ``FulfilmentResult.status``.

    Deliberately a plain class of constants rather than an
    Enum so the values interoperate cleanly with
    ``PaymentFulfilmentStatus`` on the model (which is an
    ``enum.Enum``): the strings on both sides match.
    """
    APPLIED = "applied"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Resolver — legacy PaymentOption fields (B3 source of truth)
# ---------------------------------------------------------------------------


def _payment_type_str(payment_option: PaymentOption) -> str:
    v = payment_option.payment_type
    return v.value if hasattr(v, "value") else str(v)


def _po_term_end_dt(payment_option: PaymentOption | None) -> datetime | None:
    """Return ``combine(payment_option.term_end_date, min.time())``
    but only for ``term_pass`` options. A non-term_pass option with
    a stray ``term_end_date`` returns ``None`` — mirrors the private
    helper the pre-B3 webhook inlined."""
    if payment_option is None or payment_option.term_end_date is None:
        return None
    if _payment_type_str(payment_option) != "term_pass":
        return None
    return datetime.combine(payment_option.term_end_date, datetime.min.time())


def _load_series_or_none(
    db: Session, payment_option: PaymentOption | None,
) -> EventSeries | None:
    """Resolve the ``EventSeries`` row for a series-attached option."""
    if payment_option is None:
        return None
    if payment_option.attaches_to_kind != "event_series":
        return None
    return (
        db.query(EventSeries)
        .filter(EventSeries.id == payment_option.attaches_to_id)
        .first()
    )


def resolve_intent_from_legacy(
    db: Session,
    *,
    payment_option: PaymentOption | None,
    metadata_pathway_id: str | None,
    now: datetime,
) -> FulfilmentResolution:
    """Compute a ``FulfilmentResolution`` from legacy
    ``PaymentOption`` fields.

    The three historically-supported shapes today produce:

      * Pathway-only purchase        → one EntitlementIntent
      * Series-only purchase         → one AccessPassIntent
      * Series + bundled Pathway     → one of each

    A series-attached option whose ``attaches_to_id`` points at
    a missing Series row returns
    ``FulfilmentResolution(fatal_error=...)`` with an empty intent.

    Rules preserved from the pre-B3 webhook:

    Series-attached option
      * Entitlement (if any) targets ``option.grants_pathway_id``.
      * Entitlement ``ends_at`` = ``series.ends_at`` OR
        ``_po_term_end_dt(option)`` OR ``None``.
      * ``term_pass`` additionally creates an AccessPass:
          - ``valid_from`` = ``series.starts_at``
          - ``valid_until`` = ``series.ends_at`` OR
            ``combine(option.term_end_date, min.time())`` OR ``None``
          - ``eligible_series_id`` = ``series.id``
          - ``eligible_pathway_id`` = ``None``
          - ``grants_pathway_id`` = legacy shadow of the bundled
            pathway (also expressed as a separate
            ``EntitlementIntent``)

    Pathway-attached option (or no option)
      * Entitlement targets ``option.grants_pathway_id`` when set,
        else ``metadata_pathway_id`` (legacy fallback).
      * Entitlement ``ends_at`` = ``_po_term_end_dt(option)``.
      * ``term_pass`` additionally creates an AccessPass:
          - ``valid_from`` = ``combine(option.term_start_date, min.time())``
            OR ``now``
          - ``valid_until`` = ``_po_term_end_dt(option)``
          - ``eligible_pathway_id`` = the resolved entitlement pathway
          - ``eligible_series_id`` = ``None``
    """
    series = _load_series_or_none(db, payment_option)

    if (
        payment_option is not None
        and payment_option.attaches_to_kind == "event_series"
        and series is None
    ):
        return FulfilmentResolution(
            fatal_error=(
                f"series-attached PaymentOption {payment_option.id!r} points at "
                f"missing EventSeries {payment_option.attaches_to_id!r}"
            ),
        )

    # ── Entitlement target + entitlement.ends_at ─────────────────
    entitlement_pathway_id: str | None
    term_ends_at: datetime | None = None
    if series is not None:
        entitlement_pathway_id = (
            payment_option.grants_pathway_id if payment_option else None
        )
        term_ends_at = series.ends_at or _po_term_end_dt(payment_option)
    else:
        entitlement_pathway_id = (
            payment_option.grants_pathway_id
            if payment_option and payment_option.grants_pathway_id
            else metadata_pathway_id
        )
        term_ends_at = _po_term_end_dt(payment_option)

    entitlements: tuple[EntitlementIntent, ...] = ()
    if entitlement_pathway_id:
        entitlements = (EntitlementIntent(
            pathway_id=entitlement_pathway_id,
            ends_at=term_ends_at,
        ),)

    # ── AccessPass for term_pass options ──────────────────────────
    access_passes: tuple[AccessPassIntent, ...] = ()
    if payment_option and _payment_type_str(payment_option) == "term_pass":
        if series is not None:
            valid_from_dt = series.starts_at
            ap_valid_until = series.ends_at or (
                datetime.combine(payment_option.term_end_date, datetime.min.time())
                if payment_option.term_end_date else None
            )
            ap_eligible_series_id = series.id
            ap_eligible_pathway_id = None
        else:
            valid_from_dt = (
                datetime.combine(payment_option.term_start_date, datetime.min.time())
                if payment_option.term_start_date
                else now
            )
            ap_valid_until = term_ends_at
            ap_eligible_series_id = None
            ap_eligible_pathway_id = entitlement_pathway_id

        access_passes = (AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=valid_from_dt,
            valid_until=ap_valid_until,
            total_credits=payment_option.total_sessions,
            credits_per_week=payment_option.sessions_per_week,
            eligible_pathway_id=ap_eligible_pathway_id,
            eligible_series_id=ap_eligible_series_id,
            grants_pathway_id=entitlement_pathway_id,
        ),)

    return FulfilmentResolution(
        intent=FulfilmentIntent(
            entitlements=entitlements,
            access_passes=access_passes,
            bookings=(),
        ),
    )


# ---------------------------------------------------------------------------
# Resolver — PaymentOptionGrant rows (B4A source of truth once cutover)
# ---------------------------------------------------------------------------


def resolve_intent_from_grants(
    db: Session, *,
    payment_option: PaymentOption,
) -> FulfilmentResolution:
    """Grant-first resolver.

    Reads ``payment_option.grants`` exclusively. Never inspects
    the legacy ``attaches_to_kind`` / ``attaches_to_id`` /
    ``grants_pathway_id`` / ``sessions_per_week`` /
    ``total_sessions`` / ``term_start_date`` / ``term_end_date``
    fields — the B2 backfill has already represented every
    legacy shape as explicit grant rows, so mixing sources would
    double-grant access.

    Grant handling:

    * ``pathway`` grant → one ``EntitlementIntent``.
        - ``starts_at`` = ``grant.valid_from_override``
          (``None`` → applier uses ``NOW()``)
        - ``ends_at``   = ``grant.valid_until_override``
          (``None`` → perpetual)

    * ``event_series`` grant → one ``AccessPassIntent``.
        - ``valid_from``  = ``grant.valid_from_override``
          if set, else ``series.starts_at``
        - ``valid_until`` = ``grant.valid_until_override``
          if set, else ``series.ends_at`` (``None`` → no end)
        - ``total_credits``    = ``grant.total_sessions``
        - ``credits_per_week`` = ``grant.sessions_per_week``
        - ``eligible_series_id`` = ``grant.series_id``
        - ``eligible_pathway_id`` = ``None``

    * ``gathering`` grant → **not yet supported at runtime**.
      The resolver returns a fatal error so the webhook marks
      ``fulfilment_status='blocked'`` rather than silently
      pretending the bundle was fulfilled. The existing paid-
      Gathering ticket-hold flow in ``services/gathering_tickets.py``
      remains authoritative for those purchases until a later
      commit unifies them.

    Legacy shadow field on ``AccessPassIntent.grants_pathway_id``:
    populated when the option has exactly one Pathway grant, so
    new AccessPass rows written via the grant path still carry
    the same shadow value the legacy resolver used to write.
    This maintains parity for legacy readers of that column
    without letting the shadow influence what access is granted
    — the bundled Pathway is expressed as its own
    ``EntitlementIntent``.

    Multi-experience purchases work uniformly: any number of
    Pathway grants produce that many entitlements; any number
    of Series grants produce that many independent AccessPasses.
    """
    grants = list(payment_option.grants)

    # ── Unsupported: Gathering grants ─────────────────────────────
    gathering_grants = [
        g for g in grants if g.grant_kind == GRANT_KIND_GATHERING
    ]
    if gathering_grants:
        return FulfilmentResolution(
            fatal_error=(
                f"PaymentOption {payment_option.id!r} carries "
                f"{len(gathering_grants)} grant(s) of kind='gathering'; "
                "standalone Gathering PaymentOption fulfilment is not "
                "yet activated. The existing paid-Gathering ticket-hold "
                "flow remains authoritative for those purchases."
            ),
        )

    pathway_grants = [
        g for g in grants if g.grant_kind == GRANT_KIND_PATHWAY
    ]
    series_grants = [
        g for g in grants if g.grant_kind == GRANT_KIND_EVENT_SERIES
    ]

    # Batch-load Series rows for window derivation. Missing rows
    # surface as ``None`` here; ``validate_intent`` catches them
    # before any writes so the whole bundle blocks atomically.
    series_by_id: dict[str, EventSeries] = {}
    if series_grants:
        series_ids = [g.series_id for g in series_grants if g.series_id]
        if series_ids:
            for s in (
                db.query(EventSeries)
                .filter(EventSeries.id.in_(series_ids))
                .all()
            ):
                series_by_id[s.id] = s

    # ── Entitlements — one per Pathway grant ──────────────────────
    entitlements: list[EntitlementIntent] = []
    for pg in pathway_grants:
        entitlements.append(EntitlementIntent(
            pathway_id=pg.pathway_id,
            ends_at=pg.valid_until_override,
            # ``None`` → applier uses ``NOW()`` (matches the pre-B3
            # "immediate access" rule for bundled pathway grants,
            # which is what every B2-backfilled grant produces).
            starts_at=pg.valid_from_override,
        ))

    # Legacy shadow on Series AccessPass: only meaningful when the
    # option has exactly one Pathway grant. Multi-Pathway options
    # cannot honestly point a single shadow at "the" pathway.
    shadow_grants_pathway_id: str | None = (
        pathway_grants[0].pathway_id
        if len(pathway_grants) == 1 else None
    )

    # ── AccessPasses — one per Series grant ───────────────────────
    access_passes: list[AccessPassIntent] = []
    for sg in series_grants:
        series = series_by_id.get(sg.series_id or "")

        # Fallback chain matches the grant semantics documented on
        # the model:
        #   valid_from  = grant.valid_from_override OR series.starts_at
        #   valid_until = grant.valid_until_override OR series.ends_at
        # If the Series row is missing here, ``validate_intent``
        # will refuse the bundle. Use a placeholder for
        # ``valid_from`` so the dataclass construction doesn't
        # crash before validation gets to speak.
        valid_from: datetime
        if sg.valid_from_override is not None:
            valid_from = sg.valid_from_override
        elif series is not None:
            valid_from = series.starts_at
        else:
            # Placeholder — validation will block on the missing
            # Series before any writes reach this value.
            valid_from = datetime.min

        valid_until: datetime | None
        if sg.valid_until_override is not None:
            valid_until = sg.valid_until_override
        elif series is not None:
            valid_until = series.ends_at
        else:
            valid_until = None

        access_passes.append(AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=valid_from,
            valid_until=valid_until,
            total_credits=sg.total_sessions,
            credits_per_week=sg.sessions_per_week,
            eligible_pathway_id=None,
            eligible_series_id=sg.series_id,
            grants_pathway_id=shadow_grants_pathway_id,
        ))

    return FulfilmentResolution(
        intent=FulfilmentIntent(
            entitlements=tuple(entitlements),
            access_passes=tuple(access_passes),
            bookings=(),
        ),
    )


# ---------------------------------------------------------------------------
# Grant-readiness — dispatcher safety check
# ---------------------------------------------------------------------------


def option_grant_readiness(
    payment_option: PaymentOption,
) -> tuple[bool, str | None]:
    """Return ``(is_ready, reason_if_not)`` for a PaymentOption's
    grant-first fulfilment eligibility.

    An option is "grant-ready" when the grant resolver's output
    fully covers what the legacy resolver would produce. The
    dispatcher uses this rule to avoid silently switching an
    option to grants when the grant representation is incomplete
    — which would mean the buyer loses access that the legacy
    resolver would have granted.

    Today the one known gap is **pathway-attached term_pass
    options**: the legacy resolver produces an ``AccessPass``
    with credits and window from
    ``sessions_per_week`` / ``total_sessions`` /
    ``term_start_date`` / ``term_end_date``; a Pathway grant has
    no fields for those, so the grant-side output is missing the
    AccessPass entirely.

    (Series-attached term_pass options are fine — the Series
    grant carries credits + window; the bundled Pathway grant
    carries the entitlement window. B2's backfill verified
    parity on those.)

    Readiness is derived deterministically from the option's
    shape, not from a manual flag. If a later migration
    canonicalises a pathway-attached term_pass into (e.g.) a
    Series-attached option or clears the Series-style fields, the
    readiness check re-evaluates to True automatically.

    The rule is intentionally conservative — "not ready" simply
    routes to the legacy resolver, which is proven correct. It
    is never a fulfilment failure.
    """
    kind = payment_option.attaches_to_kind
    payment_type = _payment_type_str(payment_option)

    if kind == "pathway" and payment_type == "term_pass":
        # Pathway grants have no ``sessions_per_week`` /
        # ``total_sessions`` / ``term_start_date`` fields — those
        # are event_series-grant-only by design. If the legacy
        # option carries any of them, the grant-side output would
        # silently omit the AccessPass the buyer paid for.
        unrepresentable = []
        if payment_option.sessions_per_week is not None:
            unrepresentable.append("sessions_per_week")
        if payment_option.total_sessions is not None:
            unrepresentable.append("total_sessions")
        if payment_option.term_start_date is not None:
            unrepresentable.append("term_start_date")
        # ``term_end_date`` IS representable on the Pathway grant
        # via ``valid_until_override``, so it does not by itself
        # make the option unrepresentable. However, the legacy
        # resolver's term_pass branch also emits an AccessPass
        # even when only ``term_end_date`` is set (credits +
        # credits_per_week both null). Any term_pass on a
        # pathway-attached option therefore loses at least the
        # AccessPass row if it goes through grants. Route to
        # legacy unconditionally for pathway-attached term_pass.
        if not unrepresentable:
            unrepresentable.append("term_pass_semantics")
        return False, (
            f"pathway-attached term_pass option carries fields the "
            f"grant representation does not yet cover: "
            f"{', '.join(unrepresentable)}"
        )

    return True, None


# ---------------------------------------------------------------------------
# Dispatcher — grants-first (when ready), else legacy fallback
# ---------------------------------------------------------------------------


def resolve_intent_for_option(
    db: Session, *,
    payment_option: PaymentOption | None,
    metadata_pathway_id: str | None,
    now: datetime,
) -> FulfilmentResolution:
    """Runtime resolver dispatch.

    Rule (B4A):

      * ``payment_option`` has grants AND is grant-ready
        (:func:`option_grant_readiness` returns True) → grants
        are authoritative; resolve exclusively from them.

      * ``payment_option`` has grants but is NOT grant-ready →
        legacy resolver + structured warning explaining the
        specific representation gap. Emitted so the transition
        can be tracked and completed; not a fulfilment failure.

      * ``payment_option`` has no grants → legacy resolver +
        structured warning naming the missing backfill.

      * No ``payment_option`` at all → legacy resolver (option-less
        R.E.A.L. Journey path). No warning; there's nothing to
        backfill.

    The dispatcher never mixes sources for the same purchase.
    """
    if payment_option is None:
        return resolve_intent_from_legacy(
            db, payment_option=None,
            metadata_pathway_id=metadata_pathway_id, now=now,
        )

    has_grants = len(payment_option.grants) > 0

    if has_grants:
        ready, reason = option_grant_readiness(payment_option)
        if ready:
            return resolve_intent_from_grants(db, payment_option=payment_option)
        # Grants exist but the option's legacy shape carries
        # information the current grant model does not yet
        # represent. Fall back to legacy so the buyer gets the
        # full access they paid for.
        logger.warning(
            "purchase_fulfilment: PaymentOption %s has grants but is not "
            "grant-ready — %s. Falling back to legacy resolver until the "
            "grant model or this option's shape is updated so grants can "
            "fully represent it.",
            payment_option.id, reason,
        )
    else:
        logger.warning(
            "purchase_fulfilment: PaymentOption %s has no grants — "
            "falling back to legacy resolver. This is a transition-"
            "period compatibility path; the option should be "
            "backfilled via app.commerce.backfill_grants.",
            payment_option.id,
        )

    return resolve_intent_from_legacy(
        db,
        payment_option=payment_option,
        metadata_pathway_id=metadata_pathway_id,
        now=now,
    )


# ---------------------------------------------------------------------------
# Validator — pre-write check every FK target the intent references
# ---------------------------------------------------------------------------


def validate_intent(db: Session, intent: FulfilmentIntent) -> ValidationResult:
    """Confirm every referenced target exists in the DB.

    Batch-queries by kind so a bundle with N entitlements + M
    passes issues at most three SELECTs (one per target table).
    Called *before* any writes so a missing target results in
    ``FulfilmentStatus.blocked`` on the whole bundle — never a
    partial application.
    """
    pathway_ids: set[str] = set()
    series_ids: set[str] = set()
    event_ids: set[str] = set()

    for ent in intent.entitlements:
        pathway_ids.add(ent.pathway_id)
    for ap in intent.access_passes:
        if ap.eligible_pathway_id:
            pathway_ids.add(ap.eligible_pathway_id)
        if ap.eligible_series_id:
            series_ids.add(ap.eligible_series_id)
        if ap.grants_pathway_id:
            pathway_ids.add(ap.grants_pathway_id)
    for b in intent.bookings:
        event_ids.add(b.event_id)

    errors: list[str] = []

    if pathway_ids:
        found = {
            p_id for (p_id,) in
            db.query(Pathway.id).filter(Pathway.id.in_(pathway_ids)).all()
        }
        for missing in sorted(pathway_ids - found):
            errors.append(f"pathway {missing!r} referenced by intent does not exist")
    if series_ids:
        found = {
            s_id for (s_id,) in
            db.query(EventSeries.id).filter(EventSeries.id.in_(series_ids)).all()
        }
        for missing in sorted(series_ids - found):
            errors.append(f"event_series {missing!r} referenced by intent does not exist")
    if event_ids:
        found = {
            e_id for (e_id,) in
            db.query(Event.id).filter(Event.id.in_(event_ids)).all()
        }
        for missing in sorted(event_ids - found):
            errors.append(f"event {missing!r} referenced by intent does not exist")

    return ValidationResult(errors=tuple(errors))


# ---------------------------------------------------------------------------
# Applier — writes rows from a FulfilmentIntent (assumes validation passed)
# ---------------------------------------------------------------------------


def _apply_entitlement(
    db: Session,
    *,
    intent: EntitlementIntent,
    payer_user_id: str,
    space_id: str,
    session_id: str | None,
    payment_intent_id: str | None,
    now: datetime,
    purchase_plan_id: str | None = None,
) -> PathwayEntitlement:
    """Create or reactivate the target PathwayEntitlement. Assumes
    the target Pathway row exists — validation should have caught
    a missing target before we reached here. If a race removes the
    pathway between validate and apply, the FK constraint will
    raise IntegrityError and the caller must roll the whole
    transaction back."""
    existing_ent = (
        db.query(PathwayEntitlement)
        .filter(
            PathwayEntitlement.user_id == payer_user_id,
            PathwayEntitlement.pathway_id == intent.pathway_id,
        )
        .order_by(PathwayEntitlement.created_at.desc())
        .first()
    )

    if existing_ent and existing_ent.status == EntitlementStatus.active:
        # Already active (re-delivery) — update Stripe fields only.
        # ``ends_at`` is deliberately NOT extended here.
        existing_ent.stripe_checkout_session_id = session_id
        existing_ent.stripe_payment_intent_id = payment_intent_id
        if purchase_plan_id and existing_ent.purchase_plan_id is None:
            existing_ent.purchase_plan_id = purchase_plan_id
        existing_ent.updated_at = now
        logger.info(
            "purchase_fulfilment: entitlement already active user=%s pathway=%s",
            payer_user_id, intent.pathway_id,
        )
        return existing_ent

    # ``intent.starts_at`` defaults to None (legacy resolver
    # never sets it). Grant-based resolvers may carry a value
    # from ``PaymentOptionGrant.valid_from_override``.
    starts_at = intent.starts_at if intent.starts_at is not None else now

    if existing_ent:
        existing_ent.status = EntitlementStatus.active
        existing_ent.source = EntitlementSource.one_time_purchase
        existing_ent.stripe_checkout_session_id = session_id
        existing_ent.stripe_payment_intent_id = payment_intent_id
        existing_ent.revoked_by_user_id = None
        existing_ent.revoked_at = None
        existing_ent.starts_at = starts_at
        existing_ent.ends_at = intent.ends_at
        if purchase_plan_id and existing_ent.purchase_plan_id is None:
            existing_ent.purchase_plan_id = purchase_plan_id
        existing_ent.updated_at = now
        logger.info(
            "purchase_fulfilment: reactivated entitlement user=%s pathway=%s starts_at=%s ends_at=%s",
            payer_user_id, intent.pathway_id, starts_at, intent.ends_at,
        )
        return existing_ent

    ent = PathwayEntitlement(
        id=str(uuid4()),
        user_id=payer_user_id,
        space_id=space_id,
        pathway_id=intent.pathway_id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=starts_at,
        ends_at=intent.ends_at,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=payment_intent_id,
        purchase_plan_id=purchase_plan_id,
        created_at=now,
        updated_at=now,
    )
    db.add(ent)
    db.flush()
    logger.info(
        "purchase_fulfilment: created entitlement %s user=%s pathway=%s starts_at=%s ends_at=%s",
        ent.id, payer_user_id, intent.pathway_id, starts_at, intent.ends_at,
    )
    return ent


def _auto_join_membership(
    db: Session, *,
    payer_user_id: str,
    space_id: str,
    now: datetime,
) -> bool:
    """Create a ``learner`` ``SpaceMembership`` if the buyer isn't
    already a member. Returns ``True`` when a row was created."""
    existing = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == payer_user_id,
        )
        .first()
    )
    if existing:
        return False
    db.add(SpaceMembership(
        id=str(uuid4()),
        space_id=space_id,
        user_id=payer_user_id,
        role="learner",
        status="active",
        source="purchase",
        joined_at=now,
    ))
    logger.info(
        "purchase_fulfilment: auto-joined user=%s as learner in space=%s",
        payer_user_id, space_id,
    )
    return True


def _apply_access_pass(
    db: Session,
    *,
    intent: AccessPassIntent,
    txn: PaymentTransaction,
    payer_user_id: str,
    space_id: str,
    payment_option_id: str,
    payment_option_schedule_id: str | None,
    entitlement_for_shadow: PathwayEntitlement | None,
    now: datetime,
    purchase_plan_id: str | None = None,
) -> AccessPass:
    """Create (or return the existing) AccessPass for this
    ``(payment_transaction_id, eligible_series_id, eligible_pathway_id)``
    triple. Idempotent so a purchase producing multiple AccessPasses
    can be replayed without duplication."""
    existing = (
        db.query(AccessPass)
        .filter(
            AccessPass.payment_transaction_id == txn.id,
            AccessPass.eligible_series_id == intent.eligible_series_id,
            AccessPass.eligible_pathway_id == intent.eligible_pathway_id,
        )
        .first()
    )
    if existing is not None:
        if purchase_plan_id and existing.purchase_plan_id is None:
            existing.purchase_plan_id = purchase_plan_id
        logger.info(
            "purchase_fulfilment: AccessPass already exists for txn=%s series=%s pathway=%s — skipping",
            txn.id, intent.eligible_series_id, intent.eligible_pathway_id,
        )
        return existing

    access_pass = AccessPass(
        id=str(uuid4()),
        user_id=payer_user_id,
        space_id=space_id,
        payment_transaction_id=txn.id,
        payment_option_id=payment_option_id,
        payment_option_schedule_id=payment_option_schedule_id or None,
        purchase_plan_id=purchase_plan_id,
        pass_type=intent.pass_type,
        status=AccessPassStatus.active,
        valid_from=intent.valid_from,
        valid_until=intent.valid_until,
        total_credits=intent.total_credits,
        used_credits=0,
        credits_per_week=intent.credits_per_week,
        eligible_pathway_id=intent.eligible_pathway_id,
        eligible_series_id=intent.eligible_series_id,
        grants_pathway_id=intent.grants_pathway_id,   # legacy shadow
        pathway_entitlement_id=(
            entitlement_for_shadow.id if entitlement_for_shadow is not None else None
        ),
        source=AccessPassSource.one_time_purchase,
        created_at=now,
        updated_at=now,
    )
    db.add(access_pass)
    logger.info(
        "purchase_fulfilment: created AccessPass %s type=%s "
        "credits=%s credits_per_week=%s valid=%s→%s series=%s pathway=%s user=%s",
        access_pass.id,
        intent.pass_type.value if hasattr(intent.pass_type, "value") else intent.pass_type,
        intent.total_credits,
        intent.credits_per_week,
        intent.valid_from,
        intent.valid_until,
        intent.eligible_series_id,
        intent.eligible_pathway_id,
        payer_user_id,
    )
    return access_pass


def _link_singular_entitlement(
    txn: PaymentTransaction, entitlements: list[PathwayEntitlement],
) -> None:
    """Populate the legacy singular ``PaymentTransaction.entitlement_id``
    pointer.

    * Exactly one entitlement produced → point at it.
    * Zero produced                    → leave null.
    * More than one produced           → leave null. The singular
      pointer cannot honestly speak for a multi-entitlement
      purchase and any auto-pick would be arbitrary.
    """
    if len(entitlements) == 1:
        txn.entitlement_id = entitlements[0].id


def apply_intent(
    db: Session,
    *,
    intent: FulfilmentIntent,
    txn: PaymentTransaction,
    payer_user_id: str,
    space_id: str,
    payment_option_id: str | None,
    payment_option_schedule_id: str | None,
    session_id: str | None,
    payment_intent_id: str | None,
    now: datetime,
    purchase_plan_id: str | None = None,
) -> FulfilmentResult:
    """Apply a FulfilmentIntent to the DB atomically.

    Preconditions
    -------------
    * ``validate_intent(db, intent)`` has passed. If a caller
      forgets to validate first, this function still runs — it
      just loses the pre-flight safety net; any missing FK
      target then raises ``IntegrityError`` on flush and the
      caller MUST roll back the whole transaction.

    Ordering
    --------
    1. Every entitlement is applied first (so
       ``pathway_entitlement_id`` on subsequent AccessPass rows
       can point at one).
    2. Membership is joined once (independent of grants).
    3. Every AccessPass is applied, each idempotently.

    Guarantees
    ----------
    * No partial-fulfilment path exists in this function.
    * The applier does not call ``db.commit()`` — the caller
      commits (or rolls back) the whole transaction. On rollback
      the applier's changes are entirely undone.

    ``payment_option_id`` is required only for populating the
    AccessPass row's FK back to the option; when the intent has no
    ``access_passes``, it may be ``None``.

    ``purchase_plan_id`` — for FIP2 finite-plan first-invoice
    fulfilment. Populated onto every created ``PathwayEntitlement``
    and ``AccessPass`` so future plan-lifecycle events (revoke on
    cancellation, reinstate after grace, etc.) can find the access
    they need to touch via ``WHERE purchase_plan_id = X``. NULL for
    legacy pay-in-full / free / manual grants.
    """
    result = FulfilmentResult(status=FulfilmentStatus.APPLIED)

    # ── Entitlements ──────────────────────────────────────────────
    for ent_intent in intent.entitlements:
        ent = _apply_entitlement(
            db,
            intent=ent_intent,
            payer_user_id=payer_user_id,
            space_id=space_id,
            session_id=session_id,
            payment_intent_id=payment_intent_id,
            now=now,
            purchase_plan_id=purchase_plan_id,
        )
        result.entitlements.append(ent)

    _link_singular_entitlement(txn, result.entitlements)

    # ── Auto-join membership (every purchase) ─────────────────────
    result.membership_created = _auto_join_membership(
        db,
        payer_user_id=payer_user_id,
        space_id=space_id,
        now=now,
    )

    # ── AccessPasses ──────────────────────────────────────────────
    if intent.access_passes and not payment_option_id:  # pragma: no cover
        raise ValueError(
            "apply_intent: access_pass intents present but payment_option_id "
            "is missing"
        )
    for ap_intent in intent.access_passes:
        # Legacy shadow: pick a single entitlement to attach to
        # ``pathway_entitlement_id`` only when exactly one was
        # produced. Same rule as ``txn.entitlement_id`` — never
        # arbitrarily point at one of many.
        shadow_ent = (
            result.entitlements[0]
            if len(result.entitlements) == 1 else None
        )
        ap = _apply_access_pass(
            db,
            intent=ap_intent,
            txn=txn,
            payer_user_id=payer_user_id,
            space_id=space_id,
            payment_option_id=payment_option_id,
            payment_option_schedule_id=payment_option_schedule_id,
            entitlement_for_shadow=shadow_ent,
            now=now,
            purchase_plan_id=purchase_plan_id,
        )
        result.access_passes.append(ap)

    # ── Bookings (reserved for future standalone-Gathering path) ──
    if intent.bookings:  # pragma: no cover — resolver doesn't produce these yet
        logger.warning(
            "purchase_fulfilment: BookingIntents present but standalone-Gathering "
            "PaymentOption fulfilment is not yet activated; ignoring %d booking(s)",
            len(intent.bookings),
        )

    return result


# ---------------------------------------------------------------------------
# FIP2 — intent snapshotting for finite plans
# ---------------------------------------------------------------------------
#
# A finite payment plan may sit in ``pending_setup`` for days between
# plan creation and first-invoice success. A Creator editing the
# Payment Option's grants in that window must not silently alter
# what an already-agreed plan grants. The plan therefore carries a
# JSON snapshot of the ``FulfilmentIntent`` resolved at plan
# creation. First-invoice fulfilment hydrates the intent from the
# snapshot (not from current DB), validates FK targets still exist,
# then applies.
#
# If the snapshot references a Pathway / Series row the Creator has
# deleted since plan creation, ``validate_intent()`` catches it and
# the caller marks the txn ``fulfilment_status='blocked'`` — the
# member has paid but access cannot be applied, and operator
# intervention is required. This matches the pay-in-full "blocked"
# semantics; do not conflate blocked-fulfilment with plan failure.


def serialise_intent(intent: FulfilmentIntent) -> dict:
    """JSON-safe dict for ``PurchasePlan.snapshot_grants_json``."""
    def _iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt is not None else None

    return {
        "version": 1,
        "entitlements": [
            {
                "pathway_id": e.pathway_id,
                "starts_at": _iso(e.starts_at),
                "ends_at": _iso(e.ends_at),
            }
            for e in intent.entitlements
        ],
        "access_passes": [
            {
                "pass_type": (
                    ap.pass_type.value
                    if hasattr(ap.pass_type, "value") else str(ap.pass_type)
                ),
                "valid_from": _iso(ap.valid_from),
                "valid_until": _iso(ap.valid_until),
                "total_credits": ap.total_credits,
                "credits_per_week": ap.credits_per_week,
                "eligible_pathway_id": ap.eligible_pathway_id,
                "eligible_series_id": ap.eligible_series_id,
                "grants_pathway_id": ap.grants_pathway_id,
            }
            for ap in intent.access_passes
        ],
        "bookings": [
            {"event_id": b.event_id} for b in intent.bookings
        ],
    }


def deserialise_intent(payload: dict) -> FulfilmentIntent:
    """Inverse of :func:`serialise_intent`. Raises on unknown version."""
    if not isinstance(payload, dict):
        raise ValueError("snapshot_grants_json must be a dict")
    version = payload.get("version")
    if version != 1:
        raise ValueError(
            f"Unsupported snapshot_grants_json version: {version!r}"
        )

    def _dt(s: str | None) -> datetime | None:
        return datetime.fromisoformat(s) if s else None

    return FulfilmentIntent(
        entitlements=tuple(
            EntitlementIntent(
                pathway_id=e["pathway_id"],
                starts_at=_dt(e.get("starts_at")),
                ends_at=_dt(e.get("ends_at")),
            )
            for e in payload.get("entitlements", [])
        ),
        access_passes=tuple(
            AccessPassIntent(
                pass_type=AccessPassType(ap["pass_type"]),
                valid_from=_dt(ap["valid_from"]),
                valid_until=_dt(ap.get("valid_until")),
                total_credits=ap.get("total_credits"),
                credits_per_week=ap.get("credits_per_week"),
                eligible_pathway_id=ap.get("eligible_pathway_id"),
                eligible_series_id=ap.get("eligible_series_id"),
                grants_pathway_id=ap.get("grants_pathway_id"),
            )
            for ap in payload.get("access_passes", [])
        ),
        bookings=tuple(
            BookingIntent(event_id=b["event_id"])
            for b in payload.get("bookings", [])
        ),
    )
