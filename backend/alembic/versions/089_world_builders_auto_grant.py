"""World Builders — auto-grant access to active Creators.

Revision ID: 089
Revises: 088
Create Date: 2026-07-23

Adds two columns and configures the *existing* World Builders
collective for automatic access by active Fresh Collective Creators:

  ``spaces.auto_grant_role`` (nullable VARCHAR(20))
    When set, users with ``users.role`` matching this value receive
    an automatic ``SpaceMembership`` (source='auto_role') as long as
    they remain eligible (role match + not suspended + not cancelled).
    Currently only used by World Builders with value 'creator'.

  ``space_memberships.source`` (nullable VARCHAR(32))
    How the membership came into existence. Values:
      * 'joined' — user pressed the public Join button
      * 'invited' — someone was invited and accepted
      * 'purchase' — auto-created by the post-payment webhook
      * 'creator_owner' — the collective's owner at creation time
      * 'auto_role' — auto-granted via Space.auto_grant_role
    Only ``auto_role`` rows are ever touched by the eligibility
    reconciler; every other source is preserved as-is.

This migration then locates the *existing* World Builders record
(slug='world-builders') and applies the auto-grant configuration:

  * auto_grant_role = 'creator'
  * is_public = false          (removes it from the public join flow)
  * visibility = 'link'        (hidden from the discovery list)
  * creator_id                 — preserved as-is (Option B: World
                                 Builders stays creator-owned so it
                                 continues to be managed via Creator
                                 Studio)
  * status                     — preserved (currently 'draft'; publishing
                                 is an explicit product decision)
  * pricing_type = 'free'      — already free; no change

If exactly one World Builders record is not found, the migration
fails loudly rather than silently creating a duplicate collective.

Finally, backfills a ``source='auto_role'`` ``SpaceMembership`` row
for every currently-eligible Creator on the platform. Existing
memberships (if any) are left alone — the eligibility reconciler
never touches non-auto_role rows.
"""

from alembic import op
import sqlalchemy as sa


revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------------
    # 1. Schema additions
    # ---------------------------------------------------------------------
    op.add_column(
        "spaces",
        sa.Column("auto_grant_role", sa.String(20), nullable=True),
    )
    op.create_check_constraint(
        "spaces_auto_grant_role_valid",
        "spaces",
        "auto_grant_role IS NULL OR auto_grant_role IN ('creator')",
    )
    op.add_column(
        "space_memberships",
        sa.Column("source", sa.String(32), nullable=True),
    )
    # Backfill every existing membership to 'joined' — the safe default
    # for any pre-existing row whose true origin we can't reconstruct.
    # The reconciler only touches rows with source='auto_role', so
    # everything backfilled here is left permanently alone.
    op.execute("UPDATE space_memberships SET source = 'joined' WHERE source IS NULL")

    # ---------------------------------------------------------------------
    # 2. Locate the existing World Builders record.
    #
    #    * Exactly 1 → configure it (the expected prod path).
    #    * Zero → skip cleanly. Environments without seed data (fresh
    #      test databases, dev machines that never ran the seed
    #      script) will simply have the columns available for later
    #      configuration by hand.
    #    * More than 1 → fail loudly. This is a genuine data-integrity
    #      problem and configuring one row would leave duplicates in
    #      an inconsistent state.
    # ---------------------------------------------------------------------
    bind = op.get_bind()
    matches = bind.execute(
        sa.text("SELECT id FROM spaces WHERE slug = 'world-builders'")
    ).all()
    if len(matches) > 1:
        raise RuntimeError(
            "Migration 089 found multiple collectives with slug='world-builders' "
            f"({len(matches)} rows). Refusing to configure auto-grant access. "
            "Investigate the spaces table before re-running."
        )
    if not matches:
        # No seed → nothing to configure or backfill. The columns are
        # in place; a later manual seed can flip auto_grant_role on.
        return
    world_builders_id = matches[0][0]

    # ---------------------------------------------------------------------
    # 3. Apply the auto-grant configuration to the existing record.
    #    Deliberately does NOT touch creator_id (Option B — World
    #    Builders remains creator-owned) or status (publishing is a
    #    separate product decision).
    # ---------------------------------------------------------------------
    bind.execute(
        sa.text(
            """
            UPDATE spaces
               SET auto_grant_role = 'creator',
                   is_public       = false,
                   visibility      = 'link'
             WHERE id = :wb_id
            """
        ),
        {"wb_id": world_builders_id},
    )

    # ---------------------------------------------------------------------
    # 4. Backfill: every eligible Creator gets an auto_role membership
    #    if they don't already have one. Uses the same eligibility
    #    predicate as ``services.creator_eligibility.is_eligible_creator``.
    # ---------------------------------------------------------------------
    bind.execute(
        sa.text(
            """
            INSERT INTO space_memberships
                (id, user_id, space_id, role, status, source, joined_at)
            SELECT gen_random_uuid()::text, u.id, :wb_id,
                   'learner', 'active', 'auto_role', NOW()
              FROM users u
             WHERE u.role = 'creator'
               AND u.creator_suspended_at IS NULL
               AND u.creator_cancelled_at IS NULL
               AND NOT EXISTS (
                     SELECT 1 FROM space_memberships m
                      WHERE m.user_id = u.id
                        AND m.space_id = :wb_id
                   )
            """
        ),
        {"wb_id": world_builders_id},
    )


def downgrade() -> None:
    # Revert World Builders to its pre-089 state as best we can. We
    # cannot cleanly reverse the auto_role membership backfill (there's
    # no way to distinguish rows we inserted here from rows a later
    # runtime reconciler inserted before the downgrade), so downgrade
    # only removes the auto-grant configuration + drops the columns.
    bind = op.get_bind()
    matches = bind.execute(
        sa.text("SELECT id FROM spaces WHERE slug = 'world-builders'")
    ).all()
    if len(matches) == 1:
        wb_id = matches[0][0]
        bind.execute(
            sa.text(
                "UPDATE spaces "
                "   SET auto_grant_role = NULL, is_public = true, visibility = 'public' "
                " WHERE id = :wb_id"
            ),
            {"wb_id": wb_id},
        )

    op.drop_constraint("spaces_auto_grant_role_valid", "spaces", type_="check")
    op.drop_column("spaces", "auto_grant_role")
    op.drop_column("space_memberships", "source")
