"""PaymentOptionGrant — one-to-many "what this Option grants" layer.

Introduced in migration 108. Replaces the polymorphic
``PaymentOption.attaches_to_kind`` / ``attaches_to_id`` +
``grants_pathway_id`` shape with a proper join so a single
Collective-level Payment Option can grant any combination of:

  * one or more Pathways (``grant_kind='pathway'``)
  * one or more Gathering Series (``grant_kind='event_series'``)
  * one or more standalone Gatherings (``grant_kind='gathering'``)

Backfill from the legacy columns lands in B2; nothing reads from
this table yet in B1. The legacy columns on ``PaymentOption`` stay
in place through the transition and are retained until the new
model has been proven in real Creator use (destructive drop is
deliberately not scheduled here).

Design decisions worth flagging:

  * ``ON DELETE CASCADE`` from Option → grants: deleting an Option
    (only ever a never-published draft, per the archive-not-delete
    rule) cleans up its own grants. Options that ever had
    transactions cannot be deleted, so no history is lost.
  * ``ON DELETE RESTRICT`` from Pathway / EventSeries / Event →
    grants: hard-deleting an experience that any Option still
    grants raises IntegrityError. The Creator must first remove
    the experience from those Options (application-layer preflight
    on the experience-delete endpoints belongs to a later commit).
  * ``sessions_per_week`` / ``total_sessions`` / window overrides
    live on the grant, not the Option — Awaken and Empower can
    grant the *same* Series with different booking allowances.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.payment_option import PaymentOption


# Kinds mirror the wire values used by OfferPage.target_kind for
# consistency. String, not an enum — future kinds (bundle, add-on)
# can slot in without an enum migration.
GRANT_KIND_PATHWAY = "pathway"
GRANT_KIND_EVENT_SERIES = "event_series"
GRANT_KIND_GATHERING = "gathering"


class PaymentOptionGrant(Base):
    __tablename__ = "payment_option_grants"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4()),
    )
    payment_option_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("payment_options.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_kind: Mapped[str] = mapped_column(String(30), nullable=False)

    # Exactly one of these three is populated per row, matched to
    # ``grant_kind`` by the CHECK constraint below. Application code
    # can rely on the invariant.
    pathway_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("pathways.id", ondelete="RESTRICT"),
        nullable=True,
    )
    series_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("event_series.id", ondelete="RESTRICT"),
        nullable=True,
    )
    event_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # ── Series-only booking allowance ──────────────────────────────────
    # Only meaningful when ``grant_kind='event_series'`` — the CHECK
    # constraint below forbids populating these for pathway/gathering
    # grants. Null means "no cap" (unbounded within the pass window).
    sessions_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Series-only pass window overrides ──────────────────────────────
    # When null, the AccessPass created at purchase inherits its
    # window from the Series (``series.starts_at`` / ``series.ends_at``).
    # When set, the grant's override wins — same precedence rule the
    # webhook has always applied. Only allowed for event_series grants.
    valid_from_override: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    valid_until_override: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    payment_option: Mapped["PaymentOption"] = relationship(
        "PaymentOption", back_populates="grants",
    )

    __table_args__ = (
        # Exactly-one-target invariant. The kind string and the
        # populated FK column must match; the other two FKs must be
        # null. Postgres enforces this so any code path (backfill,
        # future Creator UI, ad-hoc script) writing a malformed row
        # gets a hard IntegrityError.
        CheckConstraint(
            "(grant_kind = 'pathway'      AND pathway_id IS NOT NULL "
            "  AND series_id IS NULL AND event_id IS NULL)"
            " OR (grant_kind = 'event_series' AND series_id IS NOT NULL "
            "  AND pathway_id IS NULL AND event_id IS NULL)"
            " OR (grant_kind = 'gathering'    AND event_id IS NOT NULL "
            "  AND pathway_id IS NULL AND series_id IS NULL)",
            name="payment_option_grants_target_matches_kind",
        ),
        # Series-only fields cannot be populated for pathway / gathering
        # grants. Keeps grant rows honest about which kind they are.
        CheckConstraint(
            "(grant_kind = 'event_series') OR ("
            "  sessions_per_week IS NULL "
            "  AND total_sessions IS NULL "
            "  AND valid_from_override IS NULL "
            "  AND valid_until_override IS NULL)",
            name="payment_option_grants_series_fields_only_for_series",
        ),
        # A single Option should not grant the same target twice —
        # deduplicated at the DB level rather than leaving it to
        # application code. Partial indexes because each target column
        # is nullable.
        Index(
            "uq_payment_option_grants_option_pathway",
            "payment_option_id", "pathway_id",
            unique=True,
            postgresql_where=(pathway_id.isnot(None)),
        ),
        Index(
            "uq_payment_option_grants_option_series",
            "payment_option_id", "series_id",
            unique=True,
            postgresql_where=(series_id.isnot(None)),
        ),
        Index(
            "uq_payment_option_grants_option_event",
            "payment_option_id", "event_id",
            unique=True,
            postgresql_where=(event_id.isnot(None)),
        ),
        # Reverse-lookup indexes: "which Options grant this Pathway /
        # Series / Event?" is a hot query for the Creator UI (Pathway
        # settings "referenced by these Payment Options" panel) and the
        # public Offer Page snapshot builder.
        Index(
            "ix_payment_option_grants_pathway",
            "pathway_id",
            postgresql_where=(pathway_id.isnot(None)),
        ),
        Index(
            "ix_payment_option_grants_series",
            "series_id",
            postgresql_where=(series_id.isnot(None)),
        ),
        Index(
            "ix_payment_option_grants_event",
            "event_id",
            postgresql_where=(event_id.isnot(None)),
        ),
    )
