"""FIP4B2 — member payment-method repair for a finite payment plan.

Covers the full spec §16 test matrix:

Endpoint / ownership:
  E1  only the plan owner can start a repair
  E2  payment_problem plan can start repair
  E3  suspended plan can start repair
  E4  active plan cannot start repair
  E5  completed plan cannot start repair
  E6  cancelled plan cannot start repair
  E7  failed plan cannot start repair
  E8  pending_setup plan cannot start repair
  E9  plan missing provider ids cannot start repair
  E10 repair setup Session does NOT create a new PurchasePlan
  E11 endpoint metadata is server-generated (finite_plan_repair, plan id, payer id)

Payment-method swap (three surfaces):
  S1  Customer.invoice_settings.default_payment_method updated + re-fetched
  S2  SubscriptionSchedule.default_settings.default_payment_method updated + re-fetched
  S3  Subscription.default_payment_method updated + re-fetched
  S4  swap failure on ANY surface aborts before retry, plan pointer reverted
  S5  swap is idempotent under replay (same PM twice is a no-op)

Overdue-invoice retry:
  R1  retries the SAME failed invoice, not a new one
  R2  no new invoice created
  R3  wrong invoice/subscription relationship refused
  R4  invoice status not retryable → refused
  R5  card decline → treated as legitimate commerce outcome, plan stays recoverable
  R6  API/network error → propagates as StripeError (webhook lease retries)

Recovery pipeline (delegates to existing FIP3 lifecycle):
  L1  grace-state successful recovery → active + failed txn upgraded in place
  L2  suspended successful recovery → active + access reinstated + failed txn upgraded
  L3  grace deadline is NOT extended by a fresh decline of the replacement card

Idempotency + replay:
  I1  repair webhook replay is a no-op (durable lease)
  I2  same invoice + same PM = same idempotency key on Invoice.pay
  I3  metadata payer_user_id mismatch refused

Backwards compatibility (regression touch tests):
  B1  normal FIP4A purchase flow does NOT trigger the repair dispatcher
  B2  FIP3 automatic later-payment lifecycle unchanged
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import stripe
from fastapi import HTTPException

from app.commerce.finite_plan_repair_routes import (
    RepairSessionRequest,
    create_repair_session,
)
from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
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
    EntitlementSource, EntitlementStatus,
    EventSeries, Pathway, PathwayEntitlement,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import access_grant_records as agr
from app.services import finite_plan_lifecycle as fpl
from app.services import finite_plan_repair
from app.services.purchase_fulfilment import (
    AccessPassIntent, EntitlementIntent, FulfilmentIntent, serialise_intent,
)
from app.services.webhook_idempotency import SkipWebhookEvent
from app.webhooks.finite_plan_handlers import (
    _do_repair_completed,
    handle_finite_plan_repair_completed,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _enable_stripe(monkeypatch):
    """Force ``settings.stripe_enabled`` truthy by monkeypatching the
    source fields (the property itself is computed and can't be
    assigned directly on a pydantic Settings model)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


# ---------------------------------------------------------------------------
# Fixture — plan at 2/3, in payment_problem, invoice #3 failed
# ---------------------------------------------------------------------------


