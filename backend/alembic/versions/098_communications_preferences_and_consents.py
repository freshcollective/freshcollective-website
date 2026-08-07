"""Communications — preferences, consents, member settings (Milestone 2).

Revision ID: 098
Revises: 097
Create Date: 2026-08-07

Adds the per-member preference, consent and member-settings tables for
the Communications Layer. Backfills existing per-space preferences into
the new platform-wide model.

Tables created:

  * ``communication_preferences``       — one row per (user × category ×
                                          channel) deviation from the
                                          category default. Rows are
                                          only written when a member
                                          actively changes something.
  * ``communication_consents``          — append-only consent log.
                                          Latest row per (user, kind)
                                          is authoritative.
  * ``communication_member_settings``   — one row per user (lazy),
                                          holding timezone, quiet hours
                                          and digest delivery times.

Enums created:

  * ``communication_consent_kind_enum``  — terms_of_service |
                                           privacy_policy | marketing |
                                           product_updates |
                                           creator_broadcast
  * ``communication_consent_state_enum`` — granted | revoked

Backfill:

Existing ``space_member_notification_prefs`` rows are aggregated into
per-(user × category × channel) preferences using a **"most immediate
wins"** reduction:

  1. If ANY of the user's per-space rows enables an immediate email
     for a given category, the new preference is ``immediate``.
  2. Else, if ANY row enables a digest email (daily wins over weekly),
     the new preference is ``daily_digest`` / ``weekly_digest``.
  3. Else, no override row is written and the category default from
     ``communication_channel_defaults`` (seed of migration 097) applies.

This aggregation is **an intentional simplification during migration**
from the old per-space preference model to the new platform-wide
communications model. The old model let a member set different email
preferences for each collective; the new model treats communications
as a single member-controlled surface with per-category granularity.
Preserving strict per-space configuration would require a second
override table keyed by (user × collective × category × channel),
which the UX design (see docs/communications-architecture.md and the
Communications Settings UX proposal) deliberately rejects in favour of
a single-page, one-decision-per-category surface. Members whose old
per-space choices differed can adjust the new setting from
``/settings/communications``; per-creator/per-collective silencing of
Updates specifically is handled by a separate ``broadcast_silences``
table (Milestone 10).

The old ``space_member_notification_prefs`` table is **not dropped**
in this migration. It continues to back
``GET/PATCH /api/spaces/{slug}/notification-settings`` until Milestone
15's retirement pass. This is deliberate — a rollback of the new
Communications Layer must not lose members' pre-migration choices.

Consent records: **no seeding of implicit ToS / Privacy consent** for
existing users. Consent records only exist where genuine evidence of a
user's action is available. Existing users start with an empty consent
state; capture surfaces in later milestones (M9) record real evidence
going forward.

Downgrade drops all three tables and the two enum types. Old
per-space prefs are untouched.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

CONSENT_KIND_ENUM_NAME = "communication_consent_kind_enum"
CONSENT_STATE_ENUM_NAME = "communication_consent_state_enum"

CONSENT_KINDS = (
    "terms_of_service",
    "privacy_policy",
    "marketing",
    "product_updates",
    "creator_broadcast",
)
CONSENT_STATES = ("granted", "revoked")


# ---------------------------------------------------------------------------
# Backfill helpers — module-level so tests can import and exercise them
# against seeded data without running Alembic.
# ---------------------------------------------------------------------------

# Reduction rules — see module docstring for the "most immediate wins"
# rationale. Each rule maps a (category_key, channel) tuple to an
# ordered list of ``(priority, condition_groups)`` checks. Each
# ``condition_groups`` is a list of column-lists interpreted as
# **DNF** (disjunctive normal form):
#
#   * outer list → OR
#   * inner list → AND
#
# So the rule ``[["a"], ["b"]]`` reads "a=True OR b=True", while
# ``[["push_enabled", "push_replies"]]`` reads "push_enabled AND
# push_replies both True".
#
# The first priority whose condition groups are satisfied by ANY of
# the user's rows wins.
BACKFILL_RULES: dict[tuple[str, str], list[tuple[str, list[list[str]]]]] = {
    # Community — new posts OR comment replies are immediate; digest
    # columns provide the fallback cadence.
    ("community", "email_transactional"): [
        ("immediate",     [["new_post_email"], ["comment_reply_email"]]),
        ("daily_digest",  [["daily_digest_email"]]),
        ("weekly_digest", [["weekly_digest_email"]]),
    ],
    ("community", "push"): [
        # Push needs master switch AND topic switch — hence one AND-group.
        ("immediate",     [["push_enabled", "push_replies"]]),
    ],

    # Pathways — new pathway published OR step comments.
    ("pathways", "email_transactional"): [
        ("immediate",     [["new_pathway_email"], ["pathway_comment_email"]]),
    ],
    # No push mapping for pathways in the old model.

    # Gatherings — reminders + push reminders.
    ("gatherings", "email_transactional"): [
        ("immediate",     [["gathering_reminder_email"]]),
    ],
    ("gatherings", "push"): [
        ("immediate",     [["push_enabled", "push_gathering_reminders"]]),
    ],

    # Creator Updates — the old ``admin_broadcast`` column carried
    # what we now call Creator Updates (per the "Broadcasts → Updates"
    # rename).
    ("creator_updates", "email_transactional"): [
        ("immediate",     [["admin_broadcast_email"]]),
    ],
    ("creator_updates", "push"): [
        ("immediate",     [["push_enabled", "push_announcements"]]),
    ],

    # Categories the old model did not cover — account, safety,
    # purchases, messages, platform_updates — are left to their
    # channel defaults from migration 097.
}


def _row_satisfies_group(row: dict, group: list[str]) -> bool:
    """A row satisfies an AND-group when every column in the group is
    truthy on it. Missing columns are treated as False (defensive
    against schema drift).
    """
    return all(bool(row.get(col, False)) for col in group)


def _resolve_priority(
    user_rows: list[dict],
    rules: list[tuple[str, list[list[str]]]],
) -> str | None:
    """Walk the ordered priority checks. The first priority whose
    condition (DNF: any OR-group whose all AND-columns are true) is
    satisfied by ANY of the user's rows wins. Returns None if no rule
    matches — the caller leaves the category default in place.
    """
    for priority, condition_groups in rules:
        for row in user_rows:
            for group in condition_groups:
                if _row_satisfies_group(row, group):
                    return priority
    return None


def _run_backfill(connection) -> None:
    """Aggregate legacy per-space rows into platform-wide preferences.
    Extracted so tests can exercise the same logic against seeded data
    without invoking Alembic.
    """
    # Pull every old row into memory, group by user_id. The table is
    # small in practice (bounded by users × collectives-they-belong-to)
    # so this is acceptable for the migration.
    old_rows = connection.execute(
        sa.text(
            """
            SELECT user_id,
                   weekly_digest_email,
                   daily_digest_email,
                   admin_broadcast_email,
                   gathering_reminder_email,
                   new_post_email,
                   comment_reply_email,
                   pathway_comment_email,
                   new_pathway_email,
                   push_enabled,
                   push_gathering_reminders,
                   push_replies,
                   push_announcements
              FROM space_member_notification_prefs
            """
        )
    ).mappings().all()

    by_user: dict[str, list[dict]] = {}
    for r in old_rows:
        by_user.setdefault(r["user_id"], []).append(dict(r))

    # Insert one preference row per (user, category, channel) where a
    # rule matched. UNIQUE constraint means re-running is safe (ON
    # CONFLICT DO NOTHING keeps the first write).
    import uuid as _uuid

    insert_stmt = sa.text(
        """
        INSERT INTO communication_preferences
            (id, user_id, category_key, channel, priority, updated_at)
        VALUES
            (:id, :user_id, :category_key, :channel, :priority, NOW())
        ON CONFLICT (user_id, category_key, channel) DO NOTHING
        """
    )

    for user_id, rows in by_user.items():
        for (category, channel), rules in BACKFILL_RULES.items():
            resolved = _resolve_priority(rows, rules)
            if resolved is None:
                continue
            connection.execute(
                insert_stmt,
                {
                    "id": f"cpr_{_uuid.uuid4().hex[:12]}",
                    "user_id": user_id,
                    "category_key": category,
                    "channel": channel,
                    "priority": resolved,
                },
            )


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    consent_kind_enum = postgresql.ENUM(
        *CONSENT_KINDS, name=CONSENT_KIND_ENUM_NAME,
    )
    consent_state_enum = postgresql.ENUM(
        *CONSENT_STATES, name=CONSENT_STATE_ENUM_NAME,
    )
    # Reuse the enums defined in migration 097 without re-creating them.
    channel_enum = postgresql.ENUM(
        name="communication_channel_enum",
        create_type=False,
    )
    priority_enum = postgresql.ENUM(
        name="communication_priority_enum",
        create_type=False,
    )

    # ── communication_preferences ────────────────────────────────────
    op.create_table(
        "communication_preferences",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_key",
            sa.String(64),
            sa.ForeignKey("communication_categories.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column("priority", priority_enum, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "category_key", "channel",
            name="uq_comm_pref_user_category_channel",
        ),
    )
    op.create_index(
        "ix_communication_preferences_user",
        "communication_preferences",
        ["user_id"],
    )

    # ── communication_consents (append-only) ──────────────────────────
    op.create_table(
        "communication_consents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("consent_kind", consent_kind_enum, nullable=False),
        sa.Column("state", consent_state_enum, nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=True),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("evidence_ip_hash", sa.String(128), nullable=True),
        sa.Column("evidence_ua_hash", sa.String(128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_communication_consents_user_kind_occurred_at",
        "communication_consents",
        ["user_id", "consent_kind", sa.text("occurred_at DESC")],
    )

    # ── communication_member_settings ─────────────────────────────────
    op.create_table(
        "communication_member_settings",
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # IANA timezone. NULL → server-side UTC / member has not set.
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("quiet_hours_start_local", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end_local", sa.Time(), nullable=True),
        sa.Column("daily_digest_send_local_time", sa.Time(), nullable=True),
        # ISO weekday: 0=Monday .. 6=Sunday.
        sa.Column("weekly_digest_send_local_weekday", sa.SmallInteger(), nullable=True),
        sa.Column("weekly_digest_send_local_time", sa.Time(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── Backfill ──────────────────────────────────────────────────────
    _run_backfill(op.get_bind())

    # NOTE: no consent seeding for existing users. Consent records only
    # exist where genuine evidence of a user's action is available.


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_table("communication_member_settings")

    op.drop_index(
        "ix_communication_consents_user_kind_occurred_at",
        table_name="communication_consents",
    )
    op.drop_table("communication_consents")

    op.drop_index(
        "ix_communication_preferences_user",
        table_name="communication_preferences",
    )
    op.drop_table("communication_preferences")

    sa.Enum(name=CONSENT_STATE_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=CONSENT_KIND_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
