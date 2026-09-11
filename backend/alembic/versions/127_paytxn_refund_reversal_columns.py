"""Add cumulative refund-reversal columns to ``payment_transactions``.

Revision ID: 127
Revises: 126
Create Date: 2026-09-12

Motivation
----------
Migration 126 added ``refunded_amount_cents`` (Stripe's cumulative
refund total) and ``last_refunded_at``. That was enough to answer
"how much was refunded" but not "how much of the Fresh Collective
platform fee was reversed" or "how much of the creator's earnings
were reversed". Under a non-zero fee model (external paid creators),
the Payments received summary would silently overstate platform
revenue and creator earnings once any refund lands.

These two columns capture the cumulative reversal on each side of
the fee split. They are maintained by the ``charge.refunded``
webhook handler using the pure function
``services.refund_reversal.compute_cumulative_reversal_targets`` —
cumulative targets derived from Stripe's cumulative refund amount
plus the immutable snapshot fields, not incremental accumulation.

Invariant (enforced by the handler on every write)::

    refunded_platform_fee_cents + refunded_creator_amount_cents
        == refunded_amount_cents

subject only to deterministic cent rounding, with a full-refund
short-circuit that forces the columns to their exact original
values (``platform_fee_cents`` and ``net_creator_amount_cents``).

Columns added
-------------

``refunded_platform_fee_cents INTEGER NOT NULL DEFAULT 0``
    Cumulative reversed FC platform fee, in cents. Zero for any
    row that has never been refunded.

``refunded_creator_amount_cents INTEGER NOT NULL DEFAULT 0``
    Cumulative reversed creator amount, in cents. Zero for any
    row that has never been refunded.

Historical rows
---------------
Every existing row initialises to zero for both — the correct
truth on the day the migration runs. The one historical Stripe
refund already reconciled in production (Awaken $1) will be
brought into alignment by resending the ``charge.refunded`` event
through the newly-extended handler post-deploy, using the same
pattern used to reconcile ``refunded_amount_cents`` on the 126
rollout.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "127"
down_revision = "126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column(
            "refunded_platform_fee_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "payment_transactions",
        sa.Column(
            "refunded_creator_amount_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_transactions", "refunded_creator_amount_cents")
    op.drop_column("payment_transactions", "refunded_platform_fee_cents")
