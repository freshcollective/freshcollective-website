"""FIP2 — starting a finite payment plan (Stripe mocked).

Covers everything up to and including opening the Stripe setup
Checkout Session:

* Valid recurring plan creates a ``pending_setup`` PurchasePlan.
* Stripe setup Session parameters are exactly what we expect
  (mode='setup', metadata, customer creation).
* Provider setup session id + Customer reuse persisted on the plan.
* Fee rate + immutable commercial fields snapshotted.
* Grants intent snapshotted to ``snapshot_grants_json``.
* Duplicate active/pending/payment_problem plan → 409.
* Completed / failed / cancelled prior plans do NOT block a new one.
* Pay-in-full path is not affected.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.access_pass import AccessPass, AccessPassStatus, AccessPassType
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services.finite_plan_orchestration import (
    ResolvedRecurringOption,
    resolve_option_and_schedule_for_plan,
    start_finite_plan_setup,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures — Payment Option + recurring Schedule with a Series grant
# ---------------------------------------------------------------------------


@pytest.fixture
def recurring_setup(db, make_user, make_space):
    """Build a Space + published Series + published Option + published
    recurring schedule + PaymentOptionGrant so resolve_intent_for_option
    returns a viable intent."""
    from app.models.payment_option import (
        PaymentOption, PaymentOptionStatus, PaymentOptionType,
    )
    from app.models.payment_option_schedule import PaymentOptionSchedule
    from app.models.payment_option_grant import PaymentOptionGrant
    from app.models.platform import EventSeries

    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)

    series_starts = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Test Term",
        starts_at=series_starts,
        ends_at=None,
        status="published",
        published_at=series_starts,
    )
    db.add(series)
    db.flush()

    opt = PaymentOption(
        id=_uid("po"),
        space_id=space.id,
        attaches_to_kind="event_series",
        attaches_to_id=series.id,
        name="Awaken",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000,
        currency="AUD",
    )
    db.add(opt)
    db.flush()

    grant = PaymentOptionGrant(
        payment_option_id=opt.id,
        grant_kind="event_series",
        series_id=series.id,
        sessions_per_week=1,
        total_sessions=10,
    )
    db.add(grant)
    db.flush()

    sched = PaymentOptionSchedule(
        id=_uid("sched"),
        payment_option_id=opt.id,
        name="Weekly × 10",
        schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000,
        installment_count=10,
        stripe_interval="week",
        stripe_interval_count=1,
        total_amount_cents=20000,
        currency="AUD",
    )
    db.add(sched)
    db.commit()

    return SimpleNamespace(
        member=member, creator=creator, space=space,
        series=series, option=opt, schedule=sched,
    )


@pytest.fixture
def fake_stripe_setup_session():
    """Yield a Stripe-shaped Session object with a stable URL."""
    return SimpleNamespace(
        id=f"cs_test_{uuid.uuid4().hex[:16]}",
        url="https://stripe.test/checkout/cs_test_setup",
    )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TestResolveForPlan:
    def test_valid_recurring_schedule_resolves(self, db, recurring_setup):
        resolved = resolve_option_and_schedule_for_plan(
            db,
            payment_option_id=recurring_setup.option.id,
            payment_option_schedule_id=recurring_setup.schedule.id,
        )
        assert resolved.payment_schedule.schedule_type == "recurring_installments"
        assert resolved.currency == "AUD"

    def test_pay_in_full_schedule_rejected(
        self, db, recurring_setup,
    ):
        """The plan resolver refuses pay_in_full — those go through
        the existing pay-in-full path."""
        from app.models.payment_option_schedule import PaymentOptionSchedule
        pay = PaymentOptionSchedule(
            id=_uid("sched"),
            payment_option_id=recurring_setup.option.id,
            name="Pay in full",
            schedule_type="pay_in_full",
            status="published",
            total_amount_cents=20000,
            currency="AUD",
        )
        db.add(pay)
        db.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            resolve_option_and_schedule_for_plan(
                db,
                payment_option_id=recurring_setup.option.id,
                payment_option_schedule_id=pay.id,
            )
        assert exc.value.status_code == 400

    def test_unpublished_schedule_rejected(self, db, recurring_setup):
        recurring_setup.schedule.status = "draft"
        db.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            resolve_option_and_schedule_for_plan(
                db,
                payment_option_id=recurring_setup.option.id,
                payment_option_schedule_id=recurring_setup.schedule.id,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# start_finite_plan_setup
# ---------------------------------------------------------------------------


class TestStartFinitePlanSetup:
    def _resolved(self, db, s):
        return resolve_option_and_schedule_for_plan(
            db,
            payment_option_id=s.option.id,
            payment_option_schedule_id=s.schedule.id,
        )

    def test_happy_path_creates_pending_plan_and_setup_session(
        self, db, recurring_setup, fake_stripe_setup_session,
    ):
        resolved = self._resolved(db, recurring_setup)

        with patch(
            "app.services.finite_plan_orchestration.stripe_finite_plan.create_setup_session",
            return_value=fake_stripe_setup_session,
        ) as create_setup, \
             patch.object(settings, "stripe_secret_key", "sk_test_dummy"), \
             patch.object(settings, "stripe_webhook_secret", "whsec_dummy"):
            outcome = start_finite_plan_setup(
                db,
                resolved=resolved,
                payer=recurring_setup.member,
                success_url="https://example/success",
                cancel_url="https://example/cancel",
                now=datetime.utcnow(),
            )

        plan = outcome.plan
        # Plan is pending_setup with the immutable commercial snapshot.
        assert plan.status == PurchasePlanStatus.pending_setup
        assert plan.installment_amount_cents == 2000
        assert plan.installments_expected == 10
        assert plan.total_expected_cents == 20000
        assert plan.stripe_interval == "week"
        assert plan.stripe_interval_count == 1
        assert plan.currency == "AUD"
        # Provider ids: setup session id persisted; SubscriptionSchedule
        # not created yet.
        assert plan.provider_setup_session_id == fake_stripe_setup_session.id
        assert plan.provider_subscription_schedule_id is None
        assert plan.provider_subscription_id is None
        # Fee snapshot captured.
        assert plan.platform_fee_basis_points is not None
        # Grants intent snapshotted.
        assert plan.snapshot_grants_json is not None
        assert plan.snapshot_grants_json.get("version") == 1
        # Session URL returned.
        assert outcome.checkout_url == fake_stripe_setup_session.url

        # Stripe call parameters — assert exact values.
        create_setup.assert_called_once()
        call_kwargs = create_setup.call_args.kwargs
        assert call_kwargs["plan"].id == plan.id
        # Payment Option name flows through so the disclosure composer
        # can name the plan on the Stripe-hosted setup page.
        assert call_kwargs["option_name"] == recurring_setup.option.name
        assert call_kwargs["member_email"] == recurring_setup.member.email
        assert call_kwargs["success_url"] == "https://example/success"
        assert call_kwargs["cancel_url"] == "https://example/cancel"
        # No previous Customer for this member, so reuse_customer_id is None.
        assert call_kwargs["reuse_customer_id"] is None

    def test_grants_snapshot_matches_current_option(
        self, db, recurring_setup, fake_stripe_setup_session,
    ):
        resolved = self._resolved(db, recurring_setup)
        with patch(
            "app.services.finite_plan_orchestration.stripe_finite_plan.create_setup_session",
            return_value=fake_stripe_setup_session,
        ), \
             patch.object(settings, "stripe_secret_key", "sk_test_dummy"), \
             patch.object(settings, "stripe_webhook_secret", "whsec_dummy"):
            outcome = start_finite_plan_setup(
                db,
                resolved=resolved,
                payer=recurring_setup.member,
                success_url="https://example/success",
                cancel_url="https://example/cancel",
                now=datetime.utcnow(),
            )

        snap = outcome.plan.snapshot_grants_json
        # The option has one Series grant → one access_pass in the intent.
        assert isinstance(snap["access_passes"], list)
        assert len(snap["access_passes"]) == 1
        ap = snap["access_passes"][0]
        assert ap["eligible_series_id"] == recurring_setup.series.id
        assert ap["pass_type"] == AccessPassType.term_pass.value
        assert ap["total_credits"] == 10
        assert ap["credits_per_week"] == 1

    def test_customer_reused_from_prior_plan(
        self, db, recurring_setup, fake_stripe_setup_session,
    ):
        # Seed a prior plan for the same member with a Stripe customer id.
        prior = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=recurring_setup.member.id,
            payment_option_id=recurring_setup.option.id,
            payment_option_schedule_id=recurring_setup.schedule.id,
            space_id=recurring_setup.space.id,
            installment_amount_cents=2000,
            installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week",
            stripe_interval_count=1,
            status=PurchasePlanStatus.completed,
            provider_customer_id="cus_reused_test",
        )
        db.add(prior)
        db.commit()

        resolved = self._resolved(db, recurring_setup)
        with patch(
            "app.services.finite_plan_orchestration.stripe_finite_plan.create_setup_session",
            return_value=fake_stripe_setup_session,
        ) as create_setup, \
             patch.object(settings, "stripe_secret_key", "sk_test_dummy"), \
             patch.object(settings, "stripe_webhook_secret", "whsec_dummy"):
            outcome = start_finite_plan_setup(
                db,
                resolved=resolved,
                payer=recurring_setup.member,
                success_url="https://example/success",
                cancel_url="https://example/cancel",
                now=datetime.utcnow(),
            )

        assert create_setup.call_args.kwargs["reuse_customer_id"] == "cus_reused_test"
        assert outcome.plan.provider_customer_id == "cus_reused_test"


# ---------------------------------------------------------------------------
# Duplicate-plan guard
# ---------------------------------------------------------------------------


class TestDuplicatePlanGuard:
    """FIP1 Rule D — active/pending plan blocks a second start."""

    def _fake_route(self, db, recurring_setup, fake_session):
        """Simulate the route: resolve + guards + start."""
        from app.services.checkout_orchestration import (
            check_option_fulfillable_or_raise,
            check_same_option_not_active,
        )
        resolved = resolve_option_and_schedule_for_plan(
            db,
            payment_option_id=recurring_setup.option.id,
            payment_option_schedule_id=recurring_setup.schedule.id,
        )
        check_option_fulfillable_or_raise(resolved.payment_option)
        check_same_option_not_active(
            db, user=recurring_setup.member,
            payment_option=resolved.payment_option,
            now=datetime.utcnow(),
        )
        with patch(
            "app.services.finite_plan_orchestration.stripe_finite_plan.create_setup_session",
            return_value=fake_session,
        ), \
             patch.object(settings, "stripe_secret_key", "sk_test_dummy"), \
             patch.object(settings, "stripe_webhook_secret", "whsec_dummy"):
            return start_finite_plan_setup(
                db,
                resolved=resolved,
                payer=recurring_setup.member,
                success_url="https://example/success",
                cancel_url="https://example/cancel",
                now=datetime.utcnow(),
            )

    @pytest.mark.parametrize("blocking_status", [
        PurchasePlanStatus.pending_setup,
        PurchasePlanStatus.active,
        PurchasePlanStatus.payment_problem,
    ])
    def test_active_ish_plan_blocks_second_start(
        self, db, recurring_setup, fake_stripe_setup_session, blocking_status,
    ):
        existing = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=recurring_setup.member.id,
            payment_option_id=recurring_setup.option.id,
            payment_option_schedule_id=recurring_setup.schedule.id,
            space_id=recurring_setup.space.id,
            installment_amount_cents=2000,
            installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week",
            stripe_interval_count=1,
            status=blocking_status,
        )
        db.add(existing)
        db.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._fake_route(db, recurring_setup, fake_stripe_setup_session)
        assert exc.value.status_code == 409

    @pytest.mark.parametrize("non_blocking_status", [
        PurchasePlanStatus.completed,
        PurchasePlanStatus.cancelled,
        PurchasePlanStatus.failed,
    ])
    def test_terminal_plan_does_not_block_retry(
        self, db, recurring_setup, fake_stripe_setup_session, non_blocking_status,
    ):
        existing = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=recurring_setup.member.id,
            payment_option_id=recurring_setup.option.id,
            payment_option_schedule_id=recurring_setup.schedule.id,
            space_id=recurring_setup.space.id,
            installment_amount_cents=2000,
            installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week",
            stripe_interval_count=1,
            status=non_blocking_status,
        )
        db.add(existing)
        db.commit()

        outcome = self._fake_route(db, recurring_setup, fake_stripe_setup_session)
        assert outcome.plan.status == PurchasePlanStatus.pending_setup

    def test_different_option_not_blocked(
        self, db, recurring_setup, fake_stripe_setup_session, make_user,
    ):
        """An active plan on a DIFFERENT option must not block this one."""
        from app.models.payment_option import (
            PaymentOption, PaymentOptionStatus, PaymentOptionType,
        )
        other = PaymentOption(
            id=_uid("po"),
            space_id=recurring_setup.space.id,
            attaches_to_kind="space",
            attaches_to_id=recurring_setup.space.id,
            name="Different option",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=99999,
            currency="AUD",
        )
        db.add(other)
        db.commit()

        active_other = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=recurring_setup.member.id,
            payment_option_id=other.id,
            payment_option_schedule_id=recurring_setup.schedule.id,
            space_id=recurring_setup.space.id,
            installment_amount_cents=2000,
            installments_expected=10,
            total_expected_cents=20000,
            stripe_interval="week",
            stripe_interval_count=1,
            status=PurchasePlanStatus.active,
        )
        db.add(active_other)
        db.commit()

        outcome = self._fake_route(db, recurring_setup, fake_stripe_setup_session)
        assert outcome.plan.payment_option_id == recurring_setup.option.id


# ---------------------------------------------------------------------------
# Pay-in-full still unaffected
# ---------------------------------------------------------------------------


class TestPayInFullUnchanged:
    """Regression: the 503 guard still fires for callers of the
    pay-in-full resolver — they must not accidentally hit the
    finite-plan code."""

    def test_pay_in_full_resolver_still_503s_recurring(self, db, recurring_setup):
        from fastapi import HTTPException
        from app.services.checkout_orchestration import (
            resolve_option_and_schedule,
        )
        with pytest.raises(HTTPException) as exc:
            resolve_option_and_schedule(
                db,
                payment_option_id=recurring_setup.option.id,
                payment_option_schedule_id=recurring_setup.schedule.id,
            )
        assert exc.value.status_code == 503
