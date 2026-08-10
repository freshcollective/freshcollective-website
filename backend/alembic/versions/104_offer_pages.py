"""Offer Pages — public presentation layer over existing sellables.

Revision ID: 104
Revises: 103
Create Date: 2026-08-10

Introduces ``offer_pages`` — the storage side of Fresh Collective's
first commercial presentation layer. An Offer Page owns hero,
invitation copy, what's-included, practical details and FAQs; it
points at a *target* sellable (in V1: a Pathway) via a
``(target_kind, target_id)`` pair. Commerce plumbing stays where it
is — Offer Pages never create PurchaseIntents or call Stripe.

Design notes preserved for readers:

  * ``target_id`` is a plain string with **no FK constraint**. This
    is deliberate: it lets future target kinds (gathering, space
    membership, bundle) slot in without a migration and leaves the
    door open for cross-Collective offers when we're ready to relax
    the same-space check.

  * ``sections_config`` is a JSONB blob rather than child tables in
    V1. Sections have known shapes and the "structured creative
    freedom" design intent asks Fresh Collective to own the layout;
    typed inputs per section are enough and let us iterate the shape
    without migrations. If FAQs or testimonials outgrow the blob we
    extract them then — same pattern PathwayAboutBlock followed.

  * ``published_at`` is set the first time an Offer Page flips to
    ``status='published'`` and is never cleared. Slug is locked
    permanently once ``published_at`` is non-null so a link a
    Creator has shared publicly always resolves to the same page
    (or a 404 for members if it's since been unpublished/archived,
    which is a legitimate state — but the URL doesn't get reassigned
    to a different page under them). Redirect/history infrastructure
    is deferred.

  * ``status`` values: draft | published | archived. Public read
    returns 404 for anything other than published (owners see all
    statuses through the standard owner-visibility path).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "104"
down_revision = "103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_pages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("promise", sa.Text(), nullable=True),
        sa.Column("hero_image_url", sa.String(500), nullable=True),
        # Target — the sellable this Offer Page presents. No FK on
        # target_id so future kinds can slot in without a migration.
        sa.Column("target_kind", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        # 'draft' | 'published' | 'archived'. String, not enum, to
        # avoid the ALTER-TYPE dance when we later add states like
        # 'coming_soon' or 'hidden'.
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "sections_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Set the first time the page publishes; never cleared. Slug
        # is permanently locked once this is non-null.
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
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
        "offer_pages_space_slug_unique",
        "offer_pages",
        ["space_id", "slug"],
    )
    op.create_index(
        "ix_offer_pages_space_status",
        "offer_pages",
        ["space_id", "status"],
    )
    op.create_index(
        "ix_offer_pages_target",
        "offer_pages",
        ["target_kind", "target_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_offer_pages_target", table_name="offer_pages")
    op.drop_index("ix_offer_pages_space_status", table_name="offer_pages")
    op.drop_constraint(
        "offer_pages_space_slug_unique", "offer_pages", type_="unique",
    )
    op.drop_table("offer_pages")
