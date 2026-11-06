"""The creator-plan gate, enforced on the standalone Gathering ticket door.

The defect
----------
``POST /api/spaces/{slug}/events/{event_id}/checkout`` resolved the
creator fee through the legacy ``_resolve_fee_bps`` shim, which returns
the fee triple and nothing else. It was therefore the only paid door in
the system enforcing *neither* half of the gate every other one
enforces:

* ``NoActiveCreatorPlanError`` escaped unhandled, so a Collective with
  no Creator Plan answered **HTTP 500**. The buyer saw "We couldn't open
  checkout. Please try again." and could retry forever; the creator got
  no signal at all.
* ``permits_paid_offers`` was never consulted, so a **Community**
  creator — a plan explicitly for "contributing a genuine community
  without using it as a commercial business" — sold tickets. Production
  runs live Stripe keys, so that was real money through a plan that
  forbids commercial use.

Both were found on 2026-11-06, after ``CREATOR_PLAN_GUARD_ENABLED`` was
turned on in production, and both reproduce against the real endpoint —
which is why these tests drive the endpoint rather than the resolver.

Why it survived
---------------
``test_gathering_live_sales_gate.py`` covers the two sales flags only,
and ``test_creator_plan_fee_resolution.py`` tests
``_resolve_fee_bps_for_creator`` in isolation. Nothing exercised the
plan guard *through* this endpoint, so neither branch had a test to
fail.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_verified_current_user
from app.core.database import get_db
from app.main import app
from app.models.creator_billing import (
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.payment import PaymentTransaction
from app.models.platform import EventBooking
from app.services.checkout_orchestration import (
    NO_ACTIVE_CREATOR_PLAN_DETAIL,
    PLAN_FORBIDS_PAID_OFFERS_DETAIL,
)

# ---------------------------------------------------------------------------
# Plan rows. Slugs must match ``plan_config`` exactly — ``get_plan_capability``
# returns None for an unrecognised slug and ``resolve_fee_context`` then fails
# closed, so "founding_creator" would be refused where "founding-creator" is
# allowed. That asymmetry is deliberate defence-in-depth, and a test using the
# wrong spelling would look like a product bug.
# ---------------------------------------------------------------------------

PLAN_FEES = {
    "community": 0,
    "creator": 800,
    "pro": 500,
    "founding-creator": 0,
}


def _plan(db, slug: str) -> CreatorPlan:
    row = CreatorPlan(
        id=str(uuid4()), slug=slug, name=slug.replace("-", " ").title(),
        monthly_price_cents=1900 if slug == "creator" else 0,
        currency="AUD", transaction_fee_basis_points=PLAN_FEES[slug],
        is_active=True, collective_limit=1,
    )
    db.add(row)
    db.flush()
    return row


def _subscribe(
    db, creator, plan, *, source: str = "stripe_paid",
    status=CreatorSubscriptionStatus.active, ends_at=None,
) -> CreatorSubscription:
    sub = CreatorSubscription(
        id=str(uuid4()), user_id=creator.id, creator_plan_id=plan.id,
        status=status, starts_at=datetime.utcnow() - timedelta(days=1),
        ends_at=ends_at, source=source,
    )
    db.add(sub)
    db.flush()
    return sub


@pytest.fixture
def buy(db):
    """POST the real ticket checkout as a verified buyer.

    Sales flags on and Stripe in test mode, so the only variable is the
    creator's plan. A ``502`` means the request reached the Stripe call
    with a dummy key — i.e. every gate passed and the sale was
    permitted. That is the signal for "allowed", and it is a stronger
    one than a 200 would be here: it proves the refusal did *not*
    happen without needing a Stripe fixture.
    """
    def _go(space, event, buyer, *, guard: bool = True):
        app.dependency_overrides[get_verified_current_user] = lambda: buyer
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app, raise_server_exceptions=False)
        try:
            with patch(
                "app.core.config.settings.standalone_gathering_sales_enabled", True,
            ), patch(
                "app.core.config.settings.stripe_secret_key", "sk_test_dummy",
            ), patch(
                "app.core.config.settings.creator_plan_guard_enabled", guard,
            ):
                return client.post(
                    f"/api/spaces/{space.slug}/events/{event.id}/checkout",
                    json={
                        "success_url": "https://example.test/ok",
                        "cancel_url": "https://example.test/no",
                    },
                )
        finally:
            app.dependency_overrides.pop(get_verified_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    return _go


PERMITTED = 502  # reached the Stripe call; see the ``buy`` fixture


class TestWhoMaySellATicket:
    def test_no_active_plan_is_a_409_not_a_500(
        self, db, buy, make_user, make_space, make_event,
    ):
        """The defect, pinned. 500 told a buyer to retry something that
        could never succeed."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)

        r = buy(space, event, make_user(role="user"))
        assert r.status_code == 409, r.text
        # The same copy every other paid door gives, from one constant.
        assert r.json()["detail"] == NO_ACTIVE_CREATOR_PLAN_DETAIL

    def test_community_plan_is_a_403(
        self, db, buy, make_user, make_space, make_event,
    ):
        """Community forbids commercial use. This used to sell."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)
        _subscribe(db, creator, _plan(db, "community"))

        r = buy(space, event, make_user(role="user"))
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == PLAN_FORBIDS_PAID_OFFERS_DETAIL

    @pytest.mark.parametrize("slug", ["creator", "pro", "founding-creator"])
    def test_a_plan_that_permits_paid_offers_still_sells(
        self, db, buy, make_user, make_space, make_event, slug,
    ):
        """The half that matters most: the fix must not cost anybody
        their existing ability to sell."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)
        _subscribe(db, creator, _plan(db, slug))

        r = buy(space, event, make_user(role="user"))
        assert r.status_code == PERMITTED, f"{slug}: {r.status_code} {r.text}"

    def test_a_complimentary_grant_sells(
        self, db, buy, make_user, make_space, make_event,
    ):
        """A manual grant is a real subscription row with
        ``source='manual_grant'`` and an end date. It must sell exactly
        like a paid one for as long as it runs."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)
        _subscribe(
            db, creator, _plan(db, "creator"), source="manual_grant",
            ends_at=datetime.utcnow() + timedelta(days=90),
        )

        r = buy(space, event, make_user(role="user"))
        assert r.status_code == PERMITTED, r.text

    def test_a_waived_subscription_sells(
        self, db, buy, make_user, make_space, make_event,
    ):
        """The live case this work was prompted by: an active Creator
        plan whose monthly charge is waived for a period. The waiver
        lives in billing, not in eligibility — the row is active, so
        the gate passes and the plan's own fee still applies."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)
        _subscribe(
            db, creator, _plan(db, "creator"), source="manual_grant",
            ends_at=datetime.utcnow() + timedelta(days=90),
        )

        r = buy(space, event, make_user(role="user"))
        assert r.status_code == PERMITTED, r.text

    def test_past_due_keeps_selling_through_grace(
        self, db, buy, make_user, make_space, make_event,
    ):
        """``past_due`` is inside the filter on purpose, so a creator
        keeps selling through Fresh Collective's grace window. Pinned
        here because the gate now runs on a path it did not before."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)
        _subscribe(
            db, creator, _plan(db, "creator"),
            status=CreatorSubscriptionStatus.past_due,
        )

        r = buy(space, event, make_user(role="user"))
        assert r.status_code == PERMITTED, r.text

    def test_the_guard_flag_off_preserves_the_old_fallback(
        self, db, buy, make_user, make_space, make_event,
    ):
        """Grace mode. With the flag off a creator with no plan falls
        back to ``fee_bps=0`` and sells, exactly as before — the fix
        must not quietly enforce the guard when it is switched off."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)

        r = buy(space, event, make_user(role="user"), guard=False)
        assert r.status_code == PERMITTED, r.text


