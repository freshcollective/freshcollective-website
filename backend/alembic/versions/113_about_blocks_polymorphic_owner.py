"""Make `pathway_about_blocks` polymorphic so it can carry About
content for a Gathering Series as well as a Pathway.

Revision ID: 113
Revises: 112
Create Date: 2026-08-14

U1 introduces a first-class "About" tab on the Gathering Series
editor that must feel like a sibling of the Pathway About page
(same rich blocks, same rendering, same editor primitives). Rather
than duplicating the whole ``pathway_about_blocks`` table and its
downstream renderer code, this migration widens the existing table
to a polymorphic owner:

  * ``owner_kind`` — 'pathway' | 'event_series' (later kinds slot
    in without a further migration; enforced only in application
    code so the values can evolve).
  * ``owner_id``   — the actual owner row id.

The legacy ``pathway_id`` column is retained for backwards
compatibility with existing readers (Pathway About member page,
existing endpoints, indexes) but relaxed to nullable — Series rows
carry ``pathway_id=NULL`` and use ``owner_id`` instead. Existing
rows are backfilled so both columns agree.

No data destruction; downgrade is safe.
"""

from alembic import op
import sqlalchemy as sa


revision = "113"
down_revision = "112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add the polymorphic owner columns (nullable so the backfill
    #    can run before any NOT NULL is enforced).
    op.add_column(
        "pathway_about_blocks",
        sa.Column("owner_kind", sa.String(20), nullable=True),
    )
    op.add_column(
        "pathway_about_blocks",
        sa.Column("owner_id", sa.String(), nullable=True),
    )

    # 2) Backfill every existing row — they all belong to a Pathway.
    op.execute(
        "UPDATE pathway_about_blocks "
        "SET owner_kind = 'pathway', owner_id = pathway_id "
        "WHERE pathway_id IS NOT NULL AND owner_id IS NULL"
    )

    # 3) Relax the legacy ``pathway_id`` FK so Series-owned rows
    #    can carry NULL there. The FK constraint remains — we're
    #    only removing the NOT NULL requirement.
    op.alter_column(
        "pathway_about_blocks", "pathway_id",
        existing_type=sa.String(),
        nullable=True,
    )

    # 4) Compound index that mirrors the existing pathway-only
    #    order index but is polymorphic-aware. The old
    #    ``ix_pathway_about_blocks_pathway_position`` stays intact
    #    for continuity with legacy readers.
    op.create_index(
        "ix_pathway_about_blocks_owner_position",
        "pathway_about_blocks",
        ["owner_kind", "owner_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pathway_about_blocks_owner_position",
        table_name="pathway_about_blocks",
    )
    # Restore ``pathway_id`` NOT NULL only if every remaining row
    # actually has a value there — otherwise leave nullable so the
    # downgrade doesn't hard-fail on Series rows.
    conn = op.get_bind()
    has_null = conn.execute(
        sa.text(
            "SELECT 1 FROM pathway_about_blocks "
            "WHERE pathway_id IS NULL LIMIT 1"
        )
    ).first()
    if not has_null:
        op.alter_column(
            "pathway_about_blocks", "pathway_id",
            existing_type=sa.String(),
            nullable=False,
        )
    op.drop_column("pathway_about_blocks", "owner_id")
    op.drop_column("pathway_about_blocks", "owner_kind")
