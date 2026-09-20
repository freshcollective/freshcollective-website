"""Which areas of a Collective each kind of viewer may reach.

Revision ID: 137
Revises: 136
Create Date: 2026-09-21

One nullable JSONB column, same contract as ``spaces.home_config``:
``NULL`` means "never configured" and resolves to the platform
defaults, a missing area key takes that area's default, and an unknown
key is ignored. Nothing changes for any existing Collective until a
creator says otherwise.

JSON rather than a column per area because the area vocabulary grows —
adding a seventh area should not need a migration — and because nothing
filters Collectives *by* this. That is the opposite call from migration
136's ``join_policy``, which is a small closed vocabulary that is
queried, and the same call as 135's ``home_config``.

The two indexes are the reason this migration is not frontend-only.
Resolving "does this member currently hold any active access in this
Collective?" is one EXISTS over two tables, run once per request and
only for Collectives that actually use the ``active_access`` policy.
Both tables already index ``user_id`` and ``space_id`` separately;
neither can serve the three-column predicate without a heap fetch per
candidate row. These make it an index-only lookup.
"""

from alembic import op
import sqlalchemy as sa

revision = "137"
down_revision = "136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column("area_policies", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_access_passes_user_space_status",
        "access_passes",
        ["user_id", "space_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_pathway_entitlements_user_space_status",
        "pathway_entitlements",
        ["user_id", "space_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pathway_entitlements_user_space_status",
        table_name="pathway_entitlements",
    )
    op.drop_index(
        "ix_access_passes_user_space_status", table_name="access_passes",
    )
    op.drop_column("spaces", "area_policies")
