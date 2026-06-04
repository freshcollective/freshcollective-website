"""Add attendance tracking fields to event_bookings

Revision ID: 036
Revises: 035
Create Date: 2026-06-04
"""
from alembic import op

revision = '036'
down_revision = '035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE event_bookings ADD COLUMN attendance_status VARCHAR(20)")
    op.execute("ALTER TABLE event_bookings ADD COLUMN attendance_marked_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE event_bookings ADD COLUMN attendance_marked_by VARCHAR(36)")


def downgrade() -> None:
    op.execute("ALTER TABLE event_bookings DROP COLUMN attendance_marked_by")
    op.execute("ALTER TABLE event_bookings DROP COLUMN attendance_marked_at")
    op.execute("ALTER TABLE event_bookings DROP COLUMN attendance_status")
