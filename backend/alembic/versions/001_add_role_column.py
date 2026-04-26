"""add role column to users

Revision ID: 001
Revises:
Create Date: 2026-04-25

"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add role column — safe: does not modify existing rows' data
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default="user",
        ),
    )
    # Add check constraint to enforce valid values
    op.create_check_constraint(
        "users_role_check",
        "users",
        "role IN ('user', 'admin')",
    )


def downgrade() -> None:
    op.drop_constraint("users_role_check", "users", type_="check")
    op.drop_column("users", "role")
