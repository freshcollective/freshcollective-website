"""EventSeries: add ``published_at`` — never-cleared publish marker.

Revision ID: 106
Revises: 105
Create Date: 2026-08-11

Mirrors the ``offer_pages.published_at`` pattern (migration 104): set
the first time a Series transitions to ``status='published'`` and
never cleared. Enables a lifecycle rule where only a Series that has
never been published (i.e. ``published_at IS NULL`` AND
``status='draft'``) is safe to hard-delete — anything the public may
have ever seen is archived instead so historical AccessPass /
EventBooking rows keep a resolvable target for their ``eligible_series_id``.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "106"
down_revision = "105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_series",
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_series", "published_at")
