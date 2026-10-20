"""Offering file management: resource counting, replacement links, worker claims.

Revision ID: 161
Revises: 160
Create Date: 2026-10-20

Offerings Phase B5. Five columns on ``offering_files``, three CHECK
constraints and two indexes. Additive: nothing altered, nothing dropped,
no data moved.

Why each column exists
----------------------

``resource_count`` — how many *downloadable resources* this row
contributes to the plan's file allowance. 1 for a plain file; 1 for an
Office package, whose internal parts are machinery rather than resources;
the number of member files for a ZIP bundle. Computed once at upload from
the archive's central directory and stored, rather than recomputed on
every limit check, because the limit check must not have to open an R2
object to count to fifty. This column is what stops a ZIP being an
unlimited container inside a one-file allowance.

``replaces_file_id`` — the row this pending replacement will supersede.
The existing ``superseded_by_id`` points *forward* and is only set once
the replacement succeeds, which leaves the in-flight window unmodelled:
during it, the old approved file and its unvalidated replacement are both
``superseded_at IS NULL`` and would both be charged against the
allowance. On a Community plan, whose allowance is one file, that made
replacement arithmetically impossible. With this pointer the replacement
occupies the old file's slot instead of taking a new one.

A partial unique index allows at most **one** live pending replacement per
target. Two would both claim one slot, and whichever passed second would
supersede a row already superseded.

``validation_claimed_at`` / ``validation_claimed_by`` — the worker's
lease. Claiming is a short committed transaction that stamps these two
and releases the row lock immediately, so the long part (downloading and
inspecting the file) holds no lock and no open transaction. A claim older
than the lease is reclaimable, which is what makes recovery after a
process restart automatic rather than manual.

``content_deleted_at`` — the R2 object for this row has been removed
while the validation record stays. That separation is the approved
retention rule: a rejected file's *contents* go after 24 hours, and the
record of what it was and why it was refused remains for troubleshooting.

The constraint that keeps deletion honest
-----------------------------------------

``ck_offering_files_content_deleted_shape`` refuses
``content_deleted_at`` on a ``passed`` row. "Never automatically delete a
valid current file" becomes a property of the schema rather than a rule
the cleanup sweep has to remember — and if the retention policy is later
widened to superseded approved files, widening it means editing this
constraint deliberately, which is the right amount of friction.

Existing data
-------------

Production holds zero ``offering_files`` rows: the table arrived empty in
migration 158 and no upload endpoint has existed until now. The
``resource_count`` server default of 1 is therefore a backfill of
nothing, and is also the correct value for any row written by code that
predates this column.

Compatibility
-------------

The old application version does not know these columns exist and never
reads them. Either deploy order is safe. ``downgrade`` drops the indexes,
the constraints and the five columns.
"""

from alembic import op
import sqlalchemy as sa


revision = "161"
down_revision = "160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── resource accounting ───────────────────────────────────────────
    op.add_column(
        "offering_files",
        sa.Column(
            "resource_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_offering_files_resource_count",
        "offering_files",
        "resource_count >= 1",
    )

    # ── pending-replacement link ──────────────────────────────────────
    op.add_column(
        "offering_files",
        sa.Column("replaces_file_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_offering_files_replaces",
        "offering_files",
        "offering_files",
        ["replaces_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_offering_files_no_self_replace",
        "offering_files",
        "replaces_file_id IS NULL OR replaces_file_id <> id",
    )
    # At most one live pending replacement per target. See the docstring.
    op.create_index(
        "ux_offering_files_pending_replacement",
        "offering_files",
        ["replaces_file_id"],
        unique=True,
        postgresql_where=sa.text(
            "replaces_file_id IS NOT NULL AND superseded_at IS NULL"
        ),
    )

    # ── worker lease ──────────────────────────────────────────────────
    op.add_column(
        "offering_files",
        sa.Column("validation_claimed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "offering_files",
        sa.Column("validation_claimed_by", sa.String(length=80), nullable=True),
    )
    # The claim query: unclaimed or expired work, oldest first.
    op.create_index(
        "ix_offering_files_validation_claim",
        "offering_files",
        ["validation_claimed_at", "created_at"],
        postgresql_where=sa.text(
            "validation_status IN ('pending', 'error')"
        ),
    )

    # ── retention ─────────────────────────────────────────────────────
    op.add_column(
        "offering_files",
        sa.Column("content_deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_check_constraint(
        "ck_offering_files_content_deleted_shape",
        "offering_files",
        "content_deleted_at IS NULL OR validation_status <> 'passed'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_offering_files_content_deleted_shape",
        "offering_files",
        type_="check",
    )
    op.drop_column("offering_files", "content_deleted_at")

    op.drop_index("ix_offering_files_validation_claim", "offering_files")
    op.drop_column("offering_files", "validation_claimed_by")
    op.drop_column("offering_files", "validation_claimed_at")

    op.drop_index("ux_offering_files_pending_replacement", "offering_files")
    op.drop_constraint(
        "ck_offering_files_no_self_replace", "offering_files", type_="check",
    )
    op.drop_constraint(
        "fk_offering_files_replaces", "offering_files", type_="foreignkey",
    )
    op.drop_column("offering_files", "replaces_file_id")

    op.drop_constraint(
        "ck_offering_files_resource_count", "offering_files", type_="check",
    )
    op.drop_column("offering_files", "resource_count")
