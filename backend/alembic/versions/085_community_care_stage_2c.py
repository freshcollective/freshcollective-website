"""Community Care — Stage 2C schema additions.

Revision ID: 085
Revises: 084
Create Date: 2026-07-19

Adds the columns Stage 2C needs to enforce Supportive Responses and
Protective Measures against real platform state:

1. ``community_posts`` + ``post_comments``: ``cc_hidden_at`` and
   ``cc_hidden_action_id``. Kept distinct from the existing
   ``is_visible`` flag (which is used by the member-facing "Remove"
   flow) so a caretaker can tell CC-hides from member-removes when
   reviewing history, and so hides can be reversed without
   accidentally un-removing something the member removed themselves.

2. ``spaces``: ``frozen_at``, ``frozen_until``, ``freeze_reason``,
   ``frozen_by_action_id``. Separate from Stage 2A's ``suspended_at``
   (which is set on a member/creator user, not a collective) and from
   ``closed_at`` (which is the Stage 2D closure outcome).

3. ``users``: ``suspended_by_action_id`` — the CC action that issued
   the current suspension pending review, so reversal can clear the
   right state.

4. ``member_restrictions.kind`` CHECK relaxed to include ``creator``
   so a single row scheme handles both posting and creator-side
   restrictions.

Every added column is nullable to preserve every pre-existing row.
Reversible via ``downgrade()``.
"""

from alembic import op
import sqlalchemy as sa


revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


RESTRICTION_KINDS_2C = ("posting", "creator")


def upgrade() -> None:
    # --- 1. content-hide columns --------------------------------------------
    op.add_column(
        "community_posts",
        sa.Column("cc_hidden_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "community_posts",
        sa.Column(
            "cc_hidden_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_community_posts_cc_hidden_at", "community_posts", ["cc_hidden_at"]
    )

    op.add_column(
        "post_comments",
        sa.Column("cc_hidden_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "post_comments",
        sa.Column(
            "cc_hidden_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_post_comments_cc_hidden_at", "post_comments", ["cc_hidden_at"]
    )

    # --- 2. space freeze columns --------------------------------------------
    op.add_column(
        "spaces",
        sa.Column("frozen_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "spaces",
        sa.Column("frozen_until", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column("spaces", sa.Column("freeze_reason", sa.Text(), nullable=True))
    op.add_column(
        "spaces",
        sa.Column(
            "frozen_by_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- 3. user suspension linkage -----------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "suspended_by_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- 4. member_restrictions.kind — extend CHECK -------------------------
    op.drop_constraint(
        "ck_member_restrictions_kind", "member_restrictions", type_="check"
    )
    op.create_check_constraint(
        "ck_member_restrictions_kind",
        "member_restrictions",
        "kind IN ({})".format(", ".join(repr(v) for v in RESTRICTION_KINDS_2C)),
    )


def downgrade() -> None:
    # Reverse the CHECK relaxation
    op.drop_constraint(
        "ck_member_restrictions_kind", "member_restrictions", type_="check"
    )
    op.create_check_constraint(
        "ck_member_restrictions_kind",
        "member_restrictions",
        "kind IN ('posting')",
    )

    op.drop_column("users", "suspended_by_action_id")

    for col in ("frozen_by_action_id", "freeze_reason", "frozen_until", "frozen_at"):
        op.drop_column("spaces", col)

    op.drop_index("ix_post_comments_cc_hidden_at", table_name="post_comments")
    op.drop_column("post_comments", "cc_hidden_action_id")
    op.drop_column("post_comments", "cc_hidden_at")

    op.drop_index("ix_community_posts_cc_hidden_at", table_name="community_posts")
    op.drop_column("community_posts", "cc_hidden_action_id")
    op.drop_column("community_posts", "cc_hidden_at")
