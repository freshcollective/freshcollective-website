"""FIP1 — create ``webhook_events`` table.

Revision ID: 117
Revises: 116
Create Date: 2026-08-14

Durable provider webhook-event idempotency store. The unique
constraint on ``(provider, provider_event_id)`` is the deduplication
boundary consumed by ``services/webhook_idempotency.py``.

Provider-agnostic on purpose — Stripe is the only current consumer,
but the same table can protect future webhook providers without
adding another table. See ``app/models/webhook_event.py`` for the
outcome-state semantics.

FIP1 introduces the table + helper. The existing three-event Stripe
handler (``checkout.session.completed`` /
``checkout.session.expired`` / ``payment_intent.payment_failed``) is
NOT refactored to use the helper in this migration — that is a
future housekeeping pass. FIP2's new handlers will use the helper
from day 1.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sa.Enum(create_type=True) inside op.create_table emits ONE
    # CREATE TYPE atomic with the table. Downgrade drops the type
    # after dropping the table.
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "provider", sa.String(20), nullable=False, server_default="stripe",
        ),
        sa.Column("provider_event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "pending", "succeeded", "skipped", "failed",
                name="webhook_event_outcome_enum",
                create_type=True,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "received_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        # Refreshed every time the row enters ``pending`` — used by
        # the idempotency helper to distinguish an in-flight worker
        # from a dead one. See app/services/webhook_idempotency.py.
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=False), nullable=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "attempt_count", sa.Integer, nullable=False, server_default="1",
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "provider", "provider_event_id",
            name="uq_webhook_events_provider_event_id",
        ),
    )

    op.create_index(
        "ix_webhook_events_event_type", "webhook_events", ["event_type"],
    )
    op.create_index(
        "ix_webhook_events_outcome", "webhook_events", ["outcome"],
    )
    op.create_index(
        "ix_webhook_events_received_at", "webhook_events", ["received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_received_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_outcome", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.execute("DROP TYPE webhook_event_outcome_enum")
