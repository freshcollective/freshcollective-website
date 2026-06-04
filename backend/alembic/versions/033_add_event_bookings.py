"""Add event booking fields and event_bookings table

Revision ID: 033
Revises: 032
Create Date: 2026-06-04

"""
from alembic import op
import sqlalchemy as sa

revision = '033'
down_revision = '032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add booking fields to events table
    op.add_column('events', sa.Column('requires_booking', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('events', sa.Column('capacity', sa.Integer(), nullable=True))
    op.add_column('events', sa.Column('booking_closes_at', sa.DateTime(), nullable=True))
    op.add_column('events', sa.Column('booking_note', sa.Text(), nullable=True))

    # Create bookingstatus enum and event_bookings table via raw SQL to avoid
    # SQLAlchemy's _on_table_create double-CREATE-TYPE bug with transactional DDL.
    op.execute("CREATE TYPE bookingstatus AS ENUM ('confirmed', 'cancelled')")
    op.execute("""
        CREATE TABLE event_bookings (
            id VARCHAR NOT NULL,
            event_id VARCHAR NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status bookingstatus NOT NULL DEFAULT 'confirmed',
            booked_at TIMESTAMP NOT NULL DEFAULT NOW(),
            cancelled_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT pk_event_bookings PRIMARY KEY (id),
            CONSTRAINT uq_event_bookings_event_user UNIQUE (event_id, user_id)
        )
    """)
    op.execute("CREATE INDEX ix_event_bookings_event_status ON event_bookings (event_id, status)")
    op.execute("CREATE INDEX ix_event_bookings_user_id ON event_bookings (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_event_bookings_user_id")
    op.execute("DROP INDEX IF EXISTS ix_event_bookings_event_status")
    op.drop_table('event_bookings')
    op.execute("DROP TYPE IF EXISTS bookingstatus")
    op.drop_column('events', 'booking_note')
    op.drop_column('events', 'booking_closes_at')
    op.drop_column('events', 'capacity')
    op.drop_column('events', 'requires_booking')
