"""Payout reconciliation — read-only.

Why this exists
---------------
World Insights reported $1,560 outstanding to creators while Stripe
showed $1,564.28 already paid into the platform's bank account. They are
different subtractions over possibly different populations, and proving
that needs figures rather than argument.

This is the Python equivalent of ``payout_reconciliation.sql``, written
because the fc-api Render Shell has no ``psql``. It uses the application's
own SQLAlchemy engine and therefore the connection the app already has —
nothing new to configure and nothing to paste.

What it will not do
-------------------
* **It cannot write.** Every statement runs inside a transaction opened
  with ``SET TRANSACTION READ ONLY``, which PostgreSQL enforces at the
  server, and the transaction is rolled back at the end regardless. A
  stray ``UPDATE`` would raise rather than apply.
* **No secrets.** The connection string is never printed or logged. Bank
  details are not stored by Fresh Collective at all; Stripe and Connect
  account identifiers are reported as present or absent, never by value.
* **No email addresses.** Creators and Collectives are named, since the
  question is which Collective owes what, but no contact detail is read.

Usage
-----
    python scripts/reporting/payout_reconciliation.py

Run it from the fc-api Render Shell. Add ``--sql`` to print the query
behind each section instead of running it, if you would rather read the
SQL than trust the headings.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

# Side-effect import that resolves the SQLAlchemy relationship graph.
# Does not start uvicorn.
import app.models.community_care  # noqa: E402,F401
from app.core.database import engine  # noqa: E402

# ---------------------------------------------------------------------------
# The member purchase types, taken from the one authoritative definition
# rather than retyped — a reconciliation that disagreed with the metrics
# it is checking would be worse than none.
# ---------------------------------------------------------------------------
from app.reporting.eligibility import member_txn_values, settled_status_values  # noqa: E402

MEMBER_TYPES = tuple(member_txn_values())
SETTLED = tuple(settled_status_values())

#: The five types the registry knew about before this correction. Kept so
#: the script can show exactly what was invisible, which is the figure
#: worth checking against the corrected dashboard.
PRE_FIX_TYPES = (
    "member_pathway_purchase",
    "member_collective_purchase",
    "member_pathway_subscription",
    "member_collective_subscription",
    "gathering_ticket_purchase",
)


class Section:
    """One question, its SQL, and how to read the answer."""

    def __init__(self, title: str, note: str, sql: str, params: dict | None = None):
        self.title = title
        self.note = note
        self.sql = sql
        self.params = params or {}


def sections() -> list[Section]:
    member_types = {"types": list(MEMBER_TYPES)}
    settled = {"settled": list(SETTLED)}
    both = {**member_types, **settled}

    return [
        Section(
            "A. What the outstanding figure is made of",
            "Every row with payout_status = pending, grouped by what kind of "
            "row it is. The corrected metric counts only settled member "
            "purchases with a creator, in the platform's Stripe mode.",
            """
            SELECT pt.transaction_type,
                   pt.status,
                   pt.stripe_mode,
                   pt.payout_model,
                   COUNT(*) AS rows,
                   SUM(COALESCE(pt.net_creator_amount_cents, 0)
                       - COALESCE(pt.refunded_creator_amount_cents, 0))
                       / 100.0 AS dollars
            FROM payment_transactions pt
            WHERE pt.payout_status = 'pending'
            GROUP BY 1, 2, 3, 4
            ORDER BY dollars DESC
            """,
        ),
        Section(
            "B. The corrected total, and what the old one counted",
            "If these differ, the difference is rows that were never a "
            "creator obligation: abandoned checkouts, sandbox rows, or "
            "platform-owned Collectives.",
            """
            SELECT
              (SELECT SUM(COALESCE(net_creator_amount_cents, 0)
                          - COALESCE(refunded_creator_amount_cents, 0)) / 100.0
                 FROM payment_transactions
                WHERE payout_status = 'pending')                AS old_unfiltered,
              (SELECT SUM(COALESCE(net_creator_amount_cents, 0)
                          - COALESCE(refunded_creator_amount_cents, 0)) / 100.0
                 FROM payment_transactions
                WHERE payout_status = 'pending'
                  AND status::text = ANY(:settled)
                  AND transaction_type::text = ANY(:types)
                  AND creator_user_id IS NOT NULL
                  AND net_creator_amount_cents IS NOT NULL
                  AND stripe_mode = 'live')                     AS corrected_live,
              (SELECT SUM(COALESCE(net_creator_amount_cents, 0)
                          - COALESCE(refunded_creator_amount_cents, 0)) / 100.0
                 FROM payment_transactions
                WHERE payout_status = 'pending'
                  AND status::text = ANY(:settled)
                  AND transaction_type::text = ANY(:types)
                  AND creator_user_id IS NOT NULL
                  AND net_creator_amount_cents IS NOT NULL
                  AND stripe_mode = 'test')                     AS corrected_test
            """,
            both,
        ),
        Section(
            "C. Unsuccessful transactions still carrying a pending payout",
            "A ledger row is created when the Checkout Session opens, "
            "already marked pending. The Gathering-ticket release path did "
            "not clear it. Anything here is money no member ever paid; the "
            "code fix is prospective, so these are the historical rows.",
            """
            SELECT pt.status,
                   pt.transaction_type,
                   pt.stripe_mode,
                   COUNT(*) AS rows,
                   SUM(COALESCE(pt.net_creator_amount_cents, 0)) / 100.0 AS dollars,
                   MIN(pt.created_at) AS earliest,
                   MAX(pt.created_at) AS latest
            FROM payment_transactions pt
            WHERE pt.payout_status = 'pending'
              AND NOT (pt.status::text = ANY(:settled))
            GROUP BY 1, 2, 3
            ORDER BY dollars DESC NULLS LAST
            """,
            settled,
        ),
        Section(
            "D. Who the money is owed to, by Collective and arrangement",
            "Settled member purchases only, so this is the genuine "
            "obligation. 'founder-operated' means the Collective's creator "
            "holds the admin role; reporting_class is whatever an operator "
            "has assigned, and NULL means not yet reviewed.",
            """
            SELECT s.name                           AS collective,
                   u.name                           AS creator,
                   u.role                           AS creator_role,
                   COALESCE(s.reporting_class, '(unclassified)') AS reporting_class,
                   pt.payout_model,
                   pt.stripe_mode,
                   COUNT(*)                         AS payments,
                   SUM(pt.gross_amount_cents) / 100.0           AS gross,
                   SUM(pt.platform_fee_cents) / 100.0           AS platform_fee,
                   SUM(COALESCE(pt.processing_fee_cents, 0)) / 100.0 AS stripe_fee,
                   COUNT(*) - COUNT(pt.processing_fee_cents)    AS fee_unknown,
                   SUM(COALESCE(pt.net_creator_amount_cents, 0)
                       - COALESCE(pt.refunded_creator_amount_cents, 0))
                       / 100.0                      AS owed
            FROM payment_transactions pt
            LEFT JOIN spaces s ON s.id = pt.space_id
            LEFT JOIN users  u ON u.id = pt.creator_user_id
            WHERE pt.payout_status = 'pending'
              AND pt.status::text = ANY(:settled)
            GROUP BY 1, 2, 3, 4, 5, 6
            ORDER BY owed DESC NULLS LAST
            """,
            settled,
        ),
        Section(
            "E. What the old revenue metrics could not see",
            "The five types the registry knew about, against the two it did "
            "not. The 'INVISIBLE' rows are the gross sales that were missing "
            "from gross volume, creator earnings, platform fee, processing "
            "costs, refunds and contribution.",
            """
            SELECT pt.transaction_type,
                   CASE WHEN pt.transaction_type::text = ANY(:pre_fix)
                        THEN 'was counted'
                        ELSE 'INVISIBLE before the fix' END AS visibility,
                   pt.stripe_mode,
                   COUNT(*) AS payments,
                   SUM(pt.gross_amount_cents) / 100.0 AS gross,
                   SUM(pt.platform_fee_cents) / 100.0 AS platform_fee,
                   SUM(COALESCE(pt.net_creator_amount_cents, 0)) / 100.0
                       AS creator_earnings
            FROM payment_transactions pt
            WHERE pt.transaction_type::text = ANY(:types)
              AND pt.status::text = ANY(:settled)
            GROUP BY 1, 2, 3
            ORDER BY gross DESC NULLS LAST
            """,
            {**both, "pre_fix": list(PRE_FIX_TYPES)},
        ),
        Section(
            "F. Reconciling against the Stripe bank payouts",
            "Stripe pays the platform gross minus its fee. Creator earnings "
            "are gross minus the platform fee. Two different subtractions "
            "over the same charges, which is why they land close together "
            "without being the same quantity.",
            """
            SELECT to_char(date_trunc('week',
                       COALESCE(pt.settled_at, pt.created_at)),
                       'YYYY-MM-DD')                            AS week_beginning,
                   COUNT(*)                                     AS payments,
                   SUM(pt.gross_amount_cents) / 100.0           AS members_paid,
                   SUM(COALESCE(pt.processing_fee_cents, 0)) / 100.0 AS stripe_fees,
                   (SUM(pt.gross_amount_cents)
                      - SUM(COALESCE(pt.processing_fee_cents, 0))
                      - SUM(COALESCE(pt.refunded_amount_cents, 0)))
                      / 100.0                                   AS expected_into_bank,
                   SUM(pt.platform_fee_cents) / 100.0           AS platform_kept,
                   SUM(COALESCE(pt.net_creator_amount_cents, 0)
                       - COALESCE(pt.refunded_creator_amount_cents, 0))
                       / 100.0                                  AS creator_share
            FROM payment_transactions pt
            WHERE pt.status::text = ANY(:settled)
              AND pt.transaction_type::text = ANY(:types)
              AND pt.stripe_mode = 'live'
            GROUP BY 1
            ORDER BY 1
            """,
            both,
        ),
        Section(
            "G. Refunds and adjustments",
            "Shown on their own because a refund belongs to the period it "
            "happened in, not the period of the sale.",
            """
            SELECT pt.transaction_type,
                   pt.status,
                   pt.payout_status,
                   COUNT(*) AS rows,
                   SUM(COALESCE(pt.refunded_amount_cents, 0)) / 100.0
                       AS refunded_to_members,
                   SUM(COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0
                       AS reversed_from_creator,
                   SUM(COALESCE(pt.refunded_platform_fee_cents, 0)) / 100.0
                       AS reversed_from_platform,
                   MAX(pt.last_refunded_at) AS most_recent
            FROM payment_transactions pt
            WHERE COALESCE(pt.refunded_amount_cents, 0) > 0
               OR pt.transaction_type IN ('refund', 'adjustment')
            GROUP BY 1, 2, 3
            ORDER BY refunded_to_members DESC NULLS LAST
            """,
        ),
        Section(
            "H. Payouts recorded, by arrangement",
            "payout_status = paid is only ever written by a recorded payout "
            "batch. If no batch appears, no creator payout has been "
            "recorded, whatever has moved through the bank.",
            """
            SELECT pt.payout_model,
                   pt.payout_status,
                   COUNT(*) AS rows,
                   COUNT(DISTINCT pt.payout_batch_id) AS batches,
                   SUM(COALESCE(pt.net_creator_amount_cents, 0)
                       - COALESCE(pt.refunded_creator_amount_cents, 0))
                       / 100.0 AS dollars,
                   MIN(pt.payout_marked_at) AS first_marked,
                   MAX(pt.payout_marked_at) AS last_marked
            FROM payment_transactions pt
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
        ),
        Section(
            "I. Connect transfers",
            "The authority for Connect rows is their transfer status, not "
            "payout_status. Account identifiers are withheld — only whether "
            "a destination is present.",
            """
            SELECT pt.connect_transfer_status,
                   pt.stripe_mode,
                   COUNT(*) AS rows,
                   COUNT(pt.connect_destination_account_id) AS with_destination,
                   SUM(COALESCE(pt.transfer_amount_cents, 0)) / 100.0 AS transferred,
                   SUM(COALESCE(pt.connect_unrecovered_amount_cents, 0)) / 100.0
                       AS unrecovered
            FROM payment_transactions pt
            WHERE pt.payout_model = 'connect'
            GROUP BY 1, 2
            ORDER BY rows DESC
            """,
        ),
        Section(
            "J. Creator payout batches on record",
            "",
            """
            SELECT b.id,
                   b.status,
                   b.created_at,
                   b.transaction_count,
                   b.total_amount_cents / 100.0 AS dollars
            FROM creator_payout_batches b
            ORDER BY b.created_at DESC
            LIMIT 20
            """,
        ),
        Section(
            "K. Connect readiness, without account identifiers",
            "Payouts disabled or a restricted status is why a creator's rows "
            "stay on the manual arrangement.",
            """
            SELECT u.name                                   AS creator,
                   u.role,
                   a.stripe_mode,
                   a.stripe_account_id IS NOT NULL          AS account_exists,
                   a.payouts_status,
                   a.payouts_enabled,
                   a.connect_payouts_enabled_at IS NOT NULL AS fc_routing_enabled
            FROM creator_stripe_accounts a
            LEFT JOIN users u ON u.id = a.creator_user_id
            ORDER BY 1, 3
            """,
        ),
        Section(
            "L. Collectives and their reporting class",
            "Nothing is inferred from a name. NULL means an operator has not "
            "reviewed it yet, and the reporting counts those as "
            "'unclassified' rather than assuming production.",
            """
            SELECT s.name                                     AS collective,
                   s.status,
                   COALESCE(s.reporting_class, '(unclassified)') AS reporting_class,
                   u.name                                     AS creator,
                   u.role                                     AS creator_role,
                   COALESCE(u.reporting_class, '(unclassified)')
                       AS creator_reporting_class
            FROM spaces s
            LEFT JOIN users u ON u.id = s.creator_id
            ORDER BY 3, 1
            """,
        ),
    ]