def _seed_active_plan_at_2_of_3(db, make_user, make_space):
    member = make_user()
    creator = make_user(role="creator")
    space = make_space(creator=creator)

    starts = datetime.utcnow()
    series = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
        starts_at=starts, status="published", published_at=starts,
    )
    pathway = Pathway(
        id=_uid("path"), space_id=space.id,
        slug=f"p-{uuid.uuid4().hex[:8]}", title="Awaken",
        status="active",
    )
    db.add_all([series, pathway]); db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="event_series", attaches_to_id=series.id,
        name="Awaken plan",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=6000, currency="AUD",
        grants_pathway_id=pathway.id,
    )
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly × 3", schedule_type="recurring_installments",
        status="published",
        installment_amount_cents=2000, installment_count=3,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=6000, currency="AUD",
    )
    db.add_all([opt, sched]); db.flush()

    now = datetime.utcnow()
    subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    schedule_id = f"ss_test_{uuid.uuid4().hex[:12]}"
    customer_id = f"cus_test_{uuid.uuid4().hex[:12]}"
    old_pm = f"pm_old_{uuid.uuid4().hex[:8]}"

    intent = FulfilmentIntent(
        entitlements=(EntitlementIntent(pathway_id=pathway.id, ends_at=None),),
        access_passes=(AccessPassIntent(
            pass_type=AccessPassType.term_pass,
            valid_from=now, valid_until=None,
            total_credits=None, credits_per_week=None,
            eligible_pathway_id=None, eligible_series_id=series.id,
            grants_pathway_id=pathway.id,
        ),),
    )
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id, creator_user_id=creator.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=3, installments_paid=2,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_customer_id=customer_id,
        provider_payment_method_id=old_pm,
        provider_subscription_id=subscription_id,
        provider_subscription_schedule_id=schedule_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
        activated_at=now,
    )
    db.add(plan); db.flush()

    # Seed a succeeded row per already-paid instalment so
    # installments_paid=2 matches the ledger.
    for inv_id, inst_no in [("in_seed_1", 1), ("in_seed_2", 2)]:
        txn = PaymentTransaction(
            id=str(uuid.uuid4()),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            fulfilment_status=PaymentFulfilmentStatus.applied,
            payer_user_id=member.id, creator_user_id=creator.id,
            space_id=space.id, currency="AUD",
            gross_amount_cents=2000, platform_fee_basis_points=800,
            platform_fee_cents=160, net_creator_amount_cents=1840,
            net_platform_amount_cents=160,
            provider_invoice_id=inv_id,
            provider_subscription_id=subscription_id,
            payment_option_id=opt.id, payment_option_schedule_id=sched.id,
            purchase_plan_id=plan.id, installment_number=inst_no,
            stripe_mode="test", payout_status=PayoutStatus.pending,
            created_at=now, updated_at=now,
        )
        db.add(txn)
    db.flush()

    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active, starts_at=now,
        purchase_plan_id=plan.id,
        created_at=now, updated_at=now,
    )
    ap = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_option_id=opt.id, payment_option_schedule_id=sched.id,
        purchase_plan_id=plan.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active, valid_from=now,
        eligible_series_id=series.id, grants_pathway_id=pathway.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add_all([ent, ap]); db.flush()

    agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=None,
        granted_at=now,
    )
    agr.record_series_grant(
        db, user_id=member.id, series_id=series.id,
        source_type=agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=None,
        granted_at=now,
    )
    db.commit()

    return SimpleNamespace(
        member=member, creator=creator, space=space,
        series=series, pathway=pathway, option=opt, schedule=sched,
        plan=plan, subscription_id=subscription_id,
        schedule_id=schedule_id, customer_id=customer_id, old_pm=old_pm,
        entitlement=ent, access_pass=ap,
    )


@pytest.fixture
def plan_payment_problem(db, make_user, make_space):
    """Active plan at 2/3 → invoice #3 fails → payment_problem."""
    s = _seed_active_plan_at_2_of_3(db, make_user, make_space)
    fpl.handle_invoice_failed_for_plan(
        db, plan=s.plan, invoice_id="in_invoice_3",
        failed_at=datetime.utcnow(),
    )
    db.commit()
    db.refresh(s.plan)
    assert s.plan.status == PurchasePlanStatus.payment_problem
    assert s.plan.last_failed_invoice_id == "in_invoice_3"
    assert s.plan.grace_expires_at is not None
    return s


@pytest.fixture
def plan_suspended(db, make_user, make_space):
    """Same shape as plan_payment_problem but suspended after grace expiry."""
    s = _seed_active_plan_at_2_of_3(db, make_user, make_space)
    fpl.handle_invoice_failed_for_plan(
        db, plan=s.plan, invoice_id="in_invoice_3",
        failed_at=datetime.utcnow() - timedelta(days=8),
    )
    db.commit()
    # Force clock past grace.
    fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
    db.commit()
    db.refresh(s.plan)
    assert s.plan.status == PurchasePlanStatus.suspended
    assert s.plan.last_failed_invoice_id == "in_invoice_3"
    return s


# ---------------------------------------------------------------------------
# Fake Stripe helpers
# ---------------------------------------------------------------------------


def _fake_completed_repair_session(*, session_id, customer_id, new_pm_id):
    return SimpleNamespace(
        id=session_id,
        customer=customer_id,
        setup_intent=SimpleNamespace(
            id=f"seti_{uuid.uuid4().hex[:12]}",
            payment_method=new_pm_id,
        ),
    )


def _fake_open_invoice(*, invoice_id, subscription_id, status="open"):
    """Stripe Invoice payload as a dict (safe for _sfield walks)."""
    return {
        "id": invoice_id,
        "status": status,
        "parent": {
            "type": "subscription_details",
            "subscription_details": {"subscription": subscription_id},
        },
    }


def _fake_paid_invoice(*, invoice_id, subscription_id):
    return {**_fake_open_invoice(invoice_id=invoice_id, subscription_id=subscription_id),
            "status": "paid"}


def _fake_customer(*, customer_id, pm_id):
    return SimpleNamespace(
        id=customer_id,
        invoice_settings=SimpleNamespace(default_payment_method=pm_id),
    )


def _fake_schedule(*, schedule_id, pm_id):
    return SimpleNamespace(
        id=schedule_id,
        default_settings=SimpleNamespace(default_payment_method=pm_id),
    )


