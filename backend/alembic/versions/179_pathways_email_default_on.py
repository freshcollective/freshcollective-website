"""Turn the Pathway-publication email default on.

Revision ID: 179
Revises: 178
Create Date: 2026-11-03

The same seeded default that stopped Conversations emails, in the
category beside it. Migration 097 set::

    ("pathways", "in_app",              True,  False),
    ("pathways", "email_transactional", False, False),   # <-- off

So ``announce_if_newly_available`` wrote the event, the resolver found
the recipients and the template rendered, and every member without an
explicit preference row resolved to ``silent`` — a *recorded* intent,
meaning "nothing to send". The Pathway publication announcement has
never reached an inbox.

Why this cannot switch on anything else
---------------------------------------
The worry with a category-level default is that ``pathways`` carries
three events, and only one of them should email:

    pathway.published             ← the announcement
    pathway.step_added            ← must NOT email the Collective
    pathway.enrolment.completed   ← personal, to the completing member

It cannot, and the reason is structural rather than a promise.
``step_added`` and ``enrolment.completed`` have **no templates
registered on any channel** and **no emitters** — checked against
``templates/registry.py``, which returns None for both — and the
decision pipeline skips an intent entirely when no template exists for
the (event, channel) pair. There is nothing for this default to
activate.

So this flips exactly one email on, which is the one asked for.

The step announcement that *did* reach inboxes went through the legacy
``trigger_new_step``, outside this category and outside the comms
preference system altogether. That is dealt with in the same change as
this migration, in ``notification_service``: in-app stays, the
automatic email stops.

Not retroactive
---------------
Every currently-live Pathway is marked as announced first, so the flip
cannot mail the Collective about something published months ago. See
the comment on the insert.

What is not changed
-------------------
An explicit override still wins, so a member who opted out of Pathway
email stays opted out. ``is_locked`` stays false, so opting out remains
possible. No existing intent is revisited, so nothing already
published is announced retroactively.
"""
from alembic import op

revision = "179"
down_revision = "178"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Mark every Pathway that is ALREADY live as announced.
    #
    # Without this the default flip would email the Collective about
    # Pathways published months ago. ``should_announce`` is
    # "member-visible now AND never announced", and a Pathway published
    # before the comms event existed has no dedupe row — so the next
    # ordinary edit would read as a first publication. Harmless while
    # the email default was off (the intent was recorded, nothing
    # sent); not harmless afterwards.
    #
    # The row written here is the truthful statement the dedupe key
    # exists for: this Pathway's first availability is on the record,
    # and there is nothing to deliver for it. Routing is never
    # scheduled for these, so no intent and no email can follow. The
    # context marks them so the event log does not imply an
    # announcement that never went out.
    #
    # Idempotent via the partial unique index on
    # (event_type, dedupe_key) — re-running inserts nothing.
    op.execute("""
        INSERT INTO communication_events (
            id, event_type, topic_key, category_key,
            source_type, source_id, priority_hint,
            subject_type, subject_id, context, payload,
            dedupe_key, occurred_at
        )
        SELECT
            'evt_bf179_' || substr(md5(p.id), 1, 20),
            'pathway.published', 'pathways', 'pathways',
            'fresh_collective', NULL, 'silent',
            'pathway', p.id,
            jsonb_build_object(
                'space_id', p.space_id,
                'backfilled', true,
                'reason', 'already published before migration 179'
            ),
            '{}'::jsonb,
            p.id || ':' || p.space_id,
            NOW()
        FROM pathways p
        JOIN spaces s ON s.id = p.space_id
        WHERE p.status = 'active'
          AND s.status = 'active'
        ON CONFLICT DO NOTHING
    """)

    # 2. Only then turn the default on.
    op.execute("""
        UPDATE communication_channel_defaults
        SET default_enabled = true
        WHERE category_key = 'pathways'
          AND channel = 'email_transactional'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE communication_channel_defaults
        SET default_enabled = false
        WHERE category_key = 'pathways'
          AND channel = 'email_transactional'
    """)
    op.execute("""
        DELETE FROM communication_events
        WHERE event_type = 'pathway.published'
          AND context ->> 'backfilled' = 'true'
    """)
