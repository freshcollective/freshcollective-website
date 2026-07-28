"""Activity Engine — platform-wide event hub.

Revision ID: 090
Revises: 089
Create Date: 2026-07-28

Creates the ``activities`` table that becomes the single source of
truth for notifications, dashboard activity, email digests, future push
notifications and future "My World" history.

Features never send emails or notifications directly. They create an
Activity Event via ``ActivityService.create``; delivery channels
subscribe to those events. See ``app/models/activity.py`` for the
event-type catalogue and priority defaults.

The existing ``notifications`` table + service are unchanged — this
migration adds the Activity Engine alongside them.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("id", sa.String(), primary_key=True),

        # ── Event identity ───────────────────────────────────────────
        # Stored as string so migrations can add new event types
        # without an ALTER TYPE. Validation lives in Python.
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("category",   sa.String(length=32), nullable=False),
        sa.Column("priority",   sa.String(length=16), nullable=False),

        # ── Who ──────────────────────────────────────────────────────
        # actor may be null for system-generated events (e.g. a
        # subscription renewal invoiced by Stripe on the platform's
        # behalf).
        sa.Column(
            "actor_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recipient_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),

        # ── Subject entities — all nullable, ON DELETE SET NULL so the
        # activity record survives the deletion of its subject. ───────
        sa.Column(
            "collective_id",
            sa.String(),
            sa.ForeignKey("spaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "pathway_id",
            sa.String(),
            sa.ForeignKey("pathways.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "gathering_id",
            sa.String(),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("community_posts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resource_id",
            sa.String(),
            sa.ForeignKey("space_resources.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # ── Human-readable payload (title, message, url, actor_name,
        # etc.) so delivery channels don't need extra joins to render.
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),

        # ── Delivery state timestamps ────────────────────────────────
        sa.Column("read_at",     sa.DateTime(timezone=False), nullable=True),
        sa.Column("emailed_at",  sa.DateTime(timezone=False), nullable=True),
        sa.Column("pushed_at",   sa.DateTime(timezone=False), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=False), nullable=True),

        # ── Timestamps ───────────────────────────────────────────────
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Recipient-first indexes — every notification-centre query starts
    # with the signed-in user and orders newest-first.
    op.create_index(
        "ix_activities_recipient_created",
        "activities",
        ["recipient_user_id", "created_at"],
    )
    op.create_index(
        "ix_activities_recipient_unread",
        "activities",
        ["recipient_user_id", "read_at"],
    )
    # Collective feed (Creator Dashboard).
    op.create_index(
        "ix_activities_collective_created",
        "activities",
        ["collective_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_activities_collective_created", table_name="activities")
    op.drop_index("ix_activities_recipient_unread",   table_name="activities")
    op.drop_index("ix_activities_recipient_created",  table_name="activities")
    op.drop_table("activities")
