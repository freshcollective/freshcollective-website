"""Communications — foundation tables (Milestone 1).

Revision ID: 097
Revises: 096
Create Date: 2026-08-07

Introduces the scaffolding tables for the Communications Layer described
in ``docs/communications-architecture.md`` (Milestone 1). Purely additive;
no existing behaviour changes. No sending happens yet.

Tables created:

  * ``communication_topics``            — internal engineering topic registry
  * ``communication_categories``        — nine member-facing categories
  * ``communication_channel_defaults``  — per (category × channel) default
                                          and locked flag
  * ``communication_events``            — immutable event log; every
                                          business event that could be
                                          communicated persists here

Enums created (native PostgreSQL):

  * ``communication_source_type_enum``  — fresh_collective | collective | creator
  * ``communication_channel_enum``      — in_app | email_transactional |
                                          email_marketing | push |
                                          webhook_outbound
  * ``communication_priority_enum``     — immediate | scheduled |
                                          daily_digest | weekly_digest |
                                          silent

Reference data (categories, topics, channel defaults) is seeded here so
``alembic upgrade head`` on a fresh database yields a fully functioning
registry. Adding a new category or topic in code should always ship with
a companion migration seeding its row.

Downgrade drops all of the above cleanly (tables, indexes, enums).
"""

from alembic import op
import sqlalchemy as sa


revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Enum definitions (reused for create/drop)
# ---------------------------------------------------------------------------

SOURCE_TYPE_ENUM_NAME = "communication_source_type_enum"
CHANNEL_ENUM_NAME = "communication_channel_enum"
PRIORITY_ENUM_NAME = "communication_priority_enum"

SOURCE_TYPES = ("fresh_collective", "collective", "creator")
CHANNELS = (
    "in_app",
    "email_transactional",
    "email_marketing",
    "push",
    "webhook_outbound",
)
PRIORITIES = (
    "immediate",
    "scheduled",
    "daily_digest",
    "weekly_digest",
    "silent",
)


# ---------------------------------------------------------------------------
# Reference data — seeded on upgrade
# ---------------------------------------------------------------------------

# Nine member-facing categories. `key` is stable and machine-safe;
# `label` is the display string; `is_critical` locks the category
# in-app (Account, Purchases, Safety cannot be silenced in-app).
CATEGORIES = [
    # key                  label                sort  critical  description
    ("account",            "Account",             10, True,
     "Sign-in, password changes and other account-level updates."),
    ("safety",             "Safety",              20, True,
     "Moderation notices, community-care actions and safety updates."),
    ("purchases",          "Purchases",           30, True,
     "Purchase confirmations, activations and receipts."),
    ("messages",           "Messages",            40, False,
     "Direct messages from other members."),
    ("gatherings",         "Gatherings",          50, False,
     "Bookings, reminders and updates about gatherings you're part of."),
    ("pathways",           "Pathways",            60, False,
     "New pathways, step updates and enrolment progress."),
    ("community",          "Community",           70, False,
     "New posts, replies, mentions and answers in your collectives."),
    ("creator_updates",    "Creator Updates",     80, False,
     "Updates from creators of collectives you're part of."),
    ("platform_updates",   "Platform Updates",    90, False,
     "Announcements and product news from Fresh Collective."),
]

# Internal engineering topics. Each event_type declares which topic it
# belongs to; the topic → category mapping lives in code
# (``app/comms/registry.py``) so it can be reviewed as PRs.
TOPICS = [
    ("account",             "Account"),
    ("security",            "Security"),
    ("conversations",       "Conversations"),
    ("collective_updates",  "Collective Updates"),
    ("pathways",            "Pathways"),
    ("gatherings",          "Gatherings"),
    ("direct_messages",     "Direct Messages"),
    ("purchases",           "Purchases"),
    ("subscriptions",       "Subscriptions"),
    ("creator_broadcasts",  "Creator Broadcasts (Updates)"),
    ("product_updates",     "Product Updates"),
    ("marketing",           "Marketing"),
    ("moderation",          "Moderation"),
    ("community_care",      "Community Care"),
]

