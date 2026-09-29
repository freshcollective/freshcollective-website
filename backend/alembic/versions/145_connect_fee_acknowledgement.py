"""Record a creator's acknowledgement of the Connect fee model.

Revision ID: 145
Revises: 144
Create Date: 2026-09-29

Connect changes what a creator receives. Today Fresh Collective absorbs the
Stripe processing fee; once a creator's sales route through Connect, that fee
comes out of each sale before FC's own — so a Founding Creator on a 0%
platform fee goes from receiving the full price to receiving the price less
Stripe's fee. Nobody should discover that from a bank statement.

So routing cannot be switched on for a creator who has not acknowledged the
fee model, and the acknowledgement is recorded rather than assumed:

* ``fee_disclosure_acknowledged_at`` — when
* ``fee_disclosure_version`` — which wording they saw, so a later change to
  the fee model can require a fresh acknowledgement instead of silently
  inheriting consent to different terms

The constraint is the point of this revision. Acknowledgement is a
*precondition* enforced in the schema, next to the existing rule that routing
requires active payouts:

    connect_payouts_enabled_at IS NULL
      OR fee_disclosure_acknowledged_at IS NOT NULL

Acknowledging does not enable anything. It is one of five conditions the admin
action checks, and the creator controls only this one — the decision to route
their money stays a deliberate act by Fresh Collective.
"""

from alembic import op
import sqlalchemy as sa

revision = "145"
down_revision = "144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creator_stripe_accounts",
        sa.Column(
            "fee_disclosure_acknowledged_at",
            sa.DateTime(timezone=False), nullable=True,
        ),
    )
    op.add_column(
        "creator_stripe_accounts",
        sa.Column("fee_disclosure_version", sa.String(20), nullable=True),
    )

    # A version without a timestamp would be a half-recorded consent.
    op.create_check_constraint(
        "ck_creator_stripe_accounts_ack_has_version",
        "creator_stripe_accounts",
        "(fee_disclosure_acknowledged_at IS NULL) "
        "= (fee_disclosure_version IS NULL)",
    )
    # Routing requires acknowledgement. Enforced here as well as in the admin
    # action, because this is the one that cannot be forgotten.
    op.create_check_constraint(
        "ck_creator_stripe_accounts_routing_requires_ack",
        "creator_stripe_accounts",
        "connect_payouts_enabled_at IS NULL "
        "OR fee_disclosure_acknowledged_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_creator_stripe_accounts_routing_requires_ack",
        "creator_stripe_accounts", type_="check",
    )
    op.drop_constraint(
        "ck_creator_stripe_accounts_ack_has_version",
        "creator_stripe_accounts", type_="check",
    )
    op.drop_column("creator_stripe_accounts", "fee_disclosure_version")
    op.drop_column("creator_stripe_accounts", "fee_disclosure_acknowledged_at")
