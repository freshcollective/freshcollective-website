"""Creator configuration for the member Collective Home.

Revision ID: 135
Revises: 134
Create Date: 2026-09-20

Motivation
----------
Phase 1 shipped a Collective Home with a fixed tile set, fixed order
and platform copy. Creators now need to choose which doorways their
members see, in what order, with what imagery and wording.

One nullable JSON column rather than a table or a column per control.
The precedent is ``offer_pages.sections_config``, whose own migration
records the reasoning: typed sections stored as JSON "so shapes can
evolve without a migration". The same holds here — six optional
settings across six optional tiles would be a wide, almost-always-null
table, and a dedicated model would hold at most one row per Collective
forever.

Safety
------
* Additive, nullable, no backfill and no default. Every existing
  Collective keeps ``NULL`` and therefore keeps exactly the Phase 1
  Home — configuring is opt-in, and nothing has to be migrated before
  the feature works.
* NULL is a meaningful value here, not a gap: ``home_config.resolve``
  builds from the canonical tile list outwards, so a Collective
  configured today still gains a tile type added next year without
  anyone reopening the editor.
* Validation lives in ``app/spaces/home_config.py`` rather than in the
  column, which is what lets an unknown tile key be ignored instead of
  rejecting a creator's whole save.
* Reversible: ``downgrade`` drops the column. Collectives fall back to
  the default Home, which is a working state rather than a broken one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "135"
down_revision = "134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column("home_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("spaces", "home_config")
