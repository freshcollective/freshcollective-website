"""Add pathway_entitlements table as the explicit source of truth for paid pathway access.

Free and included pathways continue to work without entitlement rows.
Paid pathways (one_time, subscription) require an active entitlement row.

Backfill: existing active/completed enrollments are migrated to entitlement
records with source = 'manual_grant' (the closest semantic match — they were
granted informally via the platform before explicit access management existed).

The Enrollment table is kept intact; it is no longer the access gate for paid
pathways but continues to exist for data continuity and backward compatibility.

Revision ID: 019
Revises: 018
Create Date: 2026-05-19
"""

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create enum types
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entitlement_source_enum') THEN
                CREATE TYPE entitlement_source_enum
                    AS ENUM ('free', 'included', 'manual_grant', 'one_time_purchase', 'subscription', 'admin');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entitlement_status_enum') THEN
                CREATE TYPE entitlement_status_enum
                    AS ENUM ('active', 'revoked', 'expired', 'cancelled', 'pending');
            END IF;
        END$$;
    """)

    # 2. Create pathway_entitlements table
    op.execute("""
        CREATE TABLE IF NOT EXISTS pathway_entitlements (
            id                          VARCHAR     NOT NULL PRIMARY KEY,
            user_id                     VARCHAR     NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
            space_id                    VARCHAR     NOT NULL REFERENCES spaces(id)   ON DELETE CASCADE,
            pathway_id                  VARCHAR     NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
            source                      entitlement_source_enum  NOT NULL,
            status                      entitlement_status_enum  NOT NULL DEFAULT 'active',
            starts_at                   TIMESTAMP   NOT NULL DEFAULT NOW(),
            ends_at                     TIMESTAMP,
            granted_by_user_id          VARCHAR     REFERENCES users(id) ON DELETE SET NULL,
            revoked_by_user_id          VARCHAR     REFERENCES users(id) ON DELETE SET NULL,
            revoked_at                  TIMESTAMP,
            notes                       TEXT,
            stripe_checkout_session_id  VARCHAR(200),
            stripe_payment_intent_id    VARCHAR(200),
            stripe_subscription_id      VARCHAR(200),
            created_at                  TIMESTAMP   NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMP   NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_pathway_entitlements_user_id    ON pathway_entitlements (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pathway_entitlements_pathway_id  ON pathway_entitlements (pathway_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pathway_entitlements_space_id    ON pathway_entitlements (space_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pathway_entitlements_user_pathway ON pathway_entitlements (user_id, pathway_id);")

    # 3. Backfill from existing enrollments that relate to paid pathways.
    #    We only migrate enrollments for pathways with access_type in
    #    ('one_time', 'subscription') — these are the ones that needed explicit
    #    access.  Free/included pathways don't need entitlement rows.
    #
    #    Use 'manual_grant' as the source because these were informal grants
    #    before the entitlement system existed.
    op.execute("""
        INSERT INTO pathway_entitlements (
            id, user_id, space_id, pathway_id,
            source, status,
            starts_at, created_at, updated_at
        )
        SELECT
            'ent-backfill-' || e.id,
            e.user_id,
            p.space_id,
            e.pathway_id,
            'manual_grant'::entitlement_source_enum,
            CASE
                WHEN e.status IN ('active', 'completed') THEN 'active'::entitlement_status_enum
                ELSE 'cancelled'::entitlement_status_enum
            END,
            e.enrolled_at,
            NOW(),
            NOW()
        FROM enrollments e
        JOIN pathways p ON p.id = e.pathway_id
        WHERE p.access_type IN ('one_time', 'subscription')
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pathway_entitlements;")
    op.execute("DROP TYPE IF EXISTS entitlement_source_enum;")
    op.execute("DROP TYPE IF EXISTS entitlement_status_enum;")
