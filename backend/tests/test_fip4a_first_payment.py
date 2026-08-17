"""FIP4A — immediate first-invoice collection + first-payment failure semantics.

After the FIP2 setup Checkout completes, the setup webhook handler
now finalises + pays the initial ``subscription_create`` invoice
server-side (Stripe's default 1-hour ``next_payment_attempt`` delay
would otherwise strand the member on a "we're confirming your
payment" screen for up to an hour).

Access is still granted exclusively by the
``invoice.payment_succeeded`` webhook running through the existing
FIP2 first-invoice handler. This test file covers:

  * happy path — setup handler triggers finalize + pay, resulting
    webhook activates access exactly once
  * setup handler replay doesn't double-charge (Stripe idempotency
    keys + plan-status guard)
  * transient Stripe API errors propagate (webhook retries)
  * card decline terminates the plan (schedule cancelled, plan
    failed, no access, Rule D unblocked)
  * non-``paid`` invoice status after Invoice.pay (e.g. 3DS
    ``requires_action``) terminates the plan the same way
  * ``invoice.payment_failed`` on a still-``pending_setup`` plan
    terminates the plan and cancels the schedule
  * later-instalment failure on an ``active`` plan still opens the
    FIP3 7-day grace window (unchanged)
  * ``customer.subscription.deleted`` after a first-payment
    failure is a no-op (doesn't corrupt the already-failed plan)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import stripe

from app.models.access_pass import AccessPassType
from app.models.payment import (
    PaymentFulfilmentStatus, PaymentProvider,
    PaymentTransaction, PaymentTransactionStatus, PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    EventSeries, Pathway, PathwayEntitlement,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import finite_plan_lifecycle as fpl
from app.services.purchase_fulfilment import (
    AccessPassIntent, FulfilmentIntent, serialise_intent,
)
from app.webhooks.finite_plan_handlers import (
    _do_setup_completed, _do_invoice_failed, _do_subscription_deleted,
    handle_invoice_payment_succeeded,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pending_plan(db, make_user, make_space):
    """A PurchasePlan in ``pending_setup`` with a Stripe Session id
    but NO subscription-schedule yet — the shape at the entry of
    ``_do_setup_completed``. The test builder is also given the
    Payment Option and Series so the snapshot grants land on real
    FK targets when the first invoice succeeds."""
    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)

    starts = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
        starts_at=starts, status="published", published_at=starts,
    )
    db.add(series); db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Test PO",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=6000, currency="AUD",
    )
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly x 3",
        schedule_type="recurring_installments", status="published",
        installment_amount_cents=2000, installment_count=3,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=6000, currency="AUD",
    )
    db.add_all([opt, sched]); db.flush()

    intent = FulfilmentIntent(
        access_passes=(AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=datetime.utcnow(), valid_until=None,
            total_credits=None, credits_per_week=None,
            eligible_pathway_id=None, eligible_series_id=series.id,
            grants_pathway_id=None,
        ),),
    )
    session_id = f"cs_test_{uuid.uuid4().hex[:12]}"
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id, creator_user_id=creator.id,
        status=PurchasePlanStatus.pending_setup,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=3, installments_paid=0,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=0,
        provider_setup_session_id=session_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
    )
    db.add(plan); db.commit()
    return SimpleNamespace(
        member=member, creator=creator, space=space,
        series=series, option=opt, schedule=sched,
        plan=plan, session_id=session_id,
    )


def _stripe_session_dict(session_id: str) -> dict:
    return {"id": session_id, "metadata": {"purchase_plan_id": ""}}


def _mock_completed_setup_session(customer_id: str, pm_id: str):
    """Mimic what ``stripe.checkout.Session.retrieve`` returns after
    setup completion — a Session with expanded setup_intent + customer."""
    return SimpleNamespace(
        id="cs_test_setup",
        setup_intent=SimpleNamespace(payment_method=pm_id),
        customer=customer_id,
    )


def _mock_subscription(sub_id: str, latest_invoice_id: str):
    return {"id": sub_id, "latest_invoice": latest_invoice_id}


def _mock_invoice(inv_id: str, sub_id: str, status: str = "draft",
                  billing_reason: str = "subscription_create"):
    return {
        "id": inv_id,
        "status": status,
        "billing_reason": billing_reason,
        "subscription": sub_id,
    }


class _Stripe:
    """Bundle of patches used across most tests."""

    def __init__(self, *, first_invoice_status: str = "paid",
                 raise_on_pay: Exception | None = None):
        self.first_invoice_status = first_invoice_status
        self.raise_on_pay = raise_on_pay
        # Track calls for idempotency assertions.
        self.pay_calls = 0
        self.finalize_calls = 0
        self.schedule_cancel_calls = 0

    def __enter__(self):
        self._patches = []
        cust_id = "cus_test_x"
        pm_id = "pm_test_x"
        sub_id = "sub_test_x"
        inv_id = "in_test_first"
        schedule_id = "sub_sched_test_x"

        # Setup session retrieve
        p = patch(
            "app.services.stripe_finite_plan.retrieve_completed_setup_session",
            return_value=_mock_completed_setup_session(cust_id, pm_id),
        )
        self._patches.append(p); p.start()
        # Attach PM as default (no-op mock)
        p = patch(
            "app.services.stripe_finite_plan.attach_payment_method_as_default",
            return_value=None,
        )
        self._patches.append(p); p.start()
        # Product + Price create
        p = patch(
            "app.services.stripe_finite_plan.create_product_and_price",
            return_value=("prod_test", "price_test"),
        )
        self._patches.append(p); p.start()
        # Schedule create → returns (schedule_id, subscription_id)
        p = patch(
            "app.services.stripe_finite_plan.create_finite_subscription_schedule",
            return_value=(schedule_id, sub_id),
        )
        self._patches.append(p); p.start()

        # Subscription retrieve — needed by finalize_and_pay_first_invoice
        p = patch(
            "stripe.Subscription.retrieve",
            return_value=_mock_subscription(sub_id, inv_id),
        )
        self._patches.append(p); p.start()

        # Invoice retrieve — draft state
        p = patch(
            "stripe.Invoice.retrieve",
            return_value=_mock_invoice(inv_id, sub_id, status="draft"),
        )
        self._patches.append(p); p.start()

        # Invoice finalize
        def _finalize(*args, **kwargs):
            self.finalize_calls += 1
            return _mock_invoice(inv_id, sub_id, status="open")
        p = patch("stripe.Invoice.finalize_invoice", side_effect=_finalize)
        self._patches.append(p); p.start()

        # Invoice pay — success returns paid; failure raises
        def _pay(*args, **kwargs):
            self.pay_calls += 1
            if self.raise_on_pay is not None:
                raise self.raise_on_pay
            return _mock_invoice(inv_id, sub_id,
                                 status=self.first_invoice_status)
        p = patch("stripe.Invoice.pay", side_effect=_pay)
        self._patches.append(p); p.start()

        # SubscriptionSchedule.retrieve + cancel (for termination path)
        p = patch(
            "stripe.SubscriptionSchedule.retrieve",
            return_value={"id": schedule_id, "status": "active"},
        )
        self._patches.append(p); p.start()

        def _sched_cancel(*args, **kwargs):
            self.schedule_cancel_calls += 1
            return {"id": schedule_id, "status": "canceled"}
        p = patch("stripe.SubscriptionSchedule.cancel", side_effect=_sched_cancel)
        self._patches.append(p); p.start()

        # Stripe key
        p = patch("app.core.config.settings.stripe_secret_key", "sk_test_dummy")
        self._patches.append(p); p.start()
        p = patch("app.core.config.settings.stripe_webhook_secret", "whsec_dummy")
        self._patches.append(p); p.start()

        return self

    def __exit__(self, *a):
        for p in reversed(self._patches):
            p.stop()


# ---------------------------------------------------------------------------
# Happy path — setup handler triggers finalize + pay
# ---------------------------------------------------------------------------


class TestSetupHandlerImmediatePayHappyPath:
    def test_finalize_and_pay_called_once_after_schedule_create(
        self, db, pending_plan,
    ):
        s = pending_plan
        with _Stripe() as stripe_mock:
            _do_setup_completed(
                db,
                session={"id": s.session_id},
                plan_id=s.plan.id,
                event_livemode=False,
            )
        # Exactly one finalize + one pay call.
        assert stripe_mock.finalize_calls == 1
        assert stripe_mock.pay_calls == 1
        # Plan is still pending_setup — access activation flows
        # through the resulting invoice.payment_succeeded webhook.
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.pending_setup

    def test_subsequent_invoice_succeeded_webhook_activates_plan(
        self, db, pending_plan,
    ):
        """The immediate finalize/pay results in a
        ``invoice.payment_succeeded`` event. The existing FIP2
        first-invoice handler continues to be the sole path that
        activates access."""
        s = pending_plan
        with _Stripe():
            _do_setup_completed(
                db,
                session={"id": s.session_id},
                plan_id=s.plan.id,
                event_livemode=False,
            )

        invoice_event = {
            "id": "in_test_first",
            "subscription": "sub_test_x",
            "amount_paid": 2000,
            "total": 2000,
            "currency": "aud",
            "status": "paid",
            "charge": "ch_test_x",
            "payment_intent": "pi_test_x",
        }
        handle_invoice_payment_succeeded(
            invoice_event, db,
            provider_event_id=f"evt_{uuid.uuid4().hex}",
            event_livemode=False,
        )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.active
        assert s.plan.installments_paid == 1
        # Exactly one PaymentTransaction row for the first invoice.
        txns = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.purchase_plan_id == s.plan.id)
            .all()
        )
        assert len(txns) == 1
        assert txns[0].status == PaymentTransactionStatus.succeeded


# ---------------------------------------------------------------------------
# Replay safety
# ---------------------------------------------------------------------------


class TestSetupHandlerReplaySafe:
    def test_second_delivery_of_setup_webhook_does_not_double_charge(
        self, db, pending_plan,
    ):
        """A lease-triggered redelivery of checkout.session.completed
        must not trigger a second Invoice.pay. The plan-status guard
        at the top of _do_setup_completed short-circuits before we
        reach the acceleration code."""
        s = pending_plan
        with _Stripe() as stripe_mock:
            _do_setup_completed(
                db,
                session={"id": s.session_id},
                plan_id=s.plan.id,
                event_livemode=False,
            )
            # Simulate a plan transitioning to active via the resulting
            # invoice.payment_succeeded webhook.
            db.refresh(s.plan)
            s.plan.status = PurchasePlanStatus.active
            s.plan.installments_paid = 1
            db.commit()
            # Replay the setup event.
            _do_setup_completed(
                db,
                session={"id": s.session_id},
                plan_id=s.plan.id,
                event_livemode=False,
            )
        # Only ONE finalize+pay overall.
        assert stripe_mock.finalize_calls == 1
        assert stripe_mock.pay_calls == 1


# ---------------------------------------------------------------------------
# Transient error → propagates (webhook retries)
# ---------------------------------------------------------------------------


class TestTransientStripeErrorRetryable:
    def test_stripe_api_error_propagates_for_retry(self, db, pending_plan):
        s = pending_plan
        transient = stripe.APIConnectionError("boom")
        with _Stripe(raise_on_pay=transient):
            with pytest.raises(stripe.StripeError):
                _do_setup_completed(
                    db,
                    session={"id": s.session_id},
                    plan_id=s.plan.id,
                    event_livemode=False,
                )
        # Plan remains pending_setup for the retry.
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.pending_setup


# ---------------------------------------------------------------------------
# Card decline — terminate the plan cleanly
# ---------------------------------------------------------------------------


class TestCardDeclineTerminates:
    def test_card_decline_marks_plan_failed_and_cancels_schedule(
        self, db, pending_plan,
    ):
        s = pending_plan
        decline = stripe.CardError(
            "Your card was declined.", param=None, code="card_declined",
        )
        with _Stripe(raise_on_pay=decline) as stripe_mock:
            _do_setup_completed(
                db,
                session={"id": s.session_id},
                plan_id=s.plan.id,
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed
        assert (s.plan.cancelled_reason or "").startswith("first_payment_failed")
        assert s.plan.cancelled_at is not None
        # Stripe SubscriptionSchedule was cancelled.
        assert stripe_mock.schedule_cancel_calls == 1
        # No access rows.
        assert db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == s.member.id,
        ).count() == 0


# ---------------------------------------------------------------------------
# Provider-FIRST termination: transient provider errors during cleanup
# must NOT let the local plan flip to `failed` (which would unblock
# Rule D while the abandoned Stripe schedule is still live).
# ---------------------------------------------------------------------------


class TestProviderFirstTerminationHoldsLocalFailed:
    def test_transient_stripe_cancel_error_leaves_plan_pending(
        self, db, pending_plan,
    ):
        s = pending_plan
        decline = stripe.CardError(
            "Your card was declined.", param=None, code="card_declined",
        )
        # Card decline arrives — helper tries to cancel schedule,
        # which itself raises a transient APIConnectionError.
        with _Stripe(raise_on_pay=decline):
            with patch(
                "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
                side_effect=stripe.APIConnectionError("transient network"),
            ):
                with pytest.raises(stripe.StripeError):
                    _do_setup_completed(
                        db,
                        session={"id": s.session_id},
                        plan_id=s.plan.id,
                        event_livemode=False,
                    )
        # Plan is NOT ``failed`` — must stay in a blocking status so
        # Rule D refuses a fresh purchase while the abandoned Stripe
        # schedule may still exist.
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.pending_setup

    def test_rule_d_still_blocks_while_provider_cleanup_pending(
        self, db, pending_plan,
    ):
        """Rule D must refuse a replacement purchase during the
        window where provider cleanup is still failing/deferred."""
        s = pending_plan
        decline = stripe.CardError(
            "Your card was declined.", param=None, code="card_declined",
        )
        with _Stripe(raise_on_pay=decline):
            with patch(
                "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
                side_effect=stripe.APIConnectionError("transient"),
            ):
                with pytest.raises(stripe.StripeError):
                    _do_setup_completed(
                        db,
                        session={"id": s.session_id},
                        plan_id=s.plan.id,
                        event_livemode=False,
                    )
        # Rule D still blocks a new attempt on the same option.
        from app.services.finite_plan_orchestration import check_no_active_plan
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            check_no_active_plan(db, user=s.member, payment_option=s.option)
        assert exc.value.status_code == 409

    def test_retried_cleanup_success_transitions_plan_to_failed(
        self, db, pending_plan,
    ):
        """Simulate: first delivery fails to cancel provider
        (transient), second delivery succeeds. Plan should then
        become ``failed`` and Rule D unblocks."""
        s = pending_plan
        decline = stripe.CardError(
            "Your card was declined.", param=None, code="card_declined",
        )
        # First delivery — cancel raises.
        with _Stripe(raise_on_pay=decline):
            with patch(
                "app.services.stripe_finite_plan.cancel_finite_subscription_schedule",
                side_effect=stripe.APIConnectionError("transient"),
            ):
                with pytest.raises(stripe.StripeError):
                    _do_setup_completed(
                        db,
                        session={"id": s.session_id},
                        plan_id=s.plan.id,
                        event_livemode=False,
                    )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.pending_setup

        # Second delivery — cancel succeeds. Use a fresh Stripe
        # context; the webhook lease (mocked out by direct handler
        # call) is not consulted here.
        with _Stripe(raise_on_pay=decline):
            _do_setup_completed(
                db,
                session={"id": s.session_id},
                plan_id=s.plan.id,
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed


# ---------------------------------------------------------------------------
# Cancellation semantics: invoice_now=False, prorate=False
# ---------------------------------------------------------------------------


class TestCancelUsesNoInvoiceAndNoProration:
    def test_schedule_cancel_called_with_no_invoice_and_no_proration(
        self, db, pending_plan,
    ):
        """First-payment failure cleanup must NOT emit a final
        invoice or apply proration — the member never earned any
        access to prorate against."""
        s = pending_plan
        decline = stripe.CardError(
            "Your card was declined.", param=None, code="card_declined",
        )
        cancel_calls = []
        def _capture_cancel(schedule_id, **kwargs):
            cancel_calls.append(kwargs)
            return {"id": schedule_id, "status": "canceled"}
        with _Stripe(raise_on_pay=decline):
            with patch("stripe.SubscriptionSchedule.cancel", side_effect=_capture_cancel):
                _do_setup_completed(
                    db,
                    session={"id": s.session_id},
                    plan_id=s.plan.id,
                    event_livemode=False,
                )
        assert len(cancel_calls) == 1
        kw = cancel_calls[0]
        assert kw.get("invoice_now") is False
        assert kw.get("prorate") is False


# ---------------------------------------------------------------------------
# Cancelled Stripe schedule cannot generate another scheduled charge
# ---------------------------------------------------------------------------


class TestCancelledScheduleDoesNotBillAgain:
    def test_cancelled_schedule_status_is_canceled_and_stops_billing(
        self, db, pending_plan,
    ):
        """After cancel_finite_subscription_schedule, a re-retrieve
        would show ``status=canceled`` (Stripe's own guarantee that
        no future invoices fire). We assert the helper uses
        ``SubscriptionSchedule.cancel`` (cascades to Subscription
        termination) rather than ``.release`` (which would leave
        the Subscription running autonomously)."""
        s = pending_plan
        decline = stripe.CardError(
            "Your card was declined.", param=None, code="card_declined",
        )
        with _Stripe(raise_on_pay=decline) as sm:
            # Make sure our helper does NOT call release.
            with patch("stripe.SubscriptionSchedule.release") as release_call:
                _do_setup_completed(
                    db,
                    session={"id": s.session_id},
                    plan_id=s.plan.id,
                    event_livemode=False,
                )
        assert sm.schedule_cancel_calls == 1
        release_call.assert_not_called()


# ---------------------------------------------------------------------------
# Non-paid invoice status (3DS requires_action etc.) — terminate the same way
# ---------------------------------------------------------------------------


class TestRequiresActionTerminates:
    def test_non_paid_status_after_pay_marks_plan_failed(self, db, pending_plan):
        s = pending_plan
        with _Stripe(first_invoice_status="open") as stripe_mock:
            _do_setup_completed(
                db,
                session={"id": s.session_id},
                plan_id=s.plan.id,
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed
        assert stripe_mock.schedule_cancel_calls == 1


# ---------------------------------------------------------------------------
# Async invoice.payment_failed on a pending_setup plan — same result
# ---------------------------------------------------------------------------


class TestPendingSetupInvoiceFailedBranch:
    def test_invoice_failed_on_pending_setup_marks_plan_failed(self, db, pending_plan):
        """Even if the immediate collection didn't fire (e.g. rare
        case where subscription id wasn't returned), a later
        invoice.payment_failed for the first invoice still terminates
        the plan cleanly."""
        s = pending_plan
        # Set subscription id so the failure handler can find the plan.
        s.plan.provider_subscription_id = "sub_test_async_fail"
        s.plan.provider_subscription_schedule_id = "sub_sched_test_async_fail"
        db.commit()

        with patch("stripe.SubscriptionSchedule.retrieve", return_value={"status": "active"}), \
             patch("stripe.SubscriptionSchedule.cancel", return_value={"status": "canceled"}), \
             patch("app.core.config.settings.stripe_secret_key", "sk_test_dummy"), \
             patch("app.core.config.settings.stripe_webhook_secret", "whsec_dummy"):
            fpl.handle_invoice_failed_for_plan(
                db, plan=s.plan,
                invoice_id="in_test_async_fail",
                failed_at=datetime.utcnow(),
            )
            db.flush()
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed
        assert (s.plan.cancelled_reason or "").startswith("first_payment_failed")
        # No grace window opened for a first-payment failure.
        assert s.plan.grace_expires_at is None


# ---------------------------------------------------------------------------
# Rule D unblocks a fresh purchase attempt after first-payment failure
# ---------------------------------------------------------------------------


class TestRuleDUnblocksAfterFirstPaymentFailure:
    def test_failed_plan_does_not_block_fresh_attempt(self, db, pending_plan):
        s = pending_plan
        from app.services.finite_plan_orchestration import check_no_active_plan
        from fastapi import HTTPException

        # Terminate the plan (simulating the first-payment failure).
        s.plan.status = PurchasePlanStatus.failed
        s.plan.cancelled_reason = "first_payment_failed"
        s.plan.cancelled_at = datetime.utcnow()
        db.commit()

        # A fresh call to Rule D on the same member+option should NOT raise.
        try:
            check_no_active_plan(
                db, user=s.member, payment_option=s.option,
            )
        except HTTPException:
            pytest.fail("Rule D should NOT block a fresh attempt after a first-payment failure")


# ---------------------------------------------------------------------------
# subscription.deleted after first-payment failure = no-op
# ---------------------------------------------------------------------------


class TestSubscriptionDeletedAfterFirstFailureIsNoOp:
    def test_deleted_event_leaves_failed_plan_alone(self, db, pending_plan):
        s = pending_plan
        s.plan.provider_subscription_id = "sub_test_after_fail"
        s.plan.status = PurchasePlanStatus.failed
        s.plan.cancelled_reason = "first_payment_failed"
        s.plan.cancelled_at = datetime.utcnow()
        db.commit()

        with patch("app.core.config.settings.stripe_secret_key", "sk_test_dummy"), \
             patch("app.core.config.settings.stripe_webhook_secret", "whsec_dummy"):
            _do_subscription_deleted(
                db,
                subscription={"id": "sub_test_after_fail"},
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.failed
        assert (s.plan.cancelled_reason or "").startswith("first_payment_failed")


# ---------------------------------------------------------------------------
# Later-instalment failure still opens FIP3 grace (unchanged)
# ---------------------------------------------------------------------------


class TestLaterInstalmentGraceUnchanged:
    def test_active_plan_failure_still_opens_grace(self, db, pending_plan):
        s = pending_plan
        # Simulate a plan that already succeeded its first invoice.
        s.plan.status = PurchasePlanStatus.active
        s.plan.installments_paid = 1
        s.plan.activated_at = datetime.utcnow()
        s.plan.provider_subscription_id = "sub_test_later_fail"
        db.commit()

        fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id="in_test_later_fail",
            failed_at=datetime.utcnow(),
        )
        db.flush()
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.payment_problem
        assert s.plan.grace_expires_at is not None
        # 7-day grace exists.
        delta = s.plan.grace_expires_at - s.plan.payment_problem_started_at
        assert 6.9 < delta.days < 7.1
