"""Snapshot a payment plan's payout routing when the plan is created.

Revision ID: 144
Revises: 143
Create Date: 2026-09-29

A ten-month plan must not change how it pays out in month four. The creator
may finish Connect onboarding, lose a capability, or swap their Stripe
account while the plan is running, and none of that should alter the terms
the plan was set up under — a member's instalments would otherwise be split
between two payout models with no record of why.

So the decision is made once, at plan creation, and every instalment inherits
it. Exactly the discipline already applied to ``platform_fee_basis_points`` on
this table, and to ``payout_model`` on ``payment_transactions`` for
pay-in-full purchases.

Two columns, mirroring the transaction snapshot:

* ``payout_model`` — ``manual`` / ``connect`` / ``not_applicable``
* ``connect_destination_account_id`` — the ``acct_…`` as it stood at creation

Backfill
--------
Every existing plan becomes ``manual``. No historical plan can silently
become Connect-routed: in production none could anyway, because no creator
has ever been enabled, but the backfill makes that a property of the data
rather than a fact about the current configuration.

``not_applicable`` is possible for a platform-owned Collective, where no
creator share exists. The backfill does not try to detect those
retrospectively — ``manual`` is the safe reading for anything already in
flight, and it changes nothing about how those plans pay out.
"""

from alembic import op
import sqlalchemy as sa

revision = "144"
down_revision = "143"
branch_labels = None
depends_on = None


PAYOUT_MODELS = ("manual", "connect", "not_applicable")


def upgrade() -> None:
    op.add_column(
        "purchase_plans",
        sa.Column(
            "payout_model", sa.String(20),
            nullable=False, server_default="manual",
        ),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("connect_destination_account_id", sa.String(255), nullable=True),
    )

    # Explicit rather than relying on the server default, so the intent is
    # recorded in the migration and not just in the column definition.
    op.execute("UPDATE purchase_plans SET payout_model = 'manual'")

    rendered = ", ".join(f"'{m}'" for m in PAYOUT_MODELS)
    op.create_check_constraint(
        "ck_purchase_plans_payout_model",
        "purchase_plans",
        f"payout_model IN ({rendered})",
    )
    # A Connect-routed plan must name the account its instalments will pay.
    # Same guarantee as on ``payment_transactions``: the snapshot is enforced,
    # not merely intended.
    op.create_check_constraint(
        "ck_purchase_plans_connect_has_destination",
        "purchase_plans",
        "payout_model <> 'connect' OR connect_destination_account_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_purchase_plans_non_connect_has_no_destination",
        "purchase_plans",
        "payout_model = 'connect' OR connect_destination_account_id IS NULL",
    )


def downgrade() -> None:
    for name in (
        "ck_purchase_plans_non_connect_has_no_destination",
        "ck_purchase_plans_connect_has_destination",
        "ck_purchase_plans_payout_model",
    ):
        op.drop_constraint(name, "purchase_plans", type_="check")
    op.drop_column("purchase_plans", "connect_destination_account_id")
    op.drop_column("purchase_plans", "payout_model")
