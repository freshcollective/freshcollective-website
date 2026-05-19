"""add payment_transactions table

Revision ID: 020
Revises: 019
Create Date: 2026-05-19
"""

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enums ---
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_transaction_type_enum') THEN
                CREATE TYPE payment_transaction_type_enum AS ENUM (
                    'creator_subscription_payment',
                    'member_pathway_purchase',
                    'member_collective_purchase',
                    'member_pathway_subscription',
                    'member_collective_subscription',
                    'refund',
                    'adjustment'
                );
            END IF;
        END$$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_transaction_status_enum') THEN
                CREATE TYPE payment_transaction_status_enum AS ENUM (
                    'pending',
                    'succeeded',
                    'failed',
                    'refunded',
                    'partially_refunded',
                    'disputed',
                    'cancelled'
                );
            END IF;
        END$$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_provider_enum') THEN
                CREATE TYPE payment_provider_enum AS ENUM (
                    'manual',
                    'stripe'
                );
            END IF;
        END$$;
    """)

    # --- Table ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_transactions (
            id                          VARCHAR PRIMARY KEY,
            transaction_type            payment_transaction_type_enum   NOT NULL,
            status                      payment_transaction_status_enum NOT NULL DEFAULT 'pending',
            payment_provider            payment_provider_enum           NOT NULL DEFAULT 'manual',

            -- Parties (nullable — not every transaction has both)
            payer_user_id               VARCHAR REFERENCES users(id)                    ON DELETE SET NULL,
            creator_user_id             VARCHAR REFERENCES users(id)                    ON DELETE SET NULL,

            -- Resource references
            space_id                    VARCHAR REFERENCES spaces(id)                   ON DELETE SET NULL,
            pathway_id                  VARCHAR REFERENCES pathways(id)                 ON DELETE SET NULL,
            entitlement_id              VARCHAR REFERENCES pathway_entitlements(id)     ON DELETE SET NULL,
            creator_plan_id             VARCHAR REFERENCES creator_plans(id)            ON DELETE SET NULL,
            creator_subscription_id     VARCHAR REFERENCES creator_subscriptions(id)    ON DELETE SET NULL,

            -- Money (integer cents)
            currency                    VARCHAR(3)  NOT NULL DEFAULT 'AUD',
            gross_amount_cents          INTEGER     NOT NULL,
            platform_fee_basis_points   INTEGER     NOT NULL DEFAULT 0,
            platform_fee_cents          INTEGER     NOT NULL DEFAULT 0,
            processing_fee_cents        INTEGER,
            net_creator_amount_cents    INTEGER,
            net_platform_amount_cents   INTEGER,

            -- TODO: Stripe webhook — populate these from webhook events when Stripe is integrated
            provider_checkout_session_id    VARCHAR(200),
            provider_payment_intent_id      VARCHAR(200),
            provider_charge_id              VARCHAR(200),
            provider_invoice_id             VARCHAR(200),
            provider_subscription_id        VARCHAR(200),

            notes       TEXT,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """)

    # --- Indexes ---
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_transactions_creator_user_id ON payment_transactions (creator_user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_transactions_payer_user_id   ON payment_transactions (payer_user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_transactions_space_id        ON payment_transactions (space_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_transactions_pathway_id      ON payment_transactions (pathway_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_transactions_status          ON payment_transactions (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_transactions_transaction_type ON payment_transactions (transaction_type);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_transactions_created_at      ON payment_transactions (created_at);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_transactions;")
    op.execute("DROP TYPE IF EXISTS payment_transaction_type_enum;")
    op.execute("DROP TYPE IF EXISTS payment_transaction_status_enum;")
    op.execute("DROP TYPE IF EXISTS payment_provider_enum;")
