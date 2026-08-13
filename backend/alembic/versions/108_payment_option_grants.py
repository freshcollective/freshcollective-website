"""PaymentOptionGrant — one-to-many "what this Option grants" layer.

Revision ID: 108
Revises: 107
Create Date: 2026-08-13

B1 of the Payment Options architecture redesign — creates the join
table only. No code reads from it yet, no backfill runs here, no
legacy columns are dropped. Legacy ``PaymentOption.attaches_to_*`` /
``grants_pathway_id`` + Series-limit columns remain the source of
truth through B2. The destructive drop of those columns is
deliberately not scheduled — it happens only after the new model has
been proven in real Creator use.

FK behaviour:
  * payment_options → CASCADE. Deleting a (never-published draft)
    Option cleans up its grants.
  * pathways / event_series / events → RESTRICT. Hard-deleting an
    experience that any Option still grants raises IntegrityError.
    The Creator must remove the experience from those Options first
    (application-layer preflight lives on the experience-delete
    endpoints, a later commit).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "108"
down_revision = "107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_option_grants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "payment_option_id",
            sa.String(),
            sa.ForeignKey("payment_options.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grant_kind", sa.String(30), nullable=False),
        sa.Column(
            "pathway_id",
            sa.String(),
            sa.ForeignKey("pathways.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "series_id",
            sa.String(),
            sa.ForeignKey("event_series.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("sessions_per_week", sa.Integer(), nullable=True),
        sa.Column("total_sessions", sa.Integer(), nullable=True),
        sa.Column("valid_from_override", sa.DateTime(timezone=False), nullable=True),
        sa.Column("valid_until_override", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "position", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "(grant_kind = 'pathway'      AND pathway_id IS NOT NULL"
            "   AND series_id IS NULL AND event_id IS NULL)"
            " OR (grant_kind = 'event_series' AND series_id IS NOT NULL"
            "   AND pathway_id IS NULL AND event_id IS NULL)"
            " OR (grant_kind = 'gathering'    AND event_id IS NOT NULL"
            "   AND pathway_id IS NULL AND series_id IS NULL)",
            name="payment_option_grants_target_matches_kind",
        ),
        sa.CheckConstraint(
            "(grant_kind = 'event_series') OR ("
            "  sessions_per_week IS NULL"
            "   AND total_sessions IS NULL"
            "   AND valid_from_override IS NULL"
            "   AND valid_until_override IS NULL)",
            name="payment_option_grants_series_fields_only_for_series",
        ),
    )

    op.create_index(
        "ix_payment_option_grants_payment_option_id",
        "payment_option_grants",
        ["payment_option_id"],
    )
    # Uniqueness: an Option cannot grant the same target twice.
    # Partial unique indexes because each target column is nullable.
    op.create_index(
        "uq_payment_option_grants_option_pathway",
        "payment_option_grants",
        ["payment_option_id", "pathway_id"],
        unique=True,
        postgresql_where=sa.text("pathway_id IS NOT NULL"),
    )
    op.create_index(
        "uq_payment_option_grants_option_series",
        "payment_option_grants",
        ["payment_option_id", "series_id"],
        unique=True,
        postgresql_where=sa.text("series_id IS NOT NULL"),
    )
    op.create_index(
        "uq_payment_option_grants_option_event",
        "payment_option_grants",
        ["payment_option_id", "event_id"],
        unique=True,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )
    # Reverse-lookup indexes for "which Options grant this experience?".
    op.create_index(
        "ix_payment_option_grants_pathway",
        "payment_option_grants",
        ["pathway_id"],
        postgresql_where=sa.text("pathway_id IS NOT NULL"),
    )
    op.create_index(
        "ix_payment_option_grants_series",
        "payment_option_grants",
        ["series_id"],
        postgresql_where=sa.text("series_id IS NOT NULL"),
    )
    op.create_index(
        "ix_payment_option_grants_event",
        "payment_option_grants",
        ["event_id"],
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_payment_option_grants_event", table_name="payment_option_grants")
    op.drop_index("ix_payment_option_grants_series", table_name="payment_option_grants")
    op.drop_index("ix_payment_option_grants_pathway", table_name="payment_option_grants")
    op.drop_index("uq_payment_option_grants_option_event", table_name="payment_option_grants")
    op.drop_index("uq_payment_option_grants_option_series", table_name="payment_option_grants")
    op.drop_index("uq_payment_option_grants_option_pathway", table_name="payment_option_grants")
    op.drop_index("ix_payment_option_grants_payment_option_id", table_name="payment_option_grants")
    op.drop_table("payment_option_grants")
