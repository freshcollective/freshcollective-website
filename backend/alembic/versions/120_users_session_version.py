"""SEC-008 / SEC-015 — per-user session version for JWT invalidation.

Revision ID: 120
Revises: 119
Create Date: 2026-09-03

Adds ``users.session_version INTEGER NOT NULL DEFAULT 1``.

The column is embedded as the ``sv`` claim in every newly-issued
authentication JWT. ``get_current_user`` refuses any token whose
``sv`` does not match the current DB value, giving the app a
single-integer server-side revocation mechanism.

Incremented on:
  * successful ``POST /api/auth/me/change-password``
  * successful ``POST /api/auth/reset-password``
  * ``POST /api/auth/logout-all`` (self-service kick-all-devices)

Deliberately NOT incremented on:
  * ``POST /api/auth/logout`` (current-device logout is client-cookie
    only; other devices are intentionally left signed in);
  * role changes / suspension / cancellation / deletion (already
    effective immediately via live-DB reads inside
    ``get_current_user``, no session-version bump required).

Additive column with a server default of ``1``; every existing row
is backfilled to ``1`` by Postgres in a single DDL statement. Zero
lock concern at the current Fresh Collective scale. No index — the
column is always read alongside the ``User`` row by primary key.

Deployment note: JWTs issued before this deploy have no ``sv`` claim,
so ``get_current_user`` will reject them (401). Every user will be
required to sign in once after deployment. This is the intended
security posture — accepting legacy tokens would defeat the
mechanism from the moment of rollout.
"""

from alembic import op
import sqlalchemy as sa


revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "session_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "session_version")