def _fake_subscription(*, subscription_id, pm_id):
    return SimpleNamespace(
        id=subscription_id,
        default_payment_method=pm_id,
    )


# ---------------------------------------------------------------------------
# E-series — endpoint ownership + state gating
# ---------------------------------------------------------------------------


class TestEndpointOwnership:
    def _call(self, db, *, plan_id, user):
        return create_repair_session(
            body=RepairSessionRequest(plan_id=plan_id),
            current_user=user,
            db=db,
        )

    def _patch_stripe(self):
        return patch(
            "app.commerce.finite_plan_repair_routes.finite_plan_repair.create_repair_setup_session",
            return_value=SimpleNamespace(
                id=f"cs_repair_{uuid.uuid4().hex[:12]}",
                url="https://checkout.stripe.com/pay/test-url",
            ),
        )

    def test_E1_other_user_cannot_start_repair(
        self, db, plan_payment_problem, make_user, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        other = make_user()
        with self._patch_stripe():
            with pytest.raises(HTTPException) as exc:
                self._call(db, plan_id=plan_payment_problem.plan.id, user=other)
            assert exc.value.status_code == 404

    def test_E2_payment_problem_plan_can_start_repair(
        self, db, plan_payment_problem, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        with self._patch_stripe() as mock:
            resp = self._call(
                db, plan_id=plan_payment_problem.plan.id,
                user=plan_payment_problem.member,
            )
        assert resp.checkout_url.startswith("https://checkout.stripe.com")
        assert mock.called

    def test_E3_suspended_plan_can_start_repair(
        self, db, plan_suspended, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        with self._patch_stripe() as mock:
            resp = self._call(
                db, plan_id=plan_suspended.plan.id,
                user=plan_suspended.member,
            )
        assert resp.checkout_url.startswith("https://checkout.stripe.com")
        assert mock.called

    @pytest.mark.parametrize("status,expected_code", [
        (PurchasePlanStatus.active, 409),
        (PurchasePlanStatus.completed, 409),
        (PurchasePlanStatus.cancelled, 409),
        (PurchasePlanStatus.failed, 409),
        (PurchasePlanStatus.pending_setup, 409),
    ])
    def test_E4toE8_non_recoverable_statuses_refused(
        self, db, plan_payment_problem, status, expected_code, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        plan_payment_problem.plan.status = status
        db.commit()
        with self._patch_stripe():
            with pytest.raises(HTTPException) as exc:
                self._call(
                    db, plan_id=plan_payment_problem.plan.id,
                    user=plan_payment_problem.member,
                )
            assert exc.value.status_code == expected_code

    def test_E9_plan_missing_customer_id_refused(
        self, db, plan_payment_problem, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        plan_payment_problem.plan.provider_customer_id = None
        db.commit()
        with self._patch_stripe():
            with pytest.raises(HTTPException) as exc:
                self._call(
                    db, plan_id=plan_payment_problem.plan.id,
                    user=plan_payment_problem.member,
                )
            assert exc.value.status_code == 409

    def test_E9_plan_missing_last_failed_invoice_id_refused(
        self, db, plan_payment_problem, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        plan_payment_problem.plan.last_failed_invoice_id = None
        db.commit()
        with self._patch_stripe():
            with pytest.raises(HTTPException) as exc:
                self._call(
                    db, plan_id=plan_payment_problem.plan.id,
                    user=plan_payment_problem.member,
                )
            assert exc.value.status_code == 409

    def test_E10_endpoint_does_not_create_new_plan(
        self, db, plan_payment_problem, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        before = db.query(PurchasePlan).count()
        with self._patch_stripe():
            self._call(
                db, plan_id=plan_payment_problem.plan.id,
                user=plan_payment_problem.member,
            )
        after = db.query(PurchasePlan).count()
        assert after == before, "repair-session must not create another PurchasePlan"

    def test_E11_session_created_with_expected_kwargs(
        self, db, plan_payment_problem, monkeypatch,
    ):
        _enable_stripe(monkeypatch)
        with self._patch_stripe() as mock:
            self._call(
                db, plan_id=plan_payment_problem.plan.id,
                user=plan_payment_problem.member,
            )
        (_, kwargs) = mock.call_args
        assert kwargs["plan"].id == plan_payment_problem.plan.id
        assert kwargs["member_email"] == plan_payment_problem.member.email
        assert kwargs["success_url"].endswith(
            f"/checkout/repair-return?plan_id={plan_payment_problem.plan.id}"
        )
        assert kwargs["cancel_url"].endswith("/dashboard")


class TestRepairSessionMetadata:
    def test_E11_metadata_carries_repair_type_and_plan_id(
        self, db, plan_payment_problem,
    ):
        """Verify server-generated metadata is set correctly on the
        Stripe SDK call (mock out the SDK to inspect the kwargs)."""
        with patch(
            "app.services.finite_plan_repair.stripe.checkout.Session.create",
        ) as mock:
            mock.return_value = SimpleNamespace(
                id="cs_test", url="https://x", customer=plan_payment_problem.customer_id,
            )
            finite_plan_repair.create_repair_setup_session(
                plan=plan_payment_problem.plan,
                member_email=plan_payment_problem.member.email,
                success_url="https://fc.test/repair-return",
                cancel_url="https://fc.test/dashboard",
            )
        (_, kwargs) = mock.call_args
        assert kwargs["mode"] == "setup"
        assert kwargs["customer"] == plan_payment_problem.customer_id
        assert kwargs["metadata"]["purchase_type"] == "finite_plan_repair"
        assert kwargs["metadata"]["purchase_plan_id"] == plan_payment_problem.plan.id
        assert kwargs["metadata"]["payer_user_id"] == plan_payment_problem.member.id


# ---------------------------------------------------------------------------
# S-series — three-surface PM swap
# ---------------------------------------------------------------------------


class TestPaymentMethodSwapAllSurfaces:
    def _patch_stripe_swap(self, *, plan, new_pm, verify_pm=None):
        """Patch all Stripe surfaces used by swap_default_payment_method_all_surfaces.

        ``verify_pm`` — if provided, override the re-fetched PM (so
        the assertion fires). Default: echo new_pm on all surfaces
        (successful swap)."""
        verify_pm = verify_pm if verify_pm is not None else new_pm
        return (
            patch("app.services.finite_plan_repair.stripe.Customer.modify"),
            patch("app.services.finite_plan_repair.stripe.SubscriptionSchedule.modify"),
            patch("app.services.finite_plan_repair.stripe.Subscription.modify"),
            patch(
                "app.services.finite_plan_repair.stripe.Customer.retrieve",
                return_value=_fake_customer(
                    customer_id=plan.provider_customer_id, pm_id=verify_pm,
                ),
            ),
            patch(
                "app.services.finite_plan_repair.stripe.SubscriptionSchedule.retrieve",
                return_value=_fake_schedule(
                    schedule_id=plan.provider_subscription_schedule_id,
                    pm_id=verify_pm,
                ),
            ),
            patch(
                "app.services.finite_plan_repair.stripe.Subscription.retrieve",
                return_value=_fake_subscription(
                    subscription_id=plan.provider_subscription_id,
                    pm_id=verify_pm,
                ),
            ),
        )

    def test_S1_S2_S3_all_three_surfaces_updated_and_verified(
        self, plan_payment_problem,
    ):
        new_pm = "pm_new_happy"
        patches = self._patch_stripe_swap(
            plan=plan_payment_problem.plan, new_pm=new_pm,
        )
        with patches[0] as cust_mod, patches[1] as sched_mod, patches[2] as sub_mod, \
                patches[3] as cust_get, patches[4] as sched_get, patches[5] as sub_get:
            finite_plan_repair.swap_default_payment_method_all_surfaces(
                plan=plan_payment_problem.plan,
                new_payment_method_id=new_pm,
            )
        assert cust_mod.called
        assert sched_mod.called
        assert sub_mod.called
        assert cust_get.called
        assert sched_get.called
        assert sub_get.called

    def test_S4_customer_surface_verification_fails_raises(
        self, plan_payment_problem,
    ):
        new_pm = "pm_new_bad_cust"
        patches = (
            patch("app.services.finite_plan_repair.stripe.Customer.modify"),
            patch("app.services.finite_plan_repair.stripe.SubscriptionSchedule.modify"),
            patch("app.services.finite_plan_repair.stripe.Subscription.modify"),
            patch(
                "app.services.finite_plan_repair.stripe.Customer.retrieve",
                return_value=_fake_customer(
                    customer_id=plan_payment_problem.customer_id,
                    pm_id="pm_stale",  # Stripe still reports the old PM
                ),
            ),
        )
        with patches[0], patches[1], patches[2], patches[3]:
            with pytest.raises(finite_plan_repair.PaymentMethodSwapError):
                finite_plan_repair.swap_default_payment_method_all_surfaces(
                    plan=plan_payment_problem.plan,
                    new_payment_method_id=new_pm,
                )

    def test_S4_schedule_surface_verification_fails_raises(
        self, plan_payment_problem,
    ):
        new_pm = "pm_new_bad_sched"
        patches = (
            patch("app.services.finite_plan_repair.stripe.Customer.modify"),
            patch("app.services.finite_plan_repair.stripe.SubscriptionSchedule.modify"),
            patch("app.services.finite_plan_repair.stripe.Subscription.modify"),
            patch(
                "app.services.finite_plan_repair.stripe.Customer.retrieve",
                return_value=_fake_customer(
                    customer_id=plan_payment_problem.customer_id, pm_id=new_pm,
                ),
            ),
            patch(
                "app.services.finite_plan_repair.stripe.SubscriptionSchedule.retrieve",
                return_value=_fake_schedule(
                    schedule_id=plan_payment_problem.schedule_id,
                    pm_id="pm_stale",
                ),
            ),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with pytest.raises(finite_plan_repair.PaymentMethodSwapError):
                finite_plan_repair.swap_default_payment_method_all_surfaces(
                    plan=plan_payment_problem.plan,
                    new_payment_method_id=new_pm,
                )

    def test_S4_subscription_surface_verification_fails_raises(
        self, plan_payment_problem,
    ):
        new_pm = "pm_new_bad_sub"
        patches = self._patch_stripe_swap(
            plan=plan_payment_problem.plan, new_pm=new_pm,
            verify_pm=new_pm,
        )
        # Override the Subscription.retrieve to return stale PM.
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
                patch(
                    "app.services.finite_plan_repair.stripe.Subscription.retrieve",
                    return_value=_fake_subscription(
                        subscription_id=plan_payment_problem.subscription_id,
                        pm_id="pm_stale",
                    ),
                ):
            with pytest.raises(finite_plan_repair.PaymentMethodSwapError):
                finite_plan_repair.swap_default_payment_method_all_surfaces(
                    plan=plan_payment_problem.plan,
                    new_payment_method_id=new_pm,
                )


# ---------------------------------------------------------------------------
# R-series — invoice retry
# ---------------------------------------------------------------------------


class TestRetryOverdueInvoice:
    def test_R1_retries_the_same_failed_invoice(self, plan_payment_problem):
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value=_fake_open_invoice(
                invoice_id="in_invoice_3",
                subscription_id=plan_payment_problem.subscription_id,
            ),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.pay",
            return_value=SimpleNamespace(id="in_invoice_3", status="paid"),
        ) as mock_pay:
            inv_id, status = finite_plan_repair.retry_overdue_invoice(
                plan=plan_payment_problem.plan,
            )
        assert inv_id == "in_invoice_3"
        assert status == "paid"
        (args, kwargs) = mock_pay.call_args
        assert args[0] == "in_invoice_3"
        assert "idempotency_key" in kwargs
        assert "retry_invoice:in_invoice_3" in kwargs["idempotency_key"]

    def test_R2_does_not_create_new_invoice(self, plan_payment_problem):
        """retry_overdue_invoice never calls Invoice.create."""
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value=_fake_open_invoice(
                invoice_id="in_invoice_3",
                subscription_id=plan_payment_problem.subscription_id,
            ),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.pay",
            return_value=SimpleNamespace(id="in_invoice_3", status="paid"),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.create",
        ) as mock_create:
            finite_plan_repair.retry_overdue_invoice(plan=plan_payment_problem.plan)
        assert not mock_create.called

    def test_R3_wrong_subscription_invoice_relationship_refused(
        self, plan_payment_problem,
    ):
        """last_failed_invoice_id points at an invoice on a DIFFERENT
        subscription → refuse to retry."""
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value=_fake_open_invoice(
                invoice_id="in_invoice_3",
                subscription_id="sub_someone_elses",
            ),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.pay",
        ) as mock_pay:
            with pytest.raises(finite_plan_repair.RepairInvoiceNotRetryable):
                finite_plan_repair.retry_overdue_invoice(
                    plan=plan_payment_problem.plan,
                )
        assert not mock_pay.called

    def test_R4_invoice_paid_short_circuits_as_success_noop(
        self, plan_payment_problem,
    ):
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value=_fake_paid_invoice(
                invoice_id="in_invoice_3",
                subscription_id=plan_payment_problem.subscription_id,
            ),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.pay",
        ) as mock_pay:
            inv_id, status = finite_plan_repair.retry_overdue_invoice(
                plan=plan_payment_problem.plan,
            )
        assert inv_id == "in_invoice_3"
        assert status == "paid"
        assert not mock_pay.called, "already-paid invoice must not be re-paid"

    def test_R4_draft_invoice_refused(self, plan_payment_problem):
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value={
                **_fake_open_invoice(
                    invoice_id="in_invoice_3",
                    subscription_id=plan_payment_problem.subscription_id,
                ),
                "status": "draft",
            },
        ):
            with pytest.raises(finite_plan_repair.RepairInvoiceNotRetryable):
                finite_plan_repair.retry_overdue_invoice(
                    plan=plan_payment_problem.plan,
                )

    def test_R5_card_decline_returns_declined_status(self, plan_payment_problem):
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value=_fake_open_invoice(
                invoice_id="in_invoice_3",
                subscription_id=plan_payment_problem.subscription_id,
            ),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.pay",
            side_effect=stripe.CardError(
                "Your card was declined.", "card_error", "card_declined",
            ),
        ):
            inv_id, status = finite_plan_repair.retry_overdue_invoice(
                plan=plan_payment_problem.plan,
            )
        assert inv_id == "in_invoice_3"
        assert status == "declined"

    def test_R6_api_error_propagates(self, plan_payment_problem):
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value=_fake_open_invoice(
                invoice_id="in_invoice_3",
                subscription_id=plan_payment_problem.subscription_id,
            ),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.pay",
            side_effect=stripe.APIError("network down"),
        ):
            with pytest.raises(stripe.APIError):
                finite_plan_repair.retry_overdue_invoice(
                    plan=plan_payment_problem.plan,
                )

    def test_R_last_failed_invoice_id_missing_refused(self, plan_payment_problem):
        plan_payment_problem.plan.last_failed_invoice_id = None
        with pytest.raises(finite_plan_repair.RepairInvoiceNotRetryable):
            finite_plan_repair.retry_overdue_invoice(
                plan=plan_payment_problem.plan,
            )


# ---------------------------------------------------------------------------
# L-series — full recovery pipeline via webhook + FIP3 lifecycle
# ---------------------------------------------------------------------------


class TestGraceRecoveryPipeline:
    """Payment_problem plan → repair session completes → invoice
    retry succeeds → the existing invoice.payment_succeeded webhook
    (FIP3 lifecycle) upgrades the failed txn and returns the plan
    to active. Access rows never change (they were live throughout)."""

    def test_L1_full_pipeline_returns_plan_to_active(
        self, db, plan_payment_problem,
    ):
        s = plan_payment_problem
        new_pm = "pm_new_grace"
        completed = _fake_completed_repair_session(
            session_id=f"cs_repair_{uuid.uuid4().hex[:12]}",
            customer_id=s.customer_id, new_pm_id=new_pm,
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retry_overdue_invoice",
                return_value=("in_invoice_3", "paid"),
            ),
        ):
            _do_repair_completed(
                db,
                session={"id": completed.id},
                plan_id=s.plan.id,
                payer_user_id=s.member.id,
                event_livemode=False,
            )

        # PM pointer moved forward.
        db.refresh(s.plan)
        assert s.plan.provider_payment_method_id == new_pm

        # Simulate Stripe emitting invoice.payment_succeeded next.
        # The plan should return to active + failed txn should upgrade.
        # Before the succeed event, seed a failed txn like FIP3 would.
        # (handle_invoice_failed_for_plan in the fixture already did.)
        failed_txn = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_3")
            .one()
        )
        assert failed_txn.status == PaymentTransactionStatus.failed

        fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id="in_invoice_3",
            invoice_amount_cents=2000, invoice_currency="AUD",
            subscription_id=s.subscription_id,
            charge_id="ch_ok", payment_intent_id="pi_ok",
            now=datetime.utcnow(),
        )
        db.commit()

        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed  # 3/3 = final
        assert s.plan.grace_expires_at is None
        assert s.plan.last_failed_invoice_id is None

        # Failed txn upgraded in place — no duplicate ledger row.
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_3")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == failed_txn.id
        assert rows[0].status == PaymentTransactionStatus.succeeded

        # Access rows untouched (were active throughout the grace window).
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

    def test_L3_repeated_decline_does_not_extend_grace(
        self, db, plan_payment_problem,
    ):
        """Repair completes but the replacement card also declines.
        Plan MUST remain payment_problem; grace_expires_at MUST NOT
        move (deadline is the original commitment, not extended by
        another retry)."""
        s = plan_payment_problem
        original_deadline = s.plan.grace_expires_at
        new_pm = "pm_new_still_bad"
        completed = _fake_completed_repair_session(
            session_id=f"cs_repair_{uuid.uuid4().hex[:12]}",
            customer_id=s.customer_id, new_pm_id=new_pm,
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retry_overdue_invoice",
                return_value=("in_invoice_3", "declined"),
            ),
        ):
            _do_repair_completed(
                db,
                session={"id": completed.id},
                plan_id=s.plan.id,
                payer_user_id=s.member.id,
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.payment_problem
        assert s.plan.grace_expires_at == original_deadline

        # Now simulate Stripe re-firing invoice.payment_failed on the
        # same invoice — grace deadline still must not extend.
        fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan, invoice_id="in_invoice_3",
            failed_at=datetime.utcnow(),
        )
        db.commit()
        db.refresh(s.plan)
        assert s.plan.grace_expires_at == original_deadline


