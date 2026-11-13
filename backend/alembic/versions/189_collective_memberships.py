"""Recurring paid membership of a Collective.

One new table and one new column. Nothing is backfilled, nobody is
subscribed, and the whole feature stays behind
``PAID_COLLECTIVE_MEMBERSHIP_ENABLED`` — so applying this migration
changes no behaviour at all.

``collective_memberships`` is the member's *financial agreement*, kept
separate from ``space_memberships``, which remains the one record of who
belongs. The two are joined only by the flow that activates one from the
other: a verified first payment calls
``membership_grant.ensure_membership_for_purchase``. A member who
returns keeps their one membership relationship and gains a second
subscription row, which is why there is no unique constraint on
``(user_id, space_id)`` outright — only on the live ones.

Agreed terms are columns rather than lookups
--------------------------------------------
``interval``, ``amount_cents``, ``currency`` and the Stripe Price are
frozen here at subscribe time, and the fee context with them. A creator
who re-prices their Collective tomorrow does not re-price anybody who
already subscribed, because nothing re-reads
``spaces.pricing_amount_cents`` after this row exists. The same
reasoning, and the same column shape, as ``purchase_plans``.

``payment_transactions.billing_period_*``
--------------------------------------
Two nullable columns on the shared ledger, naming which period a
recurring payment bought. On the payment rather than the subscription
because that is whose question it is — a renewal differs from a first
invoice by its period and nothing else, and the creator's Payments
received has to be able to say which month a row covers.

``spaces.paid_membership_effective_at``
---------------------------------------
Nullable, and left NULL by this migration. It is the single field the
free-to-paid transition needs later: NULL means no transition is set,
and a timestamp is the date from which membership must be paid for.
Added now because the billing foundation reads it to decide whether an
existing free member is being asked to subscribe, and one nullable
column is cheaper than a second migration.

Nothing reads it to *act* yet — no sweep, no pausing, no scheduling.
That is Stage 5A.2.

Revision ID: 189
Revises: 188
"""

from alembic import op
import sqlalchemy as sa

revision = "189"
down_revision = "188"
branch_labels = None
depends_on = None


#: Live statuses — a subscription that is or could still be billing.
#: The partial unique index below uses exactly this list, so a member
#: cannot hold two live agreements for one Collective while keeping any
#: number of finished ones.
_LIVE = ("pending", "active", "past_due")


def upgrade() -> None:
    op.create_table(
        "collective_memberships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "space_id", sa.String(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),

        # ── Agreed terms, frozen ────────────────────────────────────
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("interval_count", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("stripe_product_id", sa.String(200), nullable=True),
        sa.Column("stripe_price_id", sa.String(200), nullable=True),

        # ── Stripe ──────────────────────────────────────────────────
        sa.Column("stripe_customer_id", sa.String(200), nullable=True),
        sa.Column("stripe_checkout_session_id", sa.String(200), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(200), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=False),
                  nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=False),
                  nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),

        # ── Creator payment context, frozen ─────────────────────────
        sa.Column(
            "creator_user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("platform_fee_basis_points", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("payout_model", sa.String(20), nullable=True),
        sa.Column("connect_destination_account_id", sa.String(200),
                  nullable=True),
        sa.Column("creator_plan_id", sa.String(), nullable=True),

        # ── Lifecycle ───────────────────────────────────────────────
        sa.Column("activated_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancelled_reason", sa.String(250), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        # Stage 5A.2 reads these; nothing writes them yet.
        sa.Column("payment_problem_started_at", sa.DateTime(timezone=False),
                  nullable=True),
        sa.Column("grace_expires_at", sa.DateTime(timezone=False),
                  nullable=True),
        sa.Column("last_failed_invoice_id", sa.String(200), nullable=True),

        # ── Provenance ──────────────────────────────────────────────
        sa.Column("stripe_mode", sa.String(10), nullable=False,
                  server_default="test"),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),

        sa.CheckConstraint("amount_cents > 0",
                           name="ck_collective_memberships_amount_positive"),
        sa.CheckConstraint(
            "status IN ('pending','active','past_due','cancel_scheduled',"
            "'ended','cancelled','failed')",
            name="ck_collective_memberships_status",
        ),
        sa.CheckConstraint(
            "interval IN ('month','year')",
            name="ck_collective_memberships_interval",
        ),
    )

    # One live agreement per member per Collective, enforced by the
    # database rather than by a handler remembering to look. A replayed
    # webhook or a double-clicked Join collides here; finished
    # subscriptions are unconstrained, so resubscribing works.
    op.create_index(
        "uq_collective_memberships_live",
        "collective_memberships",
        ["user_id", "space_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'active', 'past_due')"
        ),
    )
    # The webhook's lookup: Stripe hands us a subscription id and we need
    # the row. Unique because one Stripe subscription is one agreement.
    op.create_index(
        "uq_collective_memberships_stripe_subscription",
        "collective_memberships",
        ["stripe_subscription_id"],
        unique=True,
        postgresql_where=sa.text("stripe_subscription_id IS NOT NULL"),
    )
    # The checkout-completion lookup, before a subscription id exists.
    op.create_index(
        "ix_collective_memberships_checkout_session",
        "collective_memberships",
        ["stripe_checkout_session_id"],
    )

    op.add_column(
        "spaces",
        sa.Column("paid_membership_effective_at",
                  sa.DateTime(timezone=False), nullable=True),
    )

    # Which period a recurring payment bought.
    #
    # Added to the shared ledger rather than kept on the subscription,
    # because the question belongs to the payment: a renewal and the
    # first invoice differ by their period and by nothing else, and the
    # creator's Payments received has to be able to say which month a
    # row is for. Nullable and left NULL for every existing row — no
    # historical transaction has a period, and inventing one would be
    # a guess.
    op.add_column(
        "payment_transactions",
        sa.Column("billing_period_start", sa.DateTime(timezone=False),
                  nullable=True),
    )
    op.add_column(
        "payment_transactions",
        sa.Column("billing_period_end", sa.DateTime(timezone=False),
                  nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_transactions", "billing_period_end")
    op.drop_column("payment_transactions", "billing_period_start")
    op.drop_column("spaces", "paid_membership_effective_at")
    op.drop_index("ix_collective_memberships_checkout_session",
                  table_name="collective_memberships")
    op.drop_index("uq_collective_memberships_stripe_subscription",
                  table_name="collective_memberships")
    op.drop_index("uq_collective_memberships_live",
                  table_name="collective_memberships")
    op.drop_table("collective_memberships")
