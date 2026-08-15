"""FIP2 — checkout.session.completed for a finite-plan setup Session.

The webhook handler:
  1. Locates the plan by ``metadata.purchase_plan_id``.
  2. Retrieves the SetupIntent + Customer.
  3. Persists ``provider_customer_id`` + ``provider_payment_method_id``.
  4. Sets the PaymentMethod as the Customer's default.
  5. Creates Stripe Product + recurring Price.
  6. Creates the SubscriptionSchedule with ``end_behavior='cancel'``.
  7. Persists the SubscriptionSchedule id (+ Subscription id if
     returned) on the plan.
  8. Does NOT grant access.

Tests cover happy path, cadence variations, replay-safety, and
verify the exact Stripe parameters passed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.webhooks.finite_plan_handlers import (
    handle_finite_plan_setup_completed,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixture — a plan in pending_setup with a persisted setup session id
# ---------------------------------------------------------------------------


@pytest.fixture
def plan_awaiting_setup(db, make_user, make_space):
    from app.models.payment_option import (
        PaymentOption, PaymentOptionStatus, PaymentOptionType,
    )
    from app.models.payment_option_schedule import PaymentOptionSchedule

    member = make_user()
    space = make_space()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="space", attaches_to_id=space.id,
        name="Awaken",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly × 10", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000, installment_count=10,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=20000, currency="AUD",
    )
    db.add(sched)
    db.flush()

    session_id = f"cs_test_{uuid.uuid4().hex[:16]}"
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        status=PurchasePlanStatus.pending_setup,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=10,
        installments_paid=0,
        total_expected_cents=20000,
        stripe_interval="week",
        stripe_interval_count=1,
        provider_setup_session_id=session_id,
        stripe_mode="test",
    )
    db.add(plan)
    db.commit()

    return SimpleNamespace(
        member=member, space=space, option=opt,
        schedule=sched, plan=plan, session_id=session_id,
    )


def _fake_completed_session(*, session_id: str, customer_id: str, pm_id: str):
    """Stripe-like object returned by ``retrieve_completed_setup_session``."""
    return SimpleNamespace(
        id=session_id,
        customer=customer_id,
        setup_intent=SimpleNamespace(
            id=f"seti_{uuid.uuid4().hex[:12]}",
            payment_method=pm_id,
        ),
    )


def _fake_subscription_schedule(*, plan_id: str, subscription_id: str | None):
    return SimpleNamespace(
        id=f"sub_sched_{uuid.uuid4().hex[:12]}",
        subscription=subscription_id,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSetupCompletionHappyPath:
    def test_creates_subscription_schedule_and_persists_ids(
        self, db, plan_awaiting_setup,
    ):
        s = plan_awaiting_setup
        customer_id = "cus_test_happy"
        pm_id = "pm_test_happy"
        subscription_id = "sub_test_happy"

        completed = _fake_completed_session(
            session_id=s.session_id,
            customer_id=customer_id, pm_id=pm_id,
        )

        with (
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.retrieve_completed_setup_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.attach_payment_method_as_default",
            ) as attach,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_product_and_price",
                return_value=("prod_test", "price_test"),
            ) as make_price,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_finite_subscription_schedule",
                return_value=("sub_sched_test", subscription_id),
            ) as make_schedule,
        ):
            handle_finite_plan_setup_completed(
                {"id": s.session_id},
                db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=False,
            )

        db.refresh(s.plan)
        assert s.plan.provider_customer_id == customer_id
        assert s.plan.provider_payment_method_id == pm_id
        assert s.plan.stripe_product_id == "prod_test"
        assert s.plan.stripe_price_id == "price_test"
        assert s.plan.provider_subscription_schedule_id == "sub_sched_test"
        assert s.plan.provider_subscription_id == subscription_id
        # Access is NOT granted yet — plan stays in pending_setup.
        # (It transitions to `active` when the first invoice succeeds.)
        assert s.plan.status == PurchasePlanStatus.pending_setup

        # PaymentMethod attached as Customer default.
        attach.assert_called_once_with(
            customer_id=customer_id,
            payment_method_id=pm_id,
        )
        # SubscriptionSchedule call params exact.
        sched_kwargs = make_schedule.call_args.kwargs
        assert sched_kwargs["customer_id"] == customer_id
        assert sched_kwargs["price_id"] == "price_test"
        assert sched_kwargs["default_payment_method_id"] == pm_id
        assert sched_kwargs["plan"].id == s.plan.id


class TestSetupCompletionReplay:
    def test_duplicate_delivery_creates_no_second_stripe_schedule(
        self, db, plan_awaiting_setup,
    ):
        """FIP1 idempotency helper + handler-level guards must
        together prevent a second SubscriptionSchedule creation."""
        s = plan_awaiting_setup
        completed = _fake_completed_session(
            session_id=s.session_id, customer_id="cus_x", pm_id="pm_x",
        )

        with (
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.retrieve_completed_setup_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.attach_payment_method_as_default",
            ),
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_product_and_price",
                return_value=("prod_x", "price_x"),
            ) as make_price,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_finite_subscription_schedule",
                return_value=("sub_sched_x", "sub_x"),
            ) as make_schedule,
        ):
            handle_finite_plan_setup_completed(
                {"id": s.session_id}, db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=False,
            )
            # Second delivery — helper skips via idempotency table.
            handle_finite_plan_setup_completed(
                {"id": s.session_id}, db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=False,
            )

        assert make_price.call_count == 1
        assert make_schedule.call_count == 1


# ---------------------------------------------------------------------------
# Cadence variations — Stripe params for weekly / fortnightly / monthly
# ---------------------------------------------------------------------------


class TestCadenceParameters:
    """The plan's ``stripe_interval`` / ``stripe_interval_count`` flow
    through unchanged to the Stripe Price, and are multiplied by
    ``installments_expected`` for the phase duration on the
    SubscriptionSchedule. Stripe removed ``phases[].iterations``
    — the current supported field is ``phases[].duration``. These
    tests assert the exact SDK-level payload for each supported
    cadence + the idempotency-key version + that no legacy
    ``iterations`` field is sent."""

    @pytest.mark.parametrize(
        "price_interval,price_interval_count,count,expected_duration_count,label",
        [
            # weekly × 3     → Price week × 1, phase duration week × 3
            ("week",  1, 3, 3,  "weekly"),
            # fortnightly × 5 → Price week × 2, phase duration week × 10
            ("week",  2, 5, 10, "fortnightly"),
            # monthly × 6    → Price month × 1, phase duration month × 6
            ("month", 1, 6, 6,  "monthly"),
        ],
    )
    def test_price_and_schedule_payload_shape(
        self, db, plan_awaiting_setup,
        price_interval, price_interval_count, count,
        expected_duration_count, label,
    ):
        s = plan_awaiting_setup
        s.plan.stripe_interval = price_interval
        s.plan.stripe_interval_count = price_interval_count
        s.plan.installments_expected = count
        s.plan.total_expected_cents = s.plan.installment_amount_cents * count
        db.commit()

        completed = _fake_completed_session(
            session_id=s.session_id, customer_id="cus_c", pm_id="pm_c",
        )

        with patch("stripe.SubscriptionSchedule.create") as create_sched, \
             patch("stripe.Price.create",
                   return_value=SimpleNamespace(id="price_c")) as create_price, \
             patch("stripe.Product.create",
                   return_value=SimpleNamespace(id="prod_c")), \
             patch("stripe.Customer.modify"), \
             patch(
                 "app.webhooks.finite_plan_handlers.stripe_finite_plan.retrieve_completed_setup_session",
                 return_value=completed,
             ):
            create_sched.return_value = SimpleNamespace(
                id=f"sub_sched_{label}", subscription="sub_x",
            )
            handle_finite_plan_setup_completed(
                {"id": s.session_id}, db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=False,
            )

        # Price uses the schedule's per-instalment cadence unchanged.
        price_call = create_price.call_args.kwargs
        assert price_call["recurring"] == {
            "interval": price_interval,
            "interval_count": price_interval_count,
        }
        assert price_call["unit_amount"] == s.plan.installment_amount_cents

        # SubscriptionSchedule: one phase with a duration covering
        # the full finite plan; end_behavior='cancel' enforces the
        # finite stop. No legacy ``iterations`` field.
        sched_call = create_sched.call_args.kwargs
        assert sched_call["end_behavior"] == "cancel"
        assert len(sched_call["phases"]) == 1
        phase = sched_call["phases"][0]

        assert phase["duration"] == {
            "interval": price_interval,
            "interval_count": expected_duration_count,
        }
        assert "iterations" not in phase, (
            "phases[].iterations is a removed Stripe field — "
            "must not be sent"
        )

        # Idempotency-key bump lives ONLY on SubscriptionSchedule.
        # v1 for that op was consumed by the initial 400 Stripe cached.
        assert sched_call["idempotency_key"].endswith(
            ":subscription_schedule:v2"
        ), sched_call["idempotency_key"]

    def test_product_and_price_idempotency_keys_unchanged(
        self, db, plan_awaiting_setup,
    ):
        """Only SubscriptionSchedule bumped; Product/Price stay at v1
        so a plan whose Product/Price already succeeded doesn't
        re-create them on retry."""
        s = plan_awaiting_setup
        completed = _fake_completed_session(
            session_id=s.session_id, customer_id="cus_k", pm_id="pm_k",
        )

        with patch("stripe.SubscriptionSchedule.create",
                   return_value=SimpleNamespace(id="sub_sched_k", subscription="sub_k")), \
             patch("stripe.Price.create",
                   return_value=SimpleNamespace(id="price_k")) as create_price, \
             patch("stripe.Product.create",
                   return_value=SimpleNamespace(id="prod_k")) as create_product, \
             patch("stripe.Customer.modify"), \
             patch(
                 "app.webhooks.finite_plan_handlers.stripe_finite_plan.retrieve_completed_setup_session",
                 return_value=completed,
             ):
            handle_finite_plan_setup_completed(
                {"id": s.session_id}, db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=False,
            )

        assert create_product.call_args.kwargs["idempotency_key"].endswith(":product:v1")
        assert create_price.call_args.kwargs["idempotency_key"].endswith(":price:v1")


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class TestSetupGuards:
    def test_missing_plan_id_metadata_skipped(self, db):
        # No purchase_plan_id → helper marks skipped without raising
        # to the outer webhook loop.
        handle_finite_plan_setup_completed(
            {"id": "cs_test_no_meta"}, db, metadata={},
            event_livemode=False,
        )
        # No plan was mutated (we can't check that directly; the
        # absence of an exception + no Stripe call = success).

    def test_unknown_plan_id_skipped(self, db):
        handle_finite_plan_setup_completed(
            {"id": "cs_test_unknown"}, db,
            metadata={"purchase_plan_id": "pplan_does_not_exist"},
            event_livemode=False,
        )
        # As above — outer skip is enough.

    def test_plan_already_past_setup_is_noop(
        self, db, plan_awaiting_setup,
    ):
        s = plan_awaiting_setup
        s.plan.status = PurchasePlanStatus.active
        db.commit()

        with (
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.retrieve_completed_setup_session",
            ) as retrieve,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_finite_subscription_schedule",
            ) as make_schedule,
        ):
            handle_finite_plan_setup_completed(
                {"id": s.session_id}, db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=False,
            )

        # No Stripe work — the plan already advanced past pending_setup.
        retrieve.assert_not_called()
        make_schedule.assert_not_called()


class TestSetupLivemodeBoundary:
    """A test event MUST NOT touch a live plan (or vice versa),
    and the check MUST happen before any provider field is
    persisted or any downstream Stripe call is made. This test is
    the hardening backstop the FIP2 review flagged."""

    def test_livemode_mismatch_skips_before_any_mutation(
        self, db, plan_awaiting_setup,
    ):
        s = plan_awaiting_setup
        assert s.plan.stripe_mode == "test"
        # Baseline: every provider field NULL before the handler runs.
        assert s.plan.provider_customer_id is None
        assert s.plan.provider_payment_method_id is None
        assert s.plan.provider_subscription_schedule_id is None
        assert s.plan.provider_subscription_id is None
        assert s.plan.stripe_product_id is None
        assert s.plan.stripe_price_id is None

        # Wire every downstream Stripe wrapper as a spy — none of
        # them may be invoked when the mode mismatches.
        completed = _fake_completed_session(
            session_id=s.session_id,
            customer_id="cus_live_should_not_touch",
            pm_id="pm_live_should_not_touch",
        )

        with (
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.retrieve_completed_setup_session",
                return_value=completed,
            ) as retrieve,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.attach_payment_method_as_default",
            ) as attach,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_product_and_price",
                return_value=("prod_x", "price_x"),
            ) as make_price,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_finite_subscription_schedule",
                return_value=("sub_sched_x", "sub_x"),
            ) as make_schedule,
        ):
            # Live event landing on a test plan — must be a skip.
            handle_finite_plan_setup_completed(
                {"id": s.session_id}, db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=True,  # <- MISMATCH
            )

        # No Stripe wrapper touched.
        retrieve.assert_not_called()
        attach.assert_not_called()
        make_price.assert_not_called()
        make_schedule.assert_not_called()

        # No provider fields persisted, no status change.
        db.refresh(s.plan)
        assert s.plan.provider_customer_id is None
        assert s.plan.provider_payment_method_id is None
        assert s.plan.provider_subscription_schedule_id is None
        assert s.plan.provider_subscription_id is None
        assert s.plan.stripe_product_id is None
        assert s.plan.stripe_price_id is None
        assert s.plan.status == PurchasePlanStatus.pending_setup

    def test_test_event_on_live_plan_skips_before_any_mutation(
        self, db, plan_awaiting_setup,
    ):
        """Symmetrical case — flip the plan to live-mode."""
        s = plan_awaiting_setup
        s.plan.stripe_mode = "live"
        db.commit()

        completed = _fake_completed_session(
            session_id=s.session_id,
            customer_id="cus_test_should_not_touch",
            pm_id="pm_test_should_not_touch",
        )

        with (
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.retrieve_completed_setup_session",
                return_value=completed,
            ) as retrieve,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.attach_payment_method_as_default",
            ) as attach,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_product_and_price",
                return_value=("prod_x", "price_x"),
            ) as make_price,
            patch(
                "app.webhooks.finite_plan_handlers.stripe_finite_plan.create_finite_subscription_schedule",
                return_value=("sub_sched_x", "sub_x"),
            ) as make_schedule,
        ):
            handle_finite_plan_setup_completed(
                {"id": s.session_id}, db,
                metadata={"purchase_plan_id": s.plan.id},
                event_livemode=False,  # <- MISMATCH (plan is live)
            )

        retrieve.assert_not_called()
        attach.assert_not_called()
        make_price.assert_not_called()
        make_schedule.assert_not_called()

        db.refresh(s.plan)
        assert s.plan.provider_customer_id is None
        assert s.plan.provider_payment_method_id is None
        assert s.plan.status == PurchasePlanStatus.pending_setup
