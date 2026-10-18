"""Offering files carry a validation record.

Revision ID: 159
Revises: 158
Create Date: 2026-10-18

Offerings Phase B. Seven columns on ``offering_files``, two CHECK
constraints and one partial index. Additive: no column altered, none
dropped, no data moved, and ``offer_pages`` untouched as ever.

Why these names
---------------

The columns are ``validation_*``, never ``scan_*``, ``security_*`` or
``safe``. Nothing in this system scans for malware, and a later reader
must not be able to infer that it does from a column name.
``validation_status = 'passed'`` means every check required at the time
ran and succeeded — which is why ``checks_performed`` exists alongside
it, holding the factual list rather than leaving the claim implicit.

Two axes, deliberately
----------------------

``validation_status`` is separate from ``superseded_at``, and that
separation is load-bearing rather than tidy. It is what allows a
replacement file to be validated while the previously approved version
stays downloadable: the old row is still ``passed`` and still current
until the new one passes. A single combined field would force a window
in which purchasers could reach neither version.

``pending`` is the default
--------------------------

So the safe state is the automatic one. Any row written by any code
path — this release's, or one written in a year by someone who has not
read this file — is not downloadable until something deliberately
passes it. The download authoriser requires ``passed``; nothing grants
availability by omission.

``quarantined`` is not ``rejected``
-----------------------------------

``rejected`` means "failed its checks at upload". ``quarantined``
means "was approved, and a problem was found afterwards" — by an
operator, or by a revalidation whose failure must not be waved away
because the file had been approved before. Keeping them apart is what
makes the history truthful, and ``quarantined_at`` is CHECK-tied to
the status so the two cannot drift.

Existing data
-------------

Production holds zero ``offering_files`` rows (the table arrived empty
in migration 158 and no upload endpoint exists yet), so the
server-default backfill is a no-op against nothing. Had there been
rows, defaulting them to ``pending`` would have made them
undownloadable until validated — which is the correct direction, and
worth saying because the opposite default would have silently approved
files nobody checked.

Compatibility
-------------

The old application version does not know these columns exist and
never reads them; the new one defaults them. Both deploy orders are
safe. ``downgrade`` drops the seven columns and their constraints.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "159"
down_revision = "158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offering_files",
        sa.Column(
            "validation_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "offering_files",
        sa.Column(
            "checks_performed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "offering_files",
        sa.Column("validation_policy_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "offering_files",
        sa.Column("validation_reason", sa.String(length=60), nullable=True),
    )
    op.add_column(
        "offering_files",
        sa.Column("validated_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "offering_files",
        sa.Column(
            "validation_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "offering_files",
        sa.Column("quarantined_at", sa.DateTime(timezone=False), nullable=True),
    )

    op.create_check_constraint(
        "ck_offering_files_validation_status",
        "offering_files",
        "validation_status IN "
        "('pending', 'passed', 'rejected', 'error', 'quarantined')",
    )
    # A quarantine timestamp without the status would be a file
    # claiming both to be fine and to have been withdrawn.
    op.create_check_constraint(
        "ck_offering_files_quarantine_shape",
        "offering_files",
        "quarantined_at IS NULL OR validation_status = 'quarantined'",
    )

    # The validation sweep's query: everything awaiting a first pass or
    # a retry. Partial, so it stays small as approved files accumulate.
    op.create_index(
        "ix_offering_files_validation_pending",
        "offering_files",
        ["validation_status"],
        postgresql_where=sa.text("validation_status IN ('pending', 'error')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_offering_files_validation_pending", table_name="offering_files",
    )
    op.drop_constraint(
        "ck_offering_files_quarantine_shape", "offering_files", type_="check",
    )
    op.drop_constraint(
        "ck_offering_files_validation_status", "offering_files", type_="check",
    )
    for col in (
        "quarantined_at",
        "validation_attempts",
        "validated_at",
        "validation_reason",
        "validation_policy_version",
        "checks_performed",
        "validation_status",
    ):
        op.drop_column("offering_files", col)
