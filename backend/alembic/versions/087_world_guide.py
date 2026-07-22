"""World Guide — governance documentation CMS.

Revision ID: 087
Revises: 086
Create Date: 2026-07-19

Introduces three tables for the World Guide — Fresh Collective's
in-platform system for publishing and versioning governance
documentation (Terms, Privacy, Community Guidelines, Creator
Agreement, Membership Terms, Payment/Refund policy, AI Policy,
Cookie Policy, and the Changelog).

Design shape:

  ``world_guide_documents``
    One row per governance document (a "Terms of Use", a "Privacy
    Policy"). Metadata that persists across every version of the
    document lives here: slug, category, audience, archived state,
    and a nullable pointer to the current published version.

  ``world_guide_versions``
    One row per version of a document. Version content is stored
    here — every published version is preserved forever. Draft
    versions are freely edited; publishing snapshots a version to
    ``published`` status and moves the document's
    ``current_version_id`` to it.

  ``world_guide_acceptances``
    Future-proofing: a member's acceptance of a specific version of
    a document. Not exposed by any endpoint yet — the table exists
    so the schema can track member acceptance without a later
    migration.

All fields with a small closed vocabulary carry CHECK constraints so
the model, schemas, and DB stay in lockstep.
"""

from alembic import op
import sqlalchemy as sa


revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


DOCUMENT_CATEGORIES = ("governance", "members", "creators", "platform", "other")
DOCUMENT_AUDIENCES = ("everyone", "members", "creators", "platform_owner", "other")
VERSION_STATUSES = ("draft", "published", "archived")


def _in_list(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Documents
    # ------------------------------------------------------------------
    op.create_table(
        "world_guide_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(length=128), nullable=False, unique=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "author_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reading_time_minutes", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=False), nullable=True),
        # Points at the current published version. Null until first publish.
        # Deferred FK — added in a separate ALTER after versions table exists
        # so the two-way reference works.
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(), onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            _in_list("category", DOCUMENT_CATEGORIES),
            name="ck_wg_documents_category",
        ),
        sa.CheckConstraint(
            _in_list("audience", DOCUMENT_AUDIENCES),
            name="ck_wg_documents_audience",
        ),
    )

    # ------------------------------------------------------------------
    # 2. Versions — the versioned content of each document.
    # ------------------------------------------------------------------
    op.create_table(
        "world_guide_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id", sa.String(),
            sa.ForeignKey("world_guide_documents.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("version_number", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        # Structured content sections — each renders as its own visible
        # block on the public document page.
        sa.Column("why_this_exists", sa.Text(), nullable=True),
        sa.Column("what_this_covers", sa.Text(), nullable=True),
        sa.Column("main_content", sa.Text(), nullable=True),
        sa.Column("whats_changed", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "published_by_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Who most recently edited the draft — surfaces in the admin list.
        sa.Column(
            "last_edited_by_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(), onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            _in_list("status", VERSION_STATUSES),
            name="ck_wg_versions_status",
        ),
        sa.UniqueConstraint(
            "document_id", "version_number",
            name="uq_wg_versions_document_version_number",
        ),
    )
    op.create_index(
        "ix_wg_versions_document_status",
        "world_guide_versions", ["document_id", "status"],
    )

    # Add the deferred FK on documents.current_version_id.
    op.create_foreign_key(
        "fk_wg_documents_current_version",
        source_table="world_guide_documents",
        referent_table="world_guide_versions",
        local_cols=["current_version_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # 3. Acceptances — future-proofing.
    # ------------------------------------------------------------------
    op.create_table(
        "world_guide_acceptances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "version_id", sa.String(),
            sa.ForeignKey("world_guide_versions.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=False), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "version_id",
            name="uq_wg_acceptances_user_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("world_guide_acceptances")
    # Drop the deferred FK first so we can drop versions cleanly.
    op.drop_constraint(
        "fk_wg_documents_current_version",
        "world_guide_documents",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_wg_versions_document_status", table_name="world_guide_versions",
    )
    op.drop_table("world_guide_versions")
    op.drop_table("world_guide_documents")
