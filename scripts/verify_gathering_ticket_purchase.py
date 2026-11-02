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
      → seeds a paid Gathering and an isolated buyer

    python scripts/verify_gathering_ticket_purchase.py url
      → signs that buyer in against the local API, calls the real
        checkout endpoint, prints the Stripe URL to pay at

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


def _stripe_key_in_use() -> str:
    """The key the application will actually send to Stripe.

    Reading ``os.environ`` alone was wrong: the key normally lives in
    ``backend/.env``, so the guard saw an empty string and refused a
    perfectly safe test setup. It failed safe, but it also meant the
    check was never really looking at the key being used — and a guard
    that inspects something other than the value in play is not a
    guard. ``settings`` resolves .env and the environment by the same
    precedence the app does.
    """
    from app.core.config import settings

    return os.environ.get("STRIPE_SECRET_KEY") or settings.stripe_secret_key or ""


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
    from app.models.creator_billing import (
        CreatorPlan,
        CreatorSubscription,
        CreatorSubscriptionStatus,
    )
    from app.models.user import User, UserRole

    db, url = _session()
    _guard_test_only(url, _stripe_key_in_use())

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
    # A real CreatorSubscription, because without one the fee resolver
    # falls back to 0 bps and the fee assertion would pass by proving
    # nothing. Production runs CREATOR_PLAN_GUARD_ENABLED=true, where
    # that fallback does not exist at all — a creator with no plan is
    # refused — so a run without a subscription is not the production
    # path. `stripe_paid` on the Creator plan mirrors the live shape.
    plan = (
        db.query(CreatorPlan)
        .filter(CreatorPlan.slug == "creator", CreatorPlan.is_active.is_(True))
        .first()
    )
    if plan is None:
        _fail(
            "no active 'creator' plan in this database. The fee path "
            "cannot be verified without one."
        )
    db.add(CreatorSubscription(
        id=uid("cs"), user_id=creator.id, creator_plan_id=plan.id,
        status=CreatorSubscriptionStatus.active, source="stripe_paid",
        starts_at=now,
    ))
    db.flush()

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
        "plan_slug": plan.slug,
        "expected_fee_bps": plan.transaction_fee_basis_points,
    }))

    expected_fee = TICKET_CENTS * plan.transaction_fee_basis_points // 10_000
    print(f"  Seeded  : {event.title} — ${TICKET_CENTS / 100:.2f} {CURRENCY}")
    print(f"  Plan    : {plan.slug} — {plan.transaction_fee_basis_points} bps")
    print(f"  Expect  : fee {expected_fee}c, creator net "
          f"{TICKET_CENTS - expected_fee}c (Stripe's fee absorbed by FC)")
    print(f"  Buyer   : {buyer.email} / {password}")
    print(f"  Checkout: POST /api/spaces/{space.slug}/events/{event.id}/checkout")
    print(f"\n  Next: python {Path(__file__).name} url")


def url() -> None:
    """Sign the seeded buyer in and ask the real endpoint for a Session.

    Going through HTTP rather than calling the service in-process is
    deliberate: the auth dependency, the route's trust boundary and the
    fee resolution are part of what is being verified, and calling
    past them would leave exactly the layers a purchase depends on
    untested. The buyer is the throwaway ``example.invalid`` account
    ``setup`` just created, with the password it generated — not a real
    member's.
    """
    import httpx

    if not STATE.exists():
        _fail("no setup state found — run `setup` first.")
    s = json.loads(STATE.read_text())

    base = os.environ.get("FC_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    host = base.split("//", 1)[-1].split("/")[0].split(":")[0]
    if host not in {"127.0.0.1", "localhost", "::1"}:
        _fail(
            f"FC_API_BASE points at {host!r}. This script drives a real "
            "Checkout Session and must only ever talk to a local API "
            "running test keys."
        )

    with httpx.Client(base_url=base, timeout=30.0, follow_redirects=False) as c:
        r = c.post(
            "/api/auth/login",
            json={"email": s["buyer_email"], "password": s["password"]},
        )
        if r.status_code != 200:
            _fail(f"login failed ({r.status_code}): {r.text[:200]}")

        r = c.post(
            f"/api/spaces/{s['slug']}/events/{s['event_id']}/checkout",
            json={
                "success_url": f"{base}/verify-success",
                "cancel_url": f"{base}/verify-cancel",
            },
        )

    if r.status_code != 200:
        # The two refusals worth naming, because both are configuration
        # rather than breakage and the message alone reads like a bug.
        body = r.text[:300]
        if "ticket_sales_disabled" in body or "disabled" in body:
            print(f"\n  REFUSED ({r.status_code}): {body}\n")
            print("  The API process needs STANDALONE_GATHERING_SALES_ENABLED=true.")
            print("  Restart it with that set and run this again.")
            raise SystemExit(2)
        _fail(f"checkout failed ({r.status_code}): {body}")

    data = r.json()
    if not data["checkout_url"].startswith("https://checkout.stripe.com"):
        _fail(f"unexpected checkout URL: {data['checkout_url'][:60]}")

    print(f"  Transaction : {data['transaction_id']}")
    print(f"  Reused hold : {data['reused']}")
    print("\n  Pay here, with 4242 4242 4242 4242, any future expiry, any CVC:\n")
    print(f"    {data['checkout_url']}\n")
    print(f"  Then: python {Path(__file__).name} check")


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
        # Two separate claims. That the stored rate is the plan's rate,
        # and that the money follows from it — the first would be
        # vacuous alone (0 == 0 under a fee fallback), the second
        # vacuous alone (any rate is self-consistent).
        want_bps = s.get("expected_fee_bps")
        results.append(line(
            "fee rate is the plan's configured rate",
            want_bps is not None and t.platform_fee_basis_points == want_bps,
            f"{t.platform_fee_basis_points}bps, expected {want_bps}bps "
            f"({s.get('plan_slug')})",
        ))
        expected_fee = t.gross_amount_cents * t.platform_fee_basis_points // 10_000
        results.append(line(
            "fee cents follow from that rate",
            t.platform_fee_cents == expected_fee,
            f"{t.platform_fee_cents}c of {t.gross_amount_cents}c",
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
    _guard_test_only(url, _stripe_key_in_use())

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
        ("delete from creator_subscriptions where user_id = any(:u)",
         {"u": users}),
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
    {"setup": setup, "url": url, "check": check, "teardown": teardown}.get(
        action, lambda: _fail(f"unknown action {action!r}")
    )()
