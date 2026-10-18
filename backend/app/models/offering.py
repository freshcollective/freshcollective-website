"""Offerings — digital products a Collective sells to its members.

Phase A: the data foundation only. No creator interface, no member
interface, no checkout. Nothing reads these tables in a member-facing
path yet, and the feature flag
(``settings.offerings_enabled``, default ``False``) keeps it that way.

Three tables, and the shape of each is driven by a decision that was
made deliberately rather than inherited.

``offerings``
    One Collective, one Offering. A real foreign key rather than a
    polymorphic owner, because every Phase 1 decision says an Offering
    belongs somewhere specific. ``fulfilment_kind`` is the seam for
    physical goods later: a string, not an enum, matching
    ``PaymentOptionGrant.grant_kind``, so a new kind needs no enum
    migration.

``offering_files``
    Append-only. Replacing a file writes a new row and marks the old
    one superseded; it never overwrites a storage key. That is what
    makes "existing purchasers always get the current version" and
    "never accidentally overwrite an object still needed for recovery"
    the same mechanism rather than two competing ones.

``offering_entitlements``
    What somebody owns. Deliberately **not** folded into
    ``AccessPass``: that model is documented as the source of truth for
    booking/session/ticket allowances and carries allowance columns
    that mean nothing for a file, and its readers assume bookings.
    A separate table keeps the uniqueness guarantee meaningful.

Ownership survives the Collective
---------------------------------

The approved product decisions are that a purchaser keeps their files
when they leave a Collective, when a Collective closes, and when an
Offering is retired. Three mechanisms carry that, and none of them is
a membership check:

  1. Download authorisation reads the *entitlement*, never
     ``SpaceMembership``. See ``app/uploads/authorization.py``.
  2. ``offerings.space_id`` is ``ON DELETE RESTRICT`` and
     ``offering_entitlements.offering_id`` is ``ON DELETE RESTRICT``.
     The database refuses to destroy an Offering anyone owns, or a
     Collective that still has Offerings, whatever the application
     asks for.
  3. Collective *closure* is ``SpaceStatus.archived``, not deletion.
     ``delete_space`` only ever hard-deletes a pristine ``draft``
     Collective with no commerce footprint, and this phase adds
     Offerings to that eligibility gate so a creator gets the existing
     409 rather than a foreign-key error.

``RESTRICT`` rather than ``CASCADE`` is the one place this model
departs from the prevailing convention — ``offer_pages``,
``access_passes`` and ``payment_options`` all cascade from ``spaces``.
The departure is the point: those rows describe what a Collective
offers, and this one describes what a member already paid for.

Status does not gate ownership
------------------------------

``status`` controls whether an Offering can be *acquired*. It has no
bearing on whether an existing entitlement can download. A retired
Offering stops selling and keeps serving, which is the whole
distinction between stopping future sales and removing something
somebody has already bought.
"""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enumerated values
#
# Stored as strings with CHECK constraints rather than PostgreSQL enums.
# Adding a value to a PG enum is a migration that cannot run inside a
# transaction on older servers; a CHECK is a one-line additive change.
# Same reasoning as ``payment_option_grants.grant_kind``.
# ---------------------------------------------------------------------------


class OfferingStatus(str, enum.Enum):
    """Can this Offering be acquired?

    ``retired`` is the approved word for "stop selling, keep serving".
    There is deliberately no ``deleted``: an Offering that anyone owns
    cannot be removed, and one nobody owns can simply stay a draft.
    """

    draft = "draft"
    published = "published"
    retired = "retired"


class OfferingFulfilmentKind(str, enum.Enum):
    """How an acquirer receives what they bought.

    Phase 1 is ``digital_download`` only. The column exists now so that
    physical goods — explicitly out of scope — do not require reshaping
    the table that by then holds real purchase history.
    """

    digital_download = "digital_download"


class OfferingEntitlementSource(str, enum.Enum):
    """How ownership came about. Mirrors ``AccessPassSource`` so the two
    read the same way in reports and neither needs translating."""

    one_time_purchase = "one_time_purchase"
    free = "free"
    admin_grant = "admin_grant"


class OfferingEntitlementStatus(str, enum.Enum):
    """Whether ownership is currently honoured.

    Only two states, and that is a decision: a refund does **not**
    automatically revoke access (approved), so there is no
    ``refunded`` state here. Revocation is an explicit act, recorded
    with a reason.
    """

    active = "active"
    revoked = "revoked"


#: Values accepted by the ``offerings.status`` CHECK constraint.
OFFERING_STATUSES: tuple[str, ...] = tuple(s.value for s in OfferingStatus)

#: Values accepted by the ``offerings.fulfilment_kind`` CHECK constraint.
OFFERING_FULFILMENT_KINDS: tuple[str, ...] = tuple(
    k.value for k in OfferingFulfilmentKind
)