class TestItRefusesBeforeAnythingIsCommitted:
    """A refusal must cost nothing: no hold, no seat, no transaction,
    no Stripe Session. The gate sits at step 3 of the endpoint, ahead
    of all four."""

    @pytest.mark.parametrize(
        "setup,expected",
        [("none", 409), ("community", 403)],
        ids=["no_active_plan", "community_plan"],
    )
    def test_nothing_is_created_by_a_refusal(
        self, db, buy, make_user, make_space, make_event, setup, expected,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500, capacity=1)
        buyer = make_user(role="user")
        if setup == "community":
            _subscribe(db, creator, _plan(db, "community"))

        before_bookings = db.query(EventBooking).filter(
            EventBooking.event_id == event.id,
        ).count()
        before_txns = db.query(PaymentTransaction).count()

        r = buy(space, event, buyer)
        assert r.status_code == expected, r.text

        assert db.query(EventBooking).filter(
            EventBooking.event_id == event.id,
        ).count() == before_bookings, "a refusal created a booking hold"
        assert db.query(PaymentTransaction).count() == before_txns, (
            "a refusal created a payment transaction"
        )

    def test_the_seat_is_still_available_afterwards(
        self, db, buy, make_user, make_space, make_event,
    ):
        """Capacity is confirmed + pending_payment with no clock in the
        sum, so a leaked hold would silently consume the only seat on a
        capacity-1 Gathering and nothing would release it."""
        from app.services.gathering_tickets import capacity_used

        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500, capacity=1)

        buy(space, event, make_user(role="user"))
        assert capacity_used(db, event.id) == 0

    def test_stripe_is_never_contacted(
        self, db, buy, make_user, make_space, make_event,
    ):
        """Asserted by patching the Session constructor: a refusal that
        reached Stripe would be a refusal that could leave an orphaned
        Session behind."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)

        with patch("stripe.checkout.Session.create") as create:
            r = buy(space, event, make_user(role="user"))
        assert r.status_code == 409, r.text
        create.assert_not_called()


class TestTheFeeAndPayoutAreUnchanged:
    """The replacement had to preserve fee and payout behaviour for
    every valid plan.

    It does so structurally rather than by coincidence:
    ``resolve_fee_context`` calls the very same
    ``_resolve_fee_bps_for_creator`` the old shim called, and adds only
    ``permits_paid_offers`` and ``is_platform_owned``. These tests pin
    that equivalence against the shim's own answer so a future change
    to either cannot drift silently.
    """

    @pytest.mark.parametrize("slug", ["creator", "pro", "founding-creator"])
    def test_the_context_matches_the_legacy_shim(
        self, db, make_user, make_space, slug,
    ):
        from app.checkout.routes import _resolve_fee_bps
        from app.services.checkout_orchestration import resolve_fee_context

        creator = make_user(role="creator")
        space = make_space(creator=creator)
        plan = _plan(db, slug)
        sub = _subscribe(db, creator, plan)

        with patch("app.core.config.settings.creator_plan_guard_enabled", True):
            shim = _resolve_fee_bps(space.creator_id, db)
            ctx = resolve_fee_context(space, db)

        assert (ctx.fee_bps, ctx.creator_plan_id, ctx.creator_subscription_id) == shim
        # And the values are the plan's own, not a default.
        assert ctx.fee_bps == PLAN_FEES[slug]
        assert ctx.creator_plan_id == plan.id
        assert ctx.creator_subscription_id == sub.id

    def test_a_platform_owned_collective_is_unchanged(self, db, make_space):
        """``creator_id IS NULL`` — Fresh Collective selling directly.
        Zero fee, no plan, and the gate must not refuse it."""
        from app.checkout.routes import _resolve_fee_bps
        from app.services.checkout_orchestration import (
            resolve_fee_context_or_raise_http,
        )

        space = make_space()
        space.creator_id = None
        db.flush()

        with patch("app.core.config.settings.creator_plan_guard_enabled", True):
            assert _resolve_fee_bps(None, db) == (0, None, None)
            ctx = resolve_fee_context_or_raise_http(space, db)
        assert (ctx.fee_bps, ctx.creator_plan_id) == (0, None)
        assert ctx.is_platform_owned is True
        assert ctx.permits_paid_offers is True

    def test_the_fee_reaches_the_transaction_unchanged(
        self, db, buy, make_user, make_space, make_event,
    ):
        """End to end: an 8% Creator plan still stamps 800 bps and the
        snapshotted payout model onto the pending transaction."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = make_event(space=space, ticket_price_cents=4500)
        _subscribe(db, creator, _plan(db, "creator"))
        buyer = make_user(role="user")

        class _FakeSession:
            id = "cs_test_fake"
            url = "https://checkout.stripe.test/c/pay/cs_test_fake"
            expires_at = int(
                (datetime.utcnow() + timedelta(minutes=30)).timestamp()
            )

        with patch("stripe.checkout.Session.create", return_value=_FakeSession()):
            r = buy(space, event, buyer)
        assert r.status_code == 200, r.text

        txn = db.get(PaymentTransaction, r.json()["transaction_id"])
        assert txn is not None
        assert txn.platform_fee_basis_points == 800
        assert txn.gross_amount_cents == 4500
        assert txn.currency == "AUD"
        # 8% of $45.00 = $3.60, creator keeps $41.40.
        assert txn.platform_fee_cents == 360
        assert txn.net_creator_amount_cents == 4140
        # Payout snapshot still decided here and frozen on the row.
        assert txn.payout_model is not None


