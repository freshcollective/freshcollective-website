"""Physical Locations — admin fields on Place.

Revision ID: 093
Revises: 092
Create Date: 2026-07-31

Extends the Place model (real-world Physical Locations, as used
by Discover Places) with the fields needed by the new World
Management admin surface:

  * ``hero_artwork_url``     — curated artwork uploaded by an
                                administrator. Takes precedence
                                over the deterministic fallback
                                gradient on Discover Places when
                                present.
  * ``artwork_alt_text``     — accessible alt text for the
                                uploaded artwork.
  * ``artwork_focal_x``      — normalised horizontal focal point
                                (0.0–1.0, default 0.5).
  * ``artwork_focal_y``      — normalised vertical focal point
                                (0.0–1.0, default 0.5).
  * ``admin_note``           — free-text internal note. Never
                                surfaced publicly. Distinct from
                                the member-facing ``blurb``.

Also relaxes the ``places_status_check`` constraint to include
the two new lifecycle states named by the admin surface:

  * ``draft``    — administrator is composing but hasn't
                    published; never appears anywhere public.
  * ``active``   — visible on Discover Places (unchanged).
  * ``hidden``   — preserved for links / history but not
                    surfaced publicly (unchanged).
  * ``archived`` — retired. Never surfaced. Still queryable in
                    admin.

Existing rows keep their current status; the migration only
expands the allowed vocabulary.

See docs/foundations/discovery-connection-belonging-location-model.md.
"""

from alembic import op
import sqlalchemy as sa


revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Artwork + focal-point + admin note.
    op.add_column(
        "places",
        sa.Column("hero_artwork_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "places",
        sa.Column("artwork_alt_text", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "places",
        sa.Column(
            "artwork_focal_x",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
    )
    op.add_column(
        "places",
        sa.Column(
            "artwork_focal_y",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
    )
    op.add_column(
        "places",
        sa.Column("admin_note", sa.Text(), nullable=True),
    )

    # Relax the status CHECK to include 'draft' and 'archived'.
    # Rewriting the constraint rather than ALTERing it keeps this
    # portable across Postgres versions.
    op.drop_constraint("places_status_check", "places", type_="check")
    op.create_check_constraint(
        "places_status_check",
        "places",
        "status IN ('draft', 'active', 'hidden', 'archived')",
    )


def downgrade() -> None:
    op.drop_constraint("places_status_check", "places", type_="check")
    op.create_check_constraint(
        "places_status_check",
        "places",
        "status IN ('active', 'hidden')",
    )

    op.drop_column("places", "admin_note")
    op.drop_column("places", "artwork_focal_y")
    op.drop_column("places", "artwork_focal_x")
    op.drop_column("places", "artwork_alt_text")
    op.drop_column("places", "hero_artwork_url")