#: Values accepted by the entitlement CHECK constraints.
OFFERING_ENTITLEMENT_SOURCES: tuple[str, ...] = tuple(
    s.value for s in OfferingEntitlementSource
)
OFFERING_ENTITLEMENT_STATUSES: tuple[str, ...] = tuple(
    s.value for s in OfferingEntitlementStatus
)


# ---------------------------------------------------------------------------
# Offering
# ---------------------------------------------------------------------------


class Offering(Base):
    """A digital product belonging to one Collective."""

    __tablename__ = "offerings"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4()),
    )

    #: The owning Collective. ``RESTRICT`` — see the module docstring.
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: Who created it. ``SET NULL`` so a creator closing their account
    #: does not take the product — and therefore its purchasers' files
    #: — with them. The Collective remains the owner of record.
    created_by_user_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: URL-safe identifier, unique within the Collective — not globally,
    #: because two Collectives may each sell "morning-pages" and neither
    #: should have to care.
    slug: Mapped[str] = mapped_column(String(140), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    #: One or two lines for a card. Separate from ``description`` so a
    #: listing never has to truncate rich text to make a summary.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The detail page body. Rich text, stored as the block editor
    #: produces it elsewhere in the platform.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Cover art, stored as ``/api/uploads/offering-covers/...``.
    #:
    #: A deliberately *different* namespace from the downloadable files.
    #: A cover is shown to anyone who can see the Offering; a file is
    #: shown only to someone who owns it. Keeping them apart means no
    #: future caching or public-read change to covers can reach the
    #: paid assets — the mistake the ``place-artwork`` route would
    #: invite if generalised.
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OfferingStatus.draft.value,
        server_default=OfferingStatus.draft.value,
    )

    fulfilment_kind: Mapped[str] = mapped_column(
        String(30), nullable=False,
        default=OfferingFulfilmentKind.digital_download.value,
        server_default=OfferingFulfilmentKind.digital_download.value,
    )

    #: Set once, on first publish. Not cleared by unpublishing — it
    #: records when the thing first became available, which stays true.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    files: Mapped[list["OfferingFile"]] = relationship(
        "OfferingFile",
        back_populates="offering",
        cascade="all, delete-orphan",
        order_by="OfferingFile.sort_order",
    )
    entitlements: Mapped[list["OfferingEntitlement"]] = relationship(
        "OfferingEntitlement", back_populates="offering",
    )

    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="offerings_space_slug_unique"),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_offerings_status",
        ),
        CheckConstraint(
            "fulfilment_kind IN ('digital_download')",
            name="ck_offerings_fulfilment_kind",
        ),
        # The member-facing list is "published Offerings in this
        # Collective", so the composite leads with the column that
        # narrows most.
        Index("ix_offerings_space_status", "space_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"<Offering {self.id} {self.slug!r} {self.status}>"


# ---------------------------------------------------------------------------
# OfferingFile
# ---------------------------------------------------------------------------


class OfferingFile(Base):
    """One file in an Offering's bundle, past or present.

    **Append-only.** A row is never repointed at different bytes and a
    storage key is never reused. Two lifecycle events, one mechanism:

      * **Replaced** — ``superseded_at`` set, ``superseded_by_id``
        points at the row that took its place.
      * **Removed** — ``superseded_at`` set, ``superseded_by_id`` left
        NULL. Taken out of the bundle with nothing standing in for it.

    "The current bundle" is therefore ``superseded_at IS NULL``, which
    is the only predicate member download authorisation consults. A
    purchaser who acquired the Offering last year downloads what the
    bundle holds today, at no extra cost — the approved behaviour — and
    cannot reach last year's files, because those rows are superseded.

    Nothing here deletes an R2 object. Phase A deliberately keeps every
    superseded object for recovery and audit; who may read one, and
    when it may finally be removed, is a Phase B decision.
    """

    __tablename__ = "offering_files"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4()),
    )

    #: ``CASCADE`` is safe here and intended: a file row is part of its
    #: Offering, not a thing a member owns. The Offering itself is what
    #: ``RESTRICT`` protects, so a file row can only ever be cascaded
    #: away with an Offering nobody owns.
    offering_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("offerings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The R2 object key, e.g.
    #: ``offering-files/{offering_id}/{uuid}_{sanitised-name}``.
    #: Stored as the key, not as a URL: the serving route builds
    #: ``/api/uploads/{key}`` and the storage layer maps keys to
    #: buckets, so the same value works in filesystem and R2 mode.
    #:
    #: Globally unique. Two rows pointing at one object would make
    #: "supersede this file" ambiguous and could let a superseded row
    #: keep a live key alive.
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)

    #: What the creator uploaded it as. Shown to the member and used
    #: for the download filename; never used to locate the object.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Server-determined, not client-asserted. See
    #: ``app/services/offering_files.py``.
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)

    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Creator-controlled display order within the current bundle.
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    #: NULL means "in the current bundle". Any value means it is not,
    #: whatever the reason.
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    #: The row that replaced this one, when there is one. ``SET NULL``
    #: rather than ``CASCADE`` so the history cannot be unravelled by
    #: removing a later row.
    superseded_by_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("offering_files.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    offering: Mapped["Offering"] = relationship(
        "Offering", back_populates="files",
    )

    __table_args__ = (
        UniqueConstraint("storage_key", name="offering_files_storage_key_unique"),
        CheckConstraint("byte_size > 0", name="ck_offering_files_byte_size"),
        # A replacement pointer without a supersede timestamp would be a
        # file claiming to be both current and replaced. The converse is
        # legitimate — that is a removal.
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_at IS NOT NULL",
            name="ck_offering_files_supersede_shape",
        ),
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="ck_offering_files_no_self_supersede",
        ),
        # The hot query is "the current bundle for this Offering", which
        # is this index exactly.
        Index(
            "ix_offering_files_current",
            "offering_id", "sort_order",
            postgresql_where=superseded_at.is_(None),
        ),
    )

    @property
    def is_current(self) -> bool:
        """In the current downloadable bundle."""
        return self.superseded_at is None

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        state = "current" if self.is_current else "superseded"
        return f"<OfferingFile {self.id} {self.original_filename!r} {state}>"


