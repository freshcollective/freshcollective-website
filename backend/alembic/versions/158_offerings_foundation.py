"""Offerings — the data foundation for digital products.

Revision ID: 158
Revises: 157
Create Date: 2026-10-18

Offerings Phase A. Three new tables and nothing else: no column is
altered, no constraint is dropped, no data is moved. Entirely additive,
and against empty tables, so it is safe to deploy while
``OFFERINGS_ENABLED`` is False — which is its default, and which is how
this will reach production.

Why RESTRICT where everything else cascades
-------------------------------------------

``offer_pages``, ``access_passes``, ``payment_options`` and the other
sixteen direct children of ``spaces`` all cascade. ``offerings`` does
not, and neither does ``offering_entitlements``. The difference is what
the rows mean: those tables describe what a Collective offers, and
these describe what a member has already paid for.

The approved product decisions are that a purchaser keeps their files
when they leave a Collective, when the Collective closes, and when the
Offering is retired. ``RESTRICT`` makes the database the last line of
that promise, so it holds even against a future code path that forgets.

Effect on the existing deletion lifecycle
-----------------------------------------

``delete_space`` (``app/creator/routes.py``) hard-deletes only a
pristine ``draft`` Collective whose six commerce counters are all zero;
closure of a real Collective is ``SpaceStatus.archived``, which deletes
nothing. So in practice no Collective that has ever sold anything can
reach the delete path at all.

The one gap this migration could have opened is a *draft* Collective
containing an Offering: previously nothing would have stopped the
delete, and with ``RESTRICT`` the database would raise a foreign-key
error and return a 500. The same change adds an Offering counter to
that endpoint's existing blocker list, so the creator gets the standard
409 instead. No other foreign-key relationship in the schema is
affected.

Deliberately NOT in this migration
----------------------------------

An ``offering_id`` column on ``payment_option_grants``. Adding it means
altering that table's CHECK constraint, which currently asserts that
exactly one of ``pathway_id`` / ``series_id`` / ``event_id`` is
populated and matches ``grant_kind``. That is a live commerce
constraint, nothing in Phase A exercises it, and Phase D is where an
Offering grant is actually created and testable. Raised for approval
rather than folded in here.

Forward/backward compatibility
------------------------------

The old application version does not know these tables exist and never
queries them, so fc-api and fc-web can deploy in either order. The new
version reads them only behind the feature flag. ``downgrade`` drops
the three tables in dependency order; it is safe only while they are
empty, which is stated rather than enforced because an Alembic
downgrade past real purchase history is not a thing we would do.
"""

from alembic import op
import sqlalchemy as sa


