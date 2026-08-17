"""FIP4A — member checkoutability rules for finite payment plans.

Locks in ``spaces.routes._schedule_is_member_checkoutable`` behaviour:

  * published pay_in_full is always checkoutable
  * published recurring_installments is checkoutable IFF the global
    ``FINITE_PLAN_MEMBER_CHECKOUT_ENABLED`` flag is True AND the
    schedule row is structurally valid
  * draft schedules (any type) are not checkoutable
  * invalid finite schedules (bad cadence / count / amount) are
    not checkoutable even with the gate ON
  * duplicate active-plan guard is enforced at the checkout
    endpoint level (Rule D), unaffected by this helper's return

Also confirms the pay-in-full path stays green under all gate
positions so we cannot regress the always-live path with a
finite-plan config change.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES,
    GRANT_KIND_GATHERING,
    GRANT_KIND_PATHWAY,
)
from app.spaces.routes import (
    _option_supports_finite_member_checkout,
    _schedule_is_member_checkoutable,
)


def _opt(*, grants=()) -> SimpleNamespace:
    """Duck-typed PaymentOption stand-in with a grants list."""
    return SimpleNamespace(grants=list(grants))


def _grant(kind: str) -> SimpleNamespace:
    return SimpleNamespace(grant_kind=kind)


def _sched(
    *,
    status: str = "published",
    schedule_type: str = "recurring_installments",
    installment_amount_cents: int = 2000,
    installment_count: int = 3,
    stripe_interval: str = "week",
    stripe_interval_count: int = 1,
    currency: str = "AUD",
    total_amount_cents: int | None = 6000,
) -> SimpleNamespace:
    """Structurally valid schedule row (as a duck-typed namespace).
    The helper only reads attributes off the object; a real row from
    the DB fixture set works identically."""
    return SimpleNamespace(
        id=f"sched_{uuid.uuid4().hex[:8]}",
        status=status,
        schedule_type=schedule_type,
        installment_amount_cents=installment_amount_cents,
        installment_count=installment_count,
        stripe_interval=stripe_interval,
        stripe_interval_count=stripe_interval_count,
        currency=currency,
        total_amount_cents=total_amount_cents,
    )


# ---------------------------------------------------------------------------
# Pay-in-full stays always-live
# ---------------------------------------------------------------------------


class TestPayInFullAlwaysCheckoutable:
    def test_pay_in_full_published_checkoutable_regardless_of_flag(self):
        s = _sched(schedule_type="pay_in_full", total_amount_cents=60000)
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", False):
            assert _schedule_is_member_checkoutable(s, _opt()) is True
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is True

    def test_pay_in_full_draft_not_checkoutable(self):
        s = _sched(schedule_type="pay_in_full", status="draft")
        assert _schedule_is_member_checkoutable(s) is False


# ---------------------------------------------------------------------------
# Finite plan gating
# ---------------------------------------------------------------------------


class TestFinitePlanGating:
    def test_finite_published_valid_but_gate_off_not_checkoutable(self):
        s = _sched()
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", False):
            assert _schedule_is_member_checkoutable(s, _opt()) is False

    def test_finite_published_valid_and_gate_on_is_checkoutable(self):
        s = _sched()
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is True

    def test_finite_draft_not_checkoutable_even_with_gate_on(self):
        s = _sched(status="draft")
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is False


# ---------------------------------------------------------------------------
# Structural validation gates the finite path
# ---------------------------------------------------------------------------


class TestFiniteStructuralValidity:
    def test_finite_with_zero_installment_amount_not_checkoutable(self):
        s = _sched(installment_amount_cents=0)
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is False

    def test_finite_with_installment_count_below_two_not_checkoutable(self):
        s = _sched(installment_count=1)
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is False

    def test_finite_with_unsupported_cadence_not_checkoutable(self):
        # e.g. yearly is not in the (week×1, week×2, month×1) set
        s = _sched(stripe_interval="year", stripe_interval_count=1)
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is False

    def test_finite_with_total_mismatch_not_checkoutable(self):
        # 2000 × 3 = 6000, not 5000
        s = _sched(total_amount_cents=5000)
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is False


# ---------------------------------------------------------------------------
# Manual schedule type + other unsupported types stay off
# ---------------------------------------------------------------------------


class TestOtherScheduleTypes:
    def test_manual_never_checkoutable(self):
        s = _sched(schedule_type="manual")
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, _opt()) is False


# ---------------------------------------------------------------------------
# Grant-bundle support (FIP4A correction) — unsupported bundles hide
# ---------------------------------------------------------------------------


class TestFiniteGrantBundleSupport:
    """The member surface must never advertise a finite plan whose
    PaymentOption grant bundle would 4xx at ``/api/checkout``. Today
    the unified fulfilment path refuses ``gathering`` grants (see
    ``services/purchase_fulfilment.py::resolve_intent_from_grants``);
    hiding those options prevents member-visible dead ends."""

    def test_valid_pathway_finite_plan_gate_on_is_checkoutable(self):
        s = _sched()
        opt = _opt(grants=[_grant(GRANT_KIND_PATHWAY)])
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, opt) is True

    def test_valid_series_finite_plan_gate_on_is_checkoutable(self):
        s = _sched()
        opt = _opt(grants=[_grant(GRANT_KIND_EVENT_SERIES)])
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, opt) is True

    def test_valid_mixed_pathway_and_series_finite_plan_is_checkoutable(self):
        s = _sched()
        opt = _opt(grants=[
            _grant(GRANT_KIND_PATHWAY), _grant(GRANT_KIND_EVENT_SERIES),
        ])
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, opt) is True

    def test_option_with_gathering_grant_is_not_checkoutable(self):
        s = _sched()
        opt = _opt(grants=[_grant(GRANT_KIND_GATHERING)])
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, opt) is False

    def test_mixed_supported_and_gathering_bundle_is_not_checkoutable(self):
        """A bundle mixing a supported Pathway grant AND an
        unsupported Gathering grant is entirely hidden — the
        fulfillment path refuses the whole bundle at checkout, so
        the member surface must too."""
        s = _sched()
        opt = _opt(grants=[
            _grant(GRANT_KIND_PATHWAY), _grant(GRANT_KIND_GATHERING),
        ])
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, opt) is False

    def test_option_with_no_grants_is_checkoutable_via_legacy_resolver(self):
        """Pre-grants options have no ``PaymentOptionGrant`` rows;
        the legacy resolver still fulfills them cleanly. Treat as
        supported so we don't hide legitimate legacy shapes."""
        s = _sched()
        opt = _opt(grants=[])
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s, opt) is True

    def test_helper_fail_closed_when_option_missing_for_finite(self):
        """If a caller forgets to pass ``option`` for a finite
        schedule the helper returns False. A future refactor that
        drops the arg cannot silently start advertising
        unsupported bundles."""
        s = _sched()
        with patch("app.core.config.settings.finite_plan_member_checkout_enabled", True):
            assert _schedule_is_member_checkoutable(s) is False

    def test_option_support_helper_direct(self):
        assert _option_supports_finite_member_checkout(_opt()) is True
        assert _option_supports_finite_member_checkout(
            _opt(grants=[_grant(GRANT_KIND_PATHWAY)])
        ) is True
        assert _option_supports_finite_member_checkout(
            _opt(grants=[_grant(GRANT_KIND_EVENT_SERIES)])
        ) is True
        assert _option_supports_finite_member_checkout(
            _opt(grants=[_grant(GRANT_KIND_GATHERING)])
        ) is False
        assert _option_supports_finite_member_checkout(
            _opt(grants=[_grant(GRANT_KIND_PATHWAY), _grant(GRANT_KIND_GATHERING)])
        ) is False


# ---------------------------------------------------------------------------
# Duplicate-plan guard is enforced at the checkout endpoint, not here
# ---------------------------------------------------------------------------


class TestDuplicatePlanGuardIsCheckoutLevel:
    """The helper returns True whenever the schedule ITSELF is
    checkoutable — per-viewer state (existing active plan) is
    evaluated later inside ``/api/checkout`` via
    ``check_no_active_plan``. This test locks in that separation so
    a future refactor doesn't accidentally leak per-viewer signals
    into a shape that other members share."""

    def test_helper_does_not_take_a_viewer_argument(self):
        import inspect
        sig = inspect.signature(_schedule_is_member_checkoutable)
        # Only ``schedule`` (required) + ``option`` (grant-bundle
        # check) — no viewer-scoped arg.
        assert list(sig.parameters.keys()) == ["schedule", "option"]
