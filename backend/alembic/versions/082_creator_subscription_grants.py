"""Manual creator-plan grants — source, audit fields, history table.

Revision ID: 082
Revises: 081
Create Date: 2026-07-18

Supports the "Grant plan access" admin action that replaces the old
PATCH /api/admin/creator-billing/{user_id}/plan behaviour, following the
same Option-C philosophy applied to pathway entitlements in migration 081.

Changes:

1. `creator_subscriptions.source VARCHAR(16) NOT NULL DEFAULT 'stripe_paid'`
   with CHECK constraint `IN ('stripe_paid', 'manual_grant')`.

   All pre-existing rows are backfilled to ``manual_grant`` — none of
   them have Stripe IDs populated (Stripe billing isn't live yet), so
   they represent admin-created rows from the old PATCH endpoint.

2. `creator_subscriptions.grant_reason VARCHAR(32) NULL`
   with CHECK `IN ('comp','beta','migration','correction','temporary','replacement','internal','other') OR NULL`

3. `creator_subscriptions.granted_by_user_id VARCHAR NULL FK users(id) ON DELETE SET NULL`
4. `creator_subscriptions.grant_note TEXT NULL`
5. `creator_subscriptions.revoked_at TIMESTAMP NULL`
6. `creator_subscriptions.revoked_by_user_id VARCHAR NULL FK users(id) ON DELETE SET NULL`
7. `creator_subscriptions.revoked_reason TEXT NULL`

8. New table `creator_plan_grants` — append-only history of grant events
   (granted / extended / revoked). Preserves previous grant information
   across replacements, so the audit trail is not lossy.

All changes are additive. Reversible.
"""

from alembic import op
import sqlalchemy as sa


revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


SOURCES = ("stripe_paid", "manual_grant")
GRANT_REASONS = (
    "comp", "beta", "migration", "correction",
    "temporary", "replacement", "internal", "other",
)
GRANT_ACTIONS = ("granted", "extended", "revoked")


def upgrade() -> None:
    # --- 1. creator_subscriptions.source ------------------------------------
    op.add_column(
        "creator_subscriptions",
        sa.Column(
            "source", sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual_grant'"),
        ),
    )
    op.create_check_constraint(
        "ck_creator_subscriptions_source",
        "creator_subscriptions",
        f"source IN ({', '.join(f'{c!r}' for c in SOURCES)})",
    )
    # After backfill, drop the server default so new inserts are explicit.
    # (Existing rows retain 'manual_grant' — none have Stripe IDs today.)
    op.alter_column("creator_subscriptions", "source", server_default=None)

    # --- 2-7. Audit + revocation columns -----------------------------------
    op.add_column(
        "creator_subscriptions",
        sa.Column("grant_reason", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_creator_subscriptions_grant_reason",
        "creator_subscriptions",
        (
            "grant_reason IS NULL OR grant_reason IN ("
            + ", ".join(f"{r!r}" for r in GRANT_REASONS)
            + ")"
        ),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column(
            "granted_by_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column("grant_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column("revoked_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column(
            "revoked_by_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "creator_subscriptions",
        sa.Column("revoked_reason", sa.Text(), nullable=True),
    )

    # --- 8. Grant history table --------------------------------------------
    op.create_table(
        "creator_plan_grants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "subscription_id", sa.String(),
            sa.ForeignKey("creator_subscriptions.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "creator_plan_id", sa.String(),
            sa.ForeignKey("creator_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            f"action IN ({', '.join(f'{a!r}' for a in GRANT_ACTIONS)})",
            name="ck_creator_plan_grants_action",
        ),
    )


def downgrade() -> None:
    op.drop_table("creator_plan_grants")

    for col in (
        "revoked_reason",
        "revoked_by_user_id",
        "revoked_at",
        "grant_note",
        "granted_by_user_id",
        "grant_reason",
        "source",
    ):
        try:
            op.drop_constraint(
                f"ck_creator_subscriptions_{col}",
                "creator_subscriptions",
                type_="check",
            )
        except Exception:
            pass
        op.drop_column("creator_subscriptions", col)
