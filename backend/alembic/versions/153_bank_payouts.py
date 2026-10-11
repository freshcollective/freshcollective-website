"""Creators can see their actual bank payouts, and their masked bank account.

Revision ID: 153
Revises: 152
Create Date: 2026-10-11

Fresh Collective could see a Connect *transfer* — its share leaving for the
creator's Stripe balance — and had no record of the *payout*, the later step
where Stripe sends that balance to the bank. So the furthest Creator Studio
could honestly say was "sent to Stripe". This migration adds the two things
needed to say more without guessing.

Why a table for payouts
-----------------------
A payout is not derivable from a transfer. A transfer can succeed and the
bank deposit still fail days later, and conflating the two is precisely the
claim to avoid. Stripe owns the truth; ``creator_bank_payouts`` is a
projection of ``Payout.list`` on each connected account, keyed on Stripe's
own payout id so re-reading a payout updates its row rather than adding one.
That uniqueness is the idempotency guarantee, placed in the schema rather
than trusted to the sync code.

Why masked bank columns rather than a lookup
--------------------------------------------
``bank_name`` / ``bank_last4`` / ``bank_currency`` come off the same v1
account object every sync already fetches, so they cost no extra Stripe call
and let the page render without one. Deliberately only these three: Stripe
collects account and routing numbers through hosted onboarding, and Fresh
Collective has no reason to hold them.

Nothing in the money path reads either addition. Transfers, refunds,
reversals and manual payout batches are untouched.
"""

from alembic import op
import sqlalchemy as sa

revision = "153"
down_revision = "152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creator_stripe_accounts",
        sa.Column("bank_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "creator_stripe_accounts",
        sa.Column("bank_last4", sa.String(length=4), nullable=True),
    )
    op.add_column(
        "creator_stripe_accounts",
        sa.Column("bank_currency", sa.String(length=3), nullable=True),
    )

    op.create_table(
        "creator_bank_payouts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "creator_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stripe_account_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_mode", sa.String(length=10), nullable=False),
        sa.Column("provider_payout_id", sa.String(length=255), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("arrival_date", sa.DateTime(timezone=False), nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Idempotency, in the schema. A second read of the same payout cannot
        # become a second row.
        sa.UniqueConstraint(
            "provider_payout_id",
            "stripe_mode",
            name="uq_creator_bank_payouts_provider_id_mode",
        ),
        sa.CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_creator_bank_payouts_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_transit', 'paid', 'failed', 'canceled')",
            name="ck_creator_bank_payouts_status",
        ),
        sa.CheckConstraint(
            "amount_cents >= 0",
            name="ck_creator_bank_payouts_amount_non_negative",
        ),
    )
    op.create_index(
        "ix_creator_bank_payouts_creator_mode_date",
        "creator_bank_payouts",
        ["creator_user_id", "stripe_mode", "arrival_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creator_bank_payouts_creator_mode_date",
        table_name="creator_bank_payouts",
    )
    op.drop_table("creator_bank_payouts")
    op.drop_column("creator_stripe_accounts", "bank_currency")
    op.drop_column("creator_stripe_accounts", "bank_last4")
    op.drop_column("creator_stripe_accounts", "bank_name")
