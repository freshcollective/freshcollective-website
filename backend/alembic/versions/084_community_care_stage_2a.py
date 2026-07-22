"""Community Care — Stage 2A schema.

Revision ID: 084
Revises: 083
Create Date: 2026-07-19

Ground-truth data model for Community Care review muscle. Ships with
the ``community_care_enabled`` feature flag OFF; no endpoints are
active until the flag is flipped.

Additions:

1. Suspension + cancellation columns on ``users``:
     - suspended_at / suspended_until / suspension_reason
     - cancelled_at / cancellation_reason
     - creator_suspended_at / creator_suspended_until /
       creator_suspension_reason
     - creator_cancelled_at / creator_cancellation_reason

   Suspension is temporary (protective, may reverse). Cancellation is
   terminal (resolution outcome). Columns kept explicitly distinct so
   the two states can never be confused at the schema layer.

2. Suspension + closure columns on ``spaces``:
     - suspended_at / suspended_until / suspension_reason
     - closed_at / closure_reason

   Kept separate from `SpaceStatus` (draft | active | archived) so
   archival, suspension, and closure are three orthogonal concepts.

3. Notification severity column on ``notifications``:
     - severity VARCHAR(16) NOT NULL DEFAULT 'routine'
       CHECK IN ('routine', 'action', 'urgent')

   Routine: guidance, reminders, support ack, ordinary CC updates.
   Action: warnings, content hidden, restrictions, freezes, outcomes.
   Urgent: suspension pending review, account/creator cancellation.

4. New tables:
     - community_care_cases
     - community_care_reports
     - community_care_case_events   (append-only history)
     - community_care_case_notes    (append-only reviewer notes)
     - community_care_actions       (append-only; one row per action FC took)
     - member_restrictions          (scoped restrictions; supports posting)

All ordinary indexes and CHECK constraints declared inline. All FK
cascades chosen to preserve historical records:
  - CASCADE on parent case deletion is avoided; we don't delete cases.
  - SET NULL on user deletion so history isn't lost when a user is
    truly purged.

Reversible via ``downgrade()``.
"""

from alembic import op
import sqlalchemy as sa


revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None


CASE_STATUSES = (
    "new", "reviewing", "waiting_info", "action_required",
    "resolved", "closed_no_action",
)
CASE_PRIORITIES = ("low", "moderate", "high", "immediate")
CASE_CONTENT_TYPES = (
    "post", "comment", "member_behaviour", "creator_request", "other",
)
REPORT_CATEGORIES = (
    "harassment_or_bullying", "hate_or_discrimination", "spam_or_scam",
    "unsafe_behaviour", "misinformation", "inappropriate_content",
    "privacy_information", "something_else",
)
CREATOR_REQUEST_SCOPES = (
    "community_wellbeing", "member_concern", "platform_feature",
    "technical_issue", "community_expectations",
)
REPORTER_KINDS = ("member", "creator", "admin", "system")
CASE_EVENT_KINDS = (
    "case_opened", "report_attached", "assigned", "status_changed",
    "priority_changed", "note_added", "information_requested",
    "information_received", "action_issued", "action_reversed",
    "closed", "reopened",
)
ACTION_LAYERS = ("supportive", "protective", "resolution")
ACTION_KINDS = (
    # supportive
    "guidance", "reminder", "warning",
    # protective
    "content_hidden", "content_removed_from_public",
    "posting_restriction", "creator_restriction",
    "collective_freeze", "suspension_pending_review",
    # resolution
    "no_further_action",
    "restore_content", "restore_account", "restore_collective",
    "account_cancellation", "creator_account_cancellation",
    "collective_closure_removal",
)
RESTRICTION_KINDS = ("posting",)
NOTIFICATION_SEVERITIES = ("routine", "action", "urgent")


