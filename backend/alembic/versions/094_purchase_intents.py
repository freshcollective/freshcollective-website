"""PurchaseIntent — foundation table for pre-account and pre-consumption
purchase journeys (Stage 1 of the payment-first redesign).

Revision ID: 094
Revises: 093
Create Date: 2026-08-03

Adds ``purchase_intents`` to hold a Fresh Collective purchase journey
from selection through to entitlement grant. This is deliberately
distinct from the ``payment_transactions`` ledger — a `PurchaseIntent`
may exist before any Stripe Session is created and before any user
account exists, whereas a `PaymentTransaction` represents money that
has actually moved.

This migration is additive only:

  * Creates two new native PostgreSQL enum types:
      ``purchase_intent_kind_enum``
      ``purchase_intent_status_enum``
  * Creates the ``purchase_intents`` table with the schema described
    in ``app/models/purchase_intent.py``.
  * Creates three indexes, two of which are partial unique indexes
    to allow many rows to share NULL before a Stripe Checkout Session
    or claim token is generated.

No data is migrated. No existing table is altered. All existing
Stripe, checkout, entitlement and role behaviour is untouched.
Downgrade drops the table and the two enum types.
"""

from alembic import op
import sqlalchemy as sa


revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum types are created implicitly by ``create_table`` via the
    # column-level ``sa.Enum(...)`` references below (default
    # ``create_type=True``). Downgrade drops them explicitly to leave
    # the database clean on rollback.
    kind_enum = sa.Enum(
        "creator_subscription",
        "collective_membership",
        "pathway",
        "gathering",
        name="purchase_intent_kind_enum",
    )
    status_enum = sa.Enum(
        "pending",
        "paid",
        "consumed",
        "cancelled",
        "expired",
        "refunded",
        name="purchase_intent_status_enum",
    )

    op.create_table(
        "purchase_intents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", kind_enum, nullable=False),
        sa.Column(
            "status",
            status_enum,
            nullable=False,
            server_default="pending",
        ),
        # Parties
        sa.Column(
            "payer_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Subject
        sa.Column("plan_slug", sa.String(length=32), nullable=True),
        sa.Column(
            "space_id",
            sa.String(),
            sa.ForeignKey("spaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "pathway_id",
            sa.String(),
            sa.ForeignKey("pathways.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payment_option_id",
            sa.String(),
            sa.ForeignKey("payment_options.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Pricing snapshot (populated at Session creation)
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("gross_amount_cents", sa.Integer(), nullable=True),
        sa.Column("platform_fee_bps", sa.Integer(), nullable=True),
        # Provider
        sa.Column(
            "provider",
            sa.String(length=16),
            nullable=False,
            server_default="stripe",
        ),
        sa.Column(
            "provider_checkout_session_id", sa.String(length=200), nullable=True
        ),
        sa.Column("provider_customer_id", sa.String(length=200), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=200), nullable=True),
        # Claim token (raw token never stored)
        sa.Column("claim_email", sa.String(length=320), nullable=True),
        sa.Column("claim_token_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "claim_token_expires_at", sa.DateTime(timezone=False), nullable=True
        ),
        # Consumption tracking
        sa.Column("paid_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "consumed_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Audit
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Partial unique index: at most one intent per Stripe Session, but
    # many intents can share NULL before a Session is created.
    op.create_index(
        "ix_purchase_intents_provider_checkout_session_id",
        "purchase_intents",
        ["provider_checkout_session_id"],
        unique=True,
        postgresql_where=sa.text("provider_checkout_session_id IS NOT NULL"),
    )
    # Partial unique index on claim-token hash; NULLs allowed pre-token.
    op.create_index(
        "ix_purchase_intents_claim_token_hash",
        "purchase_intents",
        ["claim_token_hash"],
        unique=True,
        postgresql_where=sa.text("claim_token_hash IS NOT NULL"),
    )
    # Reconciler / expiry-sweeper query shape.
    op.create_index(
        "ix_purchase_intents_status_created_at",
        "purchase_intents",
        ["status", "created_at"],
    )
    # Support common payer-side lookups (e.g. "my in-flight intents").
    op.create_index(
        "ix_purchase_intents_payer_user_id",
        "purchase_intents",
        ["payer_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_intents_payer_user_id",
        table_name="purchase_intents",
    )
    op.drop_index(
        "ix_purchase_intents_status_created_at",
        table_name="purchase_intents",
    )
    op.drop_index(
        "ix_purchase_intents_claim_token_hash",
        table_name="purchase_intents",
    )
    op.drop_index(
        "ix_purchase_intents_provider_checkout_session_id",
        table_name="purchase_intents",
    )
    op.drop_table("purchase_intents")
    sa.Enum(name="purchase_intent_status_enum").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="purchase_intent_kind_enum").drop(op.get_bind(), checkfirst=False)
