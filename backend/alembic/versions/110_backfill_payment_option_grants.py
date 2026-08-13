"""B2 — backfill PaymentOptionGrant rows from legacy PaymentOption
attachment fields.

Revision ID: 110
Revises: 109
Create Date: 2026-08-13

Data-only migration. Deliberately **self-contained**: does not
import ``app.commerce.backfill_grants`` (or any application
helper) so that replaying this migration in the future produces
the same transformation regardless of any later refactor of the
Python helper. The reusable helper still exists for CLI / test /
future-development use; this file freezes the historical rules.

Rules (must stay identical to
``app/commerce/backfill_grants.py::derive_grants_for_option`` at
the time of writing):

  1. ``attaches_to_kind='pathway'``
     → one Pathway grant with
       ``valid_until_override = combine(option.term_end_date, min.time())``
       when the option is a ``term_pass`` with a ``term_end_date``,
       else NULL.

  2. ``attaches_to_kind='event_series'``
     → one Series grant with the option's
       ``sessions_per_week`` / ``total_sessions``;
       ``valid_from_override`` = NULL (always inherits
                                       series.starts_at);
       ``valid_until_override`` = the option's ``term_end_date``
         only when the Series is ongoing (``series.ends_at IS NULL``)
         AND the option is a ``term_pass`` with a ``term_end_date``,
         else NULL (inherits series.ends_at or perpetual).

  3. Additionally, when the Series-attached option has
     ``grants_pathway_id`` set
     → one bundled Pathway grant with
       ``valid_from_override`` = NULL (Pathway grants with NULL
                                       ``valid_from_override`` mean
                                       "starts NOW at fulfilment",
                                       matching the current webhook);
       ``valid_until_override`` = series.ends_at, else the option's
         ``term_end_date`` when term_pass, else NULL.

Idempotency: each INSERT filters via ``NOT EXISTS`` on the same
(option_id, grant_kind, target_id) key the partial unique indexes
use. Safe to re-run.

Nothing on ``payment_options`` is mutated; this migration only
INSERTs into ``payment_option_grants``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "110"
down_revision = "109"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Frozen derivation rules — the helper below is inlined in this file
# on purpose. Do not import from app.commerce here.
# ---------------------------------------------------------------------------


def _option_term_end_dt(payment_type: str, term_end_date):
    if term_end_date is None:
        return None
    if payment_type != "term_pass":
        return None
    return datetime.combine(term_end_date, datetime.min.time())


def _series_valid_until_override(
    series_ends_at, payment_type: str, term_end_date,
):
    if series_ends_at is not None:
        return None
    return _option_term_end_dt(payment_type, term_end_date)


def _pathway_grant_valid_until_override(
    series_ends_at, series_present: bool,
    payment_type: str, term_end_date,
):
    if series_present:
        if series_ends_at is not None:
            return series_ends_at
        return _option_term_end_dt(payment_type, term_end_date)
    return _option_term_end_dt(payment_type, term_end_date)


def upgrade() -> None:
    conn = op.get_bind()

    # Snapshot every PaymentOption row together with the Series row
    # its ``attaches_to_id`` points at (LEFT JOIN so we still see
    # options that reference a stale Series id).
    rows = conn.execute(sa.text(
        """
        SELECT
            po.id AS option_id,
            po.attaches_to_kind AS kind,
            po.attaches_to_id AS target_id,
            po.grants_pathway_id AS grants_pathway_id,
            po.sessions_per_week AS sessions_per_week,
            po.total_sessions AS total_sessions,
            po.term_end_date AS term_end_date,
            po.payment_type AS payment_type,
            es.ends_at AS series_ends_at,
            (es.id IS NOT NULL) AS series_present
        FROM payment_options po
        LEFT JOIN event_series es
               ON es.id = po.attaches_to_id
              AND po.attaches_to_kind = 'event_series'
        ORDER BY po.created_at
        """
    )).mappings().all()

    # Existing grant keys — idempotency skip set.
    existing = set()
    for g in conn.execute(sa.text(
        "SELECT payment_option_id, grant_kind, pathway_id, series_id, event_id "
        "FROM payment_option_grants"
    )).mappings().all():
        target = g["pathway_id"] or g["series_id"] or g["event_id"]
        if target is not None:
            existing.add((g["payment_option_id"], g["grant_kind"], target))

    now = datetime.utcnow()
    to_insert: list[dict] = []

    def _stage(**row):
        target = row["pathway_id"] or row["series_id"] or row["event_id"]
        key = (row["payment_option_id"], row["grant_kind"], target)
        if key in existing:
            return
        existing.add(key)
        row["id"] = str(uuid4())
        row["position"] = 0
        row["created_at"] = now
        row["updated_at"] = now
        to_insert.append(row)

    for r in rows:
        kind = r["kind"]
        target_id = r["target_id"]
        if not kind or not target_id:
            # Malformed row — the helper reports a warning; the
            # migration silently skips (there is nothing to insert).
            continue

        if kind == "pathway":
            _stage(
                payment_option_id=r["option_id"],
                grant_kind="pathway",
                pathway_id=target_id,
                series_id=None,
                event_id=None,
                sessions_per_week=None,
                total_sessions=None,
                valid_from_override=None,
                valid_until_override=_pathway_grant_valid_until_override(
                    series_ends_at=None,
                    series_present=False,
                    payment_type=r["payment_type"],
                    term_end_date=r["term_end_date"],
                ),
            )
        elif kind == "event_series":
            _stage(
                payment_option_id=r["option_id"],
                grant_kind="event_series",
                pathway_id=None,
                series_id=target_id,
                event_id=None,
                sessions_per_week=r["sessions_per_week"],
                total_sessions=r["total_sessions"],
                valid_from_override=None,
                valid_until_override=_series_valid_until_override(
                    series_ends_at=r["series_ends_at"],
                    payment_type=r["payment_type"],
                    term_end_date=r["term_end_date"],
                ),
            )
            if r["grants_pathway_id"]:
                _stage(
                    payment_option_id=r["option_id"],
                    grant_kind="pathway",
                    pathway_id=r["grants_pathway_id"],
                    series_id=None,
                    event_id=None,
                    sessions_per_week=None,
                    total_sessions=None,
                    valid_from_override=None,
                    valid_until_override=_pathway_grant_valid_until_override(
                        series_ends_at=r["series_ends_at"],
                        series_present=bool(r["series_present"]),
                        payment_type=r["payment_type"],
                        term_end_date=r["term_end_date"],
                    ),
                )
        # Unknown kind: silently skip (helper emits a warning).

    if to_insert:
        conn.execute(
            sa.text(
                "INSERT INTO payment_option_grants ("
                "  id, payment_option_id, grant_kind,"
                "  pathway_id, series_id, event_id,"
                "  sessions_per_week, total_sessions,"
                "  valid_from_override, valid_until_override,"
                "  position, created_at, updated_at"
                ") VALUES ("
                "  :id, :payment_option_id, :grant_kind,"
                "  :pathway_id, :series_id, :event_id,"
                "  :sessions_per_week, :total_sessions,"
                "  :valid_from_override, :valid_until_override,"
                "  :position, :created_at, :updated_at"
                ")"
            ),
            to_insert,
        )


def downgrade() -> None:
    # Safe because B2 is the sole source of ``payment_option_grants``
    # rows. Any later migration that becomes a writer must supersede
    # this rule with its own downgrade.
    op.execute("DELETE FROM payment_option_grants")
