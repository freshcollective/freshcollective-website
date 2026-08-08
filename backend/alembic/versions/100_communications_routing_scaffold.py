"""Communications — routing scaffold (Milestone 5a).

Revision ID: 100
Revises: 099
Create Date: 2026-08-08

Prepares the schema for the M5 routing engine. Purely additive.

Adds:

  * ``delivery_mode`` column on ``communication_intents`` — an
    immutable enum that structurally separates shadow observations
    from live delivery. The worker will only ever claim
    ``delivery_mode='live'``, so a shadow intent stuck in
    ``state='queued'`` can never be dispatched, regardless of worker
    configuration or which topics later flip live.
  * ``communication_digest_items`` — the buffer M13's digest worker
    will consume. When the M5b decision layer resolves a priority of
    ``daily_digest`` or ``weekly_digest``, it inserts one row here
    rather than creating a queued intent. The ordinary M4 worker
    never touches this table, so digest items can never be
    accidentally dispatched as individual sends.
  * ``communication_suppressions`` — hard-block list keyed by hashed
    address. Brought forward from M6 so the M5b decision layer can
    read it. M6 will populate/update from inbound provider webhooks;
    M5 supports admin-manual entries only.
  * ``communication_shadow_comparisons`` — reconciliation records
    produced by the M5c cron. One row per event compared, with
    parity verdict and discrepancy notes. Deprecated after every
    topic is live and dropped in the M15 cleanup pass.

Enums created:

  * ``communication_delivery_mode_enum``               : shadow | live
  * ``communication_digest_cadence_enum``              : daily | weekly
  * ``communication_suppression_reason_enum``          : bounced | complained | manual | unsubscribed
  * ``communication_suppression_address_type_enum``    : email | phone | push_token
  * ``communication_shadow_parity_enum``               : match | shadow_extra | legacy_extra | payload_mismatch

ARCHITECTURE NOTE — shadow mode is observational only
-----------------------------------------------------

The ``delivery_mode`` column exists to enforce a hard architectural
invariant: **shadow-mode communications are observations of what the
new routing pipeline would have produced; they must never influence
production delivery behaviour.**

Concretely:

  * The dispatch worker (``app.comms.worker``) filters
    ``delivery_mode = 'live'`` in its claim SQL. Shadow intents are
    structurally invisible to it — no configuration change can
    override this.
  * Existing legacy communication code paths
    (``notification_service.trigger_*``, ``email_service.send``,
    ``notifications/routes.py``, ``messages/routes.py`` etc.)
    remain entirely responsible for production sends until each
    topic is explicitly moved into ``COMMS_LIVE_TOPICS`` (M5c).
  * Enabling ``COMMS_SHADOW=true`` in production produces intents
    for observation only. It does not produce any user-visible
    communication. Whoever is on-call can turn shadow on and off
    with zero delivery impact.

Downgrade drops all of the above (column, tables, enums) cleanly.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None


DELIVERY_MODE_ENUM_NAME = "communication_delivery_mode_enum"
DIGEST_CADENCE_ENUM_NAME = "communication_digest_cadence_enum"
SUPPRESSION_REASON_ENUM_NAME = "communication_suppression_reason_enum"
SUPPRESSION_ADDRESS_TYPE_ENUM_NAME = "communication_suppression_address_type_enum"
SHADOW_PARITY_ENUM_NAME = "communication_shadow_parity_enum"

DELIVERY_MODES = ("shadow", "live")
DIGEST_CADENCES = ("daily", "weekly")
SUPPRESSION_REASONS = ("bounced", "complained", "manual", "unsubscribed")
SUPPRESSION_ADDRESS_TYPES = ("email", "phone", "push_token")
SHADOW_PARITY_VERDICTS = ("match", "shadow_extra", "legacy_extra", "payload_mismatch")


def upgrade() -> None:
    bind = op.get_bind()

    # Enum types — created explicitly so the ADD COLUMN below can
    # reference them without SQLAlchemy trying to re-create them.
    delivery_mode_enum = postgresql.ENUM(*DELIVERY_MODES, name=DELIVERY_MODE_ENUM_NAME)
    delivery_mode_enum.create(bind, checkfirst=True)

    digest_cadence_enum = postgresql.ENUM(*DIGEST_CADENCES, name=DIGEST_CADENCE_ENUM_NAME)
    digest_cadence_enum.create(bind, checkfirst=True)

    suppression_reason_enum = postgresql.ENUM(
        *SUPPRESSION_REASONS, name=SUPPRESSION_REASON_ENUM_NAME,
    )
    suppression_reason_enum.create(bind, checkfirst=True)

    suppression_address_type_enum = postgresql.ENUM(
        *SUPPRESSION_ADDRESS_TYPES, name=SUPPRESSION_ADDRESS_TYPE_ENUM_NAME,
    )
    suppression_address_type_enum.create(bind, checkfirst=True)

    shadow_parity_enum = postgresql.ENUM(
        *SHADOW_PARITY_VERDICTS, name=SHADOW_PARITY_ENUM_NAME,
    )
    shadow_parity_enum.create(bind, checkfirst=True)

    # Reuse enums from earlier migrations.
    source_type_enum = postgresql.ENUM(
        name="communication_source_type_enum", create_type=False,
    )

    # ── communication_intents.delivery_mode ──────────────────────────
    # Server default 'live' backfills existing rows and keeps ad-hoc
    # SQL inserts safe. Application code always passes the value
    # explicitly via ``create_intent``, so the default is a safety
    # net rather than a routine convenience.
    op.add_column(
        "communication_intents",
        sa.Column(
            "delivery_mode",
            postgresql.ENUM(
                name=DELIVERY_MODE_ENUM_NAME, create_type=False,
            ),
            nullable=False,
            server_default="live",
        ),
    )

    # ── communication_digest_items ───────────────────────────────────
    op.create_table(
        "communication_digest_items",
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
            sa.ForeignKey("communication_categories.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cadence",
            postgresql.ENUM(name=DIGEST_CADENCE_ENUM_NAME, create_type=False),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("communication_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("human_reason", sa.String(240), nullable=False),
        # Structured summary the M13 digest renderer will read to
        # build one line per item in the aggregated email.
        sa.Column(
            "item_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("scheduled_window_start", sa.DateTime(timezone=False), nullable=False),
        sa.Column("scheduled_window_end", sa.DateTime(timezone=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "consumed_by_intent_id",
            sa.String(),
            sa.ForeignKey("communication_intents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Partial index for the M13 digest worker: only unconsumed items
    # need to be visited each tick.
    op.execute(
        """
        CREATE INDEX ix_communication_digest_items_pending
                  ON communication_digest_items
                     (user_id, category_key, cadence, scheduled_window_end)
               WHERE consumed_at IS NULL
        """
    )
    op.create_index(
        "ix_communication_digest_items_event",
        "communication_digest_items",
        ["event_id"],
    )

    # ── communication_suppressions ───────────────────────────────────
    op.create_table(
        "communication_suppressions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "address_type",
            postgresql.ENUM(
                name=SUPPRESSION_ADDRESS_TYPE_ENUM_NAME, create_type=False,
            ),
            nullable=False,
        ),
        # SHA-256 hex digest of the normalised address. Storing the
        # hash rather than the address means bounce lists don't
        # retain PII while still supporting exact-match lookups.
        sa.Column("address_value_hash", sa.String(64), nullable=False),
        sa.Column(
            "reason",
            postgresql.ENUM(
                name=SUPPRESSION_REASON_ENUM_NAME, create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("source_provider", sa.String(64), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "address_type", "address_value_hash",
            name="uq_comm_suppression_address",
        ),
    )

    # ── communication_shadow_comparisons ─────────────────────────────
    op.create_table(
        "communication_shadow_comparisons",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("communication_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column(
            "shadow_intent_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "legacy_notification_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "parity",
            postgresql.ENUM(name=SHADOW_PARITY_ENUM_NAME, create_type=False),
            nullable=False,
        ),
        sa.Column("discrepancy_detail", sa.Text(), nullable=True),
        sa.Column(
            "compared_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "event_id", name="uq_comm_shadow_comparison_event",
        ),
    )
    op.create_index(
        "ix_communication_shadow_comparisons_topic_compared",
        "communication_shadow_comparisons",
        ["topic_key", sa.text("compared_at DESC")],
    )
    op.execute(
        """
        CREATE INDEX ix_communication_shadow_comparisons_discrepancies
                  ON communication_shadow_comparisons
                     (parity, compared_at DESC)
               WHERE parity != 'match'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_communication_shadow_comparisons_discrepancies")
    op.drop_index(
        "ix_communication_shadow_comparisons_topic_compared",
        table_name="communication_shadow_comparisons",
    )
    op.drop_table("communication_shadow_comparisons")

    op.drop_table("communication_suppressions")

    op.drop_index(
        "ix_communication_digest_items_event",
        table_name="communication_digest_items",
    )
    op.execute("DROP INDEX IF EXISTS ix_communication_digest_items_pending")
    op.drop_table("communication_digest_items")

    op.drop_column("communication_intents", "delivery_mode")

    bind = op.get_bind()
    sa.Enum(name=SHADOW_PARITY_ENUM_NAME).drop(bind, checkfirst=True)
    sa.Enum(name=SUPPRESSION_ADDRESS_TYPE_ENUM_NAME).drop(bind, checkfirst=True)
    sa.Enum(name=SUPPRESSION_REASON_ENUM_NAME).drop(bind, checkfirst=True)
    sa.Enum(name=DIGEST_CADENCE_ENUM_NAME).drop(bind, checkfirst=True)
    sa.Enum(name=DELIVERY_MODE_ENUM_NAME).drop(bind, checkfirst=True)
