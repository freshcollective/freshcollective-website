"""Record who last replaced a piece of platform artwork.

Revision ID: 134
Revises: 133
Create Date: 2026-09-20

Motivation
----------
``platform_artwork`` has always recorded *when* a slot last changed and
never *who* changed it. With the Fresh Collective brand roles now
sharing the table, "who replaced the logo, and when" is a question
World Management should be able to answer without reading the audit
log — a wrong logo is the kind of change someone needs to trace back
to a person.

Safety
------
* Additive: one nullable column, no backfill, no default. Every
  existing row keeps working and simply has no attribution, which is
  the truthful answer for artwork uploaded before this column existed.
* ``ON DELETE SET NULL`` rather than CASCADE — deleting an
  administrator must never delete the artwork they uploaded. The
  attribution is what goes, not the image.
* Reversible: ``downgrade`` drops the column. The artwork itself lives
  in ``image_url`` and is untouched either way.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "134"
down_revision = "133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_artwork",
        sa.Column("updated_by_user_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_platform_artwork_updated_by_user",
        "platform_artwork",
        "users",
        ["updated_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_platform_artwork_updated_by_user",
        "platform_artwork",
        type_="foreignkey",
    )
    op.drop_column("platform_artwork", "updated_by_user_id")
