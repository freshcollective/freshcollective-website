"""Creator-managed discount codes.

Revision ID: 139
Revises: 138
Create Date: 2026-09-28

Three additions, all additive and nullable-or-defaulted, so existing
rows keep their current meaning and nothing needs backfilling.

``discount_codes`` — the definition a Creator authors. Unique per
Collective, not globally: two Creators may both run FAMILY50, and
``uq_discount_codes_space_code`` mirrors the prevailing pattern
(``pathways_space_slug_unique``, ``event_series_space_slug_unique``).
Codes are stored upper-cased so matching is case-insensitive without a
functional index, and the stored value is the canonical one.

``discount_redemptions`` — the ledger, and the idempotency guard. A
redemption is recorded only when a purchase genuinely succeeds, and the
two partial unique indexes make a webhook redelivery a no-op at the
database level rather than a second redemption. ``redemption_count`` on
the definition is a display cache; this table is the truth.

``discount_snapshot_json`` on ``payment_transactions`` and
``purchase_plans`` — the immutable record of the discount as it stood at
purchase. Deliberately the same shape as the ``snapshot_grants_json``
already on both tables, for the same reason: a historical purchase must
not change because a Creator later edited or disabled the code. Note
that some older transactions legitimately carry no grant snapshot, so
neither column may be assumed present on historical rows.

Money is minor units throughout. Percentages are basis points
(``5000`` = 50%) because a float percentage cannot be multiplied into
cents without inviting drift.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "139"
down_revision = "138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discount_codes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        # Stored upper-cased; the application upper-cases on the way in
        # and on lookup, so matching is case-insensitive and the stored
        # value is canonical.
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("discount_type", sa.String(20), nullable=False),
        # Basis points: 5000 = 50%. Integer, so cents arithmetic stays exact.
        sa.Column("percent_bps", sa.Integer(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column(
            "redemption_count", sa.Integer(), nullable=False,
            server_default="0",
        ),
        # 'space' → every paid offer in the Collective.
        # 'payment_option' → one offer, named by scope_id.
        sa.Column("scope_kind", sa.String(20), nullable=False,
                  server_default="space"),
        sa.Column(
            "scope_id", sa.String(),
            sa.ForeignKey("payment_options.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=False),
                  nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("space_id", "code",
                            name="uq_discount_codes_space_code"),
        sa.CheckConstraint(
            "discount_type IN ('percentage', 'fixed_amount')",
            name="ck_discount_codes_type",
        ),
        sa.CheckConstraint(
            "scope_kind IN ('space', 'payment_option')",
            name="ck_discount_codes_scope_kind",
        ),
        # A percentage code carries a percentage and nothing else; a
        # fixed-amount code carries an amount and a currency. Enforced
        # here so a malformed row cannot exist even if application
        # validation is bypassed.
        sa.CheckConstraint(
            "(discount_type = 'percentage'"
            "  AND percent_bps IS NOT NULL AND percent_bps BETWEEN 1 AND 10000"
            "  AND amount_cents IS NULL)"
            " OR (discount_type = 'fixed_amount'"
            "  AND amount_cents IS NOT NULL AND amount_cents > 0"
            "  AND currency IS NOT NULL AND percent_bps IS NULL)",
            name="ck_discount_codes_value_shape",
        ),
        sa.CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name="ck_discount_codes_max_redemptions",
        ),
        sa.CheckConstraint(
            "redemption_count >= 0", name="ck_discount_codes_redemption_count",
        ),
        # A payment-option scope must name the option it applies to.
        sa.CheckConstraint(
            "(scope_kind = 'space' AND scope_id IS NULL)"
            " OR (scope_kind = 'payment_option' AND scope_id IS NOT NULL)",
            name="ck_discount_codes_scope_shape",
        ),
    )

    op.create_table(
        "discount_redemptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "discount_code_id", sa.String(),
            sa.ForeignKey("discount_codes.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "payment_transaction_id", sa.String(),
            sa.ForeignKey("payment_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "purchase_plan_id", sa.String(),
            sa.ForeignKey("purchase_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("original_amount_cents", sa.Integer(), nullable=False),
        sa.Column("discount_amount_cents", sa.Integer(), nullable=False),
        sa.Column("final_amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=False),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "original_amount_cents >= 0 AND discount_amount_cents >= 0"
            " AND final_amount_cents >= 0"
            " AND final_amount_cents = original_amount_cents - discount_amount_cents",
            name="ck_discount_redemptions_amounts",
        ),
        # Exactly one of the two purchase references.
        sa.CheckConstraint(
            "(payment_transaction_id IS NOT NULL AND purchase_plan_id IS NULL)"
            " OR (payment_transaction_id IS NULL AND purchase_plan_id IS NOT NULL)",
            name="ck_discount_redemptions_one_purchase",
        ),
    )

    # Idempotency. Partial, because only one of the two columns is set
    # per row and NULLs would otherwise never collide.
    op.create_index(
        "uq_discount_redemptions_code_txn",
        "discount_redemptions", ["discount_code_id", "payment_transaction_id"],
        unique=True, postgresql_where=sa.text("payment_transaction_id IS NOT NULL"),
    )
    op.create_index(
        "uq_discount_redemptions_code_plan",
        "discount_redemptions", ["discount_code_id", "purchase_plan_id"],
        unique=True, postgresql_where=sa.text("purchase_plan_id IS NOT NULL"),
    )

    # The immutable record, alongside the existing grant snapshot.
    op.add_column(
        "payment_transactions",
        sa.Column("discount_snapshot_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("discount_snapshot_json", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("purchase_plans", "discount_snapshot_json")
    op.drop_column("payment_transactions", "discount_snapshot_json")
    op.drop_index("uq_discount_redemptions_code_plan", table_name="discount_redemptions")
    op.drop_index("uq_discount_redemptions_code_txn", table_name="discount_redemptions")
    op.drop_table("discount_redemptions")
    op.drop_table("discount_codes")
