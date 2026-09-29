"""A creator's Stripe Connect account and FC's projection of its readiness.

Revision ID: 141
Revises: 140
Create Date: 2026-09-29

Storage only. No routes, no Stripe calls, and no change to checkout,
payment routing, refunds or payout batches. Every existing creator keeps
today's manual payout model, because that is decided by
``connect_payouts_enabled_at`` and this migration creates no rows.

Shape verified against a real test-mode account rather than derived from
SDK type definitions. A recipient + express account was created, taken
through Stripe-hosted onboarding, transferred to, paid out to a test bank
account, and closed; these columns are the fields that actually moved.

Three decisions worth the space:

**Mode is part of the unique key.** ``UNIQUE(creator_user_id,
stripe_mode)`` — FC runs test and live keys against the same schema, and a
test-mode ``acct_…`` used under a live key fails at the worst moment. Both
may exist; they can never be confused.

**Statuses are stored raw, booleans are derived.** Stripe reports
``active | pending | restricted | unsupported`` with ``status_details``
codes. A boolean loses the difference between "restricted, provide
information" and "unsupported, nothing will help" — different screens,
different decisions. ``transfers_enabled`` / ``payouts_enabled`` survive
as conveniences for the hot path, with CHECK constraints tying them to the
status they summarise so they cannot drift.

**The routing gate is a constraint, not a convention.** Verified: the two
capabilities have different requirement sets, differing by exactly
``external_account``. So an account can reach ``stripe_transfers: active``
while ``payouts`` is still restricted for want of a bank account, and
transferring then puts real money somewhere it cannot leave.
``ck_creator_stripe_accounts_routing_requires_payouts`` makes that
unrepresentable rather than merely discouraged.

No ``rejected`` state exists: Stripe expresses rejection as
``restricted`` + ``restricted_other`` + ``contact_stripe``.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "141"
down_revision = "140"
branch_labels = None
depends_on = None


ONBOARDING_STATES = (
    "not_started", "onboarding", "verifying", "action_required",
    "transfers_only", "ready", "restricted", "unsupported", "closed",
)
CAPABILITY_STATUSES = ("active", "pending", "restricted", "unsupported")
SYNC_SOURCES = ("webhook", "onboarding_return", "manual")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


def upgrade() -> None:
    op.create_table(
        "creator_stripe_accounts",
        sa.Column("id", sa.String(), primary_key=True),  # csa_<uuid>
        sa.Column(
            "creator_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("stripe_mode", sa.String(10), nullable=False),
        # Null between creating this row and a successful v2 account
        # create, so the row can record an attempt that failed.
        sa.Column("stripe_account_id", sa.String(255), nullable=True),

        sa.Column(
            "onboarding_state", sa.String(20),
            nullable=False, server_default="not_started",
        ),

        # Capability state, as Stripe reports it.
        sa.Column("transfers_status", sa.String(20), nullable=True),
        sa.Column("transfers_status_codes", postgresql.JSONB(), nullable=True),
        sa.Column("payouts_status", sa.String(20), nullable=True),
        sa.Column("payouts_status_codes", postgresql.JSONB(), nullable=True),
        sa.Column(
            "transfers_enabled", sa.Boolean(),
            nullable=False, server_default="false",
        ),
        sa.Column(
            "payouts_enabled", sa.Boolean(),
            nullable=False, server_default="false",
        ),

        # Requirements. ``details_submitted`` is v1-only and is what
        # separates "not finished" from "finished, and Stripe has since
        # asked for more".
        sa.Column(
            "details_submitted", sa.Boolean(),
            nullable=False, server_default="false",
        ),
        # Entries, not field names: each carries ``awaiting_action_from``,
        # without which ``action_required`` and ``verifying`` are
        # indistinguishable.
        sa.Column("currently_due_json", postgresql.JSONB(), nullable=True),
        sa.Column("requirements_deadline", sa.DateTime(timezone=False), nullable=True),

        # v1-only facts about getting money to a bank.
        sa.Column(
            "external_account_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column("payout_interval", sa.String(10), nullable=True),
        sa.Column("payout_delay_days", sa.Integer(), nullable=True),
        sa.Column("debit_negative_balances", sa.Boolean(), nullable=True),

        # How the account was configured.
        sa.Column("dashboard", sa.String(10), nullable=True),
        sa.Column("fees_collector", sa.String(30), nullable=True),
        sa.Column("losses_collector", sa.String(30), nullable=True),
        sa.Column("requirements_collector", sa.String(30), nullable=True),

        # The routing gate. Left NULL for everyone by this migration.
        sa.Column(
            "connect_payouts_enabled_at", sa.DateTime(timezone=False), nullable=True,
        ),

        # Diagnostics.
        sa.Column("last_synced_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_sync_source", sa.String(30), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "last_account_link_created_at", sa.DateTime(timezone=False), nullable=True,
        ),
        sa.Column(
            "account_link_count", sa.Integer(),
            nullable=False, server_default="0",
        ),

        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),

        sa.UniqueConstraint(
            "creator_user_id", "stripe_mode",
            name="uq_creator_stripe_accounts_creator_mode",
        ),
        sa.CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_creator_stripe_accounts_mode",
        ),
        sa.CheckConstraint(
            _in_list("onboarding_state", ONBOARDING_STATES),
            name="ck_creator_stripe_accounts_onboarding_state",
        ),
        sa.CheckConstraint(
            "transfers_status IS NULL OR "
            + _in_list("transfers_status", CAPABILITY_STATUSES),
            name="ck_creator_stripe_accounts_transfers_status",
        ),
        sa.CheckConstraint(
            "payouts_status IS NULL OR "
            + _in_list("payouts_status", CAPABILITY_STATUSES),
            name="ck_creator_stripe_accounts_payouts_status",
        ),
        sa.CheckConstraint(
            "last_sync_source IS NULL OR " + _in_list("last_sync_source", SYNC_SOURCES),
            name="ck_creator_stripe_accounts_sync_source",
        ),
        # Derived booleans cannot drift from their status. The money path
        # reads the boolean, so a bad write must not be able to make it
        # lie.
        sa.CheckConstraint(
            "transfers_enabled = (transfers_status = 'active')",
            name="ck_creator_stripe_accounts_transfers_enabled_matches",
        ),
        sa.CheckConstraint(
            "payouts_enabled = (payouts_status = 'active')",
            name="ck_creator_stripe_accounts_payouts_enabled_matches",
        ),
        # Connect routing requires a creator who can actually be paid,
        # not merely one who can be transferred to.
        sa.CheckConstraint(
            "connect_payouts_enabled_at IS NULL OR "
            "(payouts_enabled AND stripe_account_id IS NOT NULL)",
            name="ck_creator_stripe_accounts_routing_requires_payouts",
        ),
    )

    # A Stripe account id belongs to exactly one row. Partial, so the
    # pre-create state — many rows with NULL — stays legal.
    op.create_index(
        "uq_creator_stripe_accounts_account_id",
        "creator_stripe_accounts", ["stripe_account_id"],
        unique=True,
        postgresql_where=sa.text("stripe_account_id IS NOT NULL"),
    )
    # Operational lookups: "who is stuck?", per environment.
    op.create_index(
        "ix_creator_stripe_accounts_mode_state",
        "creator_stripe_accounts", ["stripe_mode", "onboarding_state"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creator_stripe_accounts_mode_state",
        table_name="creator_stripe_accounts",
    )
    op.drop_index(
        "uq_creator_stripe_accounts_account_id",
        table_name="creator_stripe_accounts",
    )
    op.drop_table("creator_stripe_accounts")
