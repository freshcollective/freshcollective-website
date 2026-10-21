"""An Offering remembers which shared cover it chose, not its URL.

Revision ID: 163
Revises: 162
Create Date: 2026-10-21

One nullable column on ``offerings``. Additive: nothing altered, nothing
dropped, no data moved, no constraint touched.

Why a key and not a URL
-----------------------

Default Offering artwork moves into World Settings → World Artwork, the
same manager that already owns the dashboard tiles, the homepage scenes
and the member cards. That system stores an uploaded image under a
generated filename, so **replacing a shared default changes its URL**.

``offerings.cover_image_url`` previously held the chosen default's URL
directly. Under the new arrangement that would mean an admin replacing
the "Audio & meditations" artwork left every Offering that had chosen it
pointing at a deleted object — the exact failure the requirement
"changing a shared default must update Offerings that use that default"
exists to prevent.

So the Offering stores the **category key** it chose, and the URL is
resolved at read time from ``platform_artwork``. A replacement is then
picked up by every Offering using that category, with no backfill and
nothing to keep in step.

The two columns, and which wins
-------------------------------

``default_cover_key``   the shared category the creator chose
``cover_image_url``     a cover the creator uploaded themselves

A creator upload wins. That is the stated rule — "if a creator uploads
their own cover, it overrides the shared default" — and it is why the
two live in separate columns rather than one overloaded field: the
Offering can remember its category *and* carry a custom image, so
removing the custom image falls back to the category rather than to
nothing.

Both nullable, and both null is legitimate: a draft that has not reached
the Cover tab yet.

No CHECK constraint, deliberately
---------------------------------

The valid keys are the five in ``services.offering_covers``, and the
column is validated against that manifest in the application. A CHECK
would mean a migration every time a sixth category is added, which is
the thing ``payment_options.attaches_to_kind`` already avoids for the
same reason ("no FK ... so future kinds slot in without a migration").

The trade is explicit: a hand-written row could carry an unknown key.
Resolution treats an unknown key as "no shared artwork" and falls back
to the placeholder, so the failure is a missing image rather than a
broken one.

Existing data
-------------

Production holds **zero** ``offerings`` rows, so there is nothing to
migrate: no Offering has chosen a default, and no stored
``cover_image_url`` points at the retired ``offering-covers/`` namespace.
The column therefore starts NULL everywhere and no backfill exists or
is needed. Had there been rows, the backfill would have been a reverse
lookup from the old default URL to its category key — recorded here
because the next environment restored from an older dump may need it.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "163"
down_revision = "162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offerings",
        sa.Column("default_cover_key", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("offerings", "default_cover_key")
