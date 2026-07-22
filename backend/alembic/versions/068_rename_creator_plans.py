"""
Rename the creator plan lineup to the canonical Community / Creator / Pro
structure, and cancel any residual creator subscription that a Platform
Owner may have.

Mapping applied by this migration:

    old slug         →   new slug   changes
    ---------------  ---   --------  ------------------------------------------
    creator-basic    →    creator    same price ($19), same collective_limit=1,
                                      same fee (800bp) — pending Creator plan
                                      transaction-fee decision
    creator-plus     →    pro        same price ($79), collective_limit 3→5,
                                      fee stays at 300bp pending Pro fee decision

Also inserts:

    community        (free, 1 collective, 8% fee placeholder — irrelevant since
                     Community allows no paid offers)

Platform Owner:

    Any active/trialing creator subscription owned by a role='admin' user is
    marked 'cancelled' by this migration. Platform Owner is a distinct account
    type and does not belong to any creator plan. Rows are cancelled rather
    than deleted to preserve historical audit trail.

The `organisation` plan is intentionally NOT inserted into `creator_plans`.
Organisation is not a self-service creator plan — it is a lead pathway.

Numeric limits deliberately NOT touched by this migration:

    - pathway_limit, media_storage_limit_mb, creator_admin_seat_limit remain
      NULL. Concrete numbers will land when the plan-design task defines them.
    - Creator/Pro transaction fees remain at their existing values (800/300 bp)
      pending the transaction-fee product decision.

Revision ID: 068
Revises: 067
Create Date: 2026-07-13
"""

from alembic import op


revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


PLAN_BASIC_ID = "plan-creator-basic-001"
PLAN_PLUS_ID = "plan-creator-plus-001"
PLAN_COMMUNITY_ID = "plan-community-001"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Rename creator-basic → creator
    # ------------------------------------------------------------------
    op.execute(
        f"""
        UPDATE creator_plans
        SET slug = 'creator',
            name = 'Creator',
            description =
                'For creators beginning to build a commercial collective. '
                'One active collective, up to 500 members, paid offers.',
            updated_at = NOW()
        WHERE id = '{PLAN_BASIC_ID}'
           OR slug = 'creator-basic';
        """
    )

    # ------------------------------------------------------------------
    # 2. Rename creator-plus → pro, bump collective_limit 3 → 5
    # ------------------------------------------------------------------
    op.execute(
        f"""
        UPDATE creator_plans
        SET slug = 'pro',
            name = 'Pro',
            description =
                'For established creators growing a serious collective '
                'business. Up to five active collectives with greater '
                'capacity, collaboration and growth tools.',
            collective_limit = 5,
            updated_at = NOW()
        WHERE id = '{PLAN_PLUS_ID}'
           OR slug = 'creator-plus';
        """
    )

    # ------------------------------------------------------------------
    # 3. Insert Community plan (idempotent)
    # ------------------------------------------------------------------
    op.execute(
        f"""
        INSERT INTO creator_plans (
            id, name, slug, description,
            monthly_price_cents, currency,
            transaction_fee_basis_points,
            collective_limit, pathway_limit,
            media_storage_limit_mb, creator_admin_seat_limit,
            is_active, created_at, updated_at
        )
        VALUES (
            '{PLAN_COMMUNITY_ID}',
            'Community',
            'community',
            'Contribute freely. One approved, non-commercial collective for up to 100 members.',
            0,
            'AUD',
            0,
            1,
            NULL,
            NULL,
            NULL,
            TRUE,
            NOW(),
            NOW()
        )
        ON CONFLICT (id) DO NOTHING;
        """
    )

    # ------------------------------------------------------------------
    # 4. Cancel any residual creator subscription belonging to a
    #    Platform Owner. Platform Owner is a distinct account type and
    #    does not belong to any creator plan. Cancel (don't delete) so
    #    the row is preserved for audit.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE creator_subscriptions cs
        SET status = 'cancelled',
            ends_at = COALESCE(cs.ends_at, NOW()),
            updated_at = NOW()
        FROM users u
        WHERE cs.user_id = u.id
          AND u.role = 'admin'
          AND cs.status IN ('active', 'trialing');
        """
    )


def downgrade() -> None:
    # Reverse the rename. Not fully round-trippable because we cannot
    # know which cancelled Platform Owner subscriptions were previously
    # active vs. cancelled — those rows are left as-is on downgrade.
    op.execute(
        f"""
        UPDATE creator_plans
        SET slug = 'creator-basic',
            name = 'Creator Basic',
            description =
                'Everything you need to launch your first collective. '
                'Includes 1 collective and an 8% Fresh Collective transaction '
                'fee on member payments.',
            updated_at = NOW()
        WHERE id = '{PLAN_BASIC_ID}'
           OR slug = 'creator';
        """
    )
    op.execute(
        f"""
        UPDATE creator_plans
        SET slug = 'creator-plus',
            name = 'Creator Plus',
            description =
                'For growing creators running multiple collectives. Includes '
                '3 collectives and a reduced 3% Fresh Collective transaction '
                'fee on member payments.',
            collective_limit = 3,
            updated_at = NOW()
        WHERE id = '{PLAN_PLUS_ID}'
           OR slug = 'pro';
        """
    )
    op.execute(
        f"""
        DELETE FROM creator_plans
        WHERE id = '{PLAN_COMMUNITY_ID}';
        """
    )
