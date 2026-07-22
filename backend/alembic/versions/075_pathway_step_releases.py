"""Pathway drip scheduling — per-step release rules + manual releases.

Revision ID: 075
Revises: 074
Create Date: 2026-07-15

ADDITIVE ONLY.

Extends `pathway_steps` with a single-column release rule and stores
per-member manual releases in a small side table. Every existing step
is backfilled to `release_type='immediate'` so no one loses access.

Design rationale — the release rule is captured as a discriminated
union of columns on the step itself (`release_type` selects, other
columns hold the type-specific config). This keeps the read path
trivial (one join-free scan of the step list) at the cost of a few
sparse columns. Adding new release types later means adding new
columns or reusing existing ones; no restructuring required.

The `pathway_step_manual_releases` table records exactly one row per
(step, user) pair, so the "release for this member" action is
naturally idempotent — a duplicate call collides on the unique
constraint and we silently keep the earlier release.
"""

from alembic import op
import sqlalchemy as sa


revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pathway_steps",
        sa.Column(
            "release_type",
            sa.String(length=32),
            nullable=False,
            server_default="immediate",
        ),
    )
    op.add_column(
        "pathway_steps",
        sa.Column("release_offset_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pathway_steps",
        sa.Column("release_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "pathway_steps",
        sa.Column("release_timezone", sa.String(length=64), nullable=True),
    )
    # 'completed' | 'started'. Only 'completed' is enforced today;
    # 'started' is accepted so the schema doesn't need another migration
    # when we implement it.
    op.add_column(
        "pathway_steps",
        sa.Column(
            "release_previous_state",
            sa.String(length=16),
            nullable=False,
            server_default="completed",
        ),
    )

    op.create_table(
        "pathway_step_manual_releases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("step_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("released_by", sa.String(), nullable=True),
        sa.Column(
            "released_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["step_id"], ["pathway_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["released_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("step_id", "user_id", name="uq_pathway_step_manual_release"),
    )
    op.create_index(
        "ix_pathway_step_manual_releases_user",
        "pathway_step_manual_releases",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pathway_step_manual_releases_user",
        table_name="pathway_step_manual_releases",
    )
    op.drop_table("pathway_step_manual_releases")
    op.drop_column("pathway_steps", "release_previous_state")
    op.drop_column("pathway_steps", "release_timezone")
    op.drop_column("pathway_steps", "release_at")
    op.drop_column("pathway_steps", "release_offset_days")
    op.drop_column("pathway_steps", "release_type")
