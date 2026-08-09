"""Pathway — presentation type (guided_experience | knowledge_guide).

Revision ID: 102
Revises: 101
Create Date: 2026-08-09

Adds a single ``pathway_type`` enum column to ``pathways`` so one
content model can drive two experiences:

  * ``guided_experience`` (default) — the existing per-step, per-URL
    flow with progress, reflections, next/previous navigation.
  * ``knowledge_guide`` — a continuous reference document rendered on
    the pathway landing page. Sections become chapters, steps render
    inline beneath them. No progress or completion is displayed.

Every existing row is a Guided Experience by definition, so the
column is created with a server default of ``guided_experience`` and
made NOT NULL. No data backfill is needed.

Nothing about sections, steps, blocks, enrollments, or step progress
changes. Access control, pricing, and enrollment lifecycle work
identically for both types — the difference is purely how the member
experiences the content.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "102"
down_revision = "101"
branch_labels = None
depends_on = None


PATHWAY_TYPE_ENUM_NAME = "pathway_type_enum"
PATHWAY_TYPES = ("guided_experience", "knowledge_guide")


def upgrade() -> None:
    bind = op.get_bind()

    pathway_type_enum = postgresql.ENUM(
        *PATHWAY_TYPES, name=PATHWAY_TYPE_ENUM_NAME,
    )
    pathway_type_enum.create(bind, checkfirst=True)

    op.add_column(
        "pathways",
        sa.Column(
            "pathway_type",
            postgresql.ENUM(
                *PATHWAY_TYPES,
                name=PATHWAY_TYPE_ENUM_NAME,
                create_type=False,
            ),
            nullable=False,
            server_default="guided_experience",
        ),
    )


def downgrade() -> None:
    op.drop_column("pathways", "pathway_type")

    bind = op.get_bind()
    postgresql.ENUM(name=PATHWAY_TYPE_ENUM_NAME).drop(bind, checkfirst=True)
