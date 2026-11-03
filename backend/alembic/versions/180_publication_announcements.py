"""Let creators announce a Gathering or a Series when they publish it.

Revision ID: 180
Revises: 179
Create Date: 2026-11-03

Two columns and two backfills.

``notify_members``
------------------
The creator's choice, stored on the experience rather than inferred at
publish time, so it survives a draft being saved repeatedly and is
still there when the publish finally happens. Default true: announcing
is the expected behaviour and publishing quietly is the deliberate
exception.

It is only ever *read* at a first publication, so a draft carrying
``true`` for a fortnight announces nothing until the creator publishes.

Why the backfills matter more than the columns
----------------------------------------------
``should_announce`` for both experiences is "publicly live now AND
never announced", the same shape as the Pathway rule. Every Gathering
and Series already published predates these events and so has no
dedupe row — which would make the next ordinary edit read as a first
publication and mail the whole Collective about something from months
ago.

So both are marked as announced here, before anything can emit. The
rows carry ``backfilled`` in their context and no routing is ever
scheduled for them, so no intent and no email can follow. Idempotent
through the partial unique index on ``(event_type, dedupe_key)``.

This is the third time this pattern has been needed (178, 179, here).
The lesson is that turning on an announcement is never only a code
change: the absence of a dedupe row means "never announced", and for
existing content that is true but misleading.

Series occurrences
------------------
Nothing is needed here for them. A Gathering belonging to a Series is
suppressed at the source — see ``publication_announcement`` — because
it carries ``series_id`` or ``recurrence_series_id``, not because of
anything stored by this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "180"
down_revision = "179"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("events", "event_series"):
        op.add_column(
            table,
            sa.Column(
                "notify_members", sa.Boolean(), nullable=False,
                server_default=sa.true(),
            ),
        )

    # Already-published Gatherings: marked announced, nothing sent.
    op.execute("""
        INSERT INTO communication_events (
            id, event_type, topic_key, category_key,
            source_type, source_id, priority_hint,
            subject_type, subject_id, context, payload,
            dedupe_key, occurred_at
        )
        SELECT
            'evt_bf180g_' || substr(md5(e.id), 1, 18),
            'gathering.published', 'gatherings', 'gatherings',
            'fresh_collective', NULL, 'silent',
            'gathering', e.id,
            jsonb_build_object(
                'space_id', e.space_id,
                'backfilled', true,
                'reason', 'already published before migration 180'
            ),
            '{}'::jsonb,
            e.id || ':' || e.space_id,
            NOW()
        FROM events e
        JOIN spaces s ON s.id = e.space_id
        WHERE e.is_published IS TRUE
        ON CONFLICT DO NOTHING
    """)

    # Already-published Series, same reasoning.
    op.execute("""
        INSERT INTO communication_events (
            id, event_type, topic_key, category_key,
            source_type, source_id, priority_hint,
            subject_type, subject_id, context, payload,
            dedupe_key, occurred_at
        )
        SELECT
            'evt_bf180s_' || substr(md5(es.id), 1, 18),
            'series.published', 'gatherings', 'gatherings',
            'fresh_collective', NULL, 'silent',
            'series', es.id,
            jsonb_build_object(
                'space_id', es.space_id,
                'backfilled', true,
                'reason', 'already published before migration 180'
            ),
            '{}'::jsonb,
            es.id || ':' || es.space_id,
            NOW()
        FROM event_series es
        JOIN spaces s ON s.id = es.space_id
        WHERE es.published_at IS NOT NULL OR es.status = 'published'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM communication_events
        WHERE event_type IN ('gathering.published', 'series.published')
          AND context ->> 'backfilled' = 'true'
    """)
    for table in ("event_series", "events"):
        op.drop_column(table, "notify_members")