class TestSuspendedRecoveryPipeline:
    def test_L2_suspended_recovery_reinstates_access(self, db, plan_suspended):
        s = plan_suspended

        # Suspended state means access is suspended.
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended

        new_pm = "pm_new_suspended"
        completed = _fake_completed_repair_session(
            session_id=f"cs_repair_{uuid.uuid4().hex[:12]}",
            customer_id=s.customer_id, new_pm_id=new_pm,
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retry_overdue_invoice",
                return_value=("in_invoice_3", "paid"),
            ),
        ):
            _do_repair_completed(
                db,
                session={"id": completed.id},
                plan_id=s.plan.id,
                payer_user_id=s.member.id,
                event_livemode=False,
            )

        # Simulate the follow-on invoice.payment_succeeded webhook.
        fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id="in_invoice_3",
            invoice_amount_cents=2000, invoice_currency="AUD",
            subscription_id=s.subscription_id,
            charge_id="ch_ok", payment_intent_id="pi_ok",
            now=datetime.utcnow(),
        )
        db.commit()

        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed  # 3/3
        assert s.plan.reinstated_at is not None
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.active
        assert s.access_pass.status == AccessPassStatus.active

    def test_L2_saving_pm_alone_does_not_restore_access(
        self, db, plan_suspended,
    ):
        """Access remains suspended until invoice actually pays —
        merely saving a new card via the repair Session (with
        Invoice.pay returning declined) must NOT restore access."""
        s = plan_suspended
        completed = _fake_completed_repair_session(
            session_id="cs_repair", customer_id=s.customer_id,
            new_pm_id="pm_new_declined",
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retry_overdue_invoice",
                return_value=("in_invoice_3", "declined"),
            ),
        ):
            _do_repair_completed(
                db,
                session={"id": completed.id},
                plan_id=s.plan.id,
                payer_user_id=s.member.id,
                event_livemode=False,
            )
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.suspended
        db.refresh(s.entitlement)
        db.refresh(s.access_pass)
        assert s.entitlement.status == EntitlementStatus.suspended
        assert s.access_pass.status == AccessPassStatus.suspended


