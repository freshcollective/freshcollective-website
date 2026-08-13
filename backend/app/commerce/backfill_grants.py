"""B2 — Idempotent backfill of PaymentOptionGrant rows from the
legacy ``PaymentOption`` attachment fields.

Purpose
-------
Prove that ``PaymentOptionGrant`` (B1) can represent everything the
legacy ``PaymentOption.attaches_to_kind`` / ``attaches_to_id`` /
``grants_pathway_id`` + Series-limit columns represent, *before*
any runtime code path (checkout, webhook, booking) starts reading
from grants. This module never mutates the legacy columns, never
merges duplicate Options, and never changes any behaviour.

Backfill rules
--------------
For every ``PaymentOption`` row:

  * ``attaches_to_kind='pathway'`` + ``attaches_to_id=<pathway>``
    → one ``PaymentOptionGrant(grant_kind='pathway',
                               pathway_id=<pathway>)``

  * ``attaches_to_kind='event_series'`` + ``attaches_to_id=<series>``
    → one ``PaymentOptionGrant(grant_kind='event_series',
                               series_id=<series>,
                               sessions_per_week=<option.sessions_per_week>,
                               total_sessions=<option.total_sessions>,
                               valid_from_override=None,
                               valid_until_override=<see webhook precedence>)``

    plus, if ``option.grants_pathway_id`` is set:

    → one ``PaymentOptionGrant(grant_kind='pathway',
                               pathway_id=<option.grants_pathway_id>)``

    (This preserves the EMBODY case where a Series pass also grants
    The EMBODY Practice pathway on purchase.)

Access-window semantics
-----------------------
Reproduce exactly what the webhook currently does when creating an
AccessPass for a series-attached term_pass purchase (see
``app/webhooks/routes.py::_handle_checkout_completed``):

  valid_from = series.starts_at                       # never overridden by option
  valid_until = series.ends_at                        # series end wins if set
               OR option.term_end_date               # ongoing series w/ option cap
               OR NULL                                # perpetual on ongoing series

Translated to the grants model where an *override* means "wins over
the Series' own dates":

  * ``valid_from_override``: always ``None``. The webhook always
    inherits from ``series.starts_at``.
  * ``valid_until_override``: set ONLY when ``series.ends_at IS NULL``
    AND ``option.term_end_date IS NOT NULL``. Any other combination
    leaves it ``None`` and inherits from the Series row.

Bundled Pathway grant (option.grants_pathway_id + Series
attachment) creates a *separate* Pathway grant with no window
overrides — matching the current webhook, which grants the pathway
entitlement with ``starts_at=now`` (immediate access even while the
Series hasn't begun yet).

Idempotency
-----------
Idempotency key = ``(payment_option_id, grant_kind, target_id)``.
Existing keys are skipped rather than reinserted; running the
backfill any number of times converges to the same grant set. The
partial unique indexes on the table (B1) are the defence-in-depth,
but this module never provokes them by checking existence first.

Legacy shapes that cannot be represented cleanly
------------------------------------------------
Reported (with ``warnings``) but not inserted:

  * Options with empty / unknown ``attaches_to_kind`` or
    ``attaches_to_id`` — nothing to derive from.
  * Series-attached options where ``attaches_to_id`` points at a
    Series row that no longer exists — window override cannot be
    computed; the Series grant is still inserted (the grants-model
    read code will surface the missing target when it lands), but
    the warning flags it for Creator review.
  * Pathway-attached options carrying ``sessions_per_week`` /
    ``total_sessions`` / ``term_start_date`` / ``term_end_date``.
    A Pathway grant does not (by design) carry Series booking
    allowances. The grant is still inserted; the warning records
    that the legacy AccessPass fulfilment continues via the shadow
    columns and that these rows should be inspected as part of the
    (later, deliberate) duplicate-cleanup phase.

The report enumerates every warning so the Creator can review
before B3 flips the read path to grants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.platform import EventSeries, Pathway


# ---------------------------------------------------------------------------
# Derivation — pure functions, no DB writes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedGrant:
    """The shape of a grant we would insert. Kept separate from the
    ORM row so ``derive_grants_for_option`` stays purely functional
    and easy to test."""

    grant_kind: str
    pathway_id: str | None = None
    series_id: str | None = None
    event_id: str | None = None
    sessions_per_week: int | None = None
    total_sessions: int | None = None
    valid_from_override: datetime | None = None
    valid_until_override: datetime | None = None

    @property
    def target_id(self) -> str | None:
        return self.pathway_id or self.series_id or self.event_id

    @property
    def idempotency_key(self) -> tuple[str, str | None]:
        return (self.grant_kind, self.target_id)


def _payment_type_str(option: PaymentOption) -> str:
    v = option.payment_type
    return v.value if hasattr(v, "value") else str(v)


def _option_term_end_dt(option: PaymentOption) -> datetime | None:
    """Return the option's ``term_end_date`` as a naive datetime,
    ONLY when the option is a term_pass. Mirrors the current webhook
    helper ``_po_term_end_dt`` — a non-term_pass option with a
    stray ``term_end_date`` is ignored."""
    if option.term_end_date is None:
        return None
    if _payment_type_str(option) != "term_pass":
        return None
    return datetime.combine(option.term_end_date, datetime.min.time())


def _series_valid_until_override(
    series: EventSeries | None, option: PaymentOption,
) -> datetime | None:
    """Reproduce the current webhook precedence for AccessPass
    ``valid_until`` on a series-attached term_pass purchase:

        ap_valid_until = series.ends_at
                         OR (combine(term_end_date, min.time()) if term_pass else None)

    An *override* is only set when the current fallback path would
    actually be in effect — i.e. the Series is ongoing (``ends_at IS
    NULL``) AND the option carries a valid term_pass ``term_end_date``.
    Any other combination leaves the override null and lets the
    grants-model read path (B3+) inherit from the Series row.
    """
    if series is None:
        # Series row missing — cannot compute an override we could
        # confidently reason about. Leave null; the read path will
        # surface the missing target through its own error handling.
        return None
    if series.ends_at is not None:
        return None
    return _option_term_end_dt(option)


def _pathway_grant_valid_until_override(
    option: PaymentOption, series: EventSeries | None,
) -> datetime | None:
    """Compute ``valid_until_override`` for a Pathway grant derived
    from ``option``.

    Mirrors the current webhook's ``term_ends_at`` computation for
    the PathwayEntitlement it creates:

        # Bundled with a Series (option.grants_pathway_id set):
        term_ends_at = series.ends_at OR _po_term_end_dt(option)

        # Solo pathway-attached (no Series):
        term_ends_at = _po_term_end_dt(option)

    Making the Pathway grant self-contained on this value means
    fulfilment (B3+) never has to *infer* the effective end by
    looking at other grants on the same Option — which is
    important because Options will eventually be allowed to grant
    multiple experiences.

    ``valid_from_override`` is deliberately NOT computed here — a
    Pathway grant with ``valid_from_override IS NULL`` means
    "starts NOW at fulfilment time", which matches the current
    webhook (both bundled and solo pathway entitlements always get
    ``starts_at=now``).
    """
    if series is not None:
        # Bundled Pathway: Series end wins; else option's term_end_date
        # fallback; else perpetual.
        if series.ends_at is not None:
            return series.ends_at
        return _option_term_end_dt(option)
    # Solo pathway-attached: only term_pass options with term_end_date
    # cap the entitlement; every other pathway option produces a
    # perpetual entitlement (matches the current webhook exactly).
    return _option_term_end_dt(option)


def derive_grants_for_option(
    option: PaymentOption, db: Session,
) -> tuple[list[DerivedGrant], list[str]]:
    """Return ``(grants, warnings)`` for a single PaymentOption.

    Pure: reads the option and (only when needed) the referenced
    Series row for window computation. Does not touch any legacy
    columns. Never raises for malformed input — records warnings
    and returns an empty grants list instead.
    """
    grants: list[DerivedGrant] = []
    warnings: list[str] = []

    kind = option.attaches_to_kind
    target_id = option.attaches_to_id

    if not kind or not target_id:
        warnings.append(
            f"option {option.id!r} has empty attaches_to_kind or "
            f"attaches_to_id — cannot backfill; skipping."
        )
        return grants, warnings

    if kind == "pathway":
        grants.append(DerivedGrant(
            grant_kind="pathway",
            pathway_id=target_id,
            # Migration 109 relaxed the CHECK so Pathway grants can
            # carry their own window. Solo pathway-attached options
            # produce an entitlement whose ``ends_at`` is either the
            # option's term_pass ``term_end_date`` or NULL — captured
            # here as ``valid_until_override``.
            valid_until_override=_pathway_grant_valid_until_override(
                option, series=None,
            ),
        ))
        # Booking allowances on a pathway-attached term_pass option
        # (``sessions_per_week`` / ``total_sessions``) still cannot
        # be represented on a Pathway grant — those are Series-only
        # by design. Flag rows carrying them so they get inspected
        # during the later duplicate-cleanup phase.
        if (
            option.sessions_per_week is not None
            or option.total_sessions is not None
        ):
            warnings.append(
                f"option {option.id!r} is pathway-attached but carries "
                f"term_pass booking allowances (sessions_per_week / "
                f"total_sessions). Pathway grants do not carry these "
                f"Series-only fields; legacy AccessPass fulfilment "
                f"continues via the shadow columns until this row is "
                f"deliberately cleaned up."
            )
        return grants, warnings

    if kind == "event_series":
        series: EventSeries | None = db.get(EventSeries, target_id)
        if series is None:
            warnings.append(
                f"option {option.id!r} attaches to unknown event_series "
                f"{target_id!r}. Inserting the grant anyway; the read path "
                f"will surface the missing target."
            )
        grants.append(DerivedGrant(
            grant_kind="event_series",
            series_id=target_id,
            sessions_per_week=option.sessions_per_week,
            total_sessions=option.total_sessions,
            valid_from_override=None,   # always inherit from series.starts_at
            valid_until_override=_series_valid_until_override(series, option),
        ))
        if option.grants_pathway_id:
            # Bundled Pathway grant. Carries its own
            # ``valid_until_override`` so fulfilment does not have to
            # infer "use the Series in this Option" — Options will
            # eventually grant multiple experiences.
            #
            # ``valid_from_override`` stays NULL: the current webhook
            # gives bundled pathway entitlements ``starts_at=now``
            # regardless of Series start (immediate access even for
            # future terms), which is exactly what a Pathway grant
            # with a null ``valid_from_override`` will mean.
            grants.append(DerivedGrant(
                grant_kind="pathway",
                pathway_id=option.grants_pathway_id,
                valid_until_override=_pathway_grant_valid_until_override(
                    option, series=series,
                ),
            ))
        return grants, warnings

    warnings.append(
        f"option {option.id!r} has unknown attaches_to_kind {kind!r}; "
        f"skipping."
    )
    return grants, warnings


# ---------------------------------------------------------------------------
# Apply — idempotent walker over all Options
# ---------------------------------------------------------------------------


@dataclass
class BackfillReport:
    options_scanned: int = 0
    grants_created_pathway: int = 0
    grants_created_event_series: int = 0
    grants_created_gathering: int = 0
    grants_already_present: int = 0
    options_with_warnings: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "Backfill report",
            "---------------",
            f"  Options scanned:            {self.options_scanned}",
            f"  Grants created (pathway):   {self.grants_created_pathway}",
            f"  Grants created (series):    {self.grants_created_event_series}",
            f"  Grants created (gathering): {self.grants_created_gathering}",
            f"  Grants already present:     {self.grants_already_present}",
            f"  Options with warnings:      {self.options_with_warnings}",
        ]
        if self.warnings:
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        return "\n".join(lines)


def _load_existing_keys(db: Session) -> set[tuple[str, str, str]]:
    """(option_id, grant_kind, target_id) tuples currently in the
    grants table. Used as the idempotency skip set."""
    out: set[tuple[str, str, str]] = set()
    for g in db.query(PaymentOptionGrant).all():
        target = g.pathway_id or g.series_id or g.event_id
        if target is not None:
            out.add((g.payment_option_id, g.grant_kind, target))
    return out


def run_backfill(
    db: Session, *, dry_run: bool = False,
) -> BackfillReport:
    """Walk every PaymentOption; insert any missing grants.

    Idempotent: running any number of times converges to the same
    grant set. Never mutates PaymentOption columns. Never merges
    Options.

    Set ``dry_run=True`` to compute the report without writing.
    Session is *not* committed on dry-run.
    """
    report = BackfillReport()
    options = db.query(PaymentOption).order_by(PaymentOption.created_at).all()
    report.options_scanned = len(options)

    existing = _load_existing_keys(db)
    options_with_warnings = 0

    for opt in options:
        derived, warnings = derive_grants_for_option(opt, db)
        if warnings:
            options_with_warnings += 1
            report.warnings.extend(warnings)

        for d in derived:
            if d.target_id is None:  # pragma: no cover — validator forbids this
                continue
            key = (opt.id, d.grant_kind, d.target_id)
            if key in existing:
                report.grants_already_present += 1
                continue

            if not dry_run:
                db.add(PaymentOptionGrant(
                    payment_option_id=opt.id,
                    grant_kind=d.grant_kind,
                    pathway_id=d.pathway_id,
                    series_id=d.series_id,
                    event_id=d.event_id,
                    sessions_per_week=d.sessions_per_week,
                    total_sessions=d.total_sessions,
                    valid_from_override=d.valid_from_override,
                    valid_until_override=d.valid_until_override,
                ))

            existing.add(key)
            if d.grant_kind == "pathway":
                report.grants_created_pathway += 1
            elif d.grant_kind == "event_series":
                report.grants_created_event_series += 1
            elif d.grant_kind == "gathering":  # pragma: no cover — B2 never derives this
                report.grants_created_gathering += 1

    report.options_with_warnings = options_with_warnings

    if not dry_run:
        db.commit()

    return report


# ---------------------------------------------------------------------------
# CLI entry point — `python -m app.commerce.backfill_grants [--dry-run]`
# ---------------------------------------------------------------------------


def _cli() -> None:  # pragma: no cover — manual invocation only
    import argparse

    # Ensure every model that PaymentOption/PaymentOptionGrant
    # relationships reference is registered against Base.metadata
    # before we open a Session. Without this, standalone invocation
    # of the CLI fails to resolve string-referenced classes ("User",
    # "Pathway", etc.) that only get imported via app.main / alembic
    # env in normal use.
    import app.models.user           # noqa: F401
    import app.models.platform       # noqa: F401
    import app.models.payment        # noqa: F401
    import app.models.payment_option  # noqa: F401
    import app.models.payment_option_schedule  # noqa: F401
    import app.models.payment_option_grant     # noqa: F401
    import app.models.access_pass    # noqa: F401
    import app.models.creator_billing  # noqa: F401

    from app.core.database import SessionLocal

    parser = argparse.ArgumentParser(
        description=(
            "Backfill PaymentOptionGrant rows from legacy PaymentOption "
            "attachment fields. Idempotent; safe to rerun."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute the report without writing.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        report = run_backfill(db, dry_run=args.dry_run)
    print(report.summary())


if __name__ == "__main__":  # pragma: no cover
    _cli()
