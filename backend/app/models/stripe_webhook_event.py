"""``stripe_webhook_events`` — idempotency dedup for the Stripe
webhook endpoint.

Each Stripe event carries a globally-unique ``event.id``. Writing that
id into this table with a UNIQUE PK gives us a trivial "have I seen
this event before?" check. Every creator-billing (and any future)
webhook handler must:

  1. Check for an existing row with the incoming ``event.id``.
  2. If present, log-and-skip.
  3. If absent, insert (INSERT ... ON CONFLICT DO NOTHING is safest
     against concurrent deliveries), then process, then set
     ``processed_at``.

``payload_sha256`` is stored as a defence against replay-with-mutation:
if the same event.id ever arrives with a different body hash, we treat
it as suspicious and refuse to process.

Not populated retroactively — earlier finite-plan handlers use
row-level SELECT FOR UPDATE for their own idempotency and are
unaffected by this table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StripeWebhookEvent(Base):
    __tablename__ = "stripe_webhook_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # stripe event.id
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True,
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
