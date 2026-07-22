"""Add managed member status, payment fields, and pathway access table

Revision ID: 052
Revises: 051
Create Date: 2026-06-19
"""

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'managed' value to the ManualMemberStatus enum
    op.execute("ALTER TYPE manual_member_status_enum ADD VALUE IF NOT EXISTS 'managed'")

    # Add payment tracking columns to manual_members
    op.execute("""
        ALTER TABLE manual_members
            ADD COLUMN IF NOT EXISTS payment_option_id VARCHAR
                REFERENCES payment_options(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50)
                NOT NULL DEFAULT 'unpaid'
    """)

    # New table: pathway access grants for managed members
    op.execute("""
        CREATE TABLE IF NOT EXISTS manual_member_pathway_access (
            id                  VARCHAR     NOT NULL PRIMARY KEY,
            manual_member_id    VARCHAR     NOT NULL
                REFERENCES manual_members(id) ON DELETE CASCADE,
            pathway_id          VARCHAR     NOT NULL
                REFERENCES pathways(id) ON DELETE CASCADE,
            granted_by_user_id  VARCHAR
                REFERENCES users(id) ON DELETE SET NULL,
            notes               TEXT,
            created_at          TIMESTAMP   NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_mm_pathway UNIQUE (manual_member_id, pathway_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mm_pathway_access_member ON manual_member_pathway_access(manual_member_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS manual_member_pathway_access")
    op.execute("ALTER TABLE manual_members DROP COLUMN IF EXISTS payment_option_id")
    op.execute("ALTER TABLE manual_members DROP COLUMN IF EXISTS payment_status")
    # Cannot remove enum value in Postgres without recreating the type