def _render(rows, keys) -> None:
    """A plain fixed-width table. No dependency, no cleverness."""
    if not rows:
        print("    (no rows)")
        return
    text_rows = [
        ["" if v is None else str(v) for v in row]
        for row in rows
    ]
    widths = [
        max(len(str(k)), *(len(r[i]) for r in text_rows))
        for i, k in enumerate(keys)
    ]
    line = "    " + "  ".join(str(k).ljust(w) for k, w in zip(keys, widths))
    print(line)
    print("    " + "  ".join("-" * w for w in widths))
    for r in text_rows:
        print("    " + "  ".join(v.ljust(w) for v, w in zip(r, widths)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sql",
        action="store_true",
        help="print each section's SQL instead of running it",
    )
    args = parser.parse_args()

    if args.sql:
        for s in sections():
            print(f"\n--- {s.title} ---")
            if s.note:
                print(f"-- {s.note}")
            print(s.sql.strip())
        return 0

    print("Payout reconciliation — read-only. Nothing is written.\n")

    with engine.connect() as conn:
        # Enforced by PostgreSQL, not by this script's good intentions.
        conn.execute(text("SET TRANSACTION READ ONLY"))
        for s in sections():
            print(f"\n=== {s.title} ===")
            if s.note:
                for chunk in _wrap(s.note):
                    print(f"  {chunk}")
            result = conn.execute(text(s.sql), s.params)
            _render(result.fetchall(), result.keys())
        # Explicit, so the read-only transaction is closed by intent
        # rather than by the context manager's default.
        conn.rollback()

    print("\nDone. The transaction was rolled back; no rows were changed.")
    return 0


def _wrap(s: str, width: int = 74) -> list[str]:
    words, lines, current = s.split(), [], ""
    for w in words:
        if len(current) + len(w) + 1 > width:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    if current:
        lines.append(current)
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
