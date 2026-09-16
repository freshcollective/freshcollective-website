"""Creator subscription Stripe lifecycle columns + webhook dedup table.

Revision ID: 131
Revises: 130
Create Date: 2026-09-16

Motivation
----------
Backs the Creator / Pro monthly Stripe subscription workstream. Adds
the minimum lifecycle state required to reflect Stripe truthfully in
the FC ``creator_subscriptions`` row without inventing new statuses,
and adds a small dedup table so webhook handlers are idempotent by
Stripe event id.

New columns on ``creator_subscriptions``:
  * ``current_period_end``           — renewal date (from Stripe).
  * ``cancel_at_period_end``         — cancellation scheduled flag.
  * ``grace_expires_at``             — FC 7-day grace after failed
                                       invoice.
  * ``pending_downgrade_plan_id``    — Stripe Subscription Schedule
                                       target (Pro → Creator at
                                       period end).
  * ``pending_downgrade_effective_at``
  * ``stripe_subscription_schedule_id``

New table ``stripe_webhook_events`` (dedup) — small, additive:
  * ``id``              — Stripe event.id (PK).
  * ``event_type``      — for observability + partial indexing later.
  * ``received_at``     — DEFAULT NOW.
  * ``processed_at``    — set once a handler completes without raising.
  * ``payload_sha256``  — defence against replay-with-mutation.

Safety
------
* Additive only. Every new column is nullable / has a safe default,
  so existing rows stay valid without a data migration.
* No table renames, no drops, no destructive changes.
* Runs under ``preDeployCommand: alembic upgrade head`` — see
  ``render.yaml``'s migration policy at the top of the file.
"""

import sqlalchemy as sa
from alembic import op


revision = "131"
down_revision = "130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- creator_subscriptions lifecycle columns -------------------------
    op.add_column(
        "creator_subscriptions",
        sa.Column("current_period_end", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column("grace_expires_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column("pending_downgrade_plan_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "creator_subscriptions_pending_downgrade_plan_id_fkey",
        source_table="creator_subscriptions",
        referent_table="creator_plans",
        local_cols=["pending_downgrade_plan_id"],
        remote_cols=["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column(
            "pending_downgrade_effective_at",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column(
            "stripe_subscription_schedule_id", sa.String(length=200), nullable=True,
        ),
    )

    # -- stripe_webhook_events dedup table -------------------------------
    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_stripe_webhook_events_type",
        "stripe_webhook_events",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_webhook_events_type", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")
    op.drop_column("creator_subscriptions", "stripe_subscription_schedule_id")
    op.drop_column("creator_subscriptions", "pending_downgrade_effective_at")
    op.drop_constraint(
        "creator_subscriptions_pending_downgrade_plan_id_fkey",
        "creator_subscriptions",
        type_="foreignkey",
    )
    op.drop_column("creator_subscriptions", "pending_downgrade_plan_id")
    op.drop_column("creator_subscriptions", "grace_expires_at")
    op.drop_column("creator_subscriptions", "cancel_at_period_end")
    op.drop_column("creator_subscriptions", "current_period_end")
