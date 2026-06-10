"""Add access_pass_id and credits_used to event_bookings

Revision ID: 045
Revises: 044
Create Date: 2026-06-10
"""
from alembic import op

revision = '045'
down_revision = '044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE event_bookings
            ADD COLUMN IF NOT EXISTS access_pass_id VARCHAR
                REFERENCES access_passes(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS credits_used INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_event_bookings_access_pass_id
            ON event_bookings(access_pass_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_event_bookings_access_pass_id")
    op.execute("ALTER TABLE event_bookings DROP COLUMN IF EXISTS credits_used")
    op.execute("ALTER TABLE event_bookings DROP COLUMN IF EXISTS access_pass_id")
