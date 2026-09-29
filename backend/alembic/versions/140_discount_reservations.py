"""Pre-payment reservations for limited-use discount codes.

Revision ID: 140
Revises: 139
Create Date: 2026-09-29

A limited code's final slot needs holding while a member is away at
Stripe. Without that, two people can both reach the payment page with a
one-use code and both be charged — and the answer cannot be to refuse the
loser afterwards, because by then their card has been debited.

``discount_reservations`` is that hold. One row per purchase attempt,
three states, and only ``held`` consumes a slot:

  held      → a checkout that might still complete
  converted → it completed; a ``discount_redemptions`` row now exists
  released  → FC has POSITIVE KNOWLEDGE it can never complete

The governing rule, and the reason this table exists rather than a
timestamp on ``discount_codes``: **a slot may only be reused when FC
knows the prior checkout can no longer complete.** ``session_expires_at``
therefore makes a reservation *eligible for verification*, never free. A
clock-only rule would free the slot at 11:00 for a member who paid at
10:59:59 whose webhook arrived at 11:01, and both charges would stand.

``session_create_params_json`` and ``session_expires_at`` are written
BEFORE Stripe is called, so a recovery replay can re-send byte-identical
parameters — including the original absolute expiry rather than a
recomputed one. Stripe may prune idempotency keys once they are at least
24h old, so replay is only evidence inside a much shorter window; past
that an unresolved reservation stays held and is surfaced for diagnosis.

Purchase identity is ``(discount_code_id, user_id, payment_option_id,
payment_option_schedule_id)``, unique among ``held`` rows. All four are
NOT NULL, so the partial unique index cannot be evaded by a null: a
member may legitimately use one Collective-wide code on two different
offers, and those are two reservations against two slots — but a retry of
the *same* purchase must reuse its own reservation rather than be told
the code is fully used.

Diagnostics are columns, not just logs, because the failure this design
accepts is an unresolvable reservation, and someone will have to explain
one. There is deliberately NO force-release: the operator action is
"recheck Stripe", never "release despite uncertainty".
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "140"
down_revision = "139"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discount_reservations",
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
        # Identity of the purchase attempt. All NOT NULL — v1 discounts
        # are pay-in-full only, so every reservation names a real option
        # and schedule, and the unique index below can rely on that.
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "payment_option_id", sa.String(),
            sa.ForeignKey("payment_options.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "payment_option_schedule_id", sa.String(),
            sa.ForeignKey("payment_option_schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column("status", sa.String(20), nullable=False, server_default="held"),

        # Frozen pricing. Conversion uses these, never the live code —
        # the definition may be deactivated or edited while a member is
        # mid-checkout, and none of that changes what they were charged.
        sa.Column("original_amount_cents", sa.Integer(), nullable=False),
        sa.Column("discount_amount_cents", sa.Integer(), nullable=False),
        sa.Column("final_amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("discount_snapshot_json", postgresql.JSONB(), nullable=True),

        # Written before the Stripe call so a replay is byte-identical.
        sa.Column("session_idempotency_key", sa.String(255), nullable=False),
        sa.Column("session_create_params_json", postgresql.JSONB(), nullable=True),
        sa.Column("session_expires_at", sa.DateTime(timezone=False), nullable=False),
        # Plain column, not an FK: at reservation time the transaction
        # row does not exist yet. The FK-bearing link is set in
        # ``payment_transaction_id`` once it does.
        sa.Column("intended_payment_transaction_id", sa.String(), nullable=True),
        sa.Column("provider_checkout_session_id", sa.String(200), nullable=True),
        # Stored so a retry can be handed back its own payment page
        # without a Stripe round trip. Retrieving it instead would return
        # null once the Session expires, which is exactly when we most
        # need to know one existed.
        sa.Column("provider_checkout_session_url", sa.Text(), nullable=True),
        sa.Column(
            "payment_transaction_id", sa.String(),
            sa.ForeignKey("payment_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # Diagnostics — enough to explain a stuck reservation later.
        sa.Column("verification_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_verification_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_verification_status", sa.String(40), nullable=True),
        sa.Column("last_verification_error", sa.Text(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("release_reason", sa.String(60), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=False), nullable=True),

        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),

        sa.CheckConstraint(
            "status IN ('held', 'converted', 'released')",
            name="ck_discount_reservations_status",
        ),
        sa.CheckConstraint(
            "original_amount_cents >= 0 AND discount_amount_cents >= 0 "
            "AND final_amount_cents >= 0",
            name="ck_discount_reservations_amounts_non_negative",
        ),
        sa.CheckConstraint(
            "original_amount_cents - discount_amount_cents = final_amount_cents",
            name="ck_discount_reservations_amounts_balance",
        ),
        # A converted reservation must say when, and a released one must
        # say when and why. Terminal states that cannot explain
        # themselves are the thing diagnostics exist to prevent.
        sa.CheckConstraint(
            "(status <> 'converted') OR (converted_at IS NOT NULL)",
            name="ck_discount_reservations_converted_has_time",
        ),
        sa.CheckConstraint(
            "(status <> 'released') OR "
            "(released_at IS NOT NULL AND release_reason IS NOT NULL)",
            name="ck_discount_reservations_released_has_reason",
        ),
    )

    # Purchase identity. Partial on ``held`` because only live
    # reservations are exclusive: a member who completed or abandoned one
    # purchase may make the same purchase again.
    op.create_index(
        "uq_discount_reservations_held_attempt",
        "discount_reservations",
        ["discount_code_id", "user_id", "payment_option_id",
         "payment_option_schedule_id"],
        unique=True, postgresql_where=sa.text("status = 'held'"),
    )
    # The counting query: held rows for a code.
    op.create_index(
        "ix_discount_reservations_code_status",
        "discount_reservations", ["discount_code_id", "status"],
    )
    # Webhook lookup by Stripe session.
    op.create_index(
        "ix_discount_reservations_session",
        "discount_reservations", ["provider_checkout_session_id"],
        unique=True, postgresql_where=sa.text("provider_checkout_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_discount_reservations_session", table_name="discount_reservations")
    op.drop_index("ix_discount_reservations_code_status", table_name="discount_reservations")
    op.drop_index("uq_discount_reservations_held_attempt", table_name="discount_reservations")
    op.drop_table("discount_reservations")
