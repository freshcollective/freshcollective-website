"""Add creator_plans and creator_subscriptions tables, seed Basic and Plus plans,
and assign existing creators a sensible default plan.

Plans seeded:
  creator-basic  — $19 AUD/month, 1 collective, 800 bp (8%) transaction fee
  creator-plus   — $79 AUD/month, 3 collectives, 300 bp (3%) transaction fee

All existing creators are assigned Creator Basic by default.
The account lindsey.wd@gmail.com is assigned Creator Plus so the builder
is not blocked while developing and testing the platform.

Revision ID: 018
Revises: 017
Create Date: 2026-05-19
"""

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None

# Fixed UUIDs so the seed is idempotent (re-running upgrade is safe)
PLAN_BASIC_ID = "plan-creator-basic-001"
PLAN_PLUS_ID  = "plan-creator-plus-001"

ADMIN_EMAIL = "lindsey@hilliard.net.au"


def upgrade() -> None:
    # 1. Create creator_subscription_status_enum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'creator_subscription_status_enum') THEN
                CREATE TYPE creator_subscription_status_enum
                    AS ENUM ('active', 'trialing', 'past_due', 'cancelled', 'unpaid');
            END IF;
        END$$;
    """)

    # 2. Create creator_plans table
    op.execute("""
        CREATE TABLE IF NOT EXISTS creator_plans (
            id                          VARCHAR     NOT NULL PRIMARY KEY,
            name                        VARCHAR(200) NOT NULL,
            slug                        VARCHAR(100) NOT NULL UNIQUE,
            description                 TEXT,
            monthly_price_cents         INTEGER     NOT NULL,
            currency                    VARCHAR(3)  NOT NULL DEFAULT 'AUD',
            transaction_fee_basis_points INTEGER    NOT NULL,
            collective_limit            INTEGER     NOT NULL,
            pathway_limit               INTEGER,
            media_storage_limit_mb      INTEGER,
            creator_admin_seat_limit    INTEGER,
            is_active                   BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at                  TIMESTAMP   NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMP   NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_creator_plans_slug ON creator_plans (slug);
    """)

    # 3. Create creator_subscriptions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS creator_subscriptions (
            id                      VARCHAR     NOT NULL PRIMARY KEY,
            user_id                 VARCHAR     NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            creator_plan_id         VARCHAR     NOT NULL REFERENCES creator_plans(id) ON DELETE RESTRICT,
            status                  creator_subscription_status_enum NOT NULL DEFAULT 'active',
            starts_at               TIMESTAMP   NOT NULL DEFAULT NOW(),
            ends_at                 TIMESTAMP,
            created_at              TIMESTAMP   NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMP   NOT NULL DEFAULT NOW(),
            stripe_subscription_id  VARCHAR(200),
            stripe_customer_id      VARCHAR(200)
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_creator_subscriptions_user_id
            ON creator_subscriptions (user_id);
    """)

    # 4. Seed Creator Basic plan (idempotent)
    op.execute(f"""
        INSERT INTO creator_plans (
            id, name, slug, description,
            monthly_price_cents, currency,
            transaction_fee_basis_points,
            collective_limit, pathway_limit,
            media_storage_limit_mb, creator_admin_seat_limit,
            is_active, created_at, updated_at
        )
        VALUES (
            '{PLAN_BASIC_ID}',
            'Creator Basic',
            'creator-basic',
            'Everything you need to launch your first collective. Includes 1 collective and an 8% Fresh Collective transaction fee on member payments.',
            1900,
            'AUD',
            800,
            1,
            NULL,
            NULL,
            NULL,
            TRUE,
            NOW(),
            NOW()
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    # 5. Seed Creator Plus plan (idempotent)
    op.execute(f"""
        INSERT INTO creator_plans (
            id, name, slug, description,
            monthly_price_cents, currency,
            transaction_fee_basis_points,
            collective_limit, pathway_limit,
            media_storage_limit_mb, creator_admin_seat_limit,
            is_active, created_at, updated_at
        )
        VALUES (
            '{PLAN_PLUS_ID}',
            'Creator Plus',
            'creator-plus',
            'For growing creators running multiple collectives. Includes 3 collectives and a reduced 3% Fresh Collective transaction fee on member payments.',
            7900,
            'AUD',
            300,
            3,
            NULL,
            NULL,
            NULL,
            TRUE,
            NOW(),
            NOW()
        )
        ON CONFLICT (id) DO NOTHING;
    """)

    # 6. Assign all existing creators to Creator Basic (idempotent via ON CONFLICT DO NOTHING)
    # We use a subquery so this is safe to re-run.
    op.execute(f"""
        INSERT INTO creator_subscriptions (
            id, user_id, creator_plan_id, status, starts_at, created_at, updated_at
        )
        SELECT
            'sub-' || u.id,
            u.id,
            '{PLAN_BASIC_ID}',
            'active',
            NOW(),
            NOW(),
            NOW()
        FROM users u
        WHERE u.role IN ('creator', 'admin')
        ON CONFLICT (id) DO NOTHING;
    """)

    # 7. Upgrade the admin/builder account to Creator Plus
    op.execute(f"""
        UPDATE creator_subscriptions cs
        SET creator_plan_id = '{PLAN_PLUS_ID}',
            updated_at      = NOW()
        FROM users u
        WHERE cs.user_id = u.id
          AND u.email    = '{ADMIN_EMAIL}';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS creator_subscriptions;")
    op.execute("DROP TABLE IF EXISTS creator_plans;")
    op.execute("DROP TYPE IF EXISTS creator_subscription_status_enum;")
