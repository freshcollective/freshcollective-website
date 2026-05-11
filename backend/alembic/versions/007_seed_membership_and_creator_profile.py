"""Seed SpaceMembership and CreatorProfile for the admin user.

Revision ID: 007
Revises: 006
Create Date: 2026-05-11

Uses the first admin user via subquery — silently skipped if none exists.
"""

from alembic import op

FC_SPACE_ID = "80862f54-d95f-4b3b-83ab-cf926014441d"
MEMBERSHIP_ID = "sm000001-0000-4000-8000-000000000001"
NOW = "2026-05-11 00:00:00"

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SpaceMembership: admin user as creator of FC Space
    op.execute(f"""
        INSERT INTO space_memberships (id, user_id, space_id, role, status, joined_at)
        SELECT
            '{MEMBERSHIP_ID}',
            id,
            '{FC_SPACE_ID}',
            'creator',
            'active',
            '{NOW}'
        FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1
        ON CONFLICT (id) DO NOTHING;
    """)

    # CreatorProfile: public profile for the admin user
    op.execute(f"""
        INSERT INTO creator_profiles
            (user_id, display_name, bio, is_public, created_at, updated_at)
        SELECT
            id,
            name,
            $bio$Founder of Fresh Collective. Passionate about human growth, transformation, and building spaces where women can step more fully into who they already are.$bio$,
            true,
            '{NOW}',
            '{NOW}'
        FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1
        ON CONFLICT (user_id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute(f"DELETE FROM space_memberships WHERE id = '{MEMBERSHIP_ID}'")
    op.execute(f"""
        DELETE FROM creator_profiles
        WHERE user_id = (
            SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1
        )
    """)
