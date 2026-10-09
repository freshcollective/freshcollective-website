"""An optional heading on media blocks.

Revision ID: 151
Revises: 150
Create Date: 2026-10-09

Round 1, item 7. Video, audio and file-download blocks gain an optional
heading so a creator can title a recording or a worksheet without
spending the caption on it.

Why a new column rather than reusing ``label`` or ``caption``
-------------------------------------------------------------

Neither field is free across all three types. ``video_embed`` and
``audio`` have ``label`` spare, but on ``file_download`` ``label`` is
already the download button's text; ``caption`` is spare there but is the
figcaption on the other two. Reusing them would have put the heading in
``label`` for two block types and ``caption`` for the third — a trap for
the next person — and, more seriously, it would have started *rendering*
fields that are currently written but never displayed. Any published
block carrying a stray value in one of them would have had that text
appear on a live page the moment this shipped.

A new column cannot do that. Nothing has ever written to it, so every
existing block reads ``NULL`` and renders exactly as it does today.

Backward compatibility
----------------------

* Additive and nullable, with no server default and no backfill. The
  ``ALTER TABLE ... ADD COLUMN`` is metadata-only on PostgreSQL 11+ for
  a nullable column with no default, so it does not rewrite either
  table and takes a brief ACCESS EXCLUSIVE lock rather than a long one.
* Safe to apply before the application code that reads it: the column is
  simply unused.
* Safe to leave in place if the application is rolled back: older code
  never selects it, and ``INSERT``s that omit it get ``NULL``.
* ``String(300)`` matches ``label``'s width, so the editor's existing
  field-length conventions carry over.

Downgrade drops the column, which discards any headings creators have
written by then. That is a real loss of authored content rather than a
neutral rollback, so prefer rolling back the application and leaving the
column in place.
"""

from alembic import op
import sqlalchemy as sa


revision = "151"
down_revision = "150"
branch_labels = None
depends_on = None

# Both tables carry the same block vocabulary and the same columns, and
# both are rendered by their own component, so the heading has to exist
# on both or About pages could not offer it.
_TABLES = ("pathway_step_blocks", "pathway_about_blocks")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("heading", sa.String(length=300), nullable=True),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "heading")
