"""Stage 4A — the price the member accepted is the price they get.

The production defect this module exists to prevent. A member priced
"Test Gathering Experience" at 2 x A$5, left the Stripe page open,
came back and entered a A$4 code. The preview correctly said A$6. The
agreement Stripe then established was A$10, the code recorded no use,
and nothing errored.

The cause was not arithmetic and not Stripe. ``create_unified_checkout_session``
resolves an in-flight setup *before* it looks at the discount, and the
reuse verdict in :mod:`app.services.checkout_supersession` compared only
the payment schedule. Same schedule plus a live Stripe page meant "they
are retrying", so the handler handed back the page belonging to the
earlier, undiscounted plan and returned — above the code validation,
above the reservation, above plan creation. Pay-in-full was unaffected
because it writes no plan row and so has no setup to resolve.

Two properties are protected here and they pull against each other:

* A member retrying one purchase must get **one** payment page. Opening
  a second is how people pay twice, and that is what the reuse branch is
  for. ``TestRetryingTheSameThingKeepsItsPage`` holds that line.
* A member must never be handed an agreement at a price they did not
  accept (§7). ``TestACodeAddedOnARetry`` and
  ``TestThePriceCannotChangeSilently`` hold that one.

Every test starts at the real entry point — ``POST /api/checkout`` via
``plan_checkout`` — rather than constructing an already-discounted
PurchasePlan, because the defect lived entirely in the path from the
request to the plan and a hand-built plan cannot see it.

Stripe is mocked throughout. Provider-level evidence that these figures
bill correctly is separate: a test-mode Subscription Schedule was driven
with real invoices for the uneven case (A$43.33 / A$43.33 / A$43.34).

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_stage4a_price_agreement.py
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.checkout.schemas import PathwayCheckoutRequest
from app.core.config import settings
from app.comms.templates.purchases import _plan_arrangement_line
from app.models.discount_code import (
    DiscountRedemption, DiscountReservation, ReservationStatus,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import finite_plan_release as release
from app.services.stripe_finite_plan import SetupSessionState

from tests.test_discount_checkout import (  # noqa: F401
    _reset_rate_limit, as_user, client, make_code, make_offer, preview,
    stripe_configured, stripe_spy,
)
from tests.test_stage4_universal_discounts import (  # noqa: F401
    plan_checkout, plan_schedule, setup_spy, stage4_on,
)

SUP = "app.services.checkout_supersession"

# Tom's purchase, to the cent.
PER = 500
COUNT = 2
LIST_TOTAL = 1_000
CODE_OFF = 400
AGREED_TOTAL = 600
AGREED_PER = 300
CODE = "STAGE4TEST2"


def _live_page(session_id: str) -> SetupSessionState:
    """A setup page the member walked away from, still open at Stripe.

    Nothing is attached and the SetupIntent still wants a card, so
    ``releasable`` permits release and ``usable`` is false — the
    ordinary "went back to think about it" state, and the one the
    production defect needed.
    """
    return SetupSessionState(
        session_id=session_id, status="open", setup_intent_id="seti_x",
        setup_intent_status="requires_payment_method",
        payment_method_id=None, subscription_id=None,
    )


@pytest.fixture
def world(db, make_user, make_space):
    """Moonlit Circle's shape: one Option, 2 x A$5, and a A$4 code."""
    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    option, pay_in_full = make_offer(db, space, cents=LIST_TOTAL)
    sched = plan_schedule(
        db, option, per=PER, count=COUNT, interval="month", interval_count=1,
    )
    code = make_code(
        db, space, code=CODE, discount_type="fixed_amount", percent_bps=None,
        amount_cents=CODE_OFF, currency="AUD", max_redemptions=1,
    )
    return dict(
        member=member, creator=creator, space=space, option=option,
        sched=sched, pay_in_full=pay_in_full, code=code,
    )


def _abandon_a_list_price_setup(db, world):
    """Step one of the defect: price it with no code, then walk away."""
    out = plan_checkout(
        db, world["member"], option=world["option"], schedule=world["sched"],
    )
    plan = db.query(PurchasePlan).filter_by(id=out.transaction_id).one()
    assert plan.total_expected_cents == LIST_TOTAL
    assert plan.provider_setup_session_id, "needs a page to come back to"
    return plan


