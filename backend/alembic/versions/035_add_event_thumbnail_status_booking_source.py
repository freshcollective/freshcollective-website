"""Add thumbnail_url and status to events; source and note to event_bookings."""

revision = '035'
down_revision = '034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    # Events: thumbnail image + cancellation status
    op.execute("ALTER TABLE events ADD COLUMN thumbnail_url VARCHAR(500)")
    op.execute("ALTER TABLE events ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'")

    # Event bookings: booking source + optional note
    op.execute("ALTER TABLE event_bookings ADD COLUMN source VARCHAR(20)")
    op.execute("ALTER TABLE event_bookings ADD COLUMN note TEXT")


def downgrade() -> None:
    from alembic import op

    op.execute("ALTER TABLE event_bookings DROP COLUMN note")
    op.execute("ALTER TABLE event_bookings DROP COLUMN source")
    op.execute("ALTER TABLE events DROP COLUMN status")
    op.execute("ALTER TABLE events DROP COLUMN thumbnail_url")
