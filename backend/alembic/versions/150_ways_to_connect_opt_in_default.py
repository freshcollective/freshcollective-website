"""Ways to Connect becomes opt-in: default the member switch to false.

Revision ID: 150
Revises: 149
Create Date: 2026-10-05

Migration 138 added ``users.ways_to_connect_enabled`` with
``server_default=true``, so the feature launched default-on. The product
decision is that participation should be affirmative: a member should
not be surfaced to other people because of a shared Gathering until
they have said yes.

**This migration changes the default and nothing else.** Not one
existing row is touched. That is deliberate and it is the whole of the
care here:

  * Every ``true`` row predates the decision and arrived there without
    anyone being asked, so it is not consent — but it is also not
    something to revoke silently inside a schema migration. Resetting
    live participation is a product action on real accounts; it belongs
    in a reviewed, counted, separately-approved step, not in a file that
    runs automatically on deploy. See
    ``scripts/ways_to_connect_participation_audit.py``.
  * Every ``false`` row is a deliberate opt-out — nothing writes
    ``false`` except the member's own PATCH of ``/api/auth/profile`` —
    and must survive untouched. A ``DEFAULT`` change cannot disturb
    them, which is another reason to keep the two concerns apart.

So the effect is bounded: accounts created from here on are opted out
until they choose otherwise, and everyone who already exists keeps
exactly the value they have today.

``ALTER COLUMN SET DEFAULT`` is a catalogue-only change on Postgres —
no table rewrite, no row locks beyond the brief ``ACCESS EXCLUSIVE`` on
the catalogue entry, so it is safe on a live table of any size.

The column stays NOT NULL with no nullable tri-state, for the reason
138 gave: "hasn't decided" would have to be collapsed into one of the
two answers at every read anyway. Under opt-in it collapses to
``false``, which is now the honest reading of silence — the opposite of
what 138 concluded under default-on, and the point of this change.

Downgrade restores ``true`` so the revision is reversible, and likewise
leaves every row alone.
"""

from alembic import op
import sqlalchemy as sa

revision = "150"
down_revision = "149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "ways_to_connect_enabled",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "ways_to_connect_enabled",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.true(),
    )