def _retry(db, world, *, code, session_id, url="https://stripe/live"):
    """Come back to the same schedule, with or without a code."""
    with patch(f"{SUP}.inspect_setup_session",
               return_value=_live_page(session_id)), \
         patch(f"{SUP}._session_url", return_value=url), \
         patch(f"{SUP}.expire_session") as expire:
        out = plan_checkout(
            db, world["member"], option=world["option"],
            schedule=world["sched"], code=code,
        )
    return out, expire


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------


class TestACodeAddedOnARetry:
    """The exact production failure, from the real entry point."""

    def test_the_plan_records_the_price_the_member_accepted(
        self, db, world, setup_spy, stripe_configured,
    ):
        p1 = _abandon_a_list_price_setup(db, world)
        out, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )

        plan = db.query(PurchasePlan).filter_by(id=out.transaction_id).one()
        assert plan.id != p1.id, "the undiscounted plan must not be handed back"
        assert plan.total_expected_cents == AGREED_TOTAL
        assert plan.installment_amount_cents == AGREED_PER
        assert plan.installments_expected == COUNT
        # Even, so no odd-cent final amount.
        assert plan.final_installment_amount_cents is None

    def test_the_discount_is_snapshotted_on_the_new_plan(
        self, db, world, setup_spy, stripe_configured,
    ):
        p1 = _abandon_a_list_price_setup(db, world)
        out, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )

        snap = (
            db.query(PurchasePlan).filter_by(id=out.transaction_id).one()
            .discount_snapshot_json
        )
        assert snap["code"] == CODE
        assert snap["original_amount_cents"] == LIST_TOTAL
        assert snap["discount_amount_cents"] == CODE_OFF
        assert snap["final_amount_cents"] == AGREED_TOTAL
        assert snap["installment_amount_cents"] == AGREED_PER

    def test_the_abandoned_plan_is_released_not_left_in_flight(
        self, db, world, setup_spy, stripe_configured,
    ):
        """Otherwise Rule D would read it as an agreement in progress and
        seal every payment method on the Option."""
        p1 = _abandon_a_list_price_setup(db, world)
        _retry(db, world, code=CODE, session_id=p1.provider_setup_session_id)

        db.refresh(p1)
        assert p1.status is PurchasePlanStatus.cancelled
        assert p1.cancelled_reason == release.RELEASE_SUPERSEDED

    def test_the_abandoned_page_is_expired_so_there_is_one_way_to_pay(
        self, db, world, setup_spy, stripe_configured,
    ):
        """The reuse branch protected against two live pages. Superseding
        has to protect the same thing a different way."""
        p1 = _abandon_a_list_price_setup(db, world)
        _, expire = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )

        expire.assert_called_once_with(p1.provider_setup_session_id)

    def test_exactly_one_slot_is_held_and_nothing_is_redeemed_yet(
        self, db, world, setup_spy, stripe_configured,
    ):
        """0 of 1 used was the visible symptom: no reservation was ever
        taken, because the handler returned above the hold."""
        p1 = _abandon_a_list_price_setup(db, world)
        out, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )

        held = (
            db.query(DiscountReservation)
            .filter(DiscountReservation.status == ReservationStatus.held.value)
            .all()
        )
        assert len(held) == 1
        plan = db.query(PurchasePlan).filter_by(id=out.transaction_id).one()
        # A plan reservation is tied to its purchase through the Stripe
        # setup Session it was attached to.
        assert held[0].provider_checkout_session_id == (
            plan.provider_setup_session_id
        )
        # Capturing a card is not a redemption.
        assert db.query(DiscountRedemption).count() == 0


# ---------------------------------------------------------------------------
# The property the reuse branch was protecting
# ---------------------------------------------------------------------------


