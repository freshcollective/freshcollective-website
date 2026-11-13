"""Stage 5A.2 — the rest of the recurring membership lifecycle.

The highest-risk thing in this stage is the one in
``TestLeavingRemovalAndBans``: a member who leaves, is removed or is
banned must stop being charged. That is hooked at
``membership_removal.end_membership`` — the single point every ending
passes through — rather than in each route, so a fourth path added
later gets it for free.

The second-highest is what happens when that Stripe call fails. The
member must still be able to leave, so the failure cannot raise; but it
must not be swallowed either. The agreement is left live locally
(because it is live at Stripe, and the row should say so),
``payment_action_required`` is set, and the reconciler retries. Those
three together are the "durable condition requiring recovery" §7 asks
for, and each is asserted here.

Throughout: a lapse pauses access, it never removes the member. Bookings
are released only where membership alone was holding the seat.

Stripe is mocked. Provider-level results are recorded in the report.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.platform import (
    BookingStatus, EventBooking, SpaceMembership, SpaceMembershipStatus,
)
from app.services import collective_membership_access as access
from app.services import collective_membership_lifecycle as lifecycle
from app.services import collective_membership_reconcile as reconcile
from app.services import membership_removal
from app.webhooks import collective_membership_handlers as handlers

NOW = datetime.utcnow()


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")


@pytest.fixture
def world(db, make_user, make_space):
    creator = make_user(role="creator")
    member = make_user()
    space = make_space(creator=creator)
    space.pricing_type = "paid_monthly"
    space.pricing_amount_cents = 2_900
    space.pricing_currency = "AUD"
    db.flush()
    return dict(creator=creator, member=member, space=space)


def _sub(db, world, **kw):
    row = CollectiveMembership(
        id=_uid("cmem"), user_id=kw.pop("user", world["member"]).id,
        space_id=world["space"].id,
        status=kw.pop("status", CollectiveMembershipStatus.active.value),
        interval="month", interval_count=1, amount_cents=2_900,
        currency="AUD", creator_user_id=world["creator"].id,
        platform_fee_basis_points=1_000, payout_model="manual",
        stripe_subscription_id=kw.pop("stripe_sub", "sub_test"),
        created_at=NOW, updated_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


def _membership(db, world, **kw):
    row = SpaceMembership(
        id=_uid("sm"), space_id=world["space"].id,
        user_id=kw.pop("user", world["member"]).id,
        role="learner",
        status=kw.pop("status", SpaceMembershipStatus.active),
        source=kw.pop("source", "purchase"), joined_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Failure, grace and recovery
# ---------------------------------------------------------------------------


class TestFailedRenewalsAndRecovery:
    def test_the_grace_window_matches_creator_subscriptions(self):
        """Same consideration whichever subscription it was. Two numbers
        would eventually drift with nobody noticing."""
        from app.webhooks.creator_billing_handlers import _GRACE_WINDOW
        assert lifecycle.GRACE_WINDOW == _GRACE_WINDOW == timedelta(days=7)

    def test_a_failure_starts_grace_and_leaves_access_alone(self, db, world):
        sub = _sub(db, world)
        sm = _membership(db, world)
        lifecycle.begin_payment_problem(
            db, subscription=sub, invoice_id="in_fail", now=NOW,
        )
        assert sub.status == CollectiveMembershipStatus.past_due.value
        assert sub.grace_expires_at == NOW + timedelta(days=7)
        assert sub.last_failed_invoice_id == "in_fail"
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active, (
            "a card expiring is not a reason to shut somebody out today"
        )

    def test_repeated_failures_do_not_extend_grace(self, db, world):
        sub = _sub(db, world)
        lifecycle.begin_payment_problem(
            db, subscription=sub, invoice_id="in_1", now=NOW,
        )
        first = sub.grace_expires_at
        lifecycle.begin_payment_problem(
            db, subscription=sub, invoice_id="in_2",
            now=NOW + timedelta(days=3),
        )
        assert sub.grace_expires_at == first
        assert sub.last_failed_invoice_id == "in_2"

    def test_a_failure_on_an_ended_agreement_is_ignored(self, db, world):
        sub = _sub(db, world, status=CollectiveMembershipStatus.ended.value)
        lifecycle.begin_payment_problem(
            db, subscription=sub, invoice_id="in_late", now=NOW,
        )
        assert sub.status == CollectiveMembershipStatus.ended.value

    def test_a_successful_retry_recovers_the_same_agreement(self, db, world):
        """Not a second subscription — §5 is explicit."""
        sub = _sub(db, world)
        lifecycle.begin_payment_problem(
            db, subscription=sub, invoice_id="in_f", now=NOW,
        )
        assert lifecycle.recover_payment_problem(
            db, subscription=sub, now=NOW,
        ) is True
        assert sub.status == CollectiveMembershipStatus.active.value
        assert sub.grace_expires_at is None
        assert sub.payment_problem_started_at is None
        assert sub.last_failed_invoice_id is None
        assert db.query(CollectiveMembership).count() == 1

    def test_recovery_on_a_healthy_agreement_is_a_no_op(self, db, world):
        sub = _sub(db, world)
        assert lifecycle.recover_payment_problem(
            db, subscription=sub, now=NOW,
        ) is False

    def test_grace_expiring_cancels_at_stripe_too(self, db, world):
        """Grace expiring is Fresh Collective's policy, not Stripe
        giving up — it may still be retrying, so it is told."""
        sub = _sub(db, world)
        _membership(db, world)
        lifecycle.begin_payment_problem(
            db, subscription=sub, invoice_id="in_f", now=NOW,
        )
        with patch("stripe.Subscription.delete") as delete:
            access.end_subscription(
                db, subscription=sub, reason="grace_expired",
                now=NOW + timedelta(days=8),
            )
        delete.assert_called_once_with("sub_test")
        assert sub.status == CollectiveMembershipStatus.ended.value


# ---------------------------------------------------------------------------
# Cancel at period end
# ---------------------------------------------------------------------------


class TestCancelAtPeriodEnd:
    def test_it_keeps_the_paid_period(self, db, world):
        sub = _sub(db, world, current_period_end=NOW + timedelta(days=20))
        sm = _membership(db, world)
        with patch("stripe.Subscription.modify") as modify:
            lifecycle.schedule_cancellation(db, subscription=sub, now=NOW)
        modify.assert_called_once_with("sub_test", cancel_at_period_end=True)
        assert sub.status == CollectiveMembershipStatus.cancel_scheduled.value
        assert sub.cancel_at_period_end is True
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active, (
            "cancelling renewal is not leaving"
        )

    def test_it_is_idempotent_and_keeps_the_first_decision(self, db, world):
        sub = _sub(db, world)
        with patch("stripe.Subscription.modify"):
            lifecycle.schedule_cancellation(db, subscription=sub, now=NOW)
            first = sub.cancelled_at
            lifecycle.schedule_cancellation(
                db, subscription=sub, now=NOW + timedelta(days=1),
            )
        assert sub.cancelled_at == first

    def test_it_can_be_reversed_before_the_period_ends(self, db, world):
        """Reactivates the existing agreement — a new one would reprice
        the member at today's list."""
        sub = _sub(db, world)
        with patch("stripe.Subscription.modify") as modify:
            lifecycle.schedule_cancellation(db, subscription=sub, now=NOW)
            lifecycle.resume_cancelled_renewal(
                db, subscription=sub, now=NOW + timedelta(days=1),
            )
        assert modify.call_args_list[-1].kwargs == {
            "cancel_at_period_end": False,
        }
        assert sub.status == CollectiveMembershipStatus.active.value
        assert sub.cancelled_at is None
        assert db.query(CollectiveMembership).count() == 1

    def test_an_ended_agreement_cannot_be_cancelled_or_resumed(
        self, db, world,
    ):
        sub = _sub(db, world, status=CollectiveMembershipStatus.ended.value)
        with pytest.raises(ValueError):
            lifecycle.schedule_cancellation(db, subscription=sub, now=NOW)
        with pytest.raises(ValueError):
            lifecycle.resume_cancelled_renewal(
                db, subscription=sub, now=NOW,
            )

    def test_the_period_running_out_pauses_access(self, db, world):
        sub = _sub(db, world, current_period_end=NOW - timedelta(days=1))
        sm = _membership(db, world)
        with patch("stripe.Subscription.modify"), \
             patch("stripe.Subscription.delete"):
            lifecycle.schedule_cancellation(
                db, subscription=sub, now=NOW - timedelta(days=20),
            )
            access.end_subscription(
                db, subscription=sub, reason="paid_period_ended", now=NOW,
            )
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.paused
        assert sm.removal_kind is None, "a lapse is not a removal"


