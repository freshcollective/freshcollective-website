"""Add payment_options table and payment_option_id to payment_transactions

Revision ID: 041
Revises: 040
Create Date: 2026-06-09

New table: payment_options
  - Flexible purchase options per pathway (or future gathering series / bundle)
  - Supports one_time and term_pass payment types for Phase A
  - Phase B will add BookingAllowance enforcement on top of this model

New column: payment_transactions.payment_option_id (nullable FK)
  - NULL for all existing rows (legacy single-price pathway purchases)
  - Set when a member selects a PaymentOption at checkout
"""

from alembic import op

revision = '041'
down_revision = '040'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enums (idempotent) ---------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_option_type_enum') THEN
                CREATE TYPE payment_option_type_enum AS ENUM (
                    'free', 'one_time', 'term_pass', 'subscription'
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_option_status_enum') THEN
                CREATE TYPE payment_option_status_enum AS ENUM (
                    'draft', 'published', 'archived'
                );
            END IF;
        END$$;
    """)

    # --- payment_options table -----------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_options (
            id                      TEXT                        PRIMARY KEY,

            -- Scope
            space_id                TEXT                        NOT NULL
                REFERENCES spaces(id) ON DELETE CASCADE,
            pathway_id              TEXT
                REFERENCES pathways(id) ON DELETE CASCADE,
            grants_pathway_id       TEXT
                REFERENCES pathways(id) ON DELETE SET NULL,

            -- Display
            name                    VARCHAR(200)                NOT NULL,
            description             TEXT,
            payment_type            payment_option_type_enum    NOT NULL DEFAULT 'one_time',
            status                  payment_option_status_enum  NOT NULL DEFAULT 'draft',

            -- Term dates (required for term_pass)
            term_start_date         DATE,
            term_end_date           DATE,

            -- Session breakdown
            sessions_per_week       INTEGER,
            total_sessions          INTEGER,
            price_per_session_cents INTEGER,

            -- Pricing
            calculated_total_cents  INTEGER,
            override_total_cents    INTEGER,
            currency                VARCHAR(3)                  NOT NULL DEFAULT 'AUD',

            -- Notes
            buyer_note              TEXT,
            internal_note           TEXT,

            position                INTEGER                     NOT NULL DEFAULT 0,
            created_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_options_space_id   ON payment_options (space_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_options_pathway_id ON payment_options (pathway_id)")

    # --- payment_option_id on payment_transactions ---------------------------
    op.execute("""
        ALTER TABLE payment_transactions
            ADD COLUMN IF NOT EXISTS payment_option_id TEXT
                REFERENCES payment_options(id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_payment_transactions_payment_option_id
            ON payment_transactions (payment_option_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payment_transactions_payment_option_id")
    op.execute("ALTER TABLE payment_transactions DROP COLUMN IF EXISTS payment_option_id")

    op.execute("DROP INDEX IF EXISTS ix_payment_options_pathway_id")
    op.execute("DROP INDEX IF EXISTS ix_payment_options_space_id")
    op.execute("DROP TABLE IF EXISTS payment_options")

    op.execute("DROP TYPE IF EXISTS payment_option_status_enum")
    op.execute("DROP TYPE IF EXISTS payment_option_type_enum")
