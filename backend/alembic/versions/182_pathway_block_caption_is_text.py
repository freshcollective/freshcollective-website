"""A caption is not a label, so stop sizing it like one.

Revision ID: 182
Revises: 181
Create Date: 2026-11-06

``pathway_step_blocks.caption`` was ``VARCHAR(500)``. On a media block
it is the figcaption, and creators use it for what a figcaption is
actually for in a teaching Pathway: how to do the practice, what to
listen for, a transcript. Five hundred characters is roughly a short
paragraph.

Sentry FC-API-M, five occurrences. An external creator writing
instructions for a mindfulness audio practice went past 500 characters
and the save returned HTTP 500 —
``psycopg2.errors.StringDataRightTruncation`` out of

    UPDATE pathway_step_blocks SET caption = ..., updated_at = now()

There was no API-level length rule to catch it first, so the only limit
in the system was the column, and the only feedback was a server error
on a save the creator had every reason to expect to work.

``TEXT`` rather than a larger ``VARCHAR``: ``content`` on this same
table is already ``TEXT`` for exactly this reason, and picking a new
number would only move the cliff somewhere else. In PostgreSQL the two
types are the same storage with a length trigger, so widening costs
nothing and does not rewrite the table.

Nothing is backfilled, truncated or normalised. Every existing caption
is already inside the new type and stays byte-for-byte as the creator
wrote it; nullability is unchanged, so blocks with no caption stay
``NULL`` and keep reading as "no caption".

Note that ``caption`` is overloaded on two block types — it carries the
palette token on a ``callout`` and the encoded style on a ``button``.
Both write short values through pickers, neither is affected by a wider
column, and this migration does not touch their contents.
"""

from alembic import op
import sqlalchemy as sa


revision = "182"
down_revision = "181"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "pathway_step_blocks",
        "caption",
        type_=sa.Text(),
        existing_type=sa.String(length=500),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Deliberately a plain narrowing, with no ``USING left(caption, 500)``.
    #
    # PostgreSQL refuses to shrink a column when a row would not fit —
    # it raises rather than truncating — and that refusal is the point.
    # A downgrade is a developer stepping backwards, not a licence to
    # silently delete the end of somebody's audio instructions. If this
    # fails, a creator has written a caption longer than the old limit
    # and the correct response is to decide what happens to that text,
    # not to let the migration decide.
    op.alter_column(
        "pathway_step_blocks",
        "caption",
        type_=sa.String(length=500),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
