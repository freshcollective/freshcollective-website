"""Structured grant reason on PathwayEntitlement.

Revision ID: 081
Revises: 080
Create Date: 2026-07-18

Support the "Grant access" admin action that replaces the old
"Manual purchase" behaviour. World Management can now record a
structured reason for why a PathwayEntitlement was granted, rather than
depending on free-text notes.

Changes:

1. `pathway_entitlements.grant_reason VARCHAR(32) NULL`

   Populated on create + reactivate through the new
   ``POST /api/admin/entitlements/grant`` endpoint. Nullable so
   pre-existing entitlements (which pre-date this feature) remain valid
   without a backfill. A CHECK constraint enforces the allowed set
   at the DB layer as well as at the API layer:

     comp         — complimentary access
     beta         — beta / testing access
     migration    — migrated in from another system
     correction   — purchase correction (fixing a broken paid purchase)
     replacement  — replacement access (post-refund, lost access, etc.)
     other        — anything not covered above (note field required)

   Reversible cleanly — the column is nullable and any populated values
   remain semantically meaningful even without the CHECK constraint, so
   the downgrade just drops the constraint + column.
"""

from alembic import op
import sqlalchemy as sa


revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


ALLOWED_REASONS = (
    "comp",
    "beta",
    "migration",
    "correction",
    "replacement",
    "other",
)


def upgrade() -> None:
    op.add_column(
        "pathway_entitlements",
        sa.Column("grant_reason", sa.String(length=32), nullable=True),
    )
    allowed_list = ", ".join(f"'{r}'" for r in ALLOWED_REASONS)
    op.create_check_constraint(
        "ck_pathway_entitlements_grant_reason",
        "pathway_entitlements",
        f"grant_reason IS NULL OR grant_reason IN ({allowed_list})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_pathway_entitlements_grant_reason",
        "pathway_entitlements",
        type_="check",
    )
    op.drop_column("pathway_entitlements", "grant_reason")
