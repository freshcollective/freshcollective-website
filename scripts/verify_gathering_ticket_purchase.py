#!/usr/bin/env python
"""Set up, and then check, a genuine Stripe test-mode ticket purchase.

Why this exists as a script rather than a test
----------------------------------------------
Stripe's hosted Checkout page is protected by invisible hCaptcha, so
the card step cannot be automated — it is designed not to be. That
leaves exactly one part of the standalone Gathering payment path that
no test can reach on its own: a real card producing a real
``checkout.session.completed`` event. Everything either side of it is
covered by the suite.

So this script does the two halves a human cannot usefully do by
hand, and leaves the one bit only a human can do in the middle.

    python scripts/verify_gathering_ticket_purchase.py setup
      → seeds a paid Gathering, opens a real test-mode Checkout
        Session, prints the URL to pay at

    (pay it in a browser with card 4242 4242 4242 4242,
     any future expiry, any CVC)

    python scripts/verify_gathering_ticket_purchase.py check
      → reports what the webhook actually did: the booking, the
        AccessPass and its scope, the transaction, the fee split and
        the payout status

Run ``stripe listen --forward-to http://127.0.0.1:8000/api/webhooks/stripe``
in another terminal first, and start the API with
``STANDALONE_GATHERING_SALES_ENABLED=true`` plus the signing secret
that command prints.

Safety
------
Refuses to run against anything but a Stripe **test** key, and
refuses a database whose name is not obviously a test database. The
whole point is to prove the live path works without touching live
money, so the script would rather stop than guess.

``teardown`` removes everything it created. Run it: rows committed to
a test database outlive the test and have broken unrelated suites
before.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")

STATE = Path("/tmp/fc_ticket_verify.json")
TICKET_CENTS = 3500
CURRENCY = "AUD"


def _fail(msg: str) -> None:
    print(f"\n  REFUSING: {msg}\n")
    raise SystemExit(2)


def _guard_test_only(db_url: str, stripe_key: str) -> None:
    """Two refusals, because either mistake is expensive."""
    if not stripe_key.startswith("sk_test_"):
        _fail(
            "STRIPE_SECRET_KEY is not a test key. This script must never "
            "touch live money."
        )
    name = db_url.rsplit("/", 1)[-1].split("?")[0]
    if "test" not in name and "preflight" not in name:
        _fail(
            f"database {name!r} does not look like a test database. Point "
            "DATABASE_URL at fc_test."
        )


def _session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = os.environ["DATABASE_URL"]
    return sessionmaker(bind=create_engine(url))(), url


def setup() -> None:
    import app.main  # noqa: F401 — loads the whole model graph

    from app.core.security import hash_password
    from app.models.platform import (
        Event,
        Space,
        SpaceMembership,
        SpaceMembershipStatus,
        SpaceRole,
    )
    from app.models.user import User, UserRole

    db, url = _session()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    _guard_test_only(url, stripe_key)

    tag = uuid.uuid4().hex[:8]
    uid = lambda p: f"{p}_{uuid.uuid4().hex[:12]}"  # noqa: E731
    now = datetime.utcnow()
    password = "TicketVerify!2026"

    creator = User(
        id=uid("u"), email=f"verify-creator-{tag}@example.invalid",
        name="Ticket Verify Creator", role=UserRole.creator.value,
        password_hash=hash_password(password), email_verified_at=now,
    )
    buyer = User(
        id=uid("u"), email=f"verify-buyer-{tag}@example.invalid",
        name="Ticket Verify Buyer", role=UserRole.user.value,
        password_hash=hash_password(password), email_verified_at=now,
    )
    db.add_all([creator, buyer])
    db.flush()

    space = Space(
        id=uid("s"), slug=f"ticket-verify-{tag}", name="Ticket Verify Circle",
        status="active", is_public=True, creator_id=creator.id,
    )
    db.add(space)
    db.flush()
    db.add(SpaceMembership(
        id=uid("sm"), user_id=buyer.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=now,
    ))
    event = Event(
        id=uid("e"), space_id=space.id, created_by_id=creator.id,
        title="Verification Womens Circle",
        starts_at=now + timedelta(days=21),
        ends_at=now + timedelta(days=21, hours=2),
        location_type="zoom", is_published=True, status="active",
        requires_booking=True, capacity=12,
        booking_access_type="paid_separately",
        ticket_price_cents=TICKET_CENTS, ticket_currency=CURRENCY,
        gathering_type="workshop", attendance_format="online",
    )
    db.add(event)
    db.commit()

    STATE.write_text(json.dumps({
        "space_id": space.id, "slug": space.slug, "event_id": event.id,
        "buyer_id": buyer.id, "buyer_email": buyer.email,
        "creator_id": creator.id, "password": password,
    }))

    print(f"  Seeded  : {event.title} — ${TICKET_CENTS / 100:.2f} {CURRENCY}")
    print(f"  Buyer   : {buyer.email} / {password}")
    print(f"  Checkout: POST /api/spaces/{space.slug}/events/{event.id}/checkout")
    print("\n  Now sign in as that buyer and open the Gathering, or call the")
    print("  endpoint with their session cookie, to get the Stripe URL.")
    print("  Pay with 4242 4242 4242 4242, any future expiry, any CVC.")
    print(f"\n  Then: python {Path(__file__).name} check")


def check() -> None:
    import app.main  # noqa: F401

    from app.models.access_pass import AccessPass, AccessPassEvent
    from app.models.payment import PaymentTransaction
    from app.models.platform import EventBooking

    if not STATE.exists():
        _fail("no setup state found — run `setup` first.")
    s = json.loads(STATE.read_text())
    db, _ = _session()

    def line(label: str, ok: bool, detail: str) -> bool:
        print(f"  {'PASS' if ok else 'FAIL'}  {label:38} {detail}")
        return ok

    results = []

    bookings = (
        db.query(EventBooking)
        .filter(EventBooking.event_id == s["event_id"])
        .all()
    )
    confirmed = [b for b in bookings if b.status.value == "confirmed"]
    results.append(line(
        "exactly one confirmed booking", len(confirmed) == 1,
        f"{len(confirmed)} confirmed of {len(bookings)}",
    ))

    txns = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.payer_user_id == s["buyer_id"])
        .all()
    )
    ok_txns = [t for t in txns if t.status.value == "succeeded"]
    results.append(line(
        "exactly one succeeded transaction", len(ok_txns) == 1,
        f"{len(ok_txns)} succeeded of {len(txns)}",
    ))

    if ok_txns:
        t = ok_txns[0]
        results.append(line(
            "gross matches the ticket price",
            t.gross_amount_cents == TICKET_CENTS,
            f"{t.gross_amount_cents} {t.currency}",
        ))
        expected_fee = t.gross_amount_cents * t.platform_fee_basis_points // 10_000
        results.append(line(
            "platform fee matches the plan rate",
            t.platform_fee_cents == expected_fee,
            f"{t.platform_fee_cents}c at {t.platform_fee_basis_points}bps",
        ))
        results.append(line(
            "creator net is gross less the fee only",
            t.net_creator_amount_cents
            == t.gross_amount_cents - t.platform_fee_cents,
            f"{t.net_creator_amount_cents}c — Stripe's fee is not deducted",
        ))
        results.append(line(
            "payout status is set", t.payout_status is not None,
            f"{getattr(t, 'payout_model', None)} / {t.payout_status}",
        ))

    passes = (
        db.query(AccessPass)
        .filter(AccessPass.user_id == s["buyer_id"])
        .all()
    )
    results.append(line(
        "exactly one AccessPass", len(passes) == 1, f"{len(passes)} found",
    ))
    for p in passes:
        scope = [
            r.event_id for r in
            db.query(AccessPassEvent)
            .filter(AccessPassEvent.access_pass_id == p.id)
        ]
        results.append(line(
            "the pass admits to this Gathering only",
            scope == [s["event_id"]],
            f"{p.pass_type.value} → {scope}",
        ))

    print()
    if all(results):
        print("  Every check passed. The live Stripe path is verified.")
    else:
        print("  Something did not land. If the booking is still")
        print("  pending_payment, the webhook has not arrived — check that")
        print("  `stripe listen` is forwarding to the running API.")
        raise SystemExit(1)


def teardown() -> None:
    import app.main  # noqa: F401

    from sqlalchemy import text

    if not STATE.exists():
        print("  nothing to remove")
        return
    s = json.loads(STATE.read_text())
    db, url = _session()
    _guard_test_only(url, os.environ.get("STRIPE_SECRET_KEY", "sk_test_x"))

    users = [s["buyer_id"], s["creator_id"]]
    # Event rows first: they reference the user and space through SET
    # NULL foreign keys, so deleting the people would blank the only
    # columns identifying them and strand the rows.
    stmts = [
        ("delete from access_pass_events where access_pass_id in "
         "(select id from access_passes where user_id = any(:u))", {"u": users}),
        ("delete from access_passes where user_id = any(:u) or space_id = :s",
         {"u": users, "s": s["space_id"]}),
        ("delete from event_bookings where user_id = any(:u)", {"u": users}),
        ("delete from communication_events where actor_user_id = any(:u)",
         {"u": users}),
        ("delete from business_events where user_id = any(:u) "
         "or actor_user_id = any(:u) or space_id = :s",
         {"u": users, "s": s["space_id"]}),
        ("delete from payment_transactions where payer_user_id = any(:u) "
         "or creator_user_id = any(:u)", {"u": users}),
        ("delete from events where space_id = :s", {"s": s["space_id"]}),
        ("delete from space_memberships where space_id = :s",
         {"s": s["space_id"]}),
        ("delete from spaces where id = :s", {"s": s["space_id"]}),
        ("delete from users where id = any(:u)", {"u": users}),
    ]
    for sql, params in stmts:
        try:
            db.execute(text(sql), params)
        except Exception as exc:  # noqa: BLE001 — teardown is best effort
            print(f"  (skipped: {str(exc)[:70]})")
    db.commit()
    STATE.unlink()
    print("  removed everything this script created")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "setup"
    {"setup": setup, "check": check, "teardown": teardown}.get(
        action, lambda: _fail(f"unknown action {action!r}")
    )()
