"""Connect rows leave the manual payout queue.

Revision ID: 146
Revises: 145
Create Date: 2026-10-01

``payout_status`` tracks Fresh Collective's *manual* payout bookkeeping:
``pending`` means FC owes this creator money by hand, ``paid`` means a
payout batch recorded a disbursement. Neither is true of a Connect row,
whose creator share reaches them through a Stripe transfer —
``connect_transfer_status`` is the authority for those.

Every creation path already wrote ``not_applicable`` for Connect rows.
The payment-succeeded webhook then overwrote it unconditionally with
``pending``, so every Connect sale landed back in the manual queue the
moment it was paid. No creator could be paid twice — the payout batch
query filters ``payout_model = 'manual'`` explicitly — but the money
showed up in two reporting figures as still owed by hand: the admin
"Pending Payouts" total, and the creator's own pending-payout estimate
on Payments received.

This repairs the rows that already went through that path. The webhook
is fixed in the same commit, so the condition cannot recur.

Scope and safety
----------------
Touches **only** ``payout_model = 'connect'`` rows sitting at
``pending``. Manual history is not read and not written. Rows already
``not_applicable`` are skipped by the predicate, so re-running is a
no-op — which also makes the downgrade honest: there is no way to tell,
afterwards, which ``not_applicable`` Connect rows this statement set and
which were already correct, and guessing would corrupt the ones that
were right all along. The downgrade is therefore deliberately empty.
"""

from alembic import op

revision = "146"
down_revision = "145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE payment_transactions
           SET payout_status = 'not_applicable',
               updated_at = NOW()
         WHERE payout_model = 'connect'
           AND payout_status = 'pending'
        """
    )


def downgrade() -> None:
    """Deliberately empty.

    Reverting would mean setting Connect rows back to ``pending`` — but
    the rows this touched are indistinguishable from Connect rows that
    were always ``not_applicable``, so a blanket revert would push
    correct rows into the manual payout queue. Leaving the data correct
    is the safer direction to fail in, and nothing downstream reads
    ``pending`` on a Connect row for anything but a mistake.
    """
