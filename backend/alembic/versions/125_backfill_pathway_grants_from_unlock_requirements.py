"""Backfill legacy ``PathwayUnlockRequirement`` rows into
``PaymentOptionGrant`` so ``PaymentOptionGrant`` becomes the sole
source of truth for the (PaymentOption, Pathway) unlock relationship.

Revision ID: 125
Revises: 124
Create Date: 2026-09-11

Motivation
----------
Migration 108 introduced ``PaymentOptionGrant`` and migration 110
backfilled it from the legacy ``PaymentOption.attaches_to_kind /
attaches_to_id / grants_pathway_id`` columns. But
``PathwayUnlockRequirement`` (introduced way back in migration 051
to drive ``access_type='included_with_offer'``) was never
backfilled into ``PaymentOptionGrant``.

The upcoming code change moves the ``included_with_offer`` visibility
predicate off ``PathwayUnlockRequirement`` and onto
``PaymentOptionGrant``. Any historical PUR row without a matching
``PaymentOptionGrant`` row would silently lose access after the
switchover — this migration eliminates that risk by inserting the
missing grant rows first.

Data-only, self-contained (does not import application code so a
replay from a bare DB is deterministic). Idempotent via ``NOT
EXISTS`` on the ``(payment_option_id, grant_kind, pathway_id)``
natural key that ``uq_payment_option_grants_option_pathway``
already enforces.

The legacy ``pathway_unlock_requirements`` table is NOT dropped by
this migration — housekeeping to remove it once callers are gone
lands in a separate later migration.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "125"
down_revision = "124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Every legacy unlock relationship that does NOT already have a
    # matching pathway grant on the same Option.
    rows = conn.execute(sa.text(
        """
        SELECT pur.pathway_id, pur.payment_option_id
        FROM   pathway_unlock_requirements pur
        WHERE  NOT EXISTS (
            SELECT 1
            FROM   payment_option_grants pog
            WHERE  pog.payment_option_id = pur.payment_option_id
              AND  pog.grant_kind        = 'pathway'
              AND  pog.pathway_id        = pur.pathway_id
        )
        """
    )).mappings().all()

    if not rows:
        return

    now = datetime.utcnow()
    conn.execute(
        sa.text(
            "INSERT INTO payment_option_grants ("
            "  id, payment_option_id, grant_kind,"
            "  pathway_id, series_id, event_id,"
            "  sessions_per_week, total_sessions,"
            "  valid_from_override, valid_until_override,"
            "  position, created_at, updated_at"
            ") VALUES ("
            "  :id, :payment_option_id, 'pathway',"
            "  :pathway_id, NULL, NULL,"
            "  NULL, NULL,"
            "  NULL, NULL,"
            "  0, :created_at, :updated_at"
            ")"
        ),
        [
            {
                "id": str(uuid4()),
                "payment_option_id": r["payment_option_id"],
                "pathway_id": r["pathway_id"],
                "created_at": now,
                "updated_at": now,
            }
            for r in rows
        ],
    )


def downgrade() -> None:
    # Cannot cleanly reverse — we don't know which pathway grants were
    # inserted by this backfill vs by migration 110 vs by application
    # code. Downgrading migration 110 already truncates
    # ``payment_option_grants``, so no separate action is required
    # here. Left as a no-op deliberately.
    pass
