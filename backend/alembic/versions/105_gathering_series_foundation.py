"""Gathering Series foundation — new EventSeries model + polymorphic PaymentOption + series-scoped AccessPass.

Revision ID: 105
Revises: 104
Create Date: 2026-08-11

Step 1 of the multi-target Offer Page work. Introduces the smallest
schema needed to represent EMBODY's real product: a defined term of
in-person sessions grouped as a first-class ``EventSeries``, sold via
existing ``PaymentOption`` machinery, granting an ``AccessPass`` that
gates + credits bookings across the term.

Design notes preserved for readers:

  * ``event_series`` is deliberately spare: id, space, slug, title,
    description, term window (starts_at + ends_at), status,
    cover_image_url. No membership table — events point at a series
    via ``events.series_id`` (nullable, SET NULL on series delete so a
    misdelete doesn't take the events with it).

  * ``events.recurrence_series_id`` (bulk-create UUID tag from
    migration 034) stays untouched. ``series_id`` is a **different**
    concept: it's the semantic term/cohort the event belongs to, not
    the tag that groups rows created together. A bulk create can now
    set both; a hand-created event can be added to an existing series
    without any bulk-create link.

  * ``PaymentOption`` gains ``attaches_to_kind`` + ``attaches_to_id``
    as a polymorphic pair. Existing rows are backfilled to
    ``('pathway', pathway_id)`` so every downstream query has a single
    consistent target field to read. ``pathway_id`` stays populated
    for backward compat during the transition; no code that reads
    ``pathway_id`` breaks. New rows for series-attached options
    leave ``pathway_id`` null and set ``attaches_to_kind='event_series'``,
    ``attaches_to_id=<series.id>``. Mirrors the ``offer_pages.target_*``
    pattern — no FK on ``attaches_to_id`` so future kinds slot in
    without a migration.

  * ``AccessPass`` gains ``eligible_series_id`` — the equivalent of
    ``eligible_pathway_id`` for series-scoped booking eligibility.
    Nullable, FK to event_series with ondelete SET NULL. Booking
    eligibility (see spaces/routes.py) now matches against EITHER
    ``eligible_pathway_id == event.booking_required_pathway_id`` OR
    ``eligible_series_id == event.series_id``, and enforces both ends
    of ``valid_from`` / ``valid_until`` so a future-term pass isn't
    usable early.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── event_series ────────────────────────────────────────────────────
    op.create_table(
        "event_series",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Series window. ``starts_at`` is required — every Series
        # begins on some date. ``ends_at`` is nullable so an ongoing
        # weekly circle can be a Series without pretending to end.
        # Finite terms (cohorts / EMBODY-style Terms) simply set both.
        # A ``term_pass`` PaymentOption attached to an ongoing series
        # can still bound its own AccessPass window via the option's
        # ``term_end_date``; the series alone doesn't have to.
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("ends_at",   sa.DateTime(timezone=False), nullable=True),
        # 'draft' | 'published' | 'archived'. String, not enum, mirrors
        # offer_pages.status — cheap to add new states later.
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default="draft",
        ),
        sa.Column("cover_image_url", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_unique_constraint(
        "event_series_space_slug_unique",
        "event_series",
        ["space_id", "slug"],
    )
    op.create_index(
        "ix_event_series_space_status",
        "event_series",
        ["space_id", "status"],
    )

    # ── events.series_id ────────────────────────────────────────────────
    op.add_column(
        "events",
        sa.Column(
            "series_id",
            sa.String(),
            sa.ForeignKey("event_series.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_events_series_id", "events", ["series_id"])

    # ── payment_options.attaches_to_kind + attaches_to_id ───────────────
    #
    # Add nullable, backfill from pathway_id, then flip to NOT NULL. This
    # is the standard "add-column safely" recipe — a concurrent writer
    # between the ADD and the ALTER SET NOT NULL would fail loudly, so
    # we don't need to write app code that tolerates NULL forever.
    op.add_column(
        "payment_options",
        sa.Column("attaches_to_kind", sa.String(30), nullable=True),
    )
    op.add_column(
        "payment_options",
        sa.Column("attaches_to_id", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE payment_options
           SET attaches_to_kind = 'pathway',
               attaches_to_id   = pathway_id
         WHERE pathway_id IS NOT NULL
           AND attaches_to_kind IS NULL
        """
    )
    # Any row without a pathway_id is a data anomaly — nothing in
    # today's schema writes such a row. Fail the migration loudly
    # rather than silently leaving those rows NULL.
    orphans = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM payment_options "
            "WHERE attaches_to_kind IS NULL OR attaches_to_id IS NULL"
        )
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"Migration 105: {orphans} payment_option row(s) have no pathway_id; "
            f"cannot backfill attaches_to_*. Investigate before retrying."
        )
    op.alter_column("payment_options", "attaches_to_kind", nullable=False)
    op.alter_column("payment_options", "attaches_to_id", nullable=False)
    op.create_index(
        "ix_payment_options_attaches_to",
        "payment_options",
        ["attaches_to_kind", "attaches_to_id"],
    )

    # ── access_passes.eligible_series_id ────────────────────────────────
    op.add_column(
        "access_passes",
        sa.Column(
            "eligible_series_id",
            sa.String(),
            sa.ForeignKey("event_series.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_access_passes_eligible_series",
        "access_passes",
        ["eligible_series_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_access_passes_eligible_series", table_name="access_passes")
    op.drop_column("access_passes", "eligible_series_id")

    op.drop_index("ix_payment_options_attaches_to", table_name="payment_options")
    op.drop_column("payment_options", "attaches_to_id")
    op.drop_column("payment_options", "attaches_to_kind")

    op.drop_index("ix_events_series_id", table_name="events")
    op.drop_column("events", "series_id")

    op.drop_index("ix_event_series_space_status", table_name="event_series")
    op.drop_constraint(
        "event_series_space_slug_unique", "event_series", type_="unique",
    )
    op.drop_table("event_series")
