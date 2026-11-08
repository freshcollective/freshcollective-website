"""Stage 4 — what a discounted finite plan needs to bill correctly.

Two additive, nullable columns on ``purchase_plans``:

``final_installment_amount_cents``
    The last instalment, when it differs from every other one. A
    discounted commitment rarely divides into equal cents — A$130 over
    three is 43.33 / 43.33 / 43.34 — and the remainder is carried by the
    final payment.

    NULL means "every instalment is ``installment_amount_cents``", which
    is what every row written before Stage 4 means and what an evenly
    discounted plan still means. So there is no backfill: the read
    helper (``PurchasePlan.expected_installment_cents``) treats NULL as
    the even case, and historical rows keep answering exactly as they
    did.

    This is the column ``discount_pricing`` named as the required fix
    rather than restoring a tolerance to the two invoice gates. A
    tolerance would have let a genuinely wrong invoice through; a
    declared final amount lets the gates stay exact.

``stripe_final_price_id``
    The second recurring Price an uneven plan needs. One Price can only
    express identical invoices, so an uneven plan is two schedule phases
    — N-1 invoices at the base Price, then one at this one. NULL for
    every even plan, which is one Price and one phase exactly as before.

Both nullable and both unread by anything that services an existing
plan unless they are set, so this migration is reversible and changes no
established purchase. No historical transaction or schedule is rewritten.

Revision ID: 185
Revises: 184
"""

from alembic import op
import sqlalchemy as sa

revision = "185"
down_revision = "184"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_plans",
        sa.Column("final_installment_amount_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("stripe_final_price_id", sa.String(length=200), nullable=True),
    )
    # A declared final instalment must be a real, chargeable amount. The
    # column is free to be NULL (the even case); it is not free to be
    # zero or negative, which would mean a plan whose last invoice
    # Stripe cannot raise.
    op.create_check_constraint(
        "ck_purchase_plans_final_installment_positive",
        "purchase_plans",
        "final_installment_amount_cents IS NULL "
        "OR final_installment_amount_cents > 0",
    )
    # The second Price only means something alongside a declared final
    # amount. Enforced so a half-written plan cannot reach Stripe: a
    # Price with no amount to justify it, or an uneven amount with no
    # Price to charge it, are both incoherent.
    op.create_check_constraint(
        "ck_purchase_plans_final_price_needs_amount",
        "purchase_plans",
        "stripe_final_price_id IS NULL "
        "OR final_installment_amount_cents IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_purchase_plans_final_price_needs_amount",
        "purchase_plans", type_="check",
    )
    op.drop_constraint(
        "ck_purchase_plans_final_installment_positive",
        "purchase_plans", type_="check",
    )
    op.drop_column("purchase_plans", "stripe_final_price_id")
    op.drop_column("purchase_plans", "final_installment_amount_cents")