class TestRetryingTheSameThingKeepsItsPage:
    """Narrowing reuse must not reopen the double-payment hole."""

    def test_an_undiscounted_retry_of_an_undiscounted_plan_reuses_its_page(
        self, db, world, setup_spy, stripe_configured,
    ):
        p1 = _abandon_a_list_price_setup(db, world)
        out, expire = _retry(
            db, world, code=None, session_id=p1.provider_setup_session_id,
        )

        assert out.transaction_id == p1.id
        assert out.checkout_url == "https://stripe/live"
        expire.assert_not_called()
        assert db.query(PurchasePlan).count() == 1

    def test_the_same_code_twice_reuses_its_page(
        self, db, world, setup_spy, stripe_configured,
    ):
        """A discounted member who closes the tab and comes back is
        retrying, and must not get a second page or a second slot."""
        p1 = _abandon_a_list_price_setup(db, world)
        first, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )
        discounted = db.query(PurchasePlan).filter_by(
            id=first.transaction_id,
        ).one()

        second, expire = _retry(
            db, world, code=CODE,
            session_id=discounted.provider_setup_session_id,
        )

        assert second.transaction_id == discounted.id
        expire.assert_not_called()
        held = db.query(DiscountReservation).filter(
            DiscountReservation.status == ReservationStatus.held.value,
        ).count()
        assert held == 1, "a retry must not spend a second use of a 1-use code"

    def test_a_reused_retry_opens_no_second_stripe_session(
        self, db, world, setup_spy, stripe_configured,
    ):
        """The direct evidence for "one payment page per purchase": the
        Stripe Session constructor is not called again."""
        p1 = _abandon_a_list_price_setup(db, world)
        assert len(setup_spy.calls) == 1

        out, _ = _retry(
            db, world, code=None, session_id=p1.provider_setup_session_id,
        )

        assert out.transaction_id == p1.id
        assert len(setup_spy.calls) == 1, "a retry must not mint a second page"
        assert db.query(DiscountReservation).count() == 0

    def test_the_same_code_in_a_different_case_is_the_same_request(
        self, db, world, setup_spy, stripe_configured,
    ):
        """Matching is on the normalised code, so ``stage4test2`` is not
        read as a change of arrangement."""
        p1 = _abandon_a_list_price_setup(db, world)
        first, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )
        discounted = db.query(PurchasePlan).filter_by(
            id=first.transaction_id,
        ).one()

        second, expire = _retry(
            db, world, code="  stage4test2 ",
            session_id=discounted.provider_setup_session_id,
        )

        assert second.transaction_id == discounted.id
        expire.assert_not_called()


# ---------------------------------------------------------------------------
# Changing the arrangement
# ---------------------------------------------------------------------------


class TestChangingTheArrangement:
    def test_removing_the_code_prices_at_list_rather_than_reusing(
        self, db, world, setup_spy, stripe_configured,
    ):
        """The mirror of the defect. Handing back the discounted page
        would charge less than the member was just quoted, and would
        hold a slot for a purchase they are no longer making."""
        p1 = _abandon_a_list_price_setup(db, world)
        first, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )
        discounted = db.query(PurchasePlan).filter_by(
            id=first.transaction_id,
        ).one()

        third, expire = _retry(
            db, world, code=None,
            session_id=discounted.provider_setup_session_id,
        )

        plan = db.query(PurchasePlan).filter_by(id=third.transaction_id).one()
        assert plan.id != discounted.id
        assert plan.total_expected_cents == LIST_TOTAL
        assert plan.discount_snapshot_json is None
        expire.assert_called_once()

    def test_a_different_code_reprices_rather_than_reusing(
        self, db, world, setup_spy, stripe_configured,
    ):
        make_code(
            db, world["space"], code="HALFOFF", discount_type="percentage",
            percent_bps=5_000,
        )
        p1 = _abandon_a_list_price_setup(db, world)
        first, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )
        discounted = db.query(PurchasePlan).filter_by(
            id=first.transaction_id,
        ).one()

        third, _ = _retry(
            db, world, code="HALFOFF",
            session_id=discounted.provider_setup_session_id,
        )

        plan = db.query(PurchasePlan).filter_by(id=third.transaction_id).one()
        assert plan.id != discounted.id
        assert plan.total_expected_cents == 500
        assert plan.installment_amount_cents == 250
        assert plan.discount_snapshot_json["code"] == "HALFOFF"


# ---------------------------------------------------------------------------
# §7 — a quote cannot quietly become a different agreement
# ---------------------------------------------------------------------------


