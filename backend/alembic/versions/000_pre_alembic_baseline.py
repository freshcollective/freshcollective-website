"""Pre-Alembic baseline (Prisma schema at commit 66b83e7).

At commit 249ac2d (Alembic introduction), the database was managed by
Prisma. This migration reconstructs the pre-Alembic schema exactly so a
fresh DB can run the full 001-119 chain from empty.

Column types + constraint names mirror what Prisma emitted:
  - sa.Text() for Prisma String -> PG TEXT
  - PG_TIMESTAMP(precision=3) for Prisma DateTime
  - Prisma-exact names: users_email_key, password_resets_token_hash_key,
    password_resets_user_id_idx, password_resets_user_id_fkey
  - users.updated_at has no DB DEFAULT (Prisma @updatedAt is app-side);
    migration 046 later adds the DB DEFAULT now().

Revision ID: 000_pre_alembic_baseline
Revises: None
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP


revision = "000_pre_alembic_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            PG_TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_at", PG_TIMESTAMP(precision=3), nullable=False),
    )
    op.create_unique_constraint("users_email_key", "users", ["email"])

    op.create_table(
        "password_resets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", PG_TIMESTAMP(precision=3), nullable=False),
        sa.Column("used_at", PG_TIMESTAMP(precision=3), nullable=True),
        sa.Column(
            "created_at",
            PG_TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_foreign_key(
        "password_resets_user_id_fkey",
        "password_resets",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )
    op.create_unique_constraint(
        "password_resets_token_hash_key", "password_resets", ["token_hash"]
    )
    op.create_index(
        "password_resets_user_id_idx", "password_resets", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("password_resets_user_id_idx", table_name="password_resets")
    op.drop_constraint(
        "password_resets_token_hash_key", "password_resets", type_="unique"
    )
    op.drop_constraint(
        "password_resets_user_id_fkey", "password_resets", type_="foreignkey"
    )
    op.drop_table("password_resets")
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.drop_table("users")