# Per (category × channel) default enabled + locked flag.
# Locked defaults cannot be silenced by members; every other opt is
# member-controllable through /settings/communications (Milestone 7).
# (category_key, channel, default_enabled, is_locked)
CHANNEL_DEFAULTS = [
    # ── Critical categories (locked in-app and email) ─────────────────
    ("account",            "in_app",              True,  True),
    ("account",            "email_transactional", True,  True),
    ("account",            "push",                False, False),
    ("purchases",          "in_app",              True,  True),
    ("purchases",          "email_transactional", True,  True),
    ("purchases",          "push",                False, False),
    ("safety",             "in_app",              True,  True),
    ("safety",             "email_transactional", True,  False),
    ("safety",             "push",                False, False),
    # ── Optional categories (member-controllable) ─────────────────────
    ("messages",           "in_app",              True,  False),
    ("messages",           "email_transactional", True,  False),
    ("messages",           "push",                False, False),
    ("gatherings",         "in_app",              True,  False),
    ("gatherings",         "email_transactional", True,  False),
    ("gatherings",         "push",                False, False),
    ("pathways",           "in_app",              True,  False),
    ("pathways",           "email_transactional", False, False),
    ("pathways",           "push",                False, False),
    ("community",          "in_app",              True,  False),
    ("community",          "email_transactional", False, False),
    ("community",          "push",                False, False),
    ("creator_updates",    "in_app",              True,  False),
    ("creator_updates",    "email_transactional", True,  False),
    ("creator_updates",    "push",                False, False),
    ("platform_updates",   "in_app",              True,  False),
    ("platform_updates",   "email_marketing",     False, False),
    ("platform_updates",   "push",                False, False),
]


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()

    # Native enum types. ``create_type=False`` on subsequent column-level
    # references would fail because there's no other consumer yet, so we
    # let ``create_table`` create them implicitly via first use below.
    source_type_enum = sa.Enum(*SOURCE_TYPES, name=SOURCE_TYPE_ENUM_NAME)
    channel_enum = sa.Enum(*CHANNELS, name=CHANNEL_ENUM_NAME)
    priority_enum = sa.Enum(*PRIORITIES, name=PRIORITY_ENUM_NAME)

    # ── communication_topics ─────────────────────────────────────────
    op.create_table(
        "communication_topics",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── communication_categories ─────────────────────────────────────
    op.create_table(
        "communication_categories",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column(
            "is_critical",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_communication_categories_sort_order",
        "communication_categories",
        ["sort_order"],
    )

    # ── communication_channel_defaults ───────────────────────────────
    op.create_table(
        "communication_channel_defaults",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "category_key",
            sa.String(64),
            sa.ForeignKey("communication_categories.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column(
            "default_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_locked",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "category_key", "channel", name="uq_channel_default_category_channel",
        ),
    )

    # ── communication_events (the log) ────────────────────────────────
    op.create_table(
        "communication_events",
        sa.Column("id", sa.String(), primary_key=True),
        # Monotonic ordering across all events; useful for stable
        # pagination and per-recipient replay.
        sa.Column(
            "sequence_number",
            sa.BigInteger,
            sa.Identity(always=False, start=1),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column(
            "topic_key",
            sa.String(64),
            sa.ForeignKey("communication_topics.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "category_key",
            sa.String(64),
            sa.ForeignKey("communication_categories.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", source_type_enum, nullable=False),
        # For source_type='fresh_collective' this is NULL. For
        # 'collective' it references a space/collective id. For
        # 'creator' it references a user id. We don't enforce the FK
        # at the DB level because the target table differs per source
        # type — application-layer validation in ``comms.emit()``.
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("priority_hint", priority_enum, nullable=False),
        sa.Column(
            "actor_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_type", sa.String(64), nullable=True),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column(
            "context",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "payload",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        # Optional dedupe within an event_type. Enforced via the
        # partial unique index below (only when non-NULL).
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_communication_events_event_type_occurred_at",
        "communication_events",
        ["event_type", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_communication_events_subject",
        "communication_events",
        ["subject_type", "subject_id"],
    )
    op.create_index(
        "ix_communication_events_source",
        "communication_events",
        ["source_type", "source_id"],
    )
    op.create_index(
        "ix_communication_events_sequence_number",
        "communication_events",
        ["sequence_number"],
        unique=True,
    )
    # Partial unique index on (event_type, dedupe_key) enforces
    # idempotent emit — a repeat call with the same dedupe_key is a
    # no-op. NULL dedupe_key allows unlimited unrelated events.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_communication_events_dedupe
                     ON communication_events (event_type, dedupe_key)
                  WHERE dedupe_key IS NOT NULL
        """
    )

    # ── Seed reference data ──────────────────────────────────────────
    topics_table = sa.table(
        "communication_topics",
        sa.column("key", sa.String),
        sa.column("label", sa.String),
    )
    op.bulk_insert(
        topics_table,
        [{"key": k, "label": l} for (k, l) in TOPICS],
    )

    categories_table = sa.table(
        "communication_categories",
        sa.column("key", sa.String),
        sa.column("label", sa.String),
        sa.column("description", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_critical", sa.Boolean),
    )
    op.bulk_insert(
        categories_table,
        [
            {
                "key": k,
                "label": label,
                "description": desc,
                "sort_order": sort,
                "is_critical": crit,
            }
            for (k, label, sort, crit, desc) in CATEGORIES
        ],
    )

    # Channel defaults — one row per (category × channel) we care about.
    # We deterministically synthesise IDs so re-runs are hash-stable and
    # test snapshots are deterministic.
    defaults_table = sa.table(
        "communication_channel_defaults",
        sa.column("id", sa.String),
        sa.column("category_key", sa.String),
        sa.column("channel", sa.String),
        sa.column("default_enabled", sa.Boolean),
        sa.column("is_locked", sa.Boolean),
    )
    op.bulk_insert(
        defaults_table,
        [
            {
                "id": f"ccd_{cat}_{ch}",
                "category_key": cat,
                "channel": ch,
                "default_enabled": enabled,
                "is_locked": locked,
            }
            for (cat, ch, enabled, locked) in CHANNEL_DEFAULTS
        ],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_communication_events_dedupe")
    op.drop_index(
        "ix_communication_events_sequence_number",
        table_name="communication_events",
    )
    op.drop_index(
        "ix_communication_events_source",
        table_name="communication_events",
    )
    op.drop_index(
        "ix_communication_events_subject",
        table_name="communication_events",
    )
    op.drop_index(
        "ix_communication_events_event_type_occurred_at",
        table_name="communication_events",
    )
    op.drop_table("communication_events")

    op.drop_table("communication_channel_defaults")

    op.drop_index(
        "ix_communication_categories_sort_order",
        table_name="communication_categories",
    )
    op.drop_table("communication_categories")

    op.drop_table("communication_topics")

    # Native enum types created implicitly by the columns above must be
    # dropped explicitly on downgrade.
    sa.Enum(name=PRIORITY_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=CHANNEL_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=SOURCE_TYPE_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
