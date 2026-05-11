"""Seed initial community posts for the Fresh Collective Space.

Revision ID: 006
Revises: 005
Create Date: 2026-05-11

Additive only — no schema changes.

Uses the first admin user as post author (INSERT ... SELECT). If no
admin exists in the target environment the inserts are silently skipped
— safe to run multiple times via ON CONFLICT (id) DO NOTHING.
"""

from alembic import op

FC_SPACE_ID = "80862f54-d95f-4b3b-83ab-cf926014441d"
POST_WELCOME_ID = "po000001-0000-4000-8000-000000000001"
POST_PROMPT_ID  = "po000001-0000-4000-8000-000000000002"
POST_DISCUSS_ID = "po000001-0000-4000-8000-000000000003"
NOW = "2026-05-11 00:00:00"

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Each INSERT selects the first admin user as author.
    # If no admin exists, the SELECT returns no rows → nothing inserted.

    op.execute(f"""
        INSERT INTO community_posts
            (id, space_id, author_id, post_type, title, body,
             is_pinned, is_visible, created_at, updated_at)
        SELECT
            '{POST_WELCOME_ID}',
            '{FC_SPACE_ID}',
            id,
            'announcement',
            'Welcome to Fresh Collective',
            $body$Welcome to the community space inside Fresh Collective.

This is where we gather between sessions — to share what we are noticing, to ask questions, and to move through the work of growth and change together.

There is no pressure to perform or keep up. Come when it feels right. Share when something is alive for you. The pace here is yours to set.

We are glad you are here.$body$,
            true,
            true,
            '{NOW}',
            '{NOW}'
        FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO community_posts
            (id, space_id, author_id, post_type, title, body,
             is_pinned, is_visible, created_at, updated_at)
        SELECT
            '{POST_PROMPT_ID}',
            '{FC_SPACE_ID}',
            id,
            'prompt',
            'This week''s reflection',
            $body$What is one thing you have noticed about yourself this week — not judged, just observed?

It might be a pattern, a reaction, a moment of unexpected clarity, or something small that surprised you.

Sit with it for a moment before you write. There is no right answer. We are listening.$body$,
            true,
            true,
            '{NOW}',
            '{NOW}'
        FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1
        ON CONFLICT (id) DO NOTHING;
    """)

    op.execute(f"""
        INSERT INTO community_posts
            (id, space_id, author_id, post_type, title, body,
             is_pinned, is_visible, created_at, updated_at)
        SELECT
            '{POST_DISCUSS_ID}',
            '{FC_SPACE_ID}',
            id,
            'discussion',
            'What are you exploring right now?',
            $body$A simple open question to start.

If you are comfortable sharing — what part of your REAL Journey is alive for you at the moment? What feels easy? What feels worth returning to?

No right answer. Just an honest one.$body$,
            false,
            true,
            '{NOW}',
            '{NOW}'
        FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM community_posts
        WHERE id IN ('{POST_WELCOME_ID}', '{POST_PROMPT_ID}', '{POST_DISCUSS_ID}');
    """)
