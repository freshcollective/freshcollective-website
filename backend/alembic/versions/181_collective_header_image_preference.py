"""Which image welcomes people into a Collective.

Revision ID: 181
Revises: 180
Create Date: 2026-11-05

A Collective has two visual identities: the creator's own brand, and
its home within Fresh Collective. Until now the second always won —
every header, card and signup page read Location artwork first and the
creator's uploaded banner only as a fallback. A creator who uploaded a
banner saw it nowhere.

This column is the creator's answer to "which one welcomes people in":

    'location'  — the Atlas Location artwork (the default)
    'banner'    — the creator's own uploaded ``cover_image_url``

Deliberately a preference rather than a derived rule. "Has a banner"
cannot stand in for "wants the banner": a Collective may hold an
uploaded banner from before this existed, and its appearance must not
change because a migration ran. So every existing row gets
``'location'`` — the behaviour they have today — and the stored
``cover_image_url`` is left exactly where it is, ready to be selected
without a re-upload.

Nothing here touches World Artwork. ``island_artwork_*`` and the Atlas
Location tables are not read or written by this migration or by the
code that uses the column; the artwork is still curated exclusively
through Atlas Locations, as the Atlas requires.
"""

from alembic import op
import sqlalchemy as sa


revision = "181"
down_revision = "180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column(
            "header_image_preference",
            sa.String(20),
            nullable=False,
            server_default="location",
        ),
    )
    # No backfill to 'banner' for Collectives that already hold a
    # cover image. That would be the one thing this must not do —
    # changing how an existing Collective looks because a feature
    # shipped. The creator opts in.


def downgrade() -> None:
    op.drop_column("spaces", "header_image_preference")
