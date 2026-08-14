"""FIP1 — create ``purchase_plans`` table.

Revision ID: 115
Revises: 114
Create Date: 2026-08-14

Introduces the parent record for finite Payment Option instalment
plans (see ``app/models/purchase_plan.py`` for the full class
docstring + lifecycle documentation).

The table is created empty. No row is written by any FIP1 code path
— the ``recurring_installments`` guard in
``services/checkout_orchestration.py`` continues to 503, and pay-in-
full purchases remain single-``PaymentTransaction`` with no plan
row. FIP2 will populate this table when Stripe setup checkout is
wired.

Partial-unique constraints
--------------------------
``provider_subscription_id`` and
``provider_subscription_schedule_id`` are unique when NOT NULL —
one Stripe subscription / schedule may anchor at most one plan row.
Historical NULLs (during setup) may coexist. Emitted as filtered
indexes so the constraint stays PostgreSQL-native.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The enum type is emitted by ``sa.Enum(create_type=True)`` inside
    # ``op.create_table`` below — a single CREATE TYPE per migration,
    # atomic with the table itself. Downgrade drops the type after
    # dropping the table.
    op.create_table(
        "purchase_plans",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "member_user_id",
            sa.String,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_option_id",
            sa.String,
            sa.ForeignKey("payment_options.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_option_schedule_id",
            sa.String,
            sa.ForeignKey("payment_option_schedules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            sa.String,
            sa.ForeignKey("spaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "creator_user_id",
            sa.String,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending_setup", "active", "payment_problem",
                "completed", "cancelled", "failed",
                name="purchase_plan_status_enum",
                create_type=True,
            ),
            nullable=False,
            server_default="pending_setup",
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="AUD"),
        sa.Column("installment_amount_cents", sa.Integer, nullable=False),
        sa.Column("installments_expected", sa.Integer, nullable=False),
        sa.Column("installments_paid", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_expected_cents", sa.Integer, nullable=False),
        sa.Column(
            "platform_fee_basis_points",
            sa.Integer, nullable=False, server_default="0",
        ),
        sa.Column(
            "creator_plan_id",
            sa.String,
            sa.ForeignKey("creator_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stripe_interval", sa.String(20), nullable=False),
        sa.Column("stripe_interval_count", sa.Integer, nullable=False),
        sa.Column("provider_customer_id", sa.String(200), nullable=True),
        sa.Column("provider_setup_session_id", sa.String(200), nullable=True),
        sa.Column("provider_payment_method_id", sa.String(200), nullable=True),
        sa.Column("provider_subscription_schedule_id", sa.String(200), nullable=True),
        sa.Column("provider_subscription_id", sa.String(200), nullable=True),
        sa.Column("stripe_mode", sa.String(10), nullable=False, server_default="test"),
        sa.Column("next_billing_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "cancelled_by_user_id",
            sa.String,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cancelled_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_purchase_plans_member_user_id", "purchase_plans", ["member_user_id"],
    )
    op.create_index(
        "ix_purchase_plans_payment_option_id", "purchase_plans", ["payment_option_id"],
    )
    op.create_index(
        "ix_purchase_plans_payment_option_schedule_id",
        "purchase_plans", ["payment_option_schedule_id"],
    )
    op.create_index(
        "ix_purchase_plans_space_id", "purchase_plans", ["space_id"],
    )
    op.create_index(
        "ix_purchase_plans_creator_user_id", "purchase_plans", ["creator_user_id"],
    )
    op.create_index(
        "ix_purchase_plans_provider_subscription_id",
        "purchase_plans", ["provider_subscription_id"],
    )
    op.create_index(
        "ix_purchase_plans_provider_subscription_schedule_id",
        "purchase_plans", ["provider_subscription_schedule_id"],
    )
    op.create_index(
        "ix_purchase_plans_provider_setup_session_id",
        "purchase_plans", ["provider_setup_session_id"],
    )
    op.create_index(
        "ix_purchase_plans_member_option_status",
        "purchase_plans",
        ["member_user_id", "payment_option_id", "status"],
    )

    # Partial-unique on Stripe object ids — NULL rows coexist during
    # setup, but any two rows with the same populated value would
    # indicate a bug.
    op.execute(
        "CREATE UNIQUE INDEX uq_purchase_plans_provider_subscription_id "
        "ON purchase_plans (provider_subscription_id) "
        "WHERE provider_subscription_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_purchase_plans_provider_subscription_schedule_id "
        "ON purchase_plans (provider_subscription_schedule_id) "
        "WHERE provider_subscription_schedule_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_purchase_plans_provider_subscription_schedule_id")
    op.execute("DROP INDEX IF EXISTS uq_purchase_plans_provider_subscription_id")
    op.drop_index("ix_purchase_plans_member_option_status", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_provider_setup_session_id", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_provider_subscription_schedule_id", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_provider_subscription_id", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_creator_user_id", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_space_id", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_payment_option_schedule_id", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_payment_option_id", table_name="purchase_plans")
    op.drop_index("ix_purchase_plans_member_user_id", table_name="purchase_plans")
    op.drop_table("purchase_plans")
    op.execute("DROP TYPE purchase_plan_status_enum")
