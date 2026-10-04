"""READ-ONLY: every purchase plan and payment blocking the test cleanup.

Two accounts and one Collective are blocked from deletion by commerce
records:

  * hello@freshcollective.au   — 1 row in ``purchase_plans.member_user_id``
  * lindsey.wd@gmail.com       — 2 rows in ``purchase_plans.member_user_id``
  * the shared "Test Collective" — a purchase plan and payment
    transactions attached to the space

``purchase_plans.member_user_id`` and ``.space_id`` both RESTRICT, so
these are hard blocks rather than silent cascades. That is the schema
doing the right thing: it will not let a purchase disappear because
somebody tidied up an account.

This script exists to decide *what kind* of records they are, because
the answer changes what should happen:

  * ``stripe_mode`` is on both tables and is the only trustworthy
    live-vs-test signal. An account's name proves nothing — an address
    with "test" in it can still have taken a real card.
  * ``payment_transactions`` nulls its user references on delete
    (``payer_user_id`` and ``creator_user_id`` are both SET NULL), so
    the money rows survive an account deletion with the person detached.
    ``purchase_plans`` does not: it restricts, so it has to be resolved
    deliberately either way.

**Writes nothing. There is no ``--apply``.** Addresses are masked
unless ``--show-emails`` is passed.

Usage::

    cd backend
    .venv/bin/python scripts/audit_test_account_finances.py
    .venv/bin/python scripts/audit_test_account_finances.py --show-emails

Exit codes::

    0  ran successfully
    1  unexpected error
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("FC_SERVICE_ROLE", "job")

# ruff: noqa: E402
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.test_account_cleanup import PROTECTED_EMAILS, TARGET_EMAILS

logging.basicConfig(
    level=logging.INFO, format="%(message)s", stream=sys.stdout,
)
log = logging.getLogger("finance_audit")

#: The accounts whose commerce records blocked the cleanup. Jenson is
#: absent on purpose: his audit came back clean, so he has nothing here.
BLOCKED_EMAILS = ("hello@freshcollective.au", "lindsey.wd@gmail.com")


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "<none>"
    local, _, domain = email.partition("@")
    return f"{local[0]}{'*' * max(len(local) - 1, 0)}@{domain}"


def money(cents: int | None, currency: str | None = "AUD") -> str:
    if cents is None:
        return "<none>"
    return f"{(cents / 100):,.2f} {currency or ''}".strip()


def mode_verdict(mode: str | None) -> str:
    """What ``stripe_mode`` means for whether this was real money."""
    if mode is None:
        return "UNKNOWN (no stripe_mode recorded)"
    if mode.lower() in {"test", "sandbox"}:
        return "TEST MODE — no real money moved"
    if mode.lower() == "live":
        return "*** LIVE MODE — this was real money ***"
    return f"UNRECOGNISED mode={mode!r} — treat as real until confirmed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-emails", action="store_true",
        help="Show full addresses instead of masked ones.",
    )
    args = parser.parse_args()
    show = (lambda e: e or "<none>") if args.show_emails else mask

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with Session() as db:
        try:
            log.info("=" * 74)
            log.info("Test-account financial audit — READ-ONLY, writes nothing")
            log.info("=" * 74)

            # --- who are we talking about -----------------------------
            people = {}
            for email in set(TARGET_EMAILS) | set(PROTECTED_EMAILS):
                row = db.execute(text(
                    "SELECT id, name, role FROM users "
                    "WHERE lower(email) = lower(:e)"
                ), {"e": email}).first()
                if row:
                    people[row[0]] = (email, row[1], row[2])
                    log.info(
                        "  %-28s id=%s name=%r role=%s",
                        show(email), row[0], row[1], row[2],
                    )
            log.info("")

            blocked_ids = [
                uid for uid, (email, _n, _r) in people.items()
                if email in BLOCKED_EMAILS
            ]

            def email_of(uid: str | None) -> str:
                if uid is None:
                    return "<none>"
                known = people.get(uid)
                if known:
                    return show(known[0])
                found = db.scalar(
                    text("SELECT email FROM users WHERE id = :u"), {"u": uid},
                )
                return show(found) if found else f"<deleted user {uid}>"

            # --- which Collectives are in play ------------------------
            space_ids: set[str] = set()
            for uid in blocked_ids:
                for sid in db.execute(text(
                    "SELECT DISTINCT space_id FROM purchase_plans "
                    "WHERE member_user_id = :u AND space_id IS NOT NULL"
                ), {"u": uid}).scalars():
                    space_ids.add(sid)
                for sid in db.execute(text(
                    "SELECT DISTINCT space_id FROM space_memberships "
                    "WHERE user_id = :u"
                ), {"u": uid}).scalars():
                    space_ids.add(sid)

            log.info("-" * 74)
            log.info("COLLECTIVES INVOLVED")
            for sid in sorted(space_ids):
                row = db.execute(text(
                    "SELECT s.id, s.slug, s.name, s.status, u.email "
                    "FROM spaces s LEFT JOIN users u ON u.id = s.creator_id "
                    "WHERE s.id = :s"
                ), {"s": sid}).first()
                if not row:
                    continue
                members = db.execute(text(
                    "SELECT u.email, m.role, m.status FROM space_memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE m.space_id = :s"
                ), {"s": sid}).all()
                outsiders = [
                    m[0] for m in members
                    if m[0] not in set(TARGET_EMAILS) | set(PROTECTED_EMAILS)
                ]
                log.info("")
                log.info(
                    "  '%s' (%s) id=%s status=%s owner=%s",
                    row[2], row[1], row[0], row[3], show(row[4]),
                )
                for m in members:
                    log.info("     member %-28s role=%s status=%s",
                             show(m[0]), m[1], m[2])
                log.info(
                    "     members outside the known test accounts: %s",
                    ", ".join(show(e) for e in outsiders) if outsiders
                    else "NONE",
                )
                for label, sql in (
                    ("events", "SELECT count(*) FROM events WHERE space_id = :s"),
                    ("pathways", "SELECT count(*) FROM pathways WHERE space_id = :s"),
                    ("posts",
                     "SELECT count(*) FROM community_posts WHERE space_id = :s"),
                    ("purchase_plans",
                     "SELECT count(*) FROM purchase_plans WHERE space_id = :s"),
                    ("payment_transactions",
                     "SELECT count(*) FROM payment_transactions WHERE space_id = :s"),
                    ("payment_options",
                     "SELECT count(*) FROM payment_options WHERE space_id = :s"),
                    ("discount_codes",
                     "SELECT count(*) FROM discount_codes WHERE space_id = :s"),
                ):
                    log.info("     %-22s %4d",
                             label, db.scalar(text(sql), {"s": sid}) or 0)

            # --- purchase plans ---------------------------------------
            log.info("")
            log.info("=" * 74)
            log.info("PURCHASE PLANS")
            log.info("=" * 74)

            plan_rows = db.execute(text(
                "SELECT * FROM purchase_plans "
                "WHERE member_user_id = ANY(:u) OR space_id = ANY(:s) "
                "ORDER BY created_at"
            ), {"u": blocked_ids or [""], "s": list(space_ids) or [""]}).all()

            if not plan_rows:
                log.info("  none found")

            live_plans = 0
            for row in plan_rows:
                # dict, not RowMapping: ``.get`` tolerates a column
                # this database does not have yet. The local copy of
                # production was missing ``provider_transfer_id``,
                # and a KeyError halfway through a report is worse
                # than a blank field.
                p = dict(row._mapping)
                log.info("")
                log.info("  purchase_plan id=%s", p.get("id"))
                log.info("    member            %s  (%s)",
                         email_of(p.get("member_user_id")), p.get("member_user_id"))
                log.info("    creator           %s  (%s)",
                         email_of(p.get("creator_user_id")), p.get("creator_user_id"))
                space = db.execute(text(
                    "SELECT slug, name FROM spaces WHERE id = :s"
                ), {"s": p.get("space_id")}).first()
                log.info("    Collective        %s  (%s)",
                         f"'{space[1]}' ({space[0]})" if space else "<none>",
                         p.get("space_id"))
                log.info("    status            %s", p.get("status"))
                log.info("    structure         %s x %s  (expected total %s)",
                         p.get("installments_expected"),
                         money(p.get("installment_amount_cents"), p.get("currency")),
                         money(p.get("total_expected_cents"), p.get("currency")))
                log.info("    instalments paid  %s of %s",
                         p.get("installments_paid"), p.get("installments_expected"))
                log.info("    next_billing_at   %s", p.get("next_billing_at"))
                log.info("    activated / completed / cancelled   %s / %s / %s",
                         p.get("activated_at"), p.get("completed_at"), p.get("cancelled_at"))
                if p.get("cancelled_reason"):
                    log.info("    cancelled_reason  %s", p.get("cancelled_reason"))
                log.info("    suspended / reinstated              %s / %s",
                         p.get("suspended_at"), p.get("reinstated_at"))
                log.info("    created / updated %s / %s",
                         p.get("created_at"), p.get("updated_at"))
                log.info("    STRIPE MODE       %s -> %s",
                         p.get("stripe_mode"), mode_verdict(p.get("stripe_mode")))
                if (p.get("stripe_mode") or "").lower() == "live":
                    live_plans += 1
                for label, key in (
                    ("customer", "provider_customer_id"),
                    ("subscription", "provider_subscription_id"),
                    ("subscription_schedule", "provider_subscription_schedule_id"),
                    ("setup_session", "provider_setup_session_id"),
                    ("payment_method", "provider_payment_method_id"),
                    ("product", "stripe_product_id"),
                    ("price", "stripe_price_id"),
                    ("last_failed_invoice", "last_failed_invoice_id"),
                ):
                    if p.get(key):
                        log.info("    stripe %-22s %s", label, p.get(key))

                linked = db.execute(text(
                    "SELECT count(*), coalesce(sum(gross_amount_cents), 0) "
                    "FROM payment_transactions WHERE purchase_plan_id = :p"
                ), {"p": p.get("id")}).first()
                log.info("    linked payment_transactions  %d, gross %s",
                         linked[0], money(linked[1], p.get("currency")))

                for label, sql in (
                    ("access_passes",
                     "SELECT count(*) FROM access_passes WHERE user_id = :u"),
                    ("access_grant_records",
                     "SELECT count(*) FROM access_grant_records WHERE user_id = :u"),
                    ("pathway_entitlements",
                     "SELECT count(*) FROM pathway_entitlements WHERE user_id = :u"),
                ):
                    log.info("    member's %-20s %4d", label,
                             db.scalar(text(sql), {"u": p.get("member_user_id")}) or 0)
                log.info(
                    "    deleting this plan would destroy the purchase record "
                    "itself; the payment_transactions above are separate rows "
                    "and would survive."
                )

            # --- payment transactions ---------------------------------
            log.info("")
            log.info("=" * 74)
            log.info("PAYMENT TRANSACTIONS")
            log.info("=" * 74)

            txn_rows = db.execute(text(
                "SELECT * FROM payment_transactions "
                "WHERE payer_user_id = ANY(:u) OR creator_user_id = ANY(:u) "
                "   OR space_id = ANY(:s) "
                "ORDER BY created_at"
            ), {"u": blocked_ids or [""], "s": list(space_ids) or [""]}).all()

            if not txn_rows:
                log.info("  none found")

            live_txns = 0
            total_gross = 0
            for row in txn_rows:
                t = dict(row._mapping)
                log.info("")
                log.info("  payment_transaction id=%s", t.get("id"))
                log.info("    type / status     %s / %s",
                         t.get("transaction_type"), t.get("status"))
                log.info("    gross             %s",
                         money(t.get("gross_amount_cents"), t.get("currency")))
                log.info("    payer             %s  (%s)",
                         email_of(t.get("payer_user_id")), t.get("payer_user_id"))
                log.info("    creator           %s  (%s)",
                         email_of(t.get("creator_user_id")), t.get("creator_user_id"))
                space = db.execute(text(
                    "SELECT slug, name FROM spaces WHERE id = :s"
                ), {"s": t.get("space_id")}).first()
                log.info("    Collective        %s",
                         f"'{space[1]}' ({space[0]})" if space else "<none>")
                log.info("    created_at        %s", t.get("created_at"))
                log.info("    STRIPE MODE       %s -> %s",
                         t.get("stripe_mode"), mode_verdict(t.get("stripe_mode")))
                if (t.get("stripe_mode") or "").lower() == "live":
                    live_txns += 1
                    total_gross += t.get("gross_amount_cents") or 0
                for label, key in (
                    ("payment_intent", "provider_payment_intent_id"),
                    ("charge", "provider_charge_id"),
                    ("invoice", "provider_invoice_id"),
                    ("checkout_session", "provider_checkout_session_id"),
                    ("subscription", "provider_subscription_id"),
                    ("transfer", "provider_transfer_id"),
                ):
                    if t.get(key):
                        log.info("    stripe %-18s %s", label, t.get(key))
                log.info("    refunded          %s  last_refunded_at=%s",
                         money(t.get("refunded_amount_cents"), t.get("currency")),
                         t.get("last_refunded_at"))
                log.info("    payout status     %s  batch=%s",
                         t.get("payout_status"), t.get("payout_batch_id"))
                log.info("    purchase_plan_id  %s  instalment=%s",
                         t.get("purchase_plan_id"), t.get("installment_number"))
                log.info(
                    "    on user deletion: payer_user_id and creator_user_id "
                    "are SET NULL, so this row SURVIVES with the person "
                    "detached. On Collective deletion: space_id is SET NULL, "
                    "so it survives detached from the Collective too."
                )

            # --- verdict ----------------------------------------------
            log.info("")
            log.info("=" * 74)
            log.info("SUMMARY")
            log.info("=" * 74)
            log.info("  purchase plans found          %4d", len(plan_rows))
            log.info("    of those in LIVE mode       %4d", live_plans)
            log.info("  payment transactions found    %4d", len(txn_rows))
            log.info("    of those in LIVE mode       %4d", live_txns)
            log.info("    live gross total            %s", money(total_gross))
            log.info("")
            if live_plans or live_txns:
                log.info(
                    "  VERDICT: real money is involved. These are accounting "
                    "records, not test fixtures. Do not delete them."
                )
            else:
                log.info(
                    "  VERDICT: every row above is test-mode. No real money "
                    "moved, so nothing here is accounting history."
                )
            log.info("")
            log.info(
                "  Note on Stripe: these columns are references, not the "
                "objects. Deleting rows here does not touch anything in "
                "Stripe, and test-mode objects in Stripe are harmless to "
                "leave. A live-mode subscription that is still active would "
                "keep billing regardless of what this database says."
            )
            log.info("  Nothing was written. This script has no --apply.")
            return 0

        except Exception:
            log.exception("finance_audit: failed")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