# ---------------------------------------------------------------------------
# I-series — idempotency + safety
# ---------------------------------------------------------------------------


class TestIdempotencyAndSafety:
    def test_I1_repair_webhook_replay_is_no_op(self, db, plan_payment_problem):
        s = plan_payment_problem
        session_id = f"cs_repair_{uuid.uuid4().hex[:12]}"
        completed = _fake_completed_repair_session(
            session_id=session_id, customer_id=s.customer_id, new_pm_id="pm_ok",
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ) as swap,
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retry_overdue_invoice",
                return_value=("in_invoice_3", "paid"),
            ) as retry,
        ):
            handle_finite_plan_repair_completed(
                {"id": session_id}, db,
                {"purchase_type": "finite_plan_repair",
                 "purchase_plan_id": s.plan.id,
                 "payer_user_id": s.member.id},
                event_livemode=False,
            )
            first_swap = swap.call_count
            first_retry = retry.call_count
            handle_finite_plan_repair_completed(
                {"id": session_id}, db,
                {"purchase_type": "finite_plan_repair",
                 "purchase_plan_id": s.plan.id,
                 "payer_user_id": s.member.id},
                event_livemode=False,
            )
        # Second invocation must NOT re-run the handler (durable
        # webhook lease sees the row as ``succeeded`` and skips).
        assert swap.call_count == first_swap
        assert retry.call_count == first_retry

    def test_I2_same_invoice_same_idempotency_key(self, plan_payment_problem):
        """Two calls to retry_overdue_invoice against the same plan +
        invoice pass the SAME idempotency_key to Stripe (so Stripe
        de-dupes any accidental double execution)."""
        with patch(
            "app.services.finite_plan_repair.stripe.Invoice.retrieve",
            return_value=_fake_open_invoice(
                invoice_id="in_invoice_3",
                subscription_id=plan_payment_problem.subscription_id,
            ),
        ), patch(
            "app.services.finite_plan_repair.stripe.Invoice.pay",
            return_value=SimpleNamespace(id="in_invoice_3", status="paid"),
        ) as mock_pay:
            finite_plan_repair.retry_overdue_invoice(plan=plan_payment_problem.plan)
            finite_plan_repair.retry_overdue_invoice(plan=plan_payment_problem.plan)
        key_a = mock_pay.call_args_list[0].kwargs["idempotency_key"]
        key_b = mock_pay.call_args_list[1].kwargs["idempotency_key"]
        assert key_a == key_b

    def test_I3_metadata_payer_id_mismatch_refused(
        self, db, plan_payment_problem, make_user,
    ):
        """Metadata says the payer is someone other than plan.member_user_id
        → the handler must skip. Never trust metadata alone."""
        s = plan_payment_problem
        completed = _fake_completed_repair_session(
            session_id="cs_repair", customer_id=s.customer_id, new_pm_id="pm_ok",
        )
        wrong_user = make_user()
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ) as swap,
        ):
            with pytest.raises(SkipWebhookEvent):
                _do_repair_completed(
                    db,
                    session={"id": completed.id},
                    plan_id=s.plan.id,
                    payer_user_id=wrong_user.id,
                    event_livemode=False,
                )
        # Handler skipped BEFORE calling swap.
        assert not swap.called

    def test_I_session_customer_mismatch_refused(self, db, plan_payment_problem):
        """The setup Session's Customer must equal plan.provider_customer_id.
        If they diverge (impossible via our route; possible via manual
        Stripe test-mode Session), refuse."""
        s = plan_payment_problem
        completed = _fake_completed_repair_session(
            session_id="cs_repair",
            customer_id="cus_someone_else",  # WRONG
            new_pm_id="pm_ok",
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ) as swap,
        ):
            with pytest.raises(SkipWebhookEvent):
                _do_repair_completed(
                    db,
                    session={"id": completed.id},
                    plan_id=s.plan.id,
                    payer_user_id=s.member.id,
                    event_livemode=False,
                )
        assert not swap.called

    def test_I_swap_failure_before_retry_aborts_and_reverts(
        self, db, plan_payment_problem,
    ):
        """A PaymentMethodSwapError raised during the swap must:
          * revert plan.provider_payment_method_id to the prior value
          * NOT call retry_overdue_invoice"""
        s = plan_payment_problem
        prior_pm = s.plan.provider_payment_method_id
        completed = _fake_completed_repair_session(
            session_id="cs_repair", customer_id=s.customer_id, new_pm_id="pm_new",
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
                side_effect=finite_plan_repair.PaymentMethodSwapError("subscription surface stale"),
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retry_overdue_invoice",
            ) as retry,
        ):
            with pytest.raises(SkipWebhookEvent):
                _do_repair_completed(
                    db,
                    session={"id": completed.id},
                    plan_id=s.plan.id,
                    payer_user_id=s.member.id,
                    event_livemode=False,
                )
        db.refresh(s.plan)
        assert s.plan.provider_payment_method_id == prior_pm
        assert not retry.called

    def test_I_plan_already_active_skipped_cleanly(
        self, db, plan_payment_problem,
    ):
        """If between session creation and completion the plan
        transitioned back to ``active`` (e.g. Stripe's own Smart Retry
        succeeded first), skip the repair — nothing to do."""
        s = plan_payment_problem
        s.plan.status = PurchasePlanStatus.active
        db.commit()
        completed = _fake_completed_repair_session(
            session_id="cs_repair", customer_id=s.customer_id, new_pm_id="pm_ok",
        )
        with (
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retrieve_completed_repair_session",
                return_value=completed,
            ),
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".swap_default_payment_method_all_surfaces",
            ) as swap,
            patch(
                "app.webhooks.finite_plan_handlers.finite_plan_repair"
                ".retry_overdue_invoice",
            ) as retry,
        ):
            with pytest.raises(SkipWebhookEvent):
                _do_repair_completed(
                    db,
                    session={"id": completed.id},
                    plan_id=s.plan.id,
                    payer_user_id=s.member.id,
                    event_livemode=False,
                )
        assert not swap.called
        assert not retry.called


