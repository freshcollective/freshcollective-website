"""World Builders → visibility='private'.

Configuration, not schema. No column is added, dropped or altered; one
row's ``visibility`` value changes.

Why a migration rather than a Dashboard or psql change
------------------------------------------------------
``Space.visibility`` has no write path in the creator API —
``SpaceUpdateRequest`` carries ``is_public`` and not ``visibility``, and
``update_space`` refuses ``is_public`` changes on an auto-managed
Collective anyway. The only other writer is
``build_your_collective`` at creation time. So the choices were a
migration or a manual production database edit, and the model's own
note on the sibling ``auto_grant_role`` column says how these are
meant to be set: "via migration or by a platform admin".

A migration also makes the ordering safe. ``fc-api`` runs
``alembic upgrade head`` as its pre-deploy command, so the value lands
with the code that enforces it. Neither half is dangerous alone —
before this release ``visibility`` was read by exactly one module
(``services.member_visibility``, deciding whether a Creator's profile
may name a Collective, where ``link`` and ``private`` already behaved
identically), so applying this value to older code changes nothing;
and the enforcement without the value also changes nothing, because no
Collective is ``private`` yet.

Guards
------
``WHERE slug = 'world-builders' AND auto_grant_role IS NOT NULL``.

The slug alone would be enough on this database, but the second
condition is what makes the statement describe its *intent* — "the
platform-managed Collective called world-builders" — so it cannot
match an ordinary Collective that happened to be given that slug on
some other environment. Either way the ``UPDATE`` touches at most one
row and never a Collective a creator owns.

Idempotency and rollback
------------------------
Re-running ``upgrade`` is a no-op: the row is already ``private``, so
the UPDATE rewrites the same value. ``downgrade`` restores ``link``,
which is what the row held before — recorded here rather than left to
be guessed, and the reason ``downgrade`` is not a ``pass``. Rolling
back the code without rolling back the data is also safe: a ``private``
value with no enforcement behaves exactly as ``link`` did.

``is_public`` is deliberately NOT touched. It is already ``False`` and
is what keeps the Collective out of ordinary public discovery; the
public card comes from the named exception in
``spaces.routes.PUBLICLY_DISCOVERABLE_MANAGED_SLUGS``, not from this.
"""

from alembic import op
import sqlalchemy as sa


revision = "168"
down_revision = "167"
branch_labels = None
depends_on = None


SLUG = "world-builders"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE spaces SET visibility = 'private', updated_at = now() "
            "WHERE slug = :slug AND auto_grant_role IS NOT NULL "
            "AND visibility <> 'private'"
        ).bindparams(slug=SLUG)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE spaces SET visibility = 'link', updated_at = now() "
            "WHERE slug = :slug AND auto_grant_role IS NOT NULL "
            "AND visibility = 'private'"
        ).bindparams(slug=SLUG)
    )
