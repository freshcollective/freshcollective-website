"""Membership removal provenance — why a membership ended, and what follows.

Revision ID: 166
Revises: 165
Create Date: 2026-10-25

``space_memberships.source`` records how a membership *began*. Nothing
recorded how it *ended*, and those are different questions: the second
decides whether somebody may come back.

Three writers set ``status='removed'`` for three unrelated reasons — a
creator moderating, a platform admin revoking a disputed purchase, and
the auto-grant sweep dropping somebody who stopped being an eligible
Creator — and now a fourth, a member leaving of their own accord. With
no provenance the only safe answer to any rejoin attempt was "no",
which is why ``join_space`` returned a false ``already_member`` and
``add_or_invite_member`` collided with the uniqueness constraint.

Four fields, four separate questions
------------------------------------

``removal_kind``        who ended it — voluntary | creator | admin | auto_role
``removal_reason``      why, from the creator's choice field
``removal_note``        the written explanation (caretaker-only)
``rejoin_blocked``      whether they are barred from returning

The last two are kept apart from the first two deliberately. A ban is an
explicit decision, not a consequence of picking a particular reason:
"Inappropriate behaviour" does not imply a ban, and "Member requested
removal" does not preclude one. Folding the decision into
``removal_kind`` as a ``creator_banned`` value would re-couple exactly
what these columns exist to separate.

``payment_action_required`` records the one case where a removal is
knowingly left financially unresolved — an urgent behaviour removal of
somebody with a live instalment plan. The plan keeps billing (this
release makes no Stripe call), so the flag is what stops that being
invisible, and what a later payment-resolution batch will consume.

Historical rows are deliberately left NULL
------------------------------------------

The obvious backfill — "treat existing removed rows as creator
removals" — is wrong, and so is the opposite. We do not know. Some will
be moderation, some the admin revocation path, some the sweep.

So ``removal_kind`` stays NULL and
``membership_grant.may_rejoin`` requires a known-safe value explicitly
rather than excluding the unsafe ones. NULL therefore reads as "not
known to be voluntary" and refuses, which keeps every moderation
decision that was never written down in force. A person wrongly caught
by that asks the creator to re-add them, which this release makes work;
the opposite error would silently undo removals nobody can reconstruct.

``rejoin_blocked`` defaults to ``false`` and that is safe for the same
reason: a historical row has ``removal_kind IS NULL``, so it matches no
allow branch and the boolean never gets consulted.

The CHECK constraints matter equally: a future removal path that
invents a new kind or reason fails loudly at the database rather than
being read as "not voluntary" by accident.

The restriction ledger
----------------------

``membership_restriction_events`` records each time a block is imposed
or lifted — who, when, and why. ``rejoin_blocked`` on the membership is
the current state; this table is the history, so lifting a ban leaves a
record rather than overwriting one. Modelled on
``discount_redemptions``: current state on the owning row, an append-only
ledger beside it.

Downgrade drops all of it. That returns the platform to the state where
rejoining cannot be allowed safely — acceptable only because the code
that reads it goes with it.
"""

import sqlalchemy as sa
from alembic import op

revision = "166"
down_revision = "165"
branch_labels = None
depends_on = None


REMOVAL_KINDS = ("voluntary", "creator", "admin", "auto_role")

REMOVAL_REASONS = (
    "member_requested",
    "no_longer_required",
    "inappropriate_behaviour",
    "payment_issues",
    "other",
)


def upgrade() -> None:
    # --- provenance on the membership itself ---------------------------
    op.add_column(
        "space_memberships",
        sa.Column("removal_kind", sa.String(20), nullable=True),
    )
    op.add_column(
        "space_memberships",
        sa.Column("removed_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "space_memberships",
        sa.Column("removed_by_user_id", sa.String(), nullable=True),
    )
    op.add_column(
        "space_memberships",
        sa.Column("removal_reason", sa.String(32), nullable=True),
    )
    op.add_column(
        "space_memberships",
        sa.Column("removal_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "space_memberships",
        sa.Column(
            "rejoin_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "space_memberships",
        sa.Column(
            "payment_action_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_foreign_key(
        "space_memberships_removed_by_user_id_fkey",
        "space_memberships",
        "users",
        ["removed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "space_memberships_removal_kind_valid",
        "space_memberships",
        "removal_kind IS NULL OR removal_kind IN "
        + str(REMOVAL_KINDS).replace('"', "'"),
    )
    op.create_check_constraint(
        "space_memberships_removal_reason_valid",
        "space_memberships",
        "removal_reason IS NULL OR removal_reason IN "
        + str(REMOVAL_REASONS).replace('"', "'"),
    )
    # A block is a creator decision about a removal, so it cannot exist
    # without one. Enforced here because the alternative — a blocked but
    # active membership — would be read as a ban by the purchase guards
    # while the person was still inside the Collective.
    op.create_check_constraint(
        "space_memberships_block_needs_removal",
        "space_memberships",
        "rejoin_blocked IS FALSE OR status = 'removed'",
    )
    # Partial index: the ban guards ask "is this person blocked here?" on
    # every purchase, and blocked rows are a tiny minority.
    op.create_index(
        "ix_space_memberships_blocked",
        "space_memberships",
        ["space_id", "user_id"],
        postgresql_where=sa.text("rejoin_blocked IS TRUE"),
    )
    # Same shape, for the creator's "who still owes money" view.
    op.create_index(
        "ix_space_memberships_payment_action",
        "space_memberships",
        ["space_id"],
        postgresql_where=sa.text("payment_action_required IS TRUE"),
    )

    # --- the restriction ledger ----------------------------------------
    op.create_table(
        "membership_restriction_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("space_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        # 'blocked' | 'unblocked'
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["spaces.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "action IN ('blocked', 'unblocked')",
            name="membership_restriction_events_action_valid",
        ),
    )
    op.create_index(
        "ix_membership_restriction_events_lookup",
        "membership_restriction_events",
        ["space_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_membership_restriction_events_lookup",
        table_name="membership_restriction_events",
    )
    op.drop_table("membership_restriction_events")

    op.drop_index(
        "ix_space_memberships_payment_action", table_name="space_memberships",
    )
    op.drop_index(
        "ix_space_memberships_blocked", table_name="space_memberships",
    )
    for name in (
        "space_memberships_block_needs_removal",
        "space_memberships_removal_reason_valid",
        "space_memberships_removal_kind_valid",
    ):
        op.drop_constraint(name, "space_memberships", type_="check")
    op.drop_constraint(
        "space_memberships_removed_by_user_id_fkey",
        "space_memberships",
        type_="foreignkey",
    )
    for col in (
        "payment_action_required",
        "rejoin_blocked",
        "removal_note",
        "removal_reason",
        "removed_by_user_id",
        "removed_at",
        "removal_kind",
    ):
        op.drop_column("space_memberships", col)