# ---------------------------------------------------------------------------
# The critical one
# ---------------------------------------------------------------------------


class TestLeavingRemovalAndBans:
    def _end(self, db, world, *, kind, rejoin_blocked=False, actor=None):
        sm = _membership(db, world)
        decision = membership_removal.RemovalDecision(
            kind=kind,
            reason="member_requested" if kind == "voluntary" else "other",
            # A block requires a written explanation — the service
            # refuses one without, which is its own good rule.
            note="Repeated breaches." if rejoin_blocked else "",
            rejoin_blocked=rejoin_blocked,
        )
        return sm, membership_removal.end_membership(
            db, membership=sm, space=world["space"],
            actor_user_id=(actor or world["member"]).id, now=NOW,
            decision=decision, revoke_purchased_access=False,
            cancel_passes=False, cancel_future_bookings=False,
            note="",
        )

    @pytest.mark.parametrize("kind,blocked", [
        ("voluntary", False),
        ("creator", False),
        ("creator", True),
    ])
    def test_every_ending_stops_future_charges(self, db, world, kind, blocked):
        """Leaving, creator removal and a ban — one hook covers all
        three, because all three pass through ``end_membership``."""
        sub = _sub(db, world)
        with patch("stripe.Subscription.delete") as delete:
            self._end(db, world, kind=kind, rejoin_blocked=blocked,
                      actor=world["creator"] if kind == "creator" else None)
        delete.assert_called_once_with("sub_test")
        db.refresh(sub)
        assert sub.status == CollectiveMembershipStatus.cancelled.value

    def test_a_ban_keeps_its_rejoin_block(self, db, world):
        _sub(db, world)
        with patch("stripe.Subscription.delete"):
            sm, _ = self._end(db, world, kind="creator", rejoin_blocked=True,
                              actor=world["creator"])
        assert sm.rejoin_blocked is True
        assert sm.removal_kind == "creator"

    def test_the_agreement_is_kept_for_audit_not_deleted(self, db, world):
        sub = _sub(db, world)
        with patch("stripe.Subscription.delete"):
            self._end(db, world, kind="creator", actor=world["creator"])
        assert db.query(CollectiveMembership).filter_by(id=sub.id).count() == 1
        assert sub.cancelled_reason.startswith("membership_ended:")

    def test_a_stripe_failure_does_not_block_the_departure(self, db, world):
        """The member must be able to leave even when Stripe is
        unreachable. Blocking it to protect the billing would have the
        priority backwards."""
        import stripe as _stripe
        _sub(db, world)
        with patch("stripe.Subscription.delete",
                   side_effect=_stripe.APIConnectionError("down")):
            sm, _ = self._end(db, world, kind="voluntary")
        assert sm.status is SpaceMembershipStatus.removed

    def test_a_stripe_failure_flags_the_membership_for_a_person(
        self, db, world,
    ):
        import stripe as _stripe
        _sub(db, world)
        with patch("stripe.Subscription.delete",
                   side_effect=_stripe.APIConnectionError("down")):
            sm, _ = self._end(db, world, kind="voluntary")
        assert sm.payment_action_required is True

    def test_a_stripe_failure_leaves_the_agreement_live_not_lying(
        self, db, world,
    ):
        """§7 — do not mark a subscription safely cancelled merely
        because a local field changed. It is live at Stripe, so the row
        says live, and the reconciler retries."""
        import stripe as _stripe
        sub = _sub(db, world)
        with patch("stripe.Subscription.delete",
                   side_effect=_stripe.APIConnectionError("down")):
            self._end(db, world, kind="voluntary")
        db.refresh(sub)
        assert sub.status == CollectiveMembershipStatus.active.value
        assert sub.cancelled_at is None

    def test_another_collectives_agreement_is_untouched(
        self, db, world, make_space, make_user,
    ):
        other_space = make_space(creator=make_user(role="creator"))
        other = CollectiveMembership(
            id=_uid("cmem"), user_id=world["member"].id,
            space_id=other_space.id,
            status=CollectiveMembershipStatus.active.value,
            interval="month", interval_count=1, amount_cents=1_900,
            currency="AUD", stripe_subscription_id="sub_other",
        )
        db.add(other)
        db.flush()
        _sub(db, world)

        with patch("stripe.Subscription.delete") as delete:
            self._end(db, world, kind="voluntary")

        assert delete.call_count == 1
        assert delete.call_args.args == ("sub_test",)
        db.refresh(other)
        assert other.status == CollectiveMembershipStatus.active.value

    def test_leaving_a_free_collective_still_works(self, db, world):
        """No agreement to cancel, and nothing in the way."""
        world["space"].pricing_type = "free"
        db.flush()
        with patch("stripe.Subscription.delete") as delete:
            sm, _ = self._end(db, world, kind="voluntary")
        delete.assert_not_called()
        assert sm.status is SpaceMembershipStatus.removed

    def test_the_hook_is_at_the_single_shared_point(self):
        """Not in each route. A fourth ending added later inherits it."""
        import inspect
        src = inspect.getsource(membership_removal.end_membership)
        assert "cancel_live_subscriptions_for_member" in src
        for route_module in ("app.spaces.routes", "app.creator.routes"):
            mod = __import__(route_module, fromlist=["x"])
            assert "cancel_live_subscriptions_for_member" not in (
                inspect.getsource(mod)
            ), f"{route_module} should not duplicate the cancellation"


