"""Communications — intents + deliveries (Milestone 4).

Revision ID: 099
Revises: 098
Create Date: 2026-08-08

Adds the intent + delivery layer of the Communications Layer.
Intents are one-per-recipient-per-channel decisions with enough
information to dispatch and audit; deliveries are the per-attempt
provider records that back webhook correlation and retry accounting.

Tables created:

  * ``communication_intents``     — one row per (event × recipient ×
                                     channel) decision. Carries the
                                     rendered payload snapshot plus
                                     the template provenance
                                     (``template_key``, ``template_version``,
                                     ``template_context``) so future
                                     re-rendering has full context.
  * ``communication_deliveries``  — one row per provider send attempt
                                     against an intent. Records the
                                     RenderedPayload + ProviderResult
                                     snapshots for full audit.

Enums created:

  * ``communication_intent_state_enum``  — queued | dispatching | sent
                                            | delivered | bounced |
                                            complained | failed |
                                            suppressed | recorded
  * ``communication_delivery_status_enum`` — pending | accepted | failed

Intent state machine:

    (creation)
       │
       ├── priority=silent  ────►  recorded (terminal)
       │
       └── everything else  ────►  queued
                                     │
                                     ├── worker claim  ►  dispatching
                                     │                      │
                                     │                      ├── provider accepted  ►  sent
                                     │                      │                          │
                                     │                      │                          ├── delivered  ┐
                                     │                      │                          ├── bounced    │─ terminal
                                     │                      │                          └── complained ┘
                                     │                      │
                                     │                      └── provider rejected  ►  failed (terminal)
                                     │
                                     └── decision layer  ►  suppressed (terminal)

The ``dispatching`` state is deliberately introduced between ``queued``
and ``sent`` so a worker crash mid-send leaves visible evidence rather
than losing the intent. A future recovery job can find intents stuck
in ``dispatching`` past a threshold and either retry or mark them
failed. This milestone does not implement that job — the state is the
foundation.

No data migration. No existing table altered. Purely additive.
Downgrade drops both tables and both enums.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None


INTENT_STATE_ENUM_NAME = "communication_intent_state_enum"
DELIVERY_STATUS_ENUM_NAME = "communication_delivery_status_enum"

INTENT_STATES = (
    "queued",
    "dispatching",
    "sent",
    "delivered",
    "bounced",
    "complained",
    "failed",
    "suppressed",
    "recorded",
)
DELIVERY_STATUSES = ("pending", "accepted", "failed")


def upgrade() -> None:
    intent_state_enum = postgresql.ENUM(
        *INTENT_STATES, name=INTENT_STATE_ENUM_NAME,
    )
    delivery_status_enum = postgresql.ENUM(
        *DELIVERY_STATUSES, name=DELIVERY_STATUS_ENUM_NAME,
    )
    # Enums defined by earlier migrations — reuse via create_type=False.
    source_type_enum = postgresql.ENUM(
        name="communication_source_type_enum", create_type=False,
    )
    channel_enum = postgresql.ENUM(
        name="communication_channel_enum", create_type=False,
    )
    priority_enum = postgresql.ENUM(
        name="communication_priority_enum", create_type=False,
    )

    # ── communication_intents ────────────────────────────────────────
    op.create_table(
        "communication_intents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("communication_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recipient_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # The payload "to" — email address, user id, push token, or
        # URL depending on channel. Kept independent of
        # recipient_user_id so outbound webhooks (Milestone 12) can
        # target URLs without a user.
        sa.Column("recipient_address", sa.Text(), nullable=False),
        # Denormalised from the event for efficient history queries.
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column(
            "category_key",
            sa.String(64),
            sa.ForeignKey("communication_categories.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "topic_key",
            sa.String(64),
            sa.ForeignKey("communication_topics.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column("priority", priority_enum, nullable=False),
        # Provider chosen at intent creation. The worker looks it up
        # via the providers registry. Not a FK — providers are code
        # constants, not DB rows.
        sa.Column("provider_key", sa.String(64), nullable=False),
        # Template provenance. Rendered payload is stored alongside
        # so we can display / audit what was sent, and template_key +
        # template_version + template_context let us reconstruct or
        # re-render if we ever need to.
        sa.Column("template_key", sa.String(200), nullable=True),
        sa.Column("template_version", sa.String(64), nullable=True),
        sa.Column("template_context", sa.JSON(), nullable=True),
        # Refinement 3: transparency field, shown to the member in
        # history + email footers.
        sa.Column("human_reason", sa.String(240), nullable=False),
        # Rendered snapshot — what was actually built for delivery.
        sa.Column("payload_subject", sa.Text(), nullable=False),
        sa.Column("payload_body_html", sa.Text(), nullable=True),
        sa.Column("payload_body_text", sa.Text(), nullable=True),
        sa.Column(
            "payload_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        # NULL → dispatch as soon as the worker picks it up.
        sa.Column("scheduled_for", sa.DateTime(timezone=False), nullable=True),
        sa.Column("state", intent_state_enum, nullable=False),
        sa.Column("suppression_reason", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("dispatching_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=False), nullable=True),
    )
    # Worker poll — narrow index on the small subset of intents
    # awaiting dispatch. Partial to keep the index tiny under load.
    op.execute(
        """
        CREATE INDEX ix_communication_intents_queued
                  ON communication_intents (scheduled_for NULLS FIRST, created_at)
               WHERE state = 'queued'
        """
    )
    op.create_index(
        "ix_communication_intents_recipient_created",
        "communication_intents",
        ["recipient_user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_communication_intents_event",
        "communication_intents",
        ["event_id"],
    )
    # Dedupe protection for M5's decision layer — one intent per
    # (event, recipient, channel). Enforced only when event_id is
    # non-NULL so ad-hoc intents (no upstream event) aren't blocked.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_communication_intents_event_recipient_channel
                     ON communication_intents (event_id, recipient_user_id, channel)
                  WHERE event_id IS NOT NULL
        """
    )

    # ── communication_deliveries ─────────────────────────────────────
    op.create_table(
        "communication_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "intent_id",
            sa.String(),
            sa.ForeignKey("communication_intents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column("status", delivery_status_enum, nullable=False),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        # Full RenderedPayload + ProviderResult snapshots. These are
        # verbose but small; keeping them enables reproducible debug
        # and webhook correlation without a second lookup path.
        sa.Column(
            "request_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "response_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("error_class", sa.String(120), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=False), nullable=True),
        sa.UniqueConstraint(
            "intent_id", "attempt_number",
            name="uq_comm_delivery_intent_attempt",
        ),
    )
    # Webhook correlation — providers give us a message_id we later
    # match against inbound bounce / complaint / open events.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_communication_deliveries_provider_message
                     ON communication_deliveries (provider_key, provider_message_id)
                  WHERE provider_message_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_communication_deliveries_provider_message")
    op.drop_table("communication_deliveries")

    op.execute("DROP INDEX IF EXISTS ux_communication_intents_event_recipient_channel")
    op.drop_index(
        "ix_communication_intents_event",
        table_name="communication_intents",
    )
    op.drop_index(
        "ix_communication_intents_recipient_created",
        table_name="communication_intents",
    )
    op.execute("DROP INDEX IF EXISTS ix_communication_intents_queued")
    op.drop_table("communication_intents")

    sa.Enum(name=DELIVERY_STATUS_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=INTENT_STATE_ENUM_NAME).drop(op.get_bind(), checkfirst=True)
