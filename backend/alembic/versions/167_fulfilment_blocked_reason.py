"""Record WHY a fulfilment was blocked.

Revision ID: 167
Revises: 166
Create Date: 2026-10-25

``payment_transactions.fulfilment_status = 'blocked'`` means the payment
succeeded and the access it bought could not be written. Nine code paths
set it, and until now every one of them recorded the reason in a log line
and nowhere else.

That matters because the reasons fall into two classes that call for
opposite responses:

**Temporary** — a Pathway the snapshot references was deleted, a
snapshot will not deserialise, the resolver hit a missing row. The
payment arrangement is fine. Fix the data, let Stripe re-deliver (the
handler is idempotent), and the purchase fulfils. Cancelling the
member's instalment plan here would destroy a valid arrangement.

**Permanent** — the buyer is no longer eligible for the membership the
purchase depends on. No replay will ever fix it, so somebody has to
decide between readmitting them and cancelling the plan.

Without the reason stored, an administrator looking at Admin Payments
could see *that* a purchase was undelivered but not which of those two
situations they were in. One nullable column closes that.

Deliberately NOT ``notes``
--------------------------

``payment_transactions.notes`` is existing free text used for other
purposes. Overloading it would make the reason unqueryable, unfilterable
and liable to be overwritten by an unrelated writer.

No backfill, and no inference
-----------------------------

Existing ``blocked`` rows keep ``NULL``. We do not know why they
blocked — the log line has rotated or is unattributable — and guessing
a classification is exactly the mistake this column exists to prevent.
NULL reads as "reason not recorded", which an administrator can see is
different from either class.

Nothing acts on this column automatically. It informs a human decision;
it does not make one. In particular no plan is ever cancelled because of
what it says.
"""

import sqlalchemy as sa
from alembic import op

revision = "167"
down_revision = "166"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_transactions",
        sa.Column("fulfilment_blocked_reason", sa.String(200), nullable=True),
    )
    # Partial index: "show me everything undelivered and why" is the
    # whole point, and blocked rows are a tiny minority of the table.
    op.create_index(
        "ix_payment_transactions_blocked",
        "payment_transactions",
        ["fulfilment_status"],
        postgresql_where=sa.text("fulfilment_status = 'blocked'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_transactions_blocked",
        table_name="payment_transactions",
    )
    op.drop_column("payment_transactions", "fulfilment_blocked_reason")
