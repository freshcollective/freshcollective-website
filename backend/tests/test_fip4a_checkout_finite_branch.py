"""FIP4A — /api/checkout/pathway routes finite plans correctly.

Previously the legacy pathway wrapper hit ``resolve_option_and_schedule``
for any schedule type, which raises a 503 for
``recurring_installments``. FIP4A adds a schedule-type peek + a
``_schedule_is_member_checkoutable`` gate + a branch into
``start_finite_plan_setup``, mirroring the unified endpoint.

These tests lock in the routing:

  * gate OFF → 503, no PurchasePlan created
  * gate ON + valid finite plan → PurchasePlan created, Checkout
    Session URL returned, orchestrator called
  * gate ON + draft schedule → 503
  * gate ON + structurally invalid finite schedule → 503
  * gate ON + Gathering-bundle option → 503
  * gate ON + duplicate blocking PurchasePlan (Rule D) → 409
  * pay-in-full route through the SAME endpoint stays green
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.checkout.routes import create_pathway_checkout_session
from app.checkout.schemas import PathwayCheckoutRequest
from app.core.config import settings
from app.models.payment_option import (
    PaymentOption, PaymentOptionStatus, PaymentOptionType,
)
from app.models.payment_option_grant import (
    GRANT_KIND_GATHERING, GRANT_KIND_PATHWAY, PaymentOptionGrant,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import Pathway, PathwayType
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _mock_stripe_session(session_id="cs_test_x"):
    return SimpleNamespace(
        id=session_id,
        url="https://checkout.stripe.test/finite",
    )


@pytest.fixture
def stripe_configured(monkeypatch):
    """``settings.stripe_enabled`` is a computed property that
    checks BOTH secret + webhook secret. Set both so the enabled
    guard passes. (Mirrors the fixture in test_checkout_unified.py.)"""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


@pytest.fixture
def gate_on():
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


@pytest.fixture
def gate_off():
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", False,
    ):
        yield


@pytest.fixture
def finite_pathway_option(db, make_space, make_user):
    """Locked pathway + PO with a valid recurring_installments schedule
    granting that pathway. Buyer is separate."""
    space = make_space()
    pw = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Finite test pathway",
        status="active",
        access_type="one_time",
        pricing_mode="payment_options",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(pw); db.flush()

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        pathway_id=pw.id,
        attaches_to_kind="pathway", attaches_to_id=pw.id,
        name="Test PO",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=6000, currency="AUD",
        grants_pathway_id=pw.id,
    )
    db.add(opt); db.flush()
    db.add(PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=opt.id,
        grant_kind=GRANT_KIND_PATHWAY, pathway_id=pw.id,
    ))
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Weekly x 3",
        schedule_type="recurring_installments", status="published",
        installment_amount_cents=2000, installment_count=3,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=6000, currency="AUD",
    )
    db.add(sched); db.flush()

    buyer = make_user()
    return SimpleNamespace(space=space, pathway=pw, option=opt, schedule=sched, buyer=buyer)


def _req(*, pathway_id, po_id, sched_id):
    return PathwayCheckoutRequest(
        pathway_id=pathway_id,
        payment_option_id=po_id,
        payment_option_schedule_id=sched_id,
        success_url="https://local/s", cancel_url="https://local/c",
    )


# ---------------------------------------------------------------------------
# Gate OFF: recurring returns 503
# ---------------------------------------------------------------------------


class TestGateOffBlocksRecurring:
    def test_gate_off_returns_503(
        self, db, stripe_configured, gate_off, finite_pathway_option,
    ):
        s = finite_pathway_option
        with pytest.raises(HTTPException) as exc:
            create_pathway_checkout_session(
                _req(pathway_id=s.pathway.id, po_id=s.option.id, sched_id=s.schedule.id),
                current_user=s.buyer, db=db,
            )
        assert exc.value.status_code == 503
        # No PurchasePlan minted.
        assert db.query(PurchasePlan).filter(PurchasePlan.member_user_id == s.buyer.id).count() == 0


# ---------------------------------------------------------------------------
# Gate ON: valid finite plan → PurchasePlan + Session URL
# ---------------------------------------------------------------------------


class TestGateOnValidFinitePlanRouting:
    def test_gate_on_creates_plan_and_returns_setup_session(
        self, db, stripe_configured, gate_on, finite_pathway_option,
    ):
        s = finite_pathway_option
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_test_finite")
            res = create_pathway_checkout_session(
                _req(pathway_id=s.pathway.id, po_id=s.option.id, sched_id=s.schedule.id),
                current_user=s.buyer, db=db,
            )
        assert res.checkout_url == "https://checkout.stripe.test/finite"

        plans = db.query(PurchasePlan).filter(PurchasePlan.member_user_id == s.buyer.id).all()
        assert len(plans) == 1
        plan = plans[0]
        assert plan.status == PurchasePlanStatus.pending_setup
        assert plan.payment_option_id == s.option.id
        assert plan.payment_option_schedule_id == s.schedule.id
        assert plan.installment_amount_cents == 2000
        assert plan.installments_expected == 3

        # Stripe Session call metadata carries the FIP2 route
        # discriminator + purchase_plan_id.
        session_kwargs = m.call_args.kwargs
        assert session_kwargs.get("mode") == "setup"
        assert session_kwargs["metadata"]["purchase_type"] == "finite_plan_setup"
        assert session_kwargs["metadata"]["purchase_plan_id"] == plan.id


# ---------------------------------------------------------------------------
# Gate ON: eligibility failures still refuse
# ---------------------------------------------------------------------------


class TestGateOnEligibilityRefuses:
    def test_draft_schedule_returns_503_even_with_gate_on(
        self, db, stripe_configured, gate_on, finite_pathway_option,
    ):
        s = finite_pathway_option
        s.schedule.status = "draft"
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_pathway_checkout_session(
                _req(pathway_id=s.pathway.id, po_id=s.option.id, sched_id=s.schedule.id),
                current_user=s.buyer, db=db,
            )
        assert exc.value.status_code == 503

    def test_invalid_finite_schedule_returns_503_even_with_gate_on(
        self, db, stripe_configured, gate_on, finite_pathway_option,
    ):
        s = finite_pathway_option
        s.schedule.installment_count = 1  # < 2 = invalid
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_pathway_checkout_session(
                _req(pathway_id=s.pathway.id, po_id=s.option.id, sched_id=s.schedule.id),
                current_user=s.buyer, db=db,
            )
        assert exc.value.status_code == 503

    def test_gathering_grant_bundle_returns_503_even_with_gate_on(
        self, db, stripe_configured, gate_on, finite_pathway_option,
        make_event,
    ):
        s = finite_pathway_option
        # Add an unsupported Gathering grant to the bundle. The
        # ``payment_option_grants_target_matches_kind`` CHECK
        # requires ``event_id`` for grant_kind='gathering'; create a
        # real Event to satisfy the constraint.
        ev = make_event(space=s.space)
        db.add(PaymentOptionGrant(
            id=_uid("pog_g"),
            payment_option_id=s.option.id,
            grant_kind=GRANT_KIND_GATHERING,
            event_id=ev.id,
        ))
        db.flush()
        db.refresh(s.option)
        with pytest.raises(HTTPException) as exc:
            create_pathway_checkout_session(
                _req(pathway_id=s.pathway.id, po_id=s.option.id, sched_id=s.schedule.id),
                current_user=s.buyer, db=db,
            )
        assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# Rule D — duplicate plan blocks (409)
# ---------------------------------------------------------------------------


class TestRuleDStillBlocks:
    def test_active_plan_on_same_option_blocks_second_start(
        self, db, stripe_configured, gate_on, finite_pathway_option,
    ):
        s = finite_pathway_option
        # Seed an active plan for the same (buyer, option).
        now = datetime.utcnow()
        prior = PurchasePlan(
            id=_uid("pplan_prior"),
            member_user_id=s.buyer.id,
            payment_option_id=s.option.id,
            payment_option_schedule_id=s.schedule.id,
            space_id=s.space.id,
            status=PurchasePlanStatus.active,
            currency="AUD",
            installment_amount_cents=2000,
            installments_expected=3, installments_paid=1,
            total_expected_cents=6000,
            stripe_interval="week", stripe_interval_count=1,
            stripe_mode="test",
            snapshot_grants_json={"version": 1, "entitlements": [], "access_passes": [], "bookings": []},
            created_at=now, updated_at=now,
        )
        db.add(prior); db.commit()

        with pytest.raises(HTTPException) as exc:
            create_pathway_checkout_session(
                _req(pathway_id=s.pathway.id, po_id=s.option.id, sched_id=s.schedule.id),
                current_user=s.buyer, db=db,
            )
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Pay-in-full regression — same route, unchanged
# ---------------------------------------------------------------------------


class TestPayInFullRegression:
    def test_pay_in_full_route_still_works_with_gate_on(
        self, db, make_space, make_user, stripe_configured, gate_on,
    ):
        """Pay-in-full checkout continues to work under FIP4A. The
        finite-plan branch must not accidentally intercept it."""
        space = make_space()
        buyer = make_user()
        pw = Pathway(
            id=_uid("pw"), space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}", title="PIF path",
            status="active", access_type="one_time",
            price_cents=15000,
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pw); db.flush()
        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            pathway_id=pw.id,
            attaches_to_kind="pathway", attaches_to_id=pw.id,
            name="PIF Option",
            payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=15000, currency="AUD",
            grants_pathway_id=pw.id,
        )
        db.add(opt); db.flush()
        db.add(PaymentOptionGrant(
            id=_uid("pog"), payment_option_id=opt.id,
            grant_kind=GRANT_KIND_PATHWAY, pathway_id=pw.id,
        ))
        sched = PaymentOptionSchedule(
            id=_uid("sched"), payment_option_id=opt.id,
            name="Pay in full", schedule_type="pay_in_full",
            status="published",
            total_amount_cents=15000, currency="AUD",
        )
        db.add(sched); db.commit()

        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_stripe_session("cs_test_pif")
            res = create_pathway_checkout_session(
                _req(pathway_id=pw.id, po_id=opt.id, sched_id=sched.id),
                current_user=buyer, db=db,
            )
        assert res.checkout_url == "https://checkout.stripe.test/finite"
        # No PurchasePlan (pay-in-full path doesn't create one).
        assert db.query(PurchasePlan).count() == 0
