"""Members can answer an Exercise block in writing.

Revision ID: 152
Revises: 151
Create Date: 2026-10-09

Round 2, item 9. Exercise blocks carried instructions but no room to
respond to them, so the activity stopped at the reading.

Why a table rather than a column on ``step_progress``
-----------------------------------------------------

``step_progress`` is ``UNIQUE (user_id, step_id)`` with a single
``reflection_text``, so it holds exactly one response per member per
step. A step can hold several Exercise blocks, and the brief is explicit
that saving one must not disturb another or the step reflection.

A JSONB map keyed by block id would have avoided this migration, but
saving two exercises concurrently then becomes read-modify-write on one
column — a lost update — and it puts member responses in the same row as
the step reflection, where a bug reaches both. One row per
(member, block) makes independence structural: ``UNIQUE (user_id,
block_id)`` means a save physically cannot touch another response, and
nothing in this table can reach ``reflection_text`` at all.

Cascades
--------

Both are ``CASCADE``, matching ``step_progress``, which already cascades
from both ``users`` and ``pathway_steps``. Deleting an Exercise block
therefore destroys the responses written into it, exactly as deleting a
step destroys its reflections today. That is the agreed product
decision and is worth stating plainly rather than leaving implied: it is
member-authored writing, and it goes when the exercise goes.

``response_enabled``
--------------------

Nullable with no server default, so every existing Exercise block reads
NULL and the application treats NULL as enabled — the same ``?? true``
reading ``reflection_enabled`` already gets on the client. Creators need
not republish anything, and turning the toggle off writes ``false``
without touching a single stored response.

Backward compatibility
----------------------

* The table is new and empty; nothing reads or writes it until the
  application that knows about it is serving.
* ``ADD COLUMN`` is nullable with no default, so it is metadata-only on
  PostgreSQL 11+ — no table rewrite, a brief lock rather than a long one.
* Safe to apply before the new code (both are simply unused), and safe
  to leave in place if the application is rolled back: older code
  selects neither.
* One ordering requirement, because SQLAlchemy selects every mapped
  column: the new code cannot run against an unmigrated database, so
  this must run *before* the new image serves. fc-api's
  ``preDeployCommand: alembic upgrade head`` does exactly that.

Downgrade drops both, discarding every response written by then. Prefer
rolling back the application and leaving the schema in place.
"""

from alembic import op
import sqlalchemy as sa


revision = "152"
down_revision = "151"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_responses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "block_id",
            sa.String(),
            sa.ForeignKey("pathway_step_blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # The guarantee the whole design rests on: one response per
        # member per exercise. Also what makes the upsert safe under
        # concurrency — a racing second insert violates this and is
        # retried as an update rather than becoming a duplicate row.
        sa.UniqueConstraint("user_id", "block_id", name="exercise_responses_user_block_unique"),
    )
    # ``user_id`` is covered by the unique constraint's leading column.
    # ``block_id`` needs its own index for the cascade delete.
    op.create_index(
        "ix_exercise_responses_block_id", "exercise_responses", ["block_id"],
    )

    op.add_column(
        "pathway_step_blocks",
        sa.Column("response_enabled", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pathway_step_blocks", "response_enabled")
    op.drop_index("ix_exercise_responses_block_id", table_name="exercise_responses")
    op.drop_table("exercise_responses")
