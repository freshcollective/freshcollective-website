"""event_bookings.purchase_plan_id — a seat held by a payment plan.

Revision ID: 184
Revises: 183
Create Date: 2026-11-07

Stage 3 completion. A pay-in-full purchase holds its seats against a
pending ``PaymentTransaction``, and that link is how an abandoned
checkout is later resolved: ``verify_stale_hold`` reads
``booking.payment_transaction_id``, finds the Stripe session on the
transaction, and asks Stripe what became of it.

A finite payment plan has no transaction at that point. The ledger row
is written when the first invoice is paid, which is the very thing the
hold is waiting for — so a plan-held seat would carry a NULL link, and
``verify_stale_hold`` would answer "unknown" and leave it alone. For
ever. That is the one failure mode a capacity hold must not have.

So the booking records the plan that is holding it. The plan already
carries ``provider_setup_session_id``, which gives the sweep the same
question to ask Stripe that it asks for a direct ticket, and the plan's
own status says whether the agreement is still live.

``ondelete='SET NULL'`` matches ``payment_transaction_id``: losing the
plan row must never cascade into deleting somebody's booking.

Additive and nullable, so every existing booking is untouched and the
column is simply NULL on all of them — including every direct ticket,
which keeps using the transaction link.
"""
from alembic import op
import sqlalchemy as sa


revision = "184"
down_revision = "183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_bookings",
        sa.Column("purchase_plan_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_event_bookings_purchase_plan",
        "event_bookings", "purchase_plans",
        ["purchase_plan_id"], ["id"],
        ondelete="SET NULL",
    )
    # The sweep asks "which seats is this plan holding?" on every plan
    # lifecycle event, so the lookup is by plan.
    op.create_index(
        "ix_event_bookings_purchase_plan_id",
        "event_bookings", ["purchase_plan_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_bookings_purchase_plan_id", table_name="event_bookings")
    op.drop_constraint(
        "fk_event_bookings_purchase_plan", "event_bookings", type_="foreignkey",
    )
    op.drop_column("event_bookings", "purchase_plan_id")
