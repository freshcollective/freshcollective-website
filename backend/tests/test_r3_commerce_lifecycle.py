"""R3 — commerce + finite payment-plan lifecycle emails.

Five events, all under ``TOPIC_PURCHASES`` (default-enabled + locked
in migration 097):

* ``purchase.completed`` — single-payment OR FIP first-instalment
* ``payment.instalment_failed`` — FIP ``active → payment_problem``
* ``access.suspended``          — FIP ``payment_problem → suspended``
* ``payment.recovered``         — FIP ``{payment_problem, suspended} → active``
* ``purchase.plan_completed``   — FIP ``* → completed``

Each test verifies:
  * the emit fires on the genuine transition
  * the event does NOT fire on replay / no-op / cascading failures
  * the destination URL matches the audit decisions (Option A deep-link)
  * the template branches on payment_mode / was_suspended
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

# SQLAlchemy relationship registration bootstrap.
import app.models.community_care  # noqa: F401
import app.main  # noqa: F401 — bootstraps registries + providers

from app.comms.categories import (
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
)
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.comms.rollout import _route_event_bg, is_event_live
from app.models.access_grant_record import AccessGrantRecord  # noqa: F401
from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PaymentProvider,
    PayoutStatus,
)
from app.models.payment_option import PaymentOption, PaymentOptionStatus, PaymentOptionType
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    EventSeries,
    Pathway,
    PathwayEntitlement,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.services import access_grant_records as _agr
from app.services import finite_plan_lifecycle as fpl
from app.services.purchase_fulfilment import (
    AccessPassIntent,
    EntitlementIntent,
    FulfilmentIntent,
    serialise_intent,
)


# ---------------------------------------------------------------------------
# Comms harness — mirrors R2A/R2B pattern
# ---------------------------------------------------------------------------


def _run_route_event_bg(db, event_id: str) -> None:
    class _NoClose:
        def __init__(self, real):
            self._real = real
        def __getattr__(self, name):
            return getattr(self._real, name)
        def close(self):
            pass

    from app.comms.providers import get as _get_provider
    inapp = _get_provider("in_app")
    original_factory = inapp._session_factory  # type: ignore[attr-defined]
    inapp._session_factory = lambda: _NoClose(db)  # type: ignore[attr-defined]
    try:
        with patch("app.comms.rollout.SessionLocal", return_value=_NoClose(db)):
            _route_event_bg(event_id, "live")
    finally:
        inapp._session_factory = original_factory  # type: ignore[attr-defined]


class _SDKSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict | None]] = []
        self.next_id = 1

    def __call__(self, params, options=None):
        self.calls.append((dict(params), dict(options) if options else None))
        msg_id = f"resend-r3-{self.next_id}"
        self.next_id += 1
        return {"id": msg_id}


@pytest.fixture
def sdk_spy():
    spy = _SDKSpy()
    with patch("resend.Emails.send", side_effect=spy), \
         patch("resend.api_key", create=True), \
         patch(
             "app.services.email_service.email_service.send",
             new_callable=MagicMock,
         ):
        yield spy


def _sanity_r3_events_live():
    for et in (
        "purchase.completed",
        "payment.instalment_failed",
        "access.suspended",
        "payment.recovered",
        "purchase.plan_completed",
    ):
        assert is_event_live(et), (
            f"R3 suite requires {et} to be live via COMMS_LIVE_TOPICS "
            "(topic 'purchases' should be in the default)."
        )


# ---------------------------------------------------------------------------
# Fixture — a FIP that's past its first invoice (installment 1/3 paid),
# attached to a Pathway. Matches the compact test_fip3_lifecycle pattern.
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def active_pathway_plan(db, make_user, make_space):
    member = make_user(email=f"m-{uuid.uuid4().hex[:8]}@example.com", name="Alex Test")
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    pathway = Pathway(
        id=_uid("path"), space_id=space.id,
        slug=f"p-{uuid.uuid4().hex[:8]}",
        title="Life in Alignment", status="active",
    )
    db.add(pathway)
    db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="pathway", attaches_to_id=pathway.id,
        name="Life in Alignment",
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
    db.add_all([opt, sched])
    db.flush()

    now = datetime.utcnow()
    intent = FulfilmentIntent(
        entitlements=(EntitlementIntent(pathway_id=pathway.id, ends_at=None),),
        access_passes=(),
    )
    subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    plan = PurchasePlan(
        id=_uid("pplan"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        creator_user_id=creator.id,
        status=PurchasePlanStatus.active,
        currency="AUD",
        installment_amount_cents=2000,
        installments_expected=3,
        installments_paid=1,
        total_expected_cents=6000,
        stripe_interval="week", stripe_interval_count=1,
        platform_fee_basis_points=800,
        provider_customer_id=f"cus_test_{uuid.uuid4().hex[:8]}",
        provider_subscription_schedule_id=f"sub_sched_{uuid.uuid4().hex[:8]}",
        provider_subscription_id=subscription_id,
        stripe_mode="test",
        snapshot_grants_json=serialise_intent(intent),
        activated_at=now,
    )
    db.add(plan)
    db.flush()

    # A pre-existing first-instalment PathwayEntitlement so recovery
    # after suspension has something to reinstate.
    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now,
        purchase_plan_id=plan.id,
        created_at=now, updated_at=now,
    )
    db.add(ent)
    _agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway.id,
        source_type=_agr.SOURCE_PLAN_PAYMENT,
        source_purchase_plan_id=plan.id,
        source_payment_transaction_id=None,
        granted_at=now,
    )
    db.commit()
    return SimpleNamespace(
        member=member, creator=creator, space=space, pathway=pathway,
        option=opt, schedule=sched, plan=plan, entitlement=ent,
        subscription_id=subscription_id,
    )


def _invoice(*, invoice_id, subscription_id, amount, currency="aud", status="paid"):
    return {
        "id": invoice_id, "subscription": subscription_id,
        "amount_paid": amount, "total": amount,
        "currency": currency, "status": status,
        "charge": f"ch_test_{uuid.uuid4().hex[:8]}",
        "payment_intent": f"pi_test_{uuid.uuid4().hex[:8]}",
    }


# ===========================================================================
# 1. Instalment failure → payment_problem
# ===========================================================================


class TestInstalmentFailed:
    def test_failure_transition_emits_and_dispatches(self, db, active_pathway_plan, sdk_spy):
        _sanity_r3_events_live()
        s = active_pathway_plan
        outcome = fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id=f"in_fail_{uuid.uuid4().hex[:6]}",
            failed_at=datetime.utcnow(),
        )
        db.commit()
        assert outcome.transitioned_to == "payment_problem"
        assert outcome.comms_event is not None
        assert outcome.grace_expires_at is not None
        # Payload carries the grace deadline for the template.
        assert outcome.comms_event.payload["grace_expires_at"]
        assert "/spaces/" in outcome.comms_event.payload["repair_url"]
        assert f"/pathways/{s.pathway.slug}" in outcome.comms_event.payload["repair_url"]

        _run_route_event_bg(db, outcome.comms_event.id)
        assert len(sdk_spy.calls) == 1
        params, _ = sdk_spy.calls[0]
        assert params["to"] == [s.member.email]
        assert "There" in params["subject"] and "problem" in params["subject"]
        # Member-facing copy: no Stripe internals.
        html = params["html"]
        assert "invoice" not in html.lower()
        assert "SubscriptionSchedule" not in html
        assert "PaymentIntent" not in html
        assert "Fix payment" in html
        assert f"/pathways/{s.pathway.slug}" in html

    def test_replay_of_same_failed_invoice_does_not_re_emit(self, db, active_pathway_plan, sdk_spy):
        _sanity_r3_events_live()
        s = active_pathway_plan
        inv_id = f"in_fail_{uuid.uuid4().hex[:6]}"
        first = fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan, invoice_id=inv_id, failed_at=datetime.utcnow(),
        )
        db.commit()
        assert first.comms_event is not None
        _run_route_event_bg(db, first.comms_event.id)
        assert len(sdk_spy.calls) == 1

        # Replay — same invoice, plan already in payment_problem.
        second = fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan, invoice_id=inv_id, failed_at=datetime.utcnow(),
        )
        db.commit()
        assert second.transitioned_to is None
        assert second.comms_event is None
        assert len(sdk_spy.calls) == 1  # unchanged

    def test_cascading_failure_on_different_invoice_does_not_re_emit(self, db, active_pathway_plan, sdk_spy):
        """A later failure on a fresh invoice while still in the same
        grace window preserves the original grace_expires_at and does
        NOT re-notify the member — one payment-problem email per grace
        episode."""
        _sanity_r3_events_live()
        s = active_pathway_plan
        first = fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id=f"in_fail_a_{uuid.uuid4().hex[:6]}",
            failed_at=datetime.utcnow(),
        )
        db.commit()
        original_grace = s.plan.grace_expires_at
        assert first.comms_event is not None
        _run_route_event_bg(db, first.comms_event.id)
        assert len(sdk_spy.calls) == 1

        second = fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id=f"in_fail_b_{uuid.uuid4().hex[:6]}",
            failed_at=datetime.utcnow(),
        )
        db.commit()
        assert second.transitioned_to is None
        assert second.comms_event is None
        assert s.plan.grace_expires_at == original_grace  # deadline preserved
        assert len(sdk_spy.calls) == 1


# ===========================================================================
# 2. Suspension (grace elapsed)
# ===========================================================================


class TestAccessSuspended:
    def test_suspension_transition_emits_and_dispatches(self, db, active_pathway_plan, sdk_spy):
        _sanity_r3_events_live()
        s = active_pathway_plan
        # First open the grace window.
        fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            failed_at=datetime.utcnow() - timedelta(days=8),
        )
        db.commit()
        # Force-elapse the grace window and let the reconciler suspend.
        s.plan.grace_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.flush()
        outcomes = fpl.sweep_expired_grace_plans(db, now=datetime.utcnow())
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.comms_event is not None
        # Access is now paused — assertion mirrors the R3 template promise.
        _run_route_event_bg(db, outcome.comms_event.id)
        assert len(sdk_spy.calls) == 1
        params, _ = sdk_spy.calls[0]
        assert params["to"] == [s.member.email]
        assert "paused" in params["subject"].lower() or "access" in params["subject"].lower()
        assert "Fix payment" in params["html"]


# ===========================================================================
# 3. Recovery — inside grace vs. after suspension
# ===========================================================================


class TestPaymentRecovered:
    def test_recovery_during_grace_emits_not_was_suspended(self, db, active_pathway_plan, sdk_spy):
        _sanity_r3_events_live()
        s = active_pathway_plan
        fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            failed_at=datetime.utcnow(),
        )
        db.commit()
        assert s.plan.status == PurchasePlanStatus.payment_problem

        outcome = fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id=f"in_ok_{uuid.uuid4().hex[:6]}",
            invoice_amount_cents=2000, invoice_currency="aud",
            subscription_id=s.subscription_id,
            charge_id=None, payment_intent_id=None,
            now=datetime.utcnow(),
        )
        db.commit()
        assert outcome.transitioned_to == "active"
        assert outcome.comms_event is not None
        assert outcome.comms_event.payload["was_suspended"] is False

        _run_route_event_bg(db, outcome.comms_event.id)
        assert len(sdk_spy.calls) == 1
        html = sdk_spy.calls[0][0]["html"]
        assert "remains active" in html
        assert "restored" not in html

    def test_recovery_after_suspension_emits_was_suspended(self, db, active_pathway_plan, sdk_spy):
        _sanity_r3_events_live()
        s = active_pathway_plan
        # Open grace + force-suspend.
        fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            failed_at=datetime.utcnow() - timedelta(days=8),
        )
        db.commit()
        fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
        db.commit()
        assert s.plan.status == PurchasePlanStatus.suspended

        outcome = fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id=f"in_ok_{uuid.uuid4().hex[:6]}",
            invoice_amount_cents=2000, invoice_currency="aud",
            subscription_id=s.subscription_id,
            charge_id=None, payment_intent_id=None,
            now=datetime.utcnow(),
        )
        db.commit()
        assert outcome.transitioned_to == "active"
        assert outcome.comms_event is not None
        assert outcome.comms_event.payload["was_suspended"] is True

        _run_route_event_bg(db, outcome.comms_event.id)
        assert len(sdk_spy.calls) == 1
        html = sdk_spy.calls[0][0]["html"]
        assert "active again" in html
        assert "remains active" not in html


# ===========================================================================
# 4. Completion — final scheduled instalment
# ===========================================================================


class TestPlanCompleted:
    def test_final_instalment_emits_plan_completed_not_recovery(self, db, active_pathway_plan, sdk_spy):
        _sanity_r3_events_live()
        s = active_pathway_plan
        # Advance to installment 2 to leave one payment remaining.
        fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            invoice_amount_cents=2000, invoice_currency="aud",
            subscription_id=s.subscription_id,
            charge_id=None, payment_intent_id=None,
            now=datetime.utcnow(),
        )
        db.commit()
        assert s.plan.installments_paid == 2

        # Final instalment.
        outcome = fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            invoice_amount_cents=2000, invoice_currency="aud",
            subscription_id=s.subscription_id,
            charge_id=None, payment_intent_id=None,
            now=datetime.utcnow(),
        )
        db.commit()
        assert s.plan.status == PurchasePlanStatus.completed
        assert outcome.comms_event is not None
        assert outcome.comms_event.event_type == "purchase.plan_completed"

        _run_route_event_bg(db, outcome.comms_event.id)
        assert len(sdk_spy.calls) == 1
        params, _ = sdk_spy.calls[0]
        assert "complete" in params["subject"].lower()
        html = params["html"]
        assert "final payment" in html
        assert "no further scheduled payments" in html.lower()
        # Must not promise perpetual access.
        assert "lifetime" not in html.lower()
        assert "forever" not in html.lower()

    def test_final_instalment_recovering_from_suspended_still_completes(self, db, active_pathway_plan, sdk_spy):
        """Completion supersedes recovery when the final payment lands
        from a suspended plan. Only the plan_completed event fires."""
        _sanity_r3_events_live()
        s = active_pathway_plan
        # Advance to 2/3.
        fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            invoice_amount_cents=2000, invoice_currency="aud",
            subscription_id=s.subscription_id,
            charge_id=None, payment_intent_id=None,
            now=datetime.utcnow(),
        )
        db.commit()
        # Fail + suspend.
        fpl.handle_invoice_failed_for_plan(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            failed_at=datetime.utcnow() - timedelta(days=8),
        )
        db.commit()
        fpl.suspend_plan_now(db, plan=s.plan, now=datetime.utcnow())
        db.commit()
        # Final payment lands from suspended.
        outcome = fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id=f"in_final_{uuid.uuid4().hex[:6]}",
            invoice_amount_cents=2000, invoice_currency="aud",
            subscription_id=s.subscription_id,
            charge_id=None, payment_intent_id=None,
            now=datetime.utcnow(),
        )
        db.commit()
        assert s.plan.status == PurchasePlanStatus.completed
        assert outcome.comms_event is not None
        assert outcome.comms_event.event_type == "purchase.plan_completed"


# ===========================================================================
# 5. purchase.completed does NOT fire for later instalments
# ===========================================================================


class TestNoPurchaseCompletedOnLaterInstalment:
    def test_later_instalment_success_produces_no_purchase_completed(self, db, active_pathway_plan, sdk_spy):
        """Later successful instalments emit at most ``payment.recovered``
        or ``purchase.plan_completed`` — never ``purchase.completed``
        (which is reserved for single-payment + FIP first-instalment)."""
        _sanity_r3_events_live()
        s = active_pathway_plan
        outcome = fpl.record_later_successful_instalment(
            db, plan=s.plan,
            invoice_id=f"in_{uuid.uuid4().hex[:6]}",
            invoice_amount_cents=2000, invoice_currency="aud",
            subscription_id=s.subscription_id,
            charge_id=None, payment_intent_id=None,
            now=datetime.utcnow(),
        )
        db.commit()
        # No transition (active → active) → no event.
        assert outcome.transitioned_to is None
        assert outcome.comms_event is None
        assert len(sdk_spy.calls) == 0
        # And nothing of the wrong type was persisted.
        n = db.query(CommunicationEvent).filter(
            CommunicationEvent.event_type == "purchase.completed",
            CommunicationEvent.actor_user_id == s.member.id,
        ).count()
        assert n == 0


# ===========================================================================
# 6. purchase.completed template — payment_mode branch
# ===========================================================================


class TestPurchaseCompletedTemplateBranches:
    """Direct template rendering — the resolver + emit paths are covered
    above and by upstream tests; this class checks the copy split."""

    def _render(self, *, payment_mode: str, installments=None):
        from app.comms.templates.registry import get_template_for
        from app.comms.routing.resolver import ResolvedRecipient
        tmpl = get_template_for("purchase.completed", CHANNEL_EMAIL_TRANSACTIONAL)
        ctx = {
            "first_name": "Ada",
            "experience_name": "Life in Alignment",
            "member_url": "http://localhost:3000/spaces/x/pathways/y",
            "payment_mode": payment_mode,
            "amount_cents": 2000,
            "currency": "AUD",
        }
        if installments is not None:
            ctx["installments_paid"], ctx["installments_expected"] = installments
        rp = ResolvedRecipient(
            user_id="u", role_in_event="buyer", human_reason="", template_context=ctx,
        )
        return tmpl.render(None, None, rp)

    def test_single_payment_variant(self):
        r = self._render(payment_mode="single")
        assert "Life in Alignment" in r.subject
        assert "purchase" in r.subject.lower()
        html = r.body_html
        assert "Thanks for your purchase" in html
        assert "AUD 20.00" in html
        assert "payment plan" not in html.lower()

    def test_plan_variant_shows_progress_and_first_payment_wording(self):
        r = self._render(payment_mode="plan", installments=(1, 3))
        assert "payment plan" in r.subject.lower()
        html = r.body_html
        assert "first payment" in html
        assert "Payment 1 of 3" in html
        assert "AUD 20.00" in html