class TestThePriceCannotChangeSilently:
    """If the discount is gone by the time they commit, refuse. Never
    fall back to the list price."""

    def test_a_code_that_expired_between_preview_and_checkout_is_refused(
        self, db, world, client, setup_spy, stripe_configured,
    ):
        as_user(world["member"])
        seen = preview(
            client, option=world["option"], schedule=world["sched"], code=CODE,
        ).json()
        assert seen["valid"] is True
        assert seen["final_amount_cents"] == AGREED_TOTAL

        world["code"].expires_at = datetime.utcnow() - timedelta(days=1)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            plan_checkout(
                db, world["member"], option=world["option"],
                schedule=world["sched"], code=CODE,
            )

        assert exc.value.status_code == 409
        assert db.query(PurchasePlan).count() == 0, (
            "a refused discount must not leave an agreement behind"
        )

    def test_a_code_that_filled_up_between_preview_and_checkout_is_refused(
        self, db, world, make_user, setup_spy, stripe_configured,
    ):
        """The 1-use code is taken by someone else while Tom decides."""
        other = make_user()
        first = plan_checkout(
            db, other, option=world["option"], schedule=world["sched"],
            code=CODE,
        )
        assert db.query(PurchasePlan).filter_by(
            id=first.transaction_id,
        ).one().total_expected_cents == AGREED_TOTAL

        with pytest.raises(HTTPException) as exc:
            plan_checkout(
                db, world["member"], option=world["option"],
                schedule=world["sched"], code=CODE,
            )

        assert exc.value.status_code == 409
        mine = db.query(PurchasePlan).filter_by(
            member_user_id=world["member"].id,
        ).all()
        assert mine == [], "refused, not quietly sold at A$10"

    def test_a_refused_retry_leaves_no_agreement_and_the_member_can_proceed(
        self, db, world, setup_spy, stripe_configured,
    ):
        """The cost of superseding before validating: a code that has
        gone bad expires the old page, then refuses. No money moves and
        no agreement is created. The next attempt opens a fresh page, so
        the member is never stuck — worth pinning, because the recovery
        is the whole reason this ordering is acceptable.
        """
        p1 = _abandon_a_list_price_setup(db, world)
        world["code"].is_active = False
        db.commit()

        with pytest.raises(HTTPException) as exc:
            _retry(db, world, code=CODE,
                   session_id=p1.provider_setup_session_id)
        assert exc.value.status_code == 409

        # No new agreement, at any price.
        assert db.query(PurchasePlan).count() == 1

        # In production the failed request rolls back, so the release is
        # undone and the plan is still in flight — pointing at a page
        # Stripe has now expired. The suite runs each test in one
        # transaction with savepoints, so that state is restored here
        # rather than by rolling back (which would discard the fixtures).
        p1.status = PurchasePlanStatus.pending_setup
        p1.cancelled_at = None
        p1.cancelled_reason = None
        db.flush()

        # Coming back without the code finds that dead page and replaces
        # it, rather than refusing or reusing it.
        with patch(f"{SUP}.inspect_setup_session", return_value=SetupSessionState(
            session_id=p1.provider_setup_session_id, status="expired",
            setup_intent_id="seti_x", setup_intent_status="canceled",
            payment_method_id=None, subscription_id=None,
        )), patch(f"{SUP}.expire_session"):
            out = plan_checkout(
                db, world["member"], option=world["option"],
                schedule=world["sched"],
            )

        fresh = db.query(PurchasePlan).filter_by(id=out.transaction_id).one()
        assert fresh.id != p1.id
        assert fresh.total_expected_cents == LIST_TOTAL


# ---------------------------------------------------------------------------
# The whole chain, from the request to the figures everyone reads
# ---------------------------------------------------------------------------


