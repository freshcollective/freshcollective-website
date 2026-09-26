"""A member's own switch for Ways to Connect.

Revision ID: 138
Revises: 137
Create Date: 2026-09-26

``users.ways_to_connect_enabled`` — "Include me in Ways to Connect".
Recognition is derived at read time from what two people genuinely
share; this is the one thing a member can say about that derivation.
Switched off, they are surfaced to nobody and nobody is surfaced to
them. There is no stored relationship or history to clean up when it
flips — the next read simply returns nothing.

Additive and defaulted ``true``: every existing account stays exactly
where it already was, which is the only safe reading of silence. The
column is NOT NULL with no nullable tri-state, because "hasn't
decided" would have to be interpreted as one of the two answers at
every read anyway, and a nullable column invites a caller to forget
the coalesce.

The server default stays after this migration, matching the
prevailing pattern in this chain (136, 137, 037) — defaults are only
dropped here when the default itself was the bug being fixed (046).

Not to be confused with the deployment feature flag of a similar name
(``DISCOVERY_PILLAR_ENABLED`` / ``NEXT_PUBLIC_WAYS_TO_CONNECT_ENABLED``),
which decides whether the surface exists at all. This column decides
whether one person takes part in it.
"""

from alembic import op
import sqlalchemy as sa

revision = "138"
down_revision = "137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "ways_to_connect_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "ways_to_connect_enabled")