# ---------------------------------------------------------------------------
# OfferingEntitlement
# ---------------------------------------------------------------------------


class OfferingEntitlement(Base):
    """One member's ownership of one Offering.

    This row, and nothing else, is what authorises a download. Not
    membership of the Collective, not the Offering's status, not
    whether the payment was later refunded. That is what makes the
    approved decisions — keep your files when you leave, when the
    Collective closes, when the product is retired, when you are
    refunded — a single rule rather than four special cases.

    Duplicate ownership
    -------------------

    A partial unique index allows at most one ``active`` row per
    ``(user, offering)``. Two things follow, both wanted:

      * A replayed webhook or a double-clicked acquire cannot create a
        second entitlement — the database refuses it, rather than the
        handler being trusted to notice.
      * Somebody whose access was explicitly revoked can acquire again
        later. A plain UNIQUE would have made the revoked row a
        permanent barrier, forcing a reactivate-in-place path and
        losing the record of what happened.
    """

    __tablename__ = "offering_entitlements"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4()),
    )

    #: ``CASCADE`` matches ``access_passes.user_id``: deleting a person
    #: deletes what they owned, because there is no longer anyone to
    #: own it.
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: ``RESTRICT`` — the database refuses to delete an Offering that
    #: anybody owns. The protection purchasers actually need.
    offering_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("offerings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: Denormalised from the Offering so ownership reporting and the
    #: central Library can attribute a purchase to a Collective without
    #: a join, and so attribution survives even if the Offering's own
    #: row is ever re-pointed. ``RESTRICT`` for the same reason as
    #: ``offerings.space_id``.
    space_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("spaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    source: Mapped[str] = mapped_column(String(30), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default=OfferingEntitlementStatus.active.value,
        server_default=OfferingEntitlementStatus.active.value,
    )

    #: The ledger row that paid for this, when one did. ``SET NULL``
    #: matches ``access_passes.payment_transaction_id``: the ledger is
    #: the financial source of truth and outlives this link, but losing
    #: the link must never destroy the entitlement.
    payment_transaction_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("payment_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: When ownership began. Distinct from ``created_at``: an
    #: administrative grant may record an earlier acquisition than the
    #: moment the row was written.
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )

    #: Free text, deliberately. Revocation is a human act — fraud,
    #: chargeback, a creator's request — and a closed set would invite
    #: picking the nearest wrong option.
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    offering: Mapped["Offering"] = relationship(
        "Offering", back_populates="entitlements",
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('one_time_purchase', 'free', 'admin_grant')",
            name="ck_offering_entitlements_source",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_offering_entitlements_status",
        ),
        # A revoked row must say when. An active row must not.
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL)"
            " OR (status = 'active' AND revoked_at IS NULL)",
            name="ck_offering_entitlements_revoked_shape",
        ),
        # At most one active entitlement per member per Offering. See
        # the class docstring for why this is partial.
        Index(
            "ux_offering_entitlements_active",
            "user_id", "offering_id",
            unique=True,
            postgresql_where=status == OfferingEntitlementStatus.active.value,
        ),
        # The central Library: "everything this member owns, newest
        # first", across every Collective.
        Index(
            "ix_offering_entitlements_user_acquired",
            "user_id", "acquired_at",
        ),
    )

    @property
    def is_active(self) -> bool:
        return self.status == OfferingEntitlementStatus.active.value

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return (
            f"<OfferingEntitlement {self.id} user={self.user_id} "
            f"offering={self.offering_id} {self.status}>"
        )


__all__ = [
    "Offering",
    "OfferingFile",
    "OfferingEntitlement",
    "OfferingStatus",
    "OfferingFulfilmentKind",
    "OfferingEntitlementSource",
    "OfferingEntitlementStatus",
    "OFFERING_STATUSES",
    "OFFERING_FULFILMENT_KINDS",
    "OFFERING_ENTITLEMENT_SOURCES",
    "OFFERING_ENTITLEMENT_STATUSES",
]