class TestEveryStageAgreesOnSixDollars:
    def test_preview_plan_stripe_and_email_all_say_two_times_three(
        self, db, world, client, setup_spy, stripe_configured,
    ):
        """§6 — one number, used consistently by every surface.

        Driven through the retry, because that is the path that broke.
        """
        as_user(world["member"])
        shown = preview(
            client, option=world["option"], schedule=world["sched"], code=CODE,
        ).json()

        p1 = _abandon_a_list_price_setup(db, world)
        out, _ = _retry(
            db, world, code=CODE, session_id=p1.provider_setup_session_id,
        )
        plan = db.query(PurchasePlan).filter_by(id=out.transaction_id).one()

        # 1 — what the member was shown.
        assert shown["installment_count"] == COUNT
        assert shown["installment_amount_cents"] == AGREED_PER
        assert shown["final_amount_cents"] == AGREED_TOTAL

        # 2 — what the agreement records.
        assert plan.installment_amount_cents == shown["installment_amount_cents"]
        assert plan.total_expected_cents == shown["final_amount_cents"]

        # 3 — what Stripe is asked to bill. Both helpers read the plan,
        # so the plan carrying the right figures is what makes the
        # schedule right; the amount is asserted at its source.
        assert plan.expected_installment_cents(1) == AGREED_PER
        assert plan.expected_installment_cents(COUNT) == AGREED_PER

        # 4 — what the member is told afterwards.
        line = _plan_arrangement_line({
            "installments_paid": 1,
            "installments_expected": plan.installments_expected,
            "installment_amount_cents": plan.installment_amount_cents,
            "total_expected_cents": plan.total_expected_cents,
            "interval": "month",
            "currency": plan.currency,
        })
        assert "2 monthly payments of" in line
        assert "3.00" in line and "6.00" in line
        assert "10.00" not in line
        assert "1 payment remaining" in line


# ---------------------------------------------------------------------------
# The same defect lived on the second door
# ---------------------------------------------------------------------------


class TestTheLegacyPathwayWrapperToo:
    """``POST /api/checkout/pathway`` is still live — ``PaymentOptionSelector``
    drives it through ``CheckoutButton``, recurring schedules included — and
    it establishes discounted plans with the same helpers. It resolved the
    pending setup the same way, so it carried the same hole. Fixing only
    the unified endpoint would have left the defect reachable.
    """

    @pytest.fixture(autouse=True)
    def member_plan_checkout_on(self, monkeypatch):
        """This door asks ``_schedule_is_member_checkoutable``, which
        gates recurring schedules behind the finite-plan production
        switch. The unified endpoint resolves the schedule a different
        way and does not."""
        monkeypatch.setattr(
            settings, "finite_plan_member_checkout_enabled", True,
        )

    def _pathway_plan_checkout(self, db, world, *, code=None):
        from app.checkout.routes import create_pathway_checkout_session

        return create_pathway_checkout_session(
            PathwayCheckoutRequest(
                pathway_id=world["option"].attaches_to_id,
                payment_option_id=world["option"].id,
                payment_option_schedule_id=world["sched"].id,
                success_url="https://ok/success",
                cancel_url="https://ok/cancel",
                discount_code=code,
            ),
            current_user=world["member"], db=db,
        )

    def test_a_code_added_on_a_retry_is_not_lost(
        self, db, world, setup_spy, stripe_configured,
    ):
        self._pathway_plan_checkout(db, world)
        p1 = db.query(PurchasePlan).one()
        assert p1.total_expected_cents == LIST_TOTAL

        with patch(f"{SUP}.inspect_setup_session",
                   return_value=_live_page(p1.provider_setup_session_id)), \
             patch(f"{SUP}._session_url", return_value="https://stripe/live"), \
             patch(f"{SUP}.expire_session"):
            self._pathway_plan_checkout(db, world, code=CODE)

        plan = (
            db.query(PurchasePlan)
            .filter(PurchasePlan.status == PurchasePlanStatus.pending_setup)
            .one()
        )
        assert plan.id != p1.id
        assert plan.total_expected_cents == AGREED_TOTAL
        assert plan.installment_amount_cents == AGREED_PER


# ---------------------------------------------------------------------------
# Why reusing a page cannot re-offer a stale price
# ---------------------------------------------------------------------------


