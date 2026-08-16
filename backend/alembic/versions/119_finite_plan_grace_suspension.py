"""FIP3 — grace, suspension, source-aware revocation.

Revision ID: 119
Revises: 118
Create Date: 2026-08-16

Adds the durable state FIP3's later-instalment lifecycle needs:

* ``purchase_plans.payment_problem_started_at`` — when the current
  failure window opened (first ``invoice.payment_failed`` for the
  currently-unresolved failure). NULL when the plan is not in a
  failure window.
* ``purchase_plans.grace_expires_at`` — deadline after which the
  reconciler suspends this plan if no recovery has landed. Set to
  ``payment_problem_started_at + 7 days`` and NEVER extended by
  subsequent failure re-deliveries (idempotent).
* ``purchase_plans.last_failed_invoice_id`` — provider invoice id
  of the currently-unresolved failure. Used to correlate
  reconciliation events and to avoid double-recording a duplicate
  failure delivery.
* ``purchase_plans.suspended_at`` — timestamp of the transition
  into ``suspended`` (grace expired, no recovery).
* ``purchase_plans.reinstated_at`` — timestamp of the most recent
  ``suspended → active`` transition (payment recovered after
  suspension).
* ``purchase_plan_status_enum`` gains the ``suspended`` value.
* ``entitlement_status_enum`` gains the ``suspended`` value so
  plan-driven revocation can pause a PathwayEntitlement without
  losing the audit trail of "was granted". ``AccessPassStatus``
  already carries ``suspended``.

Also creates the additive **access_grant_records** table — one row
per grant event (per (user, target, source)). Solves the FIP3
overlapping-access problem: the existing PathwayEntitlement model
collapses to one row per (user, pathway), so on plan suspension
we cannot tell from the entitlement row alone whether the user
also had access via an unrelated manual/admin/other-plan grant.
The grants log makes that check O(1).

Backfill: existing PathwayEntitlement + AccessPass rows with a
``purchase_plan_id`` (from FIP2's first-invoice fulfilment) each
get a matching grant record so plan-suspension of the existing
pplan_ can honestly reason about overlap.

All columns nullable / additive. No historical row rewrite beyond
the grants-log backfill.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "119"
down_revision = "118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── PurchasePlan columns ─────────────────────────────────────────
    op.add_column(
        "purchase_plans",
        sa.Column("payment_problem_started_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("grace_expires_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("last_failed_invoice_id", sa.String(200), nullable=True),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("suspended_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "purchase_plans",
        sa.Column("reinstated_at", sa.DateTime(timezone=False), nullable=True),
    )

    # Index for the reconciler sweep — cheap partial index.
    op.execute(
        "CREATE INDEX ix_purchase_plans_grace_expires_at "
        "ON purchase_plans (grace_expires_at) "
        "WHERE grace_expires_at IS NOT NULL"
    )

    # ── Enum extensions ─────────────────────────────────────────────
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block
    # in older PostgreSQLs. We're on modern PG; still, isolate each
    # ADD VALUE with COMMIT-safe idempotency (IF NOT EXISTS).
    op.execute(
        "ALTER TYPE purchase_plan_status_enum ADD VALUE IF NOT EXISTS 'suspended'"
    )
    op.execute(
        "ALTER TYPE entitlement_status_enum ADD VALUE IF NOT EXISTS 'suspended'"
    )

    # ── access_grant_records ────────────────────────────────────────
    op.create_table(
        "access_grant_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grant_kind", sa.String(32), nullable=False),  # 'pathway' | 'series'
        sa.Column("target_pathway_id", sa.String, sa.ForeignKey("pathways.id", ondelete="CASCADE"), nullable=True),
        sa.Column("target_series_id", sa.String, sa.ForeignKey("event_series.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),  # 'plan_payment' | 'pay_in_full' | 'admin_grant' | 'free' | 'manual' | 'subscription'
        sa.Column("source_purchase_plan_id", sa.String, sa.ForeignKey("purchase_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_payment_transaction_id", sa.String, sa.ForeignKey("payment_transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_note", sa.String(500), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("revoked_reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(target_pathway_id IS NOT NULL) <> (target_series_id IS NOT NULL)",
            name="ck_agr_exactly_one_target",
        ),
    )
    op.execute(
        "CREATE INDEX ix_agr_user_target_pathway_active "
        "ON access_grant_records (user_id, target_pathway_id) "
        "WHERE revoked_at IS NULL AND target_pathway_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_agr_user_target_series_active "
        "ON access_grant_records (user_id, target_series_id) "
        "WHERE revoked_at IS NULL AND target_series_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_agr_source_plan "
        "ON access_grant_records (source_purchase_plan_id) "
        "WHERE source_purchase_plan_id IS NOT NULL"
    )

    # ── Backfill: every currently-active entitlement / access pass ──
    # Covers three provenance shapes so plan-suspension's overlap
    # check has a truthful signal for pre-FIP3 historical grants:
    #
    #   1. plan-linked (purchase_plan_id NOT NULL)
    #      → source_type='plan_payment', source_purchase_plan_id set
    #   2. pay-in-full (payment_transaction_id NOT NULL, plan NULL)
    #      → source_type='pay_in_full', source_payment_transaction_id set
    #   3. everything else (manual / admin_grant / free / subscription)
    #      → source_type derived from the row's ``source`` column so
    #        historical admin/manual grants leave a record that
    #        overlap queries can find, even if a later plan
    #        reactivation overwrites the row's ``source`` column
    #        (see purchase_fulfilment._apply_entitlement).
    #
    # Skipping revoked/expired rows keeps the log honest about what
    # access exists RIGHT NOW. Grants that were never recorded and
    # then rescinded cannot be safely reconstructed and are out of
    # scope for FIP3.
    op.execute("""
        INSERT INTO access_grant_records (
            id, user_id, grant_kind, target_pathway_id, target_series_id,
            source_type, source_purchase_plan_id, source_payment_transaction_id,
            source_note, granted_at, created_at, updated_at
        )
        SELECT
            'agr_' || substr(md5(random()::text || pe.id), 1, 24),
            pe.user_id,
            'pathway',
            pe.pathway_id,
            NULL,
            CASE
                WHEN pe.purchase_plan_id IS NOT NULL THEN 'plan_payment'
                WHEN pe.source::text = 'one_time_purchase' THEN 'pay_in_full'
                WHEN pe.source::text = 'admin' THEN 'admin_grant'
                WHEN pe.source::text = 'manual_grant' THEN 'admin_grant'
                WHEN pe.source::text = 'subscription' THEN 'subscription'
                WHEN pe.source::text = 'free' THEN 'free'
                WHEN pe.source::text = 'included' THEN 'free'
                ELSE 'manual'
            END,
            pe.purchase_plan_id,
            NULL,
            'FIP3 backfill of pre-FIP3 pathway entitlement',
            COALESCE(pe.created_at, NOW()),
            NOW(),
            NOW()
        FROM pathway_entitlements pe
        WHERE pe.status = 'active'
    """)
    op.execute("""
        INSERT INTO access_grant_records (
            id, user_id, grant_kind, target_pathway_id, target_series_id,
            source_type, source_purchase_plan_id, source_payment_transaction_id,
            source_note, granted_at, created_at, updated_at
        )
        SELECT
            'agr_' || substr(md5(random()::text || ap.id), 1, 24),
            ap.user_id,
            CASE WHEN ap.eligible_series_id IS NOT NULL THEN 'series' ELSE 'pathway' END,
            CASE WHEN ap.eligible_series_id IS NULL THEN ap.eligible_pathway_id ELSE NULL END,
            ap.eligible_series_id,
            CASE
                WHEN ap.purchase_plan_id IS NOT NULL THEN 'plan_payment'
                WHEN ap.source::text = 'one_time_purchase' THEN 'pay_in_full'
                WHEN ap.source::text = 'admin_grant' THEN 'admin_grant'
                WHEN ap.source::text = 'manual' THEN 'admin_grant'
                WHEN ap.source::text = 'subscription' THEN 'subscription'
                WHEN ap.source::text = 'free' THEN 'free'
                ELSE 'manual'
            END,
            ap.purchase_plan_id,
            ap.payment_transaction_id,
            'FIP3 backfill of pre-FIP3 access pass',
            COALESCE(ap.created_at, NOW()),
            NOW(),
            NOW()
        FROM access_passes ap
        WHERE ap.status = 'active'
          AND (ap.eligible_pathway_id IS NOT NULL OR ap.eligible_series_id IS NOT NULL)
    """)


def downgrade() -> None:
    # Grants log — drops the backfill implicitly.
    op.execute("DROP INDEX IF EXISTS ix_agr_source_plan")
    op.execute("DROP INDEX IF EXISTS ix_agr_user_target_series_active")
    op.execute("DROP INDEX IF EXISTS ix_agr_user_target_pathway_active")
    op.drop_table("access_grant_records")

    # Enum ADD VALUE is not cleanly reversible in PostgreSQL. Leave
    # the values in place on downgrade — the enum members become
    # dormant but don't corrupt the schema. Rows in those states
    # would block downgrade regardless.

    op.execute("DROP INDEX IF EXISTS ix_purchase_plans_grace_expires_at")
    op.drop_column("purchase_plans", "reinstated_at")
    op.drop_column("purchase_plans", "suspended_at")
    op.drop_column("purchase_plans", "last_failed_invoice_id")
    op.drop_column("purchase_plans", "grace_expires_at")
    op.drop_column("purchase_plans", "payment_problem_started_at")
