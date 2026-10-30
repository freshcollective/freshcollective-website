"""Start recording the business history the schema cannot keep.

Several facts about Fresh Collective's past are currently destroyed as
they happen, because the tables that would hold them store current
state rather than history:

* A membership that is left and rejoined has its ``removed_at``,
  ``removal_kind`` and ``removal_reason`` cleared back to NULL. The
  departure is gone — not unaggregated, gone. Churn, tenure and cohort
  retention are all silently wrong for anyone who ever came back.
* ``creator_subscriptions.creator_plan_id`` is overwritten in place, so
  no upgrade or downgrade has ever been recorded. MRR movement cannot
  be reported, now or retrospectively.
* ``spaces.status`` is mutable with nothing recording the transition, so
  there is no date on which a Collective was published.
* ``spaces.themes`` is overwritten, so a Collective recategorised in six
  months retroactively changes what it always was.
* Nothing distinguishes when a payment *settled* from when its row was
  created or last touched, which is why two existing admin endpoints
  attribute revenue to different periods for the same payment.

This migration adds the storage for all of that. It is deliberately
additive only: one new table, five new nullable columns, no change to
any existing column, no constraint added to an existing table and no
data rewritten. Every current query keeps its exact meaning.

Why an event table rather than more columns
-------------------------------------------
The lost facts are *transitions*, and a column can only hold the latest
one. ``business_events`` is append-only: a membership joined, left,
rejoined and left again is four rows, which is the only shape that can
answer a retention question honestly.

It is deliberately NOT ``activities``. That table looks similar and is
a member-facing notification feed carrying read, emailed and archived
state; overloading it would tie analytics retention to somebody's inbox
and put business reporting behind a privacy boundary it should never
cross.

Why the user references do not cascade
--------------------------------------
``user_id``, ``actor_user_id`` and ``creator_user_id`` are ON DELETE SET
NULL rather than CASCADE. Deleting an account must stop the history
identifying that person, but it must not delete the financial record
that a payment settled or a payout was made. SET NULL keeps the
operational and financial history and drops the identity, which is the
balance this platform needs. Consequently ``payload`` must never
duplicate a user id — the producer's schema check enforces that.

Scoping
-------
Every event that belongs to a Collective carries ``space_id``, and every
event attributable to a creator carries ``creator_user_id``, both
indexed with ``occurred_at``. The same metric definitions can therefore
be answered platform-wide for World Management or restricted to the
Collectives a creator manages, without a second reporting architecture
and without a creator-facing query ever needing to scan rows it is not
entitled to see.

Settlement provenance
---------------------
``settled_at`` records an *observed* settlement and nothing else.
``settled_at_source`` says which kind of knowledge it is. This release
only ever writes ``'observed'``; historical rows stay NULL, because we
do not know when they settled and a reconstructed estimate presented as
fact is worse than an honest absence. A later backfill may write
``'reconstructed'``, and every report can then separate the two.

Revision ID: 171
Revises: 170
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "171"
down_revision = "170"
branch_labels = None
depends_on = None


SETTLED_AT_SOURCES = ("observed", "reconstructed")
REPORTING_CLASSES = ("production", "internal_operations", "demonstration")


def upgrade() -> None:
    # ── The event log ────────────────────────────────────────────────────
    op.create_table(
        "business_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        # When the thing happened, naive UTC — taken from the business
        # fact (the removal date being written, the Stripe event's own
        # timestamp), never from the clock at write time.
        sa.Column("occurred_at", sa.DateTime(timezone=False), nullable=False),
        # When we wrote it. Lets a late arrival be detected, tells
        # reconciliation which day's aggregate to rebuild, and gives the
        # activation boundary that separates pre-BI-1 history from a
        # genuine missing event.
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "space_id",
            sa.String(),
            sa.ForeignKey("spaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "creator_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Unique. This is the whole idempotency story: a webhook retry,
        # a re-run or two concurrent writers produce one row, with no
        # exception to catch and no savepoint to manage.
        sa.Column("dedupe_key", sa.String(300), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ux_business_events_dedupe", "business_events", ["dedupe_key"], unique=True,
    )
    op.create_index("ix_business_events_occurred", "business_events", ["occurred_at"])
    op.create_index(
        "ix_business_events_type_occurred",
        "business_events",
        ["event_type", "occurred_at"],
    )
    op.create_index(
        "ix_business_events_space_occurred",
        "business_events",
        ["space_id", "occurred_at"],
    )
    op.create_index(
        "ix_business_events_user_occurred",
        "business_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_business_events_subject", "business_events", ["subject_type", "subject_id"],
    )
    # Creator-scoped reporting. The same metric definitions must later
    # serve Creator Studio, restricted to the Collectives a creator is
    # authorised to manage — so every event that belongs to a Collective
    # carries ``space_id``, and a creator's own slice is indexed rather
    # than filtered out of a platform-wide scan.
    op.create_index(
        "ix_business_events_creator_occurred",
        "business_events",
        ["creator_user_id", "occurred_at"],
    )
    op.create_check_constraint(
        "ck_business_events_subject_type",
        "business_events",
        "subject_type IN ('membership', 'subscription', 'collective', 'transaction')",
    )

    # ``sequence_number`` is a real sequence rather than a serial column
    # so the ordering survives a table rewrite and can be read without
    # inserting.
    op.execute("CREATE SEQUENCE business_events_seq OWNED BY business_events.sequence_number")
    op.execute(
        "ALTER TABLE business_events "
        "ALTER COLUMN sequence_number SET DEFAULT nextval('business_events_seq')"
    )

    # ── Settlement provenance ────────────────────────────────────────────
    op.add_column(
        "payment_transactions",
        sa.Column("settled_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("settled_at_source", sa.String(16), nullable=True),
    )
    op.create_check_constraint(
        "ck_payment_transactions_settled_at_source",
        "payment_transactions",
        "settled_at_source IS NULL OR settled_at_source IN ('observed', 'reconstructed')",
    )
    # Partial, because the only interesting question is "which payments
    # have a settlement date", and most historical rows will not.
    op.create_index(
        "ix_payment_transactions_settled_at",
        "payment_transactions",
        ["settled_at"],
        postgresql_where=sa.text("settled_at IS NOT NULL"),
    )

    # ── Collective publication date ──────────────────────────────────────
    # Write-once. Nothing reads it in this release.
    op.add_column(
        "spaces",
        sa.Column("first_published_at", sa.DateTime(timezone=False), nullable=True),
    )

    # ── Reporting classification ─────────────────────────────────────────
    # Columns only. Every row stays NULL and nothing reads them yet: an
    # inventory goes to the platform owner for review before any existing
    # Collective or account is classified, and nothing is ever inferred
    # from a name. Carried in this migration to avoid a second one.
    for table in ("spaces", "users"):
        op.add_column(
            table, sa.Column("reporting_class", sa.String(24), nullable=True),
        )
        op.create_check_constraint(
            f"ck_{table}_reporting_class",
            table,
            "reporting_class IS NULL OR reporting_class IN "
            "('production', 'internal_operations', 'demonstration')",
        )


def downgrade() -> None:
    # Dropping this table discards recorded history that cannot be
    # recovered from anywhere else — that is the entire point of it.
    # Prefer disabling recording (``BUSINESS_EVENTS_ENABLED=false``),
    # which stops the producers and leaves every row intact.
    for table in ("users", "spaces"):
        op.drop_constraint(f"ck_{table}_reporting_class", table, type_="check")
        op.drop_column(table, "reporting_class")

    op.drop_column("spaces", "first_published_at")

    op.drop_index("ix_payment_transactions_settled_at", table_name="payment_transactions")
    op.drop_constraint(
        "ck_payment_transactions_settled_at_source",
        "payment_transactions",
        type_="check",
    )
    op.drop_column("payment_transactions", "settled_at_source")
    op.drop_column("payment_transactions", "settled_at")

    op.execute("ALTER TABLE business_events ALTER COLUMN sequence_number DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS business_events_seq")
    op.drop_table("business_events")