revision = "158"
down_revision = "157"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── offerings ─────────────────────────────────────────────────────
    op.create_table(
        "offerings",
        sa.Column("id", sa.String(), primary_key=True),
        # RESTRICT, not CASCADE. See the module docstring.
        sa.Column(
            "space_id",
            sa.String(),
            sa.ForeignKey("spaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # SET NULL so a creator closing their account does not take the
        # product — and therefore its purchasers' files — with them.
        sa.Column(
            "created_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_image_url", sa.String(length=500), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default="draft",
        ),
        # String rather than a PG enum so physical goods can slot in
        # later without an enum migration — the reasoning
        # ``payment_option_grants.grant_kind`` already follows.
        sa.Column(
            "fulfilment_kind", sa.String(length=30), nullable=False,
            server_default="digital_download",
        ),
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        # Unique per Collective, not globally: two Collectives may each
        # sell "morning-pages" and neither should have to care.
        sa.UniqueConstraint("space_id", "slug", name="offerings_space_slug_unique"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_offerings_status",
        ),
        sa.CheckConstraint(
            "fulfilment_kind IN ('digital_download')",
            name="ck_offerings_fulfilment_kind",
        ),
    )
    op.create_index("ix_offerings_space_id", "offerings", ["space_id"])
    op.create_index(
        "ix_offerings_created_by_user_id", "offerings", ["created_by_user_id"],
    )
    # The member-facing list is "published Offerings in this Collective".
    op.create_index(
        "ix_offerings_space_status", "offerings", ["space_id", "status"],
    )

    # ── offering_files ────────────────────────────────────────────────
    op.create_table(
        "offering_files",
        sa.Column("id", sa.String(), primary_key=True),
        # CASCADE is right here: a file row is part of its Offering, not
        # something a member owns. The Offering is what RESTRICT
        # protects, so these can only cascade away with an Offering
        # nobody owns.
        sa.Column(
            "offering_id",
            sa.String(),
            sa.ForeignKey("offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0",
        ),
        # NULL means "in the current downloadable bundle". Any value
        # means it is not, whichever way it left.
        sa.Column("superseded_at", sa.DateTime(timezone=False), nullable=True),
        # Populated for a replacement, NULL for a removal — one
        # mechanism, two lifecycle events, told apart.
        sa.Column(
            "superseded_by_id",
            sa.String(),
            sa.ForeignKey("offering_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        # One row per object. Two rows naming one key would make
        # "supersede this file" ambiguous and could let a superseded row
        # keep a live key reachable.
        sa.UniqueConstraint(
            "storage_key", name="offering_files_storage_key_unique",
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_offering_files_byte_size"),
        # A replacement pointer without a timestamp would be a file
        # claiming to be both current and replaced.
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_at IS NOT NULL",
            name="ck_offering_files_supersede_shape",
        ),
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="ck_offering_files_no_self_supersede",
        ),
    )
    op.create_index(
        "ix_offering_files_offering_id", "offering_files", ["offering_id"],
    )
    # The hot read is "the current bundle for this Offering", in order.
    op.create_index(
        "ix_offering_files_current",
        "offering_files",
        ["offering_id", "sort_order"],
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    # ── offering_entitlements ─────────────────────────────────────────
    op.create_table(
        "offering_entitlements",
        sa.Column("id", sa.String(), primary_key=True),
        # CASCADE matches access_passes.user_id: no person, no owner.
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT — the database refuses to delete an Offering anybody
        # owns. This is the protection purchasers actually need.
        sa.Column(
            "offering_id",
            sa.String(),
            sa.ForeignKey("offerings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Denormalised so the central Library can attribute ownership to
        # a Collective without a join.
        sa.Column(
            "space_id",
            sa.String(),
            sa.ForeignKey("spaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False,
            server_default="active",
        ),
        # SET NULL matches access_passes: the ledger is the financial
        # source of truth, and losing the link must never destroy the
        # entitlement.
        sa.Column(
            "payment_transaction_id",
            sa.String(),
            sa.ForeignKey("payment_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "acquired_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source IN ('one_time_purchase', 'free', 'admin_grant')",
            name="ck_offering_entitlements_source",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_offering_entitlements_status",
        ),
        # A revoked row must say when; an active row must not.
        sa.CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL)"
            " OR (status = 'active' AND revoked_at IS NULL)",
            name="ck_offering_entitlements_revoked_shape",
        ),
    )
    op.create_index(
        "ix_offering_entitlements_user_id", "offering_entitlements", ["user_id"],
    )
    op.create_index(
        "ix_offering_entitlements_offering_id",
        "offering_entitlements", ["offering_id"],
    )
    op.create_index(
        "ix_offering_entitlements_space_id", "offering_entitlements", ["space_id"],
    )
    op.create_index(
        "ix_offering_entitlements_payment_transaction_id",
        "offering_entitlements", ["payment_transaction_id"],
    )
    # At most one ACTIVE entitlement per member per Offering.
    #
    # Partial rather than a plain UNIQUE, and the difference is the
    # point. It blocks the duplicate that matters — a replayed webhook
    # or a double-clicked acquire creating a second live entitlement —
    # while still allowing somebody whose access was explicitly revoked
    # to acquire again later. A full UNIQUE would have made the revoked
    # row a permanent barrier and forced a reactivate-in-place path,
    # losing the record of what happened.
    op.create_index(
        "ux_offering_entitlements_active",
        "offering_entitlements",
        ["user_id", "offering_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    # The central Library: everything this member owns, newest first.
    op.create_index(
        "ix_offering_entitlements_user_acquired",
        "offering_entitlements",
        ["user_id", "acquired_at"],
    )


def downgrade() -> None:
    # Dependency order: entitlements and files both reference offerings.
    # Safe only while these tables are empty.
    op.drop_table("offering_entitlements")
    op.drop_table("offering_files")
    op.drop_table("offerings")