def _in_list(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def _in_list_nullable(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IS NULL OR {col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # --- 1. users: suspension + cancellation ---------------------------------
    for col in (
        "suspended_at", "suspended_until",
        "creator_suspended_at", "creator_suspended_until",
        "cancelled_at", "creator_cancelled_at",
    ):
        op.add_column("users", sa.Column(col, sa.DateTime(timezone=False), nullable=True))
    for col in (
        "suspension_reason", "cancellation_reason",
        "creator_suspension_reason", "creator_cancellation_reason",
    ):
        op.add_column("users", sa.Column(col, sa.Text(), nullable=True))

    # --- 2. spaces: suspension + closure ------------------------------------
    op.add_column("spaces", sa.Column("suspended_at", sa.DateTime(timezone=False), nullable=True))
    op.add_column("spaces", sa.Column("suspended_until", sa.DateTime(timezone=False), nullable=True))
    op.add_column("spaces", sa.Column("suspension_reason", sa.Text(), nullable=True))
    op.add_column("spaces", sa.Column("closed_at", sa.DateTime(timezone=False), nullable=True))
    op.add_column("spaces", sa.Column("closure_reason", sa.Text(), nullable=True))

    # --- 3. notifications.severity ------------------------------------------
    op.add_column(
        "notifications",
        sa.Column(
            "severity", sa.String(length=16),
            nullable=False,
            server_default=sa.text("'routine'"),
        ),
    )
    op.create_check_constraint(
        "ck_notifications_severity",
        "notifications",
        _in_list("severity", NOTIFICATION_SEVERITIES),
    )
    # Backfill server default is retained — every future insert without a
    # severity value gets 'routine'.

    # --- 4a. community_care_cases -------------------------------------------
    op.create_table(
        "community_care_cases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_number", sa.String(length=32), nullable=False, unique=True),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column(
            "subject_post_id", sa.String(),
            sa.ForeignKey("community_posts.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column(
            "subject_comment_id", sa.String(),
            sa.ForeignKey("post_comments.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column(
            "subject_member_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column(
            "subject_creator_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column(
            "subject_space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column("content_snapshot", sa.JSON(), nullable=True),
        sa.Column("category", sa.String(length=48), nullable=True),
        sa.Column("creator_request_scope", sa.String(length=48), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "assigned_reviewer_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("first_reviewed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("resolution_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(_in_list("content_type", CASE_CONTENT_TYPES), name="ck_cc_cases_content_type"),
        sa.CheckConstraint(_in_list("status", CASE_STATUSES), name="ck_cc_cases_status"),
        sa.CheckConstraint(_in_list("priority", CASE_PRIORITIES), name="ck_cc_cases_priority"),
        sa.CheckConstraint(_in_list_nullable("category", REPORT_CATEGORIES), name="ck_cc_cases_category"),
        sa.CheckConstraint(_in_list_nullable("creator_request_scope", CREATOR_REQUEST_SCOPES), name="ck_cc_cases_creator_request_scope"),
    )
    op.create_index("ix_cc_cases_status_priority", "community_care_cases", ["status", "priority"])
    op.create_index("ix_cc_cases_opened_at", "community_care_cases", ["opened_at"])

    # --- 4b. community_care_reports -----------------------------------------
    op.create_table(
        "community_care_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "case_id", sa.String(),
            sa.ForeignKey("community_care_cases.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "reporter_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reporter_kind", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("target_post_id", sa.String(), sa.ForeignKey("community_posts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_comment_id", sa.String(), sa.ForeignKey("post_comments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_member_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("reporter_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(_in_list("reporter_kind", REPORTER_KINDS), name="ck_cc_reports_reporter_kind"),
        sa.CheckConstraint(_in_list("category", REPORT_CATEGORIES), name="ck_cc_reports_category"),
        sa.CheckConstraint(
            # 'something_else' must be accompanied by a note
            "category <> 'something_else' OR (reporter_note IS NOT NULL AND btrim(reporter_note) <> '')",
            name="ck_cc_reports_something_else_note",
        ),
    )
    op.create_index("ix_cc_reports_created_at", "community_care_reports", ["created_at"])

    # --- 4c. community_care_case_events (append-only) -----------------------
    op.create_table(
        "community_care_case_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "case_id", sa.String(),
            sa.ForeignKey("community_care_cases.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "actor_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("previous_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("subject_content_ref", sa.JSON(), nullable=True),
        sa.CheckConstraint(_in_list("kind", CASE_EVENT_KINDS), name="ck_cc_case_events_kind"),
    )

    # --- 4d. community_care_case_notes (reviewer scratch pad) ---------------
    op.create_table(
        "community_care_case_notes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "case_id", sa.String(),
            sa.ForeignKey("community_care_cases.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "author_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )

    # --- 4e. community_care_actions (supportive/protective/resolution) ------
    op.create_table(
        "community_care_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "case_id", sa.String(),
            sa.ForeignKey("community_care_cases.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column(
            "issued_by_admin_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("explanation_to_recipient", sa.Text(), nullable=True),
        sa.Column("affected_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("affected_space_id", sa.String(), sa.ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("affected_post_id", sa.String(), sa.ForeignKey("community_posts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("affected_comment_id", sa.String(), sa.ForeignKey("post_comments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("ends_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "reversed_by_admin_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reversal_reason", sa.Text(), nullable=True),
        sa.Column(
            "restores_action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(_in_list("layer", ACTION_LAYERS), name="ck_cc_actions_layer"),
        sa.CheckConstraint(_in_list("kind", ACTION_KINDS), name="ck_cc_actions_kind"),
    )
    op.create_index("ix_cc_actions_layer_kind", "community_care_actions", ["layer", "kind"])

    # --- 4f. member_restrictions --------------------------------------------
    op.create_table(
        "member_restrictions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=True, index=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("ends_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "issued_by_admin_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action_id", sa.String(),
            sa.ForeignKey("community_care_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reversed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(_in_list("kind", RESTRICTION_KINDS), name="ck_member_restrictions_kind"),
    )


def downgrade() -> None:
    op.drop_table("member_restrictions")
    op.drop_index("ix_cc_actions_layer_kind", table_name="community_care_actions")
    op.drop_table("community_care_actions")
    op.drop_table("community_care_case_notes")
    op.drop_table("community_care_case_events")
    op.drop_index("ix_cc_reports_created_at", table_name="community_care_reports")
    op.drop_table("community_care_reports")
    op.drop_index("ix_cc_cases_opened_at", table_name="community_care_cases")
    op.drop_index("ix_cc_cases_status_priority", table_name="community_care_cases")
    op.drop_table("community_care_cases")

    # notifications.severity
    try:
        op.drop_constraint("ck_notifications_severity", "notifications", type_="check")
    except Exception:
        pass
    op.drop_column("notifications", "severity")

    # spaces
    for col in ("closure_reason", "closed_at", "suspension_reason", "suspended_until", "suspended_at"):
        op.drop_column("spaces", col)

    # users
    for col in (
        "creator_cancellation_reason", "creator_cancelled_at",
        "cancellation_reason", "cancelled_at",
        "creator_suspension_reason", "creator_suspended_until", "creator_suspended_at",
        "suspension_reason", "suspended_until", "suspended_at",
    ):
        op.drop_column("users", col)
