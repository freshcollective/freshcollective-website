"""Partial UNIQUE index enforcing at most one active/trialing
CreatorSubscription per user.

Revision ID: 130
Revises: 129
Create Date: 2026-09-15

Motivation
----------
The old admin plan-grant flow creates a new CreatorSubscription row
without revoking the previous one — a data-integrity hazard that
allowed multiple active/trialing rows to accumulate per user. Fee
resolution then picks "most recent by created_at" and silently
ignores the others.

Production audit on 2026-09-15 confirmed zero duplicates. Introducing
the constraint now closes the door before external creators are
onboarded, and pairs with the new atomic Change-Plan endpoint which
performs revoke-then-grant in a single transaction.

Safety
------
* SELECT-only check would fail at CREATE INDEX time if any duplicates
  existed. Zero duplicates in prod at audit time, so this is a clean
  additive migration.
* Old grant-only endpoint continues to function unless the caller
  attempts to grant a second active/trialing sub — in which case the
  INSERT fails with a UNIQUE violation. Callers should migrate to
  ``POST /api/admin/creators/{user_id}/plan/change`` (atomic swap).
"""

from alembic import op


revision = "130"
down_revision = "129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX creator_subscriptions_one_active_per_user_uidx "
        "ON creator_subscriptions (user_id) "
        "WHERE status IN ('active', 'trialing')"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS creator_subscriptions_one_active_per_user_uidx"
    )
