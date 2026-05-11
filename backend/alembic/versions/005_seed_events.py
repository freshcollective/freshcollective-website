"""Seed three upcoming events for the Fresh Collective Space.

Revision ID: 005
Revises: 004
Create Date: 2026-05-11

Additive only — no schema changes.
"""

from alembic import op

FC_SPACE_ID = "80862f54-d95f-4b3b-83ab-cf926014441d"

EVENT_GATHERING_ID   = "ev000001-0000-4000-8000-000000000001"
EVENT_INTEGRATION_ID = "ev000001-0000-4000-8000-000000000002"
EVENT_CHECKIN_ID     = "ev000001-0000-4000-8000-000000000003"

NOW = "2026-05-11 00:00:00"

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO events
            (id, space_id, title, description, starts_at, ends_at,
             location_type, is_published, created_at, updated_at)
        VALUES (
            '{EVENT_GATHERING_ID}',
            '{FC_SPACE_ID}',
            'Monthly Gathering — May',
            $desc$A space to gather, reflect, and set intention together.
We will open with a brief check-in, move through a shared reflection exercise, and close with space for questions and conversation.
All members welcome.$desc$,
            '2026-05-28 10:00:00',
            '2026-05-28 11:00:00',
            'zoom',
            true,
            '{NOW}',
            '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO events
            (id, space_id, title, description, starts_at, ends_at,
             location_type, is_published, created_at, updated_at)
        VALUES (
            '{EVENT_INTEGRATION_ID}',
            '{FC_SPACE_ID}',
            'REAL Journey Integration Session',
            $desc$A guided session designed for members who are partway through the REAL Journey.
We will slow down and look at what the process is revealing — not as a performance review, but as a living inquiry.
Come ready to be honest and gentle with yourself.$desc$,
            '2026-06-04 09:00:00',
            '2026-06-04 10:00:00',
            'zoom',
            true,
            '{NOW}',
            '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO events
            (id, space_id, title, description, starts_at, ends_at,
             location_type, is_published, created_at, updated_at)
        VALUES (
            '{EVENT_CHECKIN_ID}',
            '{FC_SPACE_ID}',
            'Fresh Start Check-In',
            $desc$A mid-month touchpoint for members in an active learning phase.
Shorter, lighter, and conversational. An opportunity to name what is happening and hear what others are noticing.$desc$,
            '2026-06-18 10:00:00',
            '2026-06-18 10:45:00',
            'zoom',
            true,
            '{NOW}',
            '{NOW}'
        )
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM events WHERE id IN (
            '{EVENT_GATHERING_ID}', '{EVENT_INTEGRATION_ID}', '{EVENT_CHECKIN_ID}'
        );
    """)
