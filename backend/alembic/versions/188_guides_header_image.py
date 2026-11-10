"""An optional header image for the Guides index.

Two nullable columns on the one ``guide_settings`` row. Additive, and
empty is the shipped state: with no URL the /guides header is plain
navy, exactly as it is today.

Alt text is paired with the image by a CHECK rather than by the form
alone — the form is a UX constraint and any direct HTTP call bypasses
it, and a decorative-looking header image that is actually the page's
subject deserves a description. The same shape migration 187 uses for
a Guide's own hero.

Revision ID: 188
Revises: 187
"""

from alembic import op
import sqlalchemy as sa

revision = "188"
down_revision = "187"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guide_settings",
        sa.Column("header_image_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "guide_settings",
        sa.Column("header_image_alt", sa.String(length=300), nullable=True),
    )
    op.create_check_constraint(
        "ck_guide_settings_header_alt_present",
        "guide_settings",
        "header_image_url IS NULL "
        "OR (header_image_alt IS NOT NULL AND length(trim(header_image_alt)) > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_guide_settings_header_alt_present", "guide_settings", type_="check",
    )
    op.drop_column("guide_settings", "header_image_alt")
    op.drop_column("guide_settings", "header_image_url")
