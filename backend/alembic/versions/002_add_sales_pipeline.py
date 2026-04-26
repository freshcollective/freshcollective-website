"""Add admin sales pipeline tables and seed initial plan/price.

Revision ID: 002
Revises: 001
Create Date: 2026-04-26

Tables created:
  subscription_plans
  subscription_prices
  sales_leads
  sales_opportunities
  sales_activities
  sales_tasks
  member_subscriptions

Enum types created (PostgreSQL):
  billing_interval_enum
  lead_status_enum
  pipeline_stage_enum
  interest_level_enum
  activity_type_enum
  subscription_status_enum

Seed data (idempotent — will not duplicate on re-run):
  1 x SubscriptionPlan: 'Fresh Collective Membership'
  1 x SubscriptionPrice: AUD $39.00 / month (3900 cents)
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Enum definitions
# ---------------------------------------------------------------------------
# Each enum type is created once via raw SQL (no auto-create), and referenced
# in create_table calls using PGEnum(..., create_type=False).

ENUM_DEFS = [
    ("billing_interval_enum",    ["monthly", "quarterly", "annual"]),
    ("lead_status_enum",         ["prospect", "free_user", "trialing", "active", "paused", "cancelled", "past_due", "lost"]),
    ("pipeline_stage_enum",      ["new_lead", "contacted", "qualified", "invited", "trial_or_free_user", "sales_conversation", "checkout_sent", "won", "lost", "nurture"]),
    ("interest_level_enum",      ["low", "medium", "high", "very_high"]),
    ("activity_type_enum",       ["note", "call", "email", "message", "meeting", "follow_up", "other"]),
    ("subscription_status_enum", ["trialing", "active", "paused", "cancelled", "past_due"]),
]


def _pg_enum(*values: str, name: str) -> PGEnum:
    """Return a PostgreSQL ENUM column type that references an already-created type."""
    return PGEnum(*values, name=name, create_type=False)


# Pre-build the enum column types so they're easy to reference below
billing_interval_col = _pg_enum("monthly", "quarterly", "annual", name="billing_interval_enum")
lead_status_col      = _pg_enum("prospect", "free_user", "trialing", "active", "paused", "cancelled", "past_due", "lost", name="lead_status_enum")
pipeline_stage_col   = _pg_enum("new_lead", "contacted", "qualified", "invited", "trial_or_free_user", "sales_conversation", "checkout_sent", "won", "lost", "nurture", name="pipeline_stage_enum")
interest_level_col   = _pg_enum("low", "medium", "high", "very_high", name="interest_level_enum")
activity_type_col    = _pg_enum("note", "call", "email", "message", "meeting", "follow_up", "other", name="activity_type_enum")
sub_status_col       = _pg_enum("trialing", "active", "paused", "cancelled", "past_due", name="subscription_status_enum")


def upgrade() -> None:
    conn = op.get_bind()

    # ── Create PostgreSQL enum types ──────────────────────────────────────
    for type_name, values in ENUM_DEFS:
        quoted = ", ".join(f"'{v}'" for v in values)
        conn.execute(sa.text(f"CREATE TYPE {type_name} AS ENUM ({quoted})"))

    # ── subscription_plans ────────────────────────────────────────────────
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
    )

    # ── subscription_prices ───────────────────────────────────────────────
    op.create_table(
        "subscription_prices",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("plan_id", sa.String, sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="AUD"),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("billing_interval", billing_interval_col, nullable=False, server_default="monthly"),
        sa.Column("effective_from", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("effective_to", sa.DateTime(timezone=False), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount_cents > 0", name="subscription_prices_amount_positive"),
    )
    op.create_index("ix_subscription_prices_plan_id", "subscription_prices", ["plan_id"])

    # ── sales_leads ───────────────────────────────────────────────────────
    op.create_table(
        "sales_leads",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("status", lead_status_col, nullable=False, server_default="prospect"),
        sa.Column("current_stage", pipeline_stage_col, nullable=False, server_default="new_lead"),
        sa.Column("interest_level", interest_level_col, nullable=True),
        sa.Column("notes_summary", sa.Text, nullable=True),
        sa.Column("converted_user_id", sa.String, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sales_leads_email", "sales_leads", ["email"])
    op.create_index("ix_sales_leads_converted_user_id", "sales_leads", ["converted_user_id"])

    # ── sales_opportunities ───────────────────────────────────────────────
    op.create_table(
        "sales_opportunities",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("lead_id", sa.String, sa.ForeignKey("sales_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.String, sa.ForeignKey("subscription_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("price_id", sa.String, sa.ForeignKey("subscription_prices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stage", pipeline_stage_col, nullable=False, server_default="new_lead"),
        sa.Column("estimated_value_cents", sa.Integer, nullable=True),
        sa.Column("probability", sa.Integer, nullable=True),
        sa.Column("expected_close_date", sa.DateTime(timezone=False), nullable=True),
        sa.Column("won_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("lost_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("lost_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 100)",
            name="sales_opportunities_probability_range",
        ),
    )
    op.create_index("ix_sales_opportunities_lead_id", "sales_opportunities", ["lead_id"])
    op.create_index("ix_sales_opportunities_plan_id", "sales_opportunities", ["plan_id"])

    # ── sales_activities ──────────────────────────────────────────────────
    op.create_table(
        "sales_activities",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("lead_id", sa.String, sa.ForeignKey("sales_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_id", sa.String, sa.ForeignKey("sales_opportunities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("activity_type", activity_type_col, nullable=False, server_default="note"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by_user_id", sa.String, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sales_activities_lead_id", "sales_activities", ["lead_id"])
    op.create_index("ix_sales_activities_opportunity_id", "sales_activities", ["opportunity_id"])

    # ── sales_tasks ───────────────────────────────────────────────────────
    op.create_table(
        "sales_tasks",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("lead_id", sa.String, sa.ForeignKey("sales_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_id", sa.String, sa.ForeignKey("sales_opportunities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("assigned_to_user_id", sa.String, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", sa.String, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sales_tasks_lead_id", "sales_tasks", ["lead_id"])
    op.create_index("ix_sales_tasks_opportunity_id", "sales_tasks", ["opportunity_id"])

    # ── member_subscriptions ──────────────────────────────────────────────
    op.create_table(
        "member_subscriptions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", sa.String, sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False),
        # price_id locked at subscription time — never changed — preserves join price
        sa.Column("price_id", sa.String, sa.ForeignKey("subscription_prices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sub_status_col, nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("current_period_start", sa.DateTime(timezone=False), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        sa.Column("payment_provider", sa.String(50), nullable=True),
        sa.Column("payment_provider_subscription_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_member_subscriptions_user_id", "member_subscriptions", ["user_id"])

    # ── Seed initial plan and price (idempotent) ──────────────────────────
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    plan_id = str(uuid.uuid4())
    price_id = str(uuid.uuid4())

    conn.execute(
        sa.text(f"""
            INSERT INTO subscription_plans (id, name, description, is_active, created_at, updated_at)
            SELECT '{plan_id}', 'Fresh Collective Membership',
                   'Paid monthly membership for Fresh Collective',
                   true, '{now_str}', '{now_str}'
            WHERE NOT EXISTS (
                SELECT 1 FROM subscription_plans WHERE name = 'Fresh Collective Membership'
            )
        """)
    )

    conn.execute(
        sa.text(f"""
            INSERT INTO subscription_prices
                (id, plan_id, currency, amount_cents, billing_interval,
                 effective_from, effective_to, is_active, created_at)
            SELECT '{price_id}', sp.id, 'AUD', 3900, 'monthly',
                   '{now_str}', NULL, true, '{now_str}'
            FROM subscription_plans sp
            WHERE sp.name = 'Fresh Collective Membership'
            AND NOT EXISTS (
                SELECT 1 FROM subscription_prices spr
                WHERE spr.plan_id = sp.id
                  AND spr.billing_interval = 'monthly'
                  AND spr.is_active = true
            )
        """)
    )


def downgrade() -> None:
    for idx in [
        "ix_member_subscriptions_user_id",
        "ix_sales_tasks_lead_id",
        "ix_sales_tasks_opportunity_id",
        "ix_sales_activities_lead_id",
        "ix_sales_activities_opportunity_id",
        "ix_sales_opportunities_lead_id",
        "ix_sales_opportunities_plan_id",
        "ix_sales_leads_email",
        "ix_sales_leads_converted_user_id",
        "ix_subscription_prices_plan_id",
    ]:
        op.drop_index(idx, if_exists=True)

    op.drop_table("member_subscriptions")
    op.drop_table("sales_tasks")
    op.drop_table("sales_activities")
    op.drop_table("sales_opportunities")
    op.drop_table("sales_leads")
    op.drop_table("subscription_prices")
    op.drop_table("subscription_plans")

    conn = op.get_bind()
    for type_name, _ in reversed(ENUM_DEFS):
        conn.execute(sa.text(f"DROP TYPE IF EXISTS {type_name}"))
