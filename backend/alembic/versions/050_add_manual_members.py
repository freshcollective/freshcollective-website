"""Add manual_members table for offline/pre-invite members

Revision ID: 050
Revises: 049
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE manual_member_status_enum AS ENUM ('offline', 'invited', 'converted')
    """)

    op.execute("""
        CREATE TABLE manual_members (
            id              VARCHAR     NOT NULL PRIMARY KEY,
            space_id        VARCHAR     NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            first_name      VARCHAR(100) NOT NULL,
            last_name       VARCHAR(100),
            email           VARCHAR(254),
            phone           VARCHAR(50),
            notes           TEXT,
            pass_label      VARCHAR(200),
            status          manual_member_status_enum NOT NULL DEFAULT 'offline',
            converted_user_id VARCHAR REFERENCES users(id) ON DELETE SET NULL,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX ix_manual_members_space ON manual_members(space_id)")
    op.execute("CREATE INDEX ix_manual_members_converted_user ON manual_members(converted_user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS manual_members")
    op.execute("DROP TYPE IF EXISTS manual_member_status_enum")
