"""Users — add ``creator_onboarded_at`` + backfill existing Creators.

Revision ID: 096
Revises: 095
Create Date: 2026-08-04

Introduces a Creator-specific onboarding flag, separate from the
existing Member ``onboarding_completed_at``. The two flows serve
different audiences:

  * ``onboarding_completed_at`` — the (now-optional) Fresh Collective
    orientation. Discoverable from Your World, never a gate.
  * ``creator_onboarded_at``    — a short Creator-specific welcome
    shown once after plan activation, before Build Your Collective.

Backfill: any user with an active or trialing ``CreatorSubscription``
(source-agnostic — manual grants and Stripe purchases both) is
marked as already onboarded so existing Creators do not unexpectedly
see the new welcome on their next visit. Purely additive; no data
is discarded.
"""

from alembic import op
import sqlalchemy as sa


revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "creator_onboarded_at",
            sa.DateTime(timezone=False),
            nullable=True,
        ),
    )

    # Backfill: existing Creators (active or trialing subscription of
    # any source) shouldn't see the new welcome. Uses NOW() rather
    # than the subscription's start date because that timestamp is
    # informational only — the value just needs to be non-NULL.
    op.execute(
        """
        UPDATE users
           SET creator_onboarded_at = NOW()
         WHERE id IN (
             SELECT DISTINCT user_id
               FROM creator_subscriptions
              WHERE status IN ('active', 'trialing')
         )
        """
    )


def downgrade() -> None:
    op.drop_column("users", "creator_onboarded_at")
