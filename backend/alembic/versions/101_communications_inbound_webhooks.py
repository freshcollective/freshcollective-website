"""Communications — inbound webhooks + delivery outcomes (Milestone 6).

Revision ID: 101
Revises: 100
Create Date: 2026-08-09

Closes the outbound feedback loop by giving the platform somewhere to
store provider webhook payloads and a place on the delivery row to
record what the provider ultimately said happened.

Adds:

  * ``communication_webhook_events`` — one row per received webhook
    payload. Raw payload + parse-side metadata + processed_at /
    process_error. Serves as the idempotency ledger (via a partial
    UNIQUE index on the provider's own event id when present), the
    audit trail (raw payload retained), and the replay substrate
    (future mapping changes can re-consume historic rows).
  * ``communication_deliveries.terminal_outcome`` — nullable enum
    ``delivered | bounced | complained`` set by the receiver when a
    provider webhook advances the delivery beyond the send-time
    ``status=accepted``. Kept distinct from ``status`` because "the
    provider accepted the request" and "the recipient's inbox
    accepted the message" are genuinely different questions.
  * ``communication_deliveries.terminal_outcome_at`` — timestamp.
  * ``communication_deliveries.bounce_class`` — nullable enum
    ``hard | soft`` populated on bounces. Drives suppression policy
    (M6 suppresses on hard bounces only).

Enums created:

  * ``communication_delivery_terminal_outcome_enum`` : delivered | bounced | complained
  * ``communication_delivery_bounce_class_enum``     : hard | soft

ARCHITECTURE NOTE — webhook events are provider observations, not user actions
-----------------------------------------------------------------------------

Every row in ``communication_webhook_events`` records what a *provider*
said it observed about a message. That is not the same as a user's
definitive action or expressed intent:

  * A ``delivered`` webhook means the recipient MTA accepted the
    handoff — not that a person read the message.
  * A ``bounced`` webhook means the provider's downstream refused
    delivery — the recipient may or may not know.
  * An ``opened`` / ``clicked`` webhook means the provider's tracking
    pixel or link-wrapper fired — accessible through email clients
    that block tracking, unpredictable across privacy settings.
  * An ``unsubscribed`` webhook means a link was clicked or a
    provider-managed opt-out was recorded — it is provider evidence
    of an unsubscribe signal, not a durable user consent statement.

These distinctions matter downstream. Suppression policy consumes
webhook events (a hard bounce protects future sends). Consent state
does not — consent is a member's own action captured through
Fresh Collective's own surfaces (M2, M9). M6 records unsubscribe
webhooks as suppression signals only. It does not mutate consent
records from provider payloads. Any future change that lets
providers influence consent must be an explicit, reviewed
architectural decision, not an incremental extension.

Downgrade drops all of the above cleanly.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "101"
down_revision = "100"
branch_labels = None
depends_on = None


TERMINAL_OUTCOME_ENUM_NAME = "communication_delivery_terminal_outcome_enum"
BOUNCE_CLASS_ENUM_NAME = "communication_delivery_bounce_class_enum"

TERMINAL_OUTCOMES = ("delivered", "bounced", "complained")
BOUNCE_CLASSES = ("hard", "soft")


def upgrade() -> None:
    bind = op.get_bind()

    terminal_outcome_enum = postgresql.ENUM(
        *TERMINAL_OUTCOMES, name=TERMINAL_OUTCOME_ENUM_NAME,
    )
    terminal_outcome_enum.create(bind, checkfirst=True)

    bounce_class_enum = postgresql.ENUM(
        *BOUNCE_CLASSES, name=BOUNCE_CLASS_ENUM_NAME,
    )
    bounce_class_enum.create(bind, checkfirst=True)

    # ── communication_webhook_events ──────────────────────────────────
    op.create_table(
        "communication_webhook_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider_key", sa.String(64), nullable=False),
        # Provider's own event id — used as the idempotency key.
        # NULL is allowed for providers that don't supply one; those
        # rows fall through to the downstream state machine + suppression
        # helper for effective-idempotency.
        sa.Column("provider_event_id", sa.String(200), nullable=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        # Correlation to communication_deliveries.provider_message_id.
        # Nullable — unsubscribe payloads without a message context
        # still land here.
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "raw_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("process_error", sa.Text(), nullable=True),
    )
    # Idempotency — partial unique on the provider's event id.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_communication_webhook_events_provider_event
                     ON communication_webhook_events (provider_key, provider_event_id)
                  WHERE provider_event_id IS NOT NULL
        """
    )
    op.create_index(
        "ix_communication_webhook_events_provider_received",
        "communication_webhook_events",
        ["provider_key", sa.text("received_at DESC")],
    )
    op.execute(
        """
        CREATE INDEX ix_communication_webhook_events_message_id
                  ON communication_webhook_events (provider_message_id)
               WHERE provider_message_id IS NOT NULL
        """
    )
    # Partial index for admin surface: unprocessed / errored rows.
    op.execute(
        """
        CREATE INDEX ix_communication_webhook_events_unprocessed
                  ON communication_webhook_events (received_at DESC)
               WHERE processed_at IS NULL
        """
    )

    # ── delivery outcome columns ─────────────────────────────────────
    op.add_column(
        "communication_deliveries",
        sa.Column(
            "terminal_outcome",
            postgresql.ENUM(
                name=TERMINAL_OUTCOME_ENUM_NAME, create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "communication_deliveries",
        sa.Column("terminal_outcome_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "communication_deliveries",
        sa.Column(
            "bounce_class",
            postgresql.ENUM(
                name=BOUNCE_CLASS_ENUM_NAME, create_type=False,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("communication_deliveries", "bounce_class")
    op.drop_column("communication_deliveries", "terminal_outcome_at")
    op.drop_column("communication_deliveries", "terminal_outcome")

    op.execute("DROP INDEX IF EXISTS ix_communication_webhook_events_unprocessed")
    op.execute("DROP INDEX IF EXISTS ix_communication_webhook_events_message_id")
    op.drop_index(
        "ix_communication_webhook_events_provider_received",
        table_name="communication_webhook_events",
    )
    op.execute("DROP INDEX IF EXISTS ux_communication_webhook_events_provider_event")
    op.drop_table("communication_webhook_events")

    bind = op.get_bind()
    sa.Enum(name=BOUNCE_CLASS_ENUM_NAME).drop(bind, checkfirst=True)
    sa.Enum(name=TERMINAL_OUTCOME_ENUM_NAME).drop(bind, checkfirst=True)