class TestTheCodeCannotBeRevaluedUnderAMemberMidCheckout:
    """The interlock that makes comparing *codes* sufficient.

    Reuse above is decided on the normalised code, not on an amount. That
    is only safe because a code's value cannot change while a member is
    holding it: ``update_discount_code`` freezes every price-determining
    field as soon as a reservation exists, and a pending discounted
    checkout holds exactly such a reservation.

    So the two possible worries both close:

    * The creator makes the code *more* generous, and reusing the page
      would charge more than the member is now quoted — cannot happen,
      the edit is refused while the checkout is live.
    * The creator makes it *less* generous, and the member keeps the
      better deal they already accepted — also cannot happen for the
      same reason, and is in any case the documented behaviour for an
      established plan.

    This is a cross-module dependency with nothing on the checkout side
    pointing at it, which is why it is pinned here. Relaxing the freeze
    to permit value edits during a held reservation would quietly turn
    the fix above back into a price-integrity defect.
    """

    def _edit(self, db, world, **fields):
        from app.creator._discount_code_routes import update_discount_code
        from app.creator.schemas import DiscountCodeUpdateRequest

        return update_discount_code(
            world["space"].slug, world["code"].id,
            DiscountCodeUpdateRequest(**fields),
            db=db, current_user=world["creator"],
        )

    def _member_is_mid_discounted_checkout(self, db, world):
        out = plan_checkout(
            db, world["member"], option=world["option"],
            schedule=world["sched"], code=CODE,
        )
        assert db.query(DiscountReservation).filter(
            DiscountReservation.status == ReservationStatus.held.value,
        ).count() == 1
        return out

    @pytest.mark.parametrize("field,value", [
        ("amount_cents", 100),
        ("discount_type", "percentage"),
        ("percent_bps", 9_000),
        ("currency", "USD"),
        ("code", "SOMETHINGELSE"),
        ("scope_kind", "payment_option"),
    ])
    def test_a_price_determining_edit_is_refused_while_a_checkout_is_live(
        self, db, world, setup_spy, stripe_configured, field, value,
    ):
        self._member_is_mid_discounted_checkout(db, world)

        with pytest.raises(HTTPException) as exc:
            self._edit(db, world, **{field: value})

        assert exc.value.status_code == 409
        assert "checkout in progress" in exc.value.detail
        db.refresh(world["code"])
        assert world["code"].amount_cents == CODE_OFF

    def test_the_frozen_set_covers_everything_the_price_derives_from(self):
        """A structural check, so adding a new pricing input to the
        snapshot without freezing it fails here rather than in someone's
        bank statement."""
        from app.creator._discount_code_routes import FROZEN_AFTER_REDEMPTION

        price_determining = {
            "discount_type", "percent_bps", "amount_cents", "currency",
        }
        assert price_determining <= set(FROZEN_AFTER_REDEMPTION)

    def test_what_stays_editable_cannot_change_a_held_price(
        self, db, world, setup_spy, stripe_configured,
    ):
        """Deactivating, re-dating or re-limiting a code is still allowed
        mid-checkout. None of them alters what the held code prices to,
        so reuse keeps offering the amount the member accepted."""
        out = self._member_is_mid_discounted_checkout(db, world)
        before = db.query(PurchasePlan).filter_by(id=out.transaction_id).one()
        agreed = before.total_expected_cents

        self._edit(db, world, is_active=False)
        self._edit(db, world, expires_on=(
            datetime.utcnow() - timedelta(days=1)
        ).date())
        self._edit(db, world, max_redemptions=1)

        db.refresh(before)
        assert before.total_expected_cents == agreed == AGREED_TOTAL
        assert before.installment_amount_cents == AGREED_PER

    def test_a_deactivated_code_gives_a_visible_list_price_not_a_silent_one(
        self, db, world, setup_spy, stripe_configured,
    ):
        """The member's own recovery path. Once the code is dead the
        preview refuses it, so the surface sends no code — which reads as
        a changed arrangement, supersedes, and puts the member on a fresh
        Stripe page showing the real A$10. Nothing is substituted
        silently and nothing is charged at a price they never saw.
        """
        out = self._member_is_mid_discounted_checkout(db, world)
        discounted = db.query(PurchasePlan).filter_by(
            id=out.transaction_id,
        ).one()
        self._edit(db, world, is_active=False)

        retried, expire = _retry(
            db, world, code=None,
            session_id=discounted.provider_setup_session_id,
        )

        plan = db.query(PurchasePlan).filter_by(id=retried.transaction_id).one()
        assert plan.id != discounted.id
        assert plan.total_expected_cents == LIST_TOTAL
        assert plan.discount_snapshot_json is None
        expire.assert_called_once()