class TestTheConstantsAreTheOnesTheOtherDoorsUse:
    def test_the_copy_is_unchanged_from_before_consolidation(self):
        """Three doors held this wording as byte-identical literals and
        a fourth was about to. They now share a constant — these are
        the historical strings, so the consolidation cannot have
        altered what a member or admin reads."""
        assert NO_ACTIVE_CREATOR_PLAN_DETAIL == (
            "Fresh Collective commercial terms have not been configured "
            "for this Collective. Paid checkout is unavailable until an "
            "admin assigns a Creator Plan."
        )
        assert PLAN_FORBIDS_PAID_OFFERS_DETAIL == (
            "This Collective's Fresh Collective plan does not include "
            "paid offers. The creator's plan must be upgraded to Creator "
            "or higher to enable commercial checkout."
        )

    def test_no_door_still_holds_its_own_copy(self):
        """A fifth inline copy would reintroduce the drift.

        Matched on the message's distinctive tail, not its opening
        clause. ``_space_payment_options_routes`` raises a *different*
        409 that happens to open the same way — "…for this Collective's
        creator. Assign a Creator Plan before recording manual grants"
        — which is about an audit anchor, not about paid checkout, and
        is correctly its own wording. Ban the use, not the word.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        tail = "Paid checkout is unavailable until an admin assigns"
        offenders = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if tail in path.read_text()
            and path.name != "checkout_orchestration.py"
        ]
        assert offenders == [], (
            f"inline copies of the refusal wording: {offenders}"
        )