# ---------------------------------------------------------------------------
# Bookings — §12
# ---------------------------------------------------------------------------


def _booking(db, world, event, **kw):
    row = EventBooking(
        id=_uid("bk"), event_id=event.id,
        user_id=kw.pop("user", world["member"]).id,
        status=kw.pop("status", BookingStatus.confirmed),
        booked_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


class TestBookingsWhenMembershipEnds:
    @pytest.fixture
    def future_event(self, db, world, make_event):
        return make_event(
            space=world["space"],
            starts_at=NOW + timedelta(days=14),
            ends_at=NOW + timedelta(days=14, hours=1),
            booking_access_type="included_with_collective",
            ticket_price_cents=None, ticket_currency=None,
        )

    def test_a_membership_only_seat_is_released(
        self, db, world, future_event,
    ):
        sub = _sub(db, world)
        _membership(db, world)
        booking = _booking(db, world, future_event, source="member")
        with patch("stripe.Subscription.delete"):
            outcome = access.end_subscription(
                db, subscription=sub, reason="grace_expired", now=NOW,
            )
        assert outcome.bookings_released == 1
        db.refresh(booking)
        assert booking.status is BookingStatus.cancelled

    @pytest.mark.parametrize("field,value", [
        ("payment_transaction_id", None),   # filled below
        ("purchase_plan_id", None),
        ("access_pass_id", None),
    ])
    def test_an_independently_supported_seat_survives(
        self, db, world, future_event, field, value, make_user,
    ):
        """A ticket, a plan or a Series pass is somebody's property and
        outlives their membership."""
        booking = _booking(db, world, future_event, source="member")
        # Set in memory and not flushed: the rule reads the link's
        # presence, and the real ids belong to tables this test has no
        # reason to populate.
        setattr(booking, field, "x_support")
        assert access._booking_has_independent_support(booking) is True
        db.expunge(booking)

    @pytest.mark.parametrize("source", [
        "ticket_purchase", "payment_option", "creator_manual", "creator_pass",
    ])
    def test_a_non_membership_source_survives(
        self, db, world, future_event, source,
    ):
        sub = _sub(db, world)
        _membership(db, world)
        booking = _booking(db, world, future_event, source=source)
        with patch("stripe.Subscription.delete"):
            outcome = access.end_subscription(
                db, subscription=sub, reason="grace_expired", now=NOW,
            )
        assert outcome.bookings_released == 0
        db.refresh(booking)
        assert booking.status is BookingStatus.confirmed

    def test_a_past_gathering_is_left_as_history(
        self, db, world, make_event,
    ):
        """Rewriting attendance because a card later failed would
        falsify the record."""
        past = make_event(
            space=world["space"],
            starts_at=NOW - timedelta(days=7),
            ends_at=NOW - timedelta(days=7) + timedelta(hours=1),
            booking_access_type="included_with_collective",
            ticket_price_cents=None, ticket_currency=None,
        )
        sub = _sub(db, world)
        _membership(db, world)
        booking = _booking(db, world, past, source="member")
        with patch("stripe.Subscription.delete"):
            access.end_subscription(
                db, subscription=sub, reason="grace_expired", now=NOW,
            )
        db.refresh(booking)
        assert booking.status is BookingStatus.confirmed

    def test_the_sweep_is_idempotent(self, db, world, future_event):
        sub = _sub(db, world)
        _membership(db, world)
        _booking(db, world, future_event, source="member")
        first = access.release_membership_only_bookings(
            db, user_id=world["member"].id, space_id=world["space"].id,
            now=NOW,
        )
        second = access.release_membership_only_bookings(
            db, user_id=world["member"].id, space_id=world["space"].id,
            now=NOW,
        )
        assert (first, second) == (1, 0)

    def test_another_collectives_booking_is_untouched(
        self, db, world, future_event, make_space, make_user, make_event,
    ):
        other_space = make_space(creator=make_user(role="creator"))
        other_event = make_event(
            space=other_space, starts_at=NOW + timedelta(days=14),
            ends_at=NOW + timedelta(days=14, hours=1),
            booking_access_type="included_with_collective",
            ticket_price_cents=None, ticket_currency=None,
        )
        elsewhere = _booking(db, world, other_event, source="member")
        _booking(db, world, future_event, source="member")

        released = access.release_membership_only_bookings(
            db, user_id=world["member"].id, space_id=world["space"].id,
            now=NOW,
        )
        assert released == 1
        db.refresh(elsewhere)
        assert elsewhere.status is BookingStatus.confirmed


# ---------------------------------------------------------------------------
# Pausing — §3
# ---------------------------------------------------------------------------


class TestPausingIsNotRemoving:
    def test_a_lapse_pauses_and_keeps_the_history(self, db, world):
        sub = _sub(db, world)
        sm = _membership(db, world)
        with patch("stripe.Subscription.delete"):
            access.end_subscription(
                db, subscription=sub, reason="grace_expired", now=NOW,
            )
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.paused
        assert sm.removal_kind is None
        assert sm.removed_at is None
        assert sm.source == "purchase"

    def test_the_collectives_owner_is_never_paused(self, db, world):
        """A creator locked out of their own Collective by their own
        pricing would be absurd."""
        sub = _sub(db, world, user=world["creator"])
        sm = _membership(db, world, user=world["creator"])
        with patch("stripe.Subscription.delete"):
            outcome = access.end_subscription(
                db, subscription=sub, reason="grace_expired", now=NOW,
            )
        assert outcome.skipped_reason == "collective_owner"
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active

    def test_a_removed_membership_is_not_overwritten(self, db, world):
        """It ended for a reason that outranks billing."""
        sub = _sub(db, world)
        sm = _membership(
            db, world, status=SpaceMembershipStatus.removed,
            removal_kind="creator", removed_at=NOW, rejoin_blocked=True,
        )
        with patch("stripe.Subscription.delete"):
            outcome = access.end_subscription(
                db, subscription=sub, reason="grace_expired", now=NOW,
            )
        assert outcome.membership_paused is False
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.removed
        assert sm.rejoin_blocked is True

    def test_pausing_twice_changes_nothing(self, db, world):
        sub = _sub(db, world)
        _membership(db, world)
        first = access.pause_membership_for_lapse(
            db, subscription=sub, now=NOW,
        )
        second = access.pause_membership_for_lapse(
            db, subscription=sub, now=NOW,
        )
        assert first.membership_paused is True
        assert second.membership_paused is False
        assert second.skipped_reason == "already_paused"


class TestReturningMembers:
    def test_a_paused_membership_is_unpaused_by_payment(self, db, world):
        sub = _sub(db, world)
        sm = _membership(db, world, status=SpaceMembershipStatus.paused)
        assert access.reactivate_paused_membership(
            db, subscription=sub, now=NOW,
        ) == "unpaused"
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active
        assert db.query(SpaceMembership).count() == 1, "no second identity"

    def test_a_removed_membership_is_never_unpaused_by_payment(
        self, db, world,
    ):
        sub = _sub(db, world)
        _membership(
            db, world, status=SpaceMembershipStatus.removed,
            removal_kind="creator", rejoin_blocked=True, removed_at=NOW,
        )
        assert access.reactivate_paused_membership(
            db, subscription=sub, now=NOW,
        ) == "status_removed"

    def test_the_shared_grant_is_not_widened(self):
        """``ensure_membership_for_purchase`` still skips paused rows —
        four other purchase paths share it, and any of them unpausing
        would reverse pauses unrelated to that purchase."""
        import inspect
        from app.services import membership_grant
        src = inspect.getsource(
            membership_grant.ensure_membership_for_purchase
        )
        assert 'skipped_reason=f"status_{status}"' in src


# ---------------------------------------------------------------------------
# Free-to-paid transitions — §13
# ---------------------------------------------------------------------------


class TestFreeToPaidTransitions:
    def test_a_future_date_pauses_nobody_yet(self, db, world):
        world["space"].paid_membership_effective_at = NOW + timedelta(days=60)
        db.flush()
        sm = _membership(db, world, source="joined")
        report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.transitions_paused == 0
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active

    def test_an_arrived_date_pauses_an_unsubscribed_member(self, db, world):
        world["space"].paid_membership_effective_at = NOW - timedelta(hours=1)
        db.flush()
        sm = _membership(db, world, source="joined")
        report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.transitions_paused == 1
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.paused
        assert sm.removal_kind is None, "a transition is not a removal"

    def test_a_subscribed_member_is_left_alone(self, db, world):
        world["space"].paid_membership_effective_at = NOW - timedelta(hours=1)
        db.flush()
        sm = _membership(db, world)
        _sub(db, world, status=CollectiveMembershipStatus.active.value)
        report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.transitions_paused == 0
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active

    @pytest.mark.parametrize("status", ["past_due", "cancel_scheduled"])
    def test_a_member_mid_grace_or_mid_cancellation_keeps_access(
        self, db, world, status,
    ):
        """Both are still paying or still within a paid period."""
        world["space"].paid_membership_effective_at = NOW - timedelta(hours=1)
        db.flush()
        sm = _membership(db, world)
        _sub(db, world, status=status)
        reconcile.reconcile_collective_memberships(db, now=NOW)
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active

    def test_the_owner_keeps_their_collective(self, db, world):
        world["space"].paid_membership_effective_at = NOW - timedelta(hours=1)
        db.flush()
        owner = _membership(db, world, user=world["creator"],
                            source="creator_owner")
        reconcile.reconcile_collective_memberships(db, now=NOW)
        db.refresh(owner)
        assert owner.status is SpaceMembershipStatus.active

    def test_an_invited_member_is_not_exempt(self, db, world):
        """§13 — an invitation grants permission to join, not a waiver."""
        world["space"].paid_membership_effective_at = NOW - timedelta(hours=1)
        db.flush()
        sm = _membership(db, world, source="invited")
        reconcile.reconcile_collective_memberships(db, now=NOW)
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.paused

    def test_nobody_is_charged_or_subscribed(self, db, world):
        world["space"].paid_membership_effective_at = NOW - timedelta(hours=1)
        db.flush()
        _membership(db, world, source="joined")
        reconcile.reconcile_collective_memberships(db, now=NOW)
        assert db.query(CollectiveMembership).count() == 0
        from app.models.payment import PaymentTransaction
        assert db.query(PaymentTransaction).count() == 0

    def test_a_collective_with_no_date_is_never_swept(self, db, world):
        assert world["space"].paid_membership_effective_at is None
        sm = _membership(db, world, source="joined")
        reconcile.reconcile_collective_memberships(db, now=NOW)
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.active

    def test_running_twice_pauses_once(self, db, world):
        world["space"].paid_membership_effective_at = NOW - timedelta(hours=1)
        db.flush()
        _membership(db, world, source="joined")
        first = reconcile.reconcile_collective_memberships(db, now=NOW)
        second = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert (first.transitions_paused, second.transitions_paused) == (1, 0)


# ---------------------------------------------------------------------------
# Reconciliation — §16
# ---------------------------------------------------------------------------


class TestReconciliation:
    def test_an_expired_grace_is_ended(self, db, world):
        sub = _sub(
            db, world, status=CollectiveMembershipStatus.past_due.value,
            grace_expires_at=NOW - timedelta(hours=1),
        )
        sm = _membership(db, world)
        with patch("stripe.Subscription.delete"):
            report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.grace_expired == 1
        db.refresh(sub); db.refresh(sm)
        assert sub.status == CollectiveMembershipStatus.ended.value
        assert sm.status is SpaceMembershipStatus.paused

    def test_grace_still_running_is_left_alone(self, db, world):
        sub = _sub(
            db, world, status=CollectiveMembershipStatus.past_due.value,
            grace_expires_at=NOW + timedelta(days=3),
        )
        sm = _membership(db, world)
        report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.grace_expired == 0
        db.refresh(sub); db.refresh(sm)
        assert sub.status == CollectiveMembershipStatus.past_due.value
        assert sm.status is SpaceMembershipStatus.active

    def test_an_elapsed_paid_period_is_closed(self, db, world):
        sub = _sub(
            db, world,
            status=CollectiveMembershipStatus.cancel_scheduled.value,
            current_period_end=NOW - timedelta(hours=1),
        )
        sm = _membership(db, world)
        with patch("stripe.Subscription.delete"):
            report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.period_elapsed == 1
        db.refresh(sm)
        assert sm.status is SpaceMembershipStatus.paused

    def test_billing_that_outlived_a_departure_is_stopped(self, db, world):
        """The durable retry behind ``end_membership``'s promise — the
        case where the Stripe cancel failed at the time."""
        sub = _sub(db, world)
        _membership(
            db, world, status=SpaceMembershipStatus.removed,
            removal_kind="voluntary", removed_at=NOW,
        )
        with patch("stripe.Subscription.delete") as delete:
            report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.billing_after_departure == 1
        delete.assert_called_once_with("sub_test")
        db.refresh(sub)
        assert sub.status == CollectiveMembershipStatus.cancelled.value

    def test_a_failure_there_is_counted_not_swallowed(self, db, world):
        import stripe as _stripe
        _sub(db, world)
        _membership(
            db, world, status=SpaceMembershipStatus.removed,
            removal_kind="voluntary", removed_at=NOW,
        )
        with patch("stripe.Subscription.delete",
                   side_effect=_stripe.APIConnectionError("down")):
            report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.billing_after_departure_failed == 1
        assert report.errors
        # The reconciler rolls back the failed row, which in this
        # savepoint-based harness discards the fixtures with it. The
        # report is the assertion; the ORM objects are gone by design.
        db.expunge_all()

    def test_a_live_membership_with_a_live_agreement_is_untouched(
        self, db, world,
    ):
        sub = _sub(db, world)
        sm = _membership(db, world)
        report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.as_dict()["billing_after_departure"] == 0
        db.refresh(sub); db.refresh(sm)
        assert sub.status == CollectiveMembershipStatus.active.value
        assert sm.status is SpaceMembershipStatus.active

    def test_running_on_an_empty_platform_is_quiet(self, db):
        report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.as_dict() == {
            "grace_expired": 0, "period_elapsed": 0,
            "billing_after_departure": 0,
            "billing_after_departure_failed": 0,
            "transitions_paused": 0, "bookings_released": 0, "errors": [],
        }


# ---------------------------------------------------------------------------
# The flag — servicing is never gated
# ---------------------------------------------------------------------------


class TestServicingIsNeverGatedOnTheFlag:
    @pytest.fixture(autouse=True)
    def billing_off(self, monkeypatch):
        monkeypatch.setattr(
            settings, "paid_collective_membership_enabled", False,
        )

    def test_a_renewal_failure_still_starts_grace(self, db, world):
        sub = _sub(db, world)
        lifecycle.begin_payment_problem(
            db, subscription=sub, invoice_id="in_f", now=NOW,
        )
        assert sub.status == CollectiveMembershipStatus.past_due.value

    def test_cancellation_still_works(self, db, world):
        sub = _sub(db, world)
        with patch("stripe.Subscription.modify"):
            lifecycle.schedule_cancellation(db, subscription=sub, now=NOW)
        assert sub.status == CollectiveMembershipStatus.cancel_scheduled.value

    def test_leaving_still_stops_the_billing(self, db, world):
        sub = _sub(db, world)
        sm = _membership(db, world)
        with patch("stripe.Subscription.delete") as delete:
            membership_removal.end_membership(
                db, membership=sm, space=world["space"],
                actor_user_id=world["member"].id, now=NOW,
                decision=membership_removal.RemovalDecision(
                    kind="voluntary", reason="member_requested",
                    note="", rejoin_blocked=False,
                ),
                revoke_purchased_access=False, cancel_passes=False,
                cancel_future_bookings=False, note="",
            )
        delete.assert_called_once()
        db.refresh(sub)
        assert sub.status == CollectiveMembershipStatus.cancelled.value

    def test_the_reconciler_still_runs(self, db, world):
        sub = _sub(
            db, world, status=CollectiveMembershipStatus.past_due.value,
            grace_expires_at=NOW - timedelta(hours=1),
        )
        _membership(db, world)
        with patch("stripe.Subscription.delete"):
            report = reconcile.reconcile_collective_memberships(db, now=NOW)
        assert report.grace_expired == 1

    def test_no_lifecycle_module_reads_the_flag(self):
        """Structural. A switch that could trap somebody in a
        subscription, or leave a payment unrecorded, would be the wrong
        kind of switch."""
        import ast
        import inspect
        for module in (lifecycle, access, reconcile, handlers):
            names = {
                n.attr for n in ast.walk(ast.parse(inspect.getsource(module)))
                if isinstance(n, ast.Attribute)
            }
            assert "paid_collective_membership_enabled" not in names, (
                module.__name__
            )
