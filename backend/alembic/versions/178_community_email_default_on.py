"""Turn the Conversations email default on.

Revision ID: 178
Revises: 177
Create Date: 2026-11-03

Why no emails were sent
-----------------------
Migration 097 seeded the channel defaults, and for the ``community``
category it set::

    ("community", "in_app",              True,  False),
    ("community", "email_transactional", False, False),   # <-- off
    ("community", "push",                False, False),

``get_effective_preference`` falls back to the category default when a
member has no explicit preference row, and resolves
``default_enabled=False`` to ``silent``. The decision pipeline then
creates the intent directly in ``recorded`` — a row saying "nothing to
send" — so routing looked healthy, an intent existed, and no email
ever reached Resend.

Every surrounding category had email on: ``gatherings``, ``messages``,
``purchases``, ``account``, ``safety``, ``creator_updates``. Only
``community`` and ``pathways`` were off. For Conversations that is
wrong: a creator posting to their channel is the clearest case there
is of something a member asked to hear about.

Migration 098 then backfilled preference rows from the legacy flags,
so members who already had notification settings with
``new_post_email`` on got an ``override`` row reading ``immediate``.
That is why this was invisible for a long time — the people who had
been on the platform longest were covered by their own override, and
only members with no row at all fell through to the default. A
Collective of recently created accounts is entirely in that group.

What this changes
-----------------
One boolean. Members with an explicit preference row are unaffected in
either direction: an override wins over the default, so anybody who
opted out stays opted out. ``is_locked`` stays False, so opting out
remains possible.

Nothing is sent by this migration, and no queued or recorded intent is
revisited — the Moonlit Circle post that prompted the investigation
stays as it is rather than being re-delivered.
"""
from alembic import op

revision = "178"
down_revision = "177"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE communication_channel_defaults
        SET default_enabled = true
        WHERE category_key = 'community'
          AND channel = 'email_transactional'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE communication_channel_defaults
        SET default_enabled = false
        WHERE category_key = 'community'
          AND channel = 'email_transactional'
    """)