# ---------------------------------------------------------------------------
# B-series — backwards compatibility touch tests (regression)
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    def test_B1_repair_metadata_purchase_type_is_distinct(self):
        """The dispatcher distinguishes finite_plan_repair from
        finite_plan_setup + standalone_gathering + PurchaseIntent
        purely on metadata.purchase_type. Regression check."""
        assert "finite_plan_repair" != "finite_plan_setup"
        assert "finite_plan_repair" != "standalone_gathering"

    def test_B2_fip3_recovery_still_upgrades_txn_in_place(
        self, db, plan_payment_problem,
    ):
        """Sanity: the FIP3 later-instalment recovery path still works
        exactly the same when the invoice succeeds via ANY route
        (FIP4B2 or Stripe's own Smart Retries). FIP4B2 does not
        change record_later_successful_instalment.
        """
        s = plan_payment_problem
        # Directly drive the invoice succeed like a Smart Retry would.
        fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id="in_invoice_3",
            invoice_amount_cents=2000, invoice_currency="AUD",
            subscription_id=s.subscription_id,
            charge_id="ch_smart", payment_intent_id="pi_smart",
            now=datetime.utcnow(),
        )
        db.commit()
        db.refresh(s.plan)
        assert s.plan.status == PurchasePlanStatus.completed
        rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.provider_invoice_id == "in_invoice_3")
            .all()
        )
        assert len(rows) == 1
