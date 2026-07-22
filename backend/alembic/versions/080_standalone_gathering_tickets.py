"""Standalone paid Gatherings — ticket price, hold model, transaction type.

Revision ID: 080
Revises: 079
Create Date: 2026-07-16

Additive schema for the standalone Gathering ticket flow (see Stage 1 audit
and Stage 2 spec).

Changes:

1. `events.ticket_price_cents INT NULL`
   `events.ticket_currency    VARCHAR(3) NULL`

   Both NULL for non-`paid_separately` events. Currency stored uppercase
   ISO 4217. Currency whitelist enforced at the service/schema layer.

2. `events` CHECK constraint (deferred by application state):
     `booking_access_type <> 'paid_separately'
      OR is_published = FALSE
      OR (ticket_price_cents IS NOT NULL AND ticket_price_cents > 0
          AND ticket_currency IS NOT NULL AND LENGTH(ticket_currency) = 3)`

   Guarantees a published paid Gathering always has a valid price + currency.
   Drafts and other access types can save partial state freely.

3. `event_bookings.hold_expires_at TIMESTAMP NULL` + index
   `event_bookings.payment_transaction_id VARCHAR NULL FK payment_transactions`

   Enables the temporary capacity hold for standalone paid tickets. When
   `status = 'pending_payment'`, `hold_expires_at` is set and links to the
   pending PaymentTransaction. On webhook success the row flips to
   `confirmed` and hold_expires_at is cleared. On failure/expiry it flips
   to `cancelled`. The pre-existing `UNIQUE(event_id, user_id)` is the
   backstop preventing duplicate holds + duplicate confirmed bookings for
   the same user.

4. `bookingstatus` enum gains `pending_payment` value.

5. `payment_transaction_type_enum` gains `gathering_ticket_purchase` value.

6. `payment_transactions.provider_checkout_url VARCHAR(500) NULL`

   Stores the Stripe Checkout hosted URL so a retried checkout attempt by
   the same user (with an unexpired hold on the same event) can be safely
   redirected to the original Session rather than opening a second Session
   and dangling capacity holds.

All changes are additive. Reversible with the caveats documented in
`downgrade()`.
"""

from alembic import op
import sqlalchemy as sa


revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. events: ticket_price_cents + ticket_currency ---------------------
    op.add_column(
        "events",
        sa.Column("ticket_price_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("ticket_currency", sa.String(length=3), nullable=True),
    )

    # --- 2. events: CHECK constraint on paid_separately + published ----------
    op.create_check_constraint(
        "ck_events_ticket_price_valid_when_published",
        "events",
        (
            "booking_access_type <> 'paid_separately' "
            "OR is_published = FALSE "
            "OR (ticket_price_cents IS NOT NULL "
            "    AND ticket_price_cents > 0 "
            "    AND ticket_currency IS NOT NULL "
            "    AND char_length(ticket_currency) = 3)"
        ),
    )

    # --- 3. event_bookings: hold_expires_at + payment_transaction_id --------
    op.add_column(
        "event_bookings",
        sa.Column("hold_expires_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.add_column(
        "event_bookings",
        sa.Column(
            "payment_transaction_id",
            sa.String(),
            sa.ForeignKey("payment_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_event_bookings_hold_expires_at",
        "event_bookings",
        ["hold_expires_at"],
        postgresql_where=sa.text("hold_expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_event_bookings_payment_transaction_id",
        "event_bookings",
        ["payment_transaction_id"],
    )

    # --- 4. bookingstatus enum: add pending_payment --------------------------
    # ADD VALUE cannot run in a transaction block; autocommit_block handles it.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE bookingstatus ADD VALUE IF NOT EXISTS 'pending_payment'"
        )

    # --- 5. payment_transaction_type_enum: add gathering_ticket_purchase ----
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE payment_transaction_type_enum "
            "ADD VALUE IF NOT EXISTS 'gathering_ticket_purchase'"
        )

    # --- 6. payment_transactions.provider_checkout_url ----------------------
    op.add_column(
        "payment_transactions",
        sa.Column("provider_checkout_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    # PostgreSQL cannot remove enum values without recreating the type. Since
    # rows may reference the new values, we intentionally do NOT drop the
    # enum labels here; leaving them in place is harmless.
    op.drop_column("payment_transactions", "provider_checkout_url")
    op.drop_index("ix_event_bookings_payment_transaction_id", table_name="event_bookings")
    op.drop_index("ix_event_bookings_hold_expires_at", table_name="event_bookings")
    op.drop_column("event_bookings", "payment_transaction_id")
    op.drop_column("event_bookings", "hold_expires_at")
    op.drop_constraint(
        "ck_events_ticket_price_valid_when_published",
        "events",
        type_="check",
    )
    op.drop_column("events", "ticket_currency")
    op.drop_column("events", "ticket_price_cents")
