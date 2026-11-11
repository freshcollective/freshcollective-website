"""Read-only diagnosis of a discounted instalment purchase.

Why this exists
---------------
Stage 4A: a member priced an instalment Payment Option at list price,
left the Stripe setup page open, came back and entered a discount code,
and was handed the original undiscounted Stripe session. The preview had
correctly shown the discounted total; the agreement did not. Checkout
resolved the in-flight setup before it looked at the code, and the
``reused`` verdict compared only the payment schedule — so the handler
returned above the code validation, above the reservation and above plan
creation.

The fix narrows reuse to the same *price* as well as the same schedule.
This script inspects an affected purchase so the damage can be assessed
without guessing: what the plan actually records, whether a discount
snapshot exists, whether a reservation or redemption was ever written,
and how much a plan established at the wrong price is still scheduled to
collect.

It is also the general shape of "show me everything about this discount
code and the plans it touched", so it is worth keeping after Stage 4A.

Safety
------
SELECT statements only. The transaction is set ``READ ONLY`` before
anything is read, so an accidental write fails at the database rather
than relying on this docstring being true. Nothing is printed that is
not needed to judge the purchase: member emails are redacted, and no
card, token or credential data is read at all.

Running it
----------
From the Render Shell for fc-api (or locally against a dev database)::

    python scripts/diagnose_stage4a_purchase.py --code STAGE4TEST2

Optionally narrow to one member::

    python scripts/diagnose_stage4a_purchase.py --code STAGE4TEST2 \
        --member-email someone@example.com

The member email is used to filter and is never printed back in full.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from app.core.database import SessionLocal


def redact(email: str | None) -> str:
    if not email or "@" not in email:
        return "(none)"
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


def heading(title: str) -> None:
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)


def dump(rows, *, redact_field: str | None = None) -> int:
    rows = list(rows)
    for row in rows:
        record = dict(row)
        if redact_field and redact_field in record:
            record[redact_field] = redact(record[redact_field])
        print(json.dumps(record, indent=2, default=str))
    if not rows:
        print("-- none --")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", default="STAGE4TEST2",
                        help="Discount code to inspect (case-insensitive).")
    parser.add_argument("--member-email", default=None,
                        help="Optional: restrict plans to one member.")
    args = parser.parse_args()
    code = args.code.strip().upper()

    db = SessionLocal()
    try:
        # Enforced, not promised: any write in this transaction now errors.
        db.execute(text("SET TRANSACTION READ ONLY"))

        heading(f"1. The discount code — {code}")
        codes = db.execute(text("""
            SELECT dc.id, dc.code, dc.discount_type, dc.percent_bps,
                   dc.amount_cents, dc.currency, dc.scope_kind, dc.scope_id,
                   dc.max_redemptions, dc.redemption_count, dc.is_active,
                   dc.expires_at, dc.space_id, s.slug AS space_slug
            FROM discount_codes dc
            JOIN spaces s ON s.id = dc.space_id
            WHERE upper(dc.code) = :code
        """), {"code": code}).mappings().all()
        dump(codes)
        if not codes:
            print("\nNo such code. Nothing further to inspect.")
            return
        code_ids = [c["id"] for c in codes]
        space_ids = [c["space_id"] for c in codes]
        print("\nNote: redemption_count on this row is a stale cache and is "
              "not authoritative. Section 2 is.")

        heading("2. Redemptions — the authoritative record of uses consumed")
        n_redemptions = dump(db.execute(text("""
            SELECT id, purchase_plan_id, payment_transaction_id,
                   original_amount_cents, discount_amount_cents,
                   final_amount_cents, currency, redeemed_at
            FROM discount_redemptions
            WHERE discount_code_id = ANY(:ids)
            ORDER BY redeemed_at
        """), {"ids": code_ids}).mappings())

        heading("3. Reservations — slots held while a checkout is in flight")
        n_reservations = dump(db.execute(text("""
            SELECT id, status, target_kind, target_id,
                   payment_option_id, payment_option_schedule_id,
                   original_amount_cents, discount_amount_cents,
                   final_amount_cents, currency,
                   provider_checkout_session_id,
                   created_at, converted_at, released_at, release_reason
            FROM discount_reservations
            WHERE discount_code_id = ANY(:ids)
            ORDER BY created_at
        """), {"ids": code_ids}).mappings())

        heading("4. Instalment plans in the same Collective")
        email_filter = "AND u.email = :email" if args.member_email else ""
        params = {"spaces": space_ids}
        if args.member_email:
            params["email"] = args.member_email
        plans = db.execute(text(f"""
            SELECT pp.id, pp.status, pp.currency,
                   pp.installment_amount_cents        AS per_instalment,
                   pp.final_installment_amount_cents  AS final_instalment,
                   pp.installments_expected, pp.installments_paid,
                   pp.total_expected_cents,
                   (pp.discount_snapshot_json IS NOT NULL)
                                                      AS has_discount_snapshot,
                   pp.discount_snapshot_json ->> 'code'  AS snapshot_code,
                   pp.provider_setup_session_id,
                   pp.provider_subscription_schedule_id,
                   pp.provider_subscription_id,
                   pp.next_billing_at, pp.created_at,
                   pp.cancelled_at, pp.cancelled_reason, pp.stripe_mode,
                   po.name AS option_name, u.email AS member_email
            FROM purchase_plans pp
            JOIN payment_options po ON po.id = pp.payment_option_id
            JOIN users u           ON u.id  = pp.member_user_id
            WHERE pp.space_id = ANY(:spaces)
              AND pp.payment_option_schedule_id IN (
                  SELECT id FROM payment_option_schedules
                  WHERE schedule_type = 'recurring_installments'
              )
              {email_filter}
            ORDER BY pp.created_at DESC
            LIMIT 40
        """), params).mappings().all()
        dump(plans, redact_field="member_email")

        heading("5. Payments actually collected on those plans")
        plan_ids = [p["id"] for p in plans] or ["-none-"]
        dump(db.execute(text("""
            SELECT pt.id, pt.purchase_plan_id, pt.installment_number,
                   pt.gross_amount_cents, pt.currency, pt.status,
                   pt.refunded_amount_cents, pt.created_at
            FROM payment_transactions pt
            WHERE pt.purchase_plan_id = ANY(:ids)
            ORDER BY pt.purchase_plan_id, pt.installment_number
        """), {"ids": plan_ids}).mappings())

        heading("6. VERDICT")
        print(f"uses consumed (redemptions):  {n_redemptions}")
        print(f"reservation rows:             {n_reservations}")
        suspect = [
            p for p in plans
            if not p["has_discount_snapshot"]
            and p["status"] not in ("cancelled",)
            and p["installments_expected"]
        ]
        if not suspect:
            print("\nNo live instalment plan lacking a discount snapshot.")
        for p in suspect:
            owed = (
                (p["installments_expected"] - p["installments_paid"])
                * (p["per_instalment"] or 0)
            )
            print(f"\nplan {p['id']}   option={p['option_name']!r}")
            print(f"  status                {p['status']}")
            print(f"  discount snapshot     NONE  <- priced at list")
            print(f"  paid                  {p['installments_paid']}"
                  f"/{p['installments_expected']} at {p['per_instalment']}"
                  f" each ({p['currency']})")
            print(f"  recorded total        {p['total_expected_cents']}")
            print(f"  STILL TO COLLECT      {owed}  <- exposure")
            print(f"  stripe schedule       "
                  f"{p['provider_subscription_schedule_id']}")
            print(f"  stripe subscription   {p['provider_subscription_id']}")
            print(f"  next billing          {p['next_billing_at']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
