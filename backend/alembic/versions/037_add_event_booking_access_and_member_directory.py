"""Add booking access control to events and member directory flag to spaces

Revision ID: 037
Revises: 036
Create Date: 2026-06-04
"""
from alembic import op

revision = '037'
down_revision = '036'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Event booking access — 'all_members' (default) or 'pathway_required'
    op.execute("ALTER TABLE events ADD COLUMN booking_access_type VARCHAR(20) NOT NULL DEFAULT 'all_members'")
    # Nullable FK to pathway — used when booking_access_type = 'pathway_required'
    op.execute("ALTER TABLE events ADD COLUMN booking_required_pathway_id VARCHAR(36) REFERENCES pathways(id) ON DELETE SET NULL")
    # Space member directory visibility — off by default (count only for learners)
    op.execute("ALTER TABLE spaces ADD COLUMN show_member_directory BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE events DROP COLUMN booking_required_pathway_id")
    op.execute("ALTER TABLE events DROP COLUMN booking_access_type")
    op.execute("ALTER TABLE spaces DROP COLUMN show_member_directory")
