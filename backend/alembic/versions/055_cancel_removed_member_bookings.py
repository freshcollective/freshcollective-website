"""Cancel future event bookings for already-removed members

Revision ID: 055
Revises: 054
Create Date: 2026-06-19

Fixes a bug where removing a member from a collective did not cancel their
future confirmed event bookings, so those bookings continued to count toward
session capacity.
"""

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cancel any future confirmed bookings that belong to members who have
    # already been removed from the space. Past bookings are left as-is for
    # historical records.
    op.execute("""
        UPDATE event_bookings eb
        SET status = 'cancelled',
            cancelled_at = NOW()
        FROM events e,
             space_memberships sm
        WHERE eb.event_id = e.id
          AND eb.user_id  = sm.user_id
          AND e.space_id  = sm.space_id
          AND eb.status   = 'confirmed'
          AND e.starts_at > NOW()
          AND sm.status   = 'removed'
    """)


def downgrade() -> None:
    # Not reversible — we cannot know which bookings were cancelled by this
    # migration vs by other means.
    pass
