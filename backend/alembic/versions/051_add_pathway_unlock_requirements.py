"""add pathway_unlock_requirements table

Revision ID: 051
Revises: 050
Create Date: 2026-06-19
"""

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pathway_unlock_requirements (
            id                  VARCHAR     NOT NULL PRIMARY KEY,
            pathway_id          VARCHAR     NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
            payment_option_id   VARCHAR     NOT NULL REFERENCES payment_options(id) ON DELETE CASCADE,
            created_at          TIMESTAMP   NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_pathway_unlock_pathway_option UNIQUE (pathway_id, payment_option_id)
        )
    """)
    op.execute("CREATE INDEX ix_pathway_unlock_pathway_id ON pathway_unlock_requirements(pathway_id)")
    op.execute("CREATE INDEX ix_pathway_unlock_payment_option_id ON pathway_unlock_requirements(payment_option_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pathway_unlock_requirements")
