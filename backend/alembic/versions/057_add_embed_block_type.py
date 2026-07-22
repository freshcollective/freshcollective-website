"""Add 'embed' to step_block_type_enum

Revision ID: 057
Revises: 056
Create Date: 2026-06-21

Adds a new block_type for embedded iframes from an allowlist of trusted
providers (Calendly, Typeform, Google Forms, Vimeo, Wistia, etc.).

Embed validation and host allowlisting happens in
`app/services/embed_validator.py`; this migration just opens the
PostgreSQL enum to accept the value.
"""

from alembic import op


revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL: ALTER TYPE ... ADD VALUE cannot run inside a transaction
    # block in older versions; commit the implicit transaction first to be safe.
    # AUTOCOMMIT is the simplest reliable path for ADD VALUE.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE step_block_type_enum ADD VALUE IF NOT EXISTS 'embed'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum.
    # Leaving the value in place is harmless — no rows reference it after
    # data migration. If a true rollback is required, the enum must be
    # recreated (drop column → drop type → recreate without 'embed' →
    # add column back). That's intentionally not automated here.
    pass
