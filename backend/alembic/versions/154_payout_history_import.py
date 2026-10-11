"""Creators get their full bank payout history, imported a page at a time.

Revision ID: 154
Revises: 153
Create Date: 2026-10-11

Migration 153 recorded bank payouts but read only the ten most recent per
account, so a creator's older payouts stayed visible solely in their Stripe
dashboard. These two columns let the import walk backwards through the
remaining history across successive cron runs instead of in one unbounded
request.

Why a cursor rather than a date window
--------------------------------------
Stripe lists payouts newest-first and pages with ``starting_after``, so the
id of the oldest payout read so far is exactly the right resume point. A date
window would need its own bookkeeping to stay precise across runs, and would
re-read the same records whenever two payouts shared a day.

Why on the account row
----------------------
This is sync bookkeeping, not a Stripe fact, and the row already carries
``last_synced_at``, ``last_sync_source`` and ``account_link_count`` for the
same reason. A separate table would be a second thing to keep in step with
one row per account. The projection's ``apply_to`` deliberately does not
touch either column, so a resync cannot reset the import.

``payout_history_complete`` defaults to false for existing accounts, so each
one begins its import on the next run. Nothing is back-dated and no existing
payout row is altered: the unique constraint from 153 means a re-read of a
payout already held updates it rather than duplicating it.
"""

from alembic import op
import sqlalchemy as sa

revision = "154"
down_revision = "153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creator_stripe_accounts",
        sa.Column("payout_history_cursor", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "creator_stripe_accounts",
        sa.Column(
            "payout_history_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("creator_stripe_accounts", "payout_history_complete")
    op.drop_column("creator_stripe_accounts", "payout_history_cursor")
