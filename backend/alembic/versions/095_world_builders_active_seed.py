"""World Builders — ensure it exists and is active in every environment.

Revision ID: 095
Revises: 094
Create Date: 2026-08-04

Root-cause fix for a Stage 3 discovery: the World Builders Collective
row existed in dev but at ``status='draft'``, which the Your World
dashboard correctly hides (``frontend/src/app/dashboard/page.tsx``
line 202 filters memberships to ``space.status === 'active'``). The
auto-grant enrolment itself worked — new Creators *were* being made
members — the Collective just never rendered.

Migration 089 configured the auto-grant on an assumed-existing WB row
but deliberately left ``status`` alone, and no seed guaranteed the
row's presence at all. Any environment without a manual insert was
silently missing WB.

This migration is idempotent and does two things:

  1. If a Collective with ``slug='world-builders'`` exists, update it
     to the canonical WB configuration: ``status='active'``,
     ``auto_grant_role='creator'``, ``is_public=false``,
     ``visibility='link'``.

  2. If no such row exists, INSERT one with sane defaults
     (``creator_id=NULL`` — platform-owned, per the existing
     ``creator_id nullable`` contract at ``models/platform.py:195``).

Downgrade is intentionally a no-op — WB is now a required system
Collective and reverting its status/existence would break every
active Creator. If a future migration needs to reshape it, that
migration will own the change explicitly.
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    existing = bind.execute(
        sa.text("SELECT id FROM spaces WHERE slug = 'world-builders'")
    ).fetchall()
    if len(existing) > 1:
        raise RuntimeError(
            "Migration 095 found multiple collectives with slug='world-builders' "
            f"({len(existing)} rows). Refusing to change any. Investigate the "
            "spaces table before re-running."
        )

    if existing:
        # Row exists — heal any drift.
        bind.execute(
            sa.text(
                """
                UPDATE spaces
                   SET status          = 'active',
                       auto_grant_role = 'creator',
                       is_public       = false,
                       visibility      = 'link'
                 WHERE slug = 'world-builders'
                """
            )
        )
        return

    # No row — insert the canonical WB. NULL creator_id = platform-owned.
    # Only the truly required fields are set; every other column has a
    # server_default at the SQLAlchemy level and is fine at NULL /
    # default in the DB. Admins can enrich name / tagline / artwork
    # later via the admin surface.
    bind.execute(
        sa.text(
            """
            INSERT INTO spaces (
                id, slug, name, status, auto_grant_role,
                is_public, visibility, creator_id
            ) VALUES (
                :id, 'world-builders', 'World Builders', 'active',
                'creator', false, 'link', NULL
            )
            """
        ),
        {"id": str(uuid4())},
    )


def downgrade() -> None:
    # Deliberate no-op. See module docstring: reverting World Builders'
    # status or existence would break every active Creator's home.
    pass
