"""Stage 1B.3 — would the resolver price this purchase the same way?

The question this stage answers is narrower than it looks, and the
tests are shaped around keeping it honest.

It compares, at the moment a Gathering Series checkout has decided and
is about to contact Stripe, the authoritative figures against what
``resolve_arrangement`` re-derives from the two identifiers the member
supplied. Identity, currency, the amount charged now, the total
committed, the instalment shape.

It does **not** compare accept/refuse. The resolver has no member in
its question, so ``check_same_option_not_active``, the ban guard, the
creator's plan and the archived-Pathway rule are not in the comparison
at all. Every verdict carries ``NOT_COMPARED`` naming them, and a test
below asserts that it does — because the one way this stage could do
harm is by being read as more than it is.

The other property pinned throughout: **a disagreement must never
change what the member is charged or whether checkout proceeds.** Every
disagreement test asserts the Stripe call happened with unchanged
parameters.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.checkout.routes import create_unified_checkout_session
from app.checkout.schemas import UnifiedCheckoutRequest
from app.core.config import settings
from app.models.payment import PaymentTransaction
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries
from app.models.purchase_plan import PurchasePlan
from app.services import checkout_arrangement_shadow as ccs

SHADOW_LOGGER = "app.services.checkout_arrangement_shadow"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Rows — EMBODY's real shape by default: A$180 once, or 10 weekly A$18.
# ---------------------------------------------------------------------------


def _series(db, space, *, title="EMBODY Term 4 2026", status="published"):
    s = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title, starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=70), status=status,
    )
    db.add(s)
    db.flush()
    return s


def _option(db, space, series, *, name="EMBODY Term Pass",
            status=PaymentOptionStatus.published, currency="AUD",
            position=0, attach_series=True):
    o = PaymentOption(
        id=_uid("po"), space_id=space.id,
        # The legacy Series endpoint checks ``attaches_to_*``; the
        # unified one reads grants. Both set, as production rows are.
        attaches_to_kind="event_series" if attach_series else "space",
        attaches_to_id=series.id if attach_series else space.id,
        name=name, payment_type=PaymentOptionType.one_time, status=status,
        currency=currency, position=position,
    )
    db.add(o)
    db.flush()
    db.add(PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=o.id,
        grant_kind="event_series", series_id=series.id, sessions_per_week=1,
    ))
    db.flush()
    return o


def _full(db, option, *, cents=18000, currency="AUD", status="published",
          name="Pay in full", position=0):
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="pay_in_full", status=status,
        total_amount_cents=cents, currency=currency, position=position,
    )
    db.add(s)
    db.flush()
    return s


def _plan(db, option, *, each=1800, count=10, interval="week",
          interval_count=1, total=None, currency="AUD",
          status="published", name="Weekly payments", position=1):
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="recurring_installments", status=status,
        installment_amount_cents=each, installment_count=count,
        interval=interval, stripe_interval=interval,
        stripe_interval_count=interval_count,
        total_amount_cents=total if total is not None else each * count,
        currency=currency, position=position,
    )
    db.add(s)
    db.flush()
    return s


def _creator_plan(db, creator, *, slug="creator", fee_bps=800):
    """An eligible creator — without one, the plan guard refuses before
    any of this is reached."""
    from app.models.creator_billing import (
        CreatorPlan,
        CreatorSubscription,
        CreatorSubscriptionStatus,
    )

    plan = CreatorPlan(
        id=_uid("cp"), slug=slug, name=slug.title(),
        monthly_price_cents=1900, currency="AUD",
        transaction_fee_basis_points=fee_bps, is_active=True,
        collective_limit=1,
    )
    db.add(plan)
    db.flush()
    db.add(CreatorSubscription(
        id=_uid("cs"), user_id=creator.id, creator_plan_id=plan.id,
        status=CreatorSubscriptionStatus.active,
        starts_at=datetime.utcnow() - timedelta(days=1), source="stripe_paid",
    ))
    db.flush()
    return plan


@pytest.fixture
def sale(db, make_user, make_space):
    """A Series with EMBODY's two schedules, an eligible creator and a
    buyer who holds nothing."""
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    _creator_plan(db, creator)
    series = _series(db, space)
    option = _option(db, space, series)
    return SimpleNamespace(
        creator=creator, space=space, series=series, option=option,
        full=_full(db, option), plan=_plan(db, option),
        buyer=make_user(role="user"),
    )


def _mock_session(url="https://checkout.stripe.test/x", sid=None):
    """A distinct Stripe Session per call.

    ``PaymentTransaction.provider_checkout_session_id`` is unique, so a
    constant id turns the second purchase in a test into an
    IntegrityError surfacing as a 502 — which looks exactly like a
    checkout bug and is not one.
    """
    return SimpleNamespace(
        id=sid or f"cs_test_{uuid.uuid4().hex[:16]}", url=url,
        expires_at=int((datetime.utcnow() + timedelta(minutes=30)).timestamp()),
    )


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


@pytest.fixture
def shadow_on():
    with patch(
        "app.core.config.settings.purchase_arrangements_checkout_shadow", True,
    ):
        yield


@pytest.fixture
def shadow_off():
    with patch(
        "app.core.config.settings.purchase_arrangements_checkout_shadow", False,
    ):
        yield


@pytest.fixture
def plans_on():
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


def _req(option_id, schedule_id, **kw):
    return UnifiedCheckoutRequest(
        payment_option_id=option_id,
        payment_option_schedule_id=schedule_id,
        success_url="https://example.test/ok",
        cancel_url="https://example.test/no",
        **kw,
    )


@pytest.fixture
def buy(db):
    """Drive the real unified checkout, with Stripe mocked. Returns the
    response and the Stripe mock so parameters can be inspected."""
    def _go(sale, schedule):
        with patch("stripe.checkout.Session.create") as m:
            m.return_value = _mock_session()
            res = create_unified_checkout_session(
                _req(sale.option.id, schedule.id),
                current_user=sale.buyer, db=db,
            )
        return res, m
    return _go


@pytest.fixture
def shadow_lines(caplog):
    """Capture the shadow's own log lines.

    ``caplog`` is given an explicit level and the logger is re-enabled,
    because alembic's ``fileConfig`` silences ``app.*`` under pytest —
    a naive assertion here would pass vacuously.
    """
    def _capture():
        caplog.clear()
        logging.getLogger(SHADOW_LOGGER).disabled = False
        return caplog.at_level(logging.INFO, logger=SHADOW_LOGGER)

    def _lines(level=None):
        return [
            r.getMessage() for r in caplog.records
            if r.name == SHADOW_LOGGER
            and (level is None or r.levelno == level)
        ]

    return SimpleNamespace(capture=_capture, lines=_lines)


# ---------------------------------------------------------------------------
# 1. Flag OFF
# ---------------------------------------------------------------------------


class TestWithTheFlagOff:
    def test_no_comparison_runs(self, db, sale, buy, stripe_configured, shadow_off):
        with patch.object(ccs, "compare_checkout") as compare, \
             patch.object(ccs, "series_id_for_option") as lookup:
            res, _m = buy(sale, sale.full)
        assert res.checkout_url
        compare.assert_not_called()
        # Not even the scoping query — "off" means no work, not
        # discarded work.
        lookup.assert_not_called()

    def test_the_checkout_decision_is_unchanged(
        self, db, sale, buy, stripe_configured, shadow_off,
    ):
        res, m = buy(sale, sale.full)
        assert res.free is False
        assert res.checkout_url == "https://checkout.stripe.test/x"
        assert m.call_count == 1

    def test_the_amount_and_currency_are_unchanged(
        self, db, sale, buy, stripe_configured, shadow_off,
    ):
        _res, m = buy(sale, sale.full)
        items = m.call_args.kwargs["line_items"]
        assert items[0]["price_data"]["unit_amount"] == 18000
        assert items[0]["price_data"]["currency"] == "aud"

    def test_no_shadow_log_is_emitted(
        self, db, sale, buy, stripe_configured, shadow_off, shadow_lines,
    ):
        with shadow_lines.capture():
            buy(sale, sale.full)
        assert shadow_lines.lines() == []

    def test_existing_validation_errors_are_unchanged(
        self, db, sale, stripe_configured, shadow_off,
    ):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            create_unified_checkout_session(
                _req(sale.option.id, "pos_does_not_exist"),
                current_user=sale.buyer, db=db,
            )
        assert exc.value.status_code in (400, 404)

    def test_no_extra_rows_are_written(
        self, db, sale, buy, stripe_configured, shadow_off,
    ):
        before_txn = db.query(PaymentTransaction).count()
        before_plan = db.query(PurchasePlan).count()
        buy(sale, sale.full)
        db.expire_all()
        # One transaction for the purchase itself, no plan, nothing else.
        assert db.query(PaymentTransaction).count() == before_txn + 1
        assert db.query(PurchasePlan).count() == before_plan


# ---------------------------------------------------------------------------
# 2. Flag ON — agreements
# ---------------------------------------------------------------------------


class TestAgreements:
    def test_embody_pay_in_full(
        self, db, sale, buy, stripe_configured, shadow_on, shadow_lines,
    ):
        """A$180 once."""
        with shadow_lines.capture():
            res, m = buy(sale, sale.full)
        assert res.checkout_url
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert "verdict=agree" in line
        assert "immediate=18000" in line
        assert "total=18000" in line
        assert "currency=AUD" in line
        assert "schedule_type=pay_in_full" in line
        # And the charge is untouched.
        assert m.call_args.kwargs["line_items"][0]["price_data"][
            "unit_amount"
        ] == 18000

    def test_embody_weekly_instalments(
        self, db, sale, buy, stripe_configured, shadow_on, plans_on,
        shadow_lines,
    ):
        """Ten weekly payments of A$18. The immediate charge is the
        first instalment, never a configured deposit."""
        with shadow_lines.capture():
            res, _m = buy(sale, sale.plan)
        assert res.checkout_url
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert "verdict=agree" in line
        assert "immediate=1800" in line
        assert "total=18000" in line
        assert "instalments=10x1800/week" in line

    def test_a_fortnightly_plan(
        self, db, sale, make_user, make_space, buy, stripe_configured,
        shadow_on, plans_on, shadow_lines,
    ):
        sched = _plan(
            db, sale.option, each=3000, count=6, interval="week",
            interval_count=2, total=18000, name="Fortnightly", position=2,
        )
        with shadow_lines.capture():
            res, _m = buy(sale, sched)
        assert res.checkout_url
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert "verdict=agree" in line
        assert "immediate=3000" in line
        assert "instalments=6x3000/week" in line

    @pytest.mark.parametrize(
        "which,immediate", [("full", 18000), ("plan", 1800)],
    )
    def test_multiple_schedules_under_one_option(
        self, db, sale, make_user, stripe_configured, shadow_on, plans_on,
        shadow_lines, which, immediate,
    ):
        """Each schedule compares on its own terms, and the *requested*
        one is compared — the identifiers decide, never a guess.

        Parametrised rather than looped, because a second purchase by
        the same buyer on the same Option is correctly refused by the
        duplicate guard, so each case needs its own buyer.
        """
        sched = getattr(sale, which)
        with shadow_lines.capture():
            with patch("stripe.checkout.Session.create") as m:
                m.return_value = _mock_session()
                create_unified_checkout_session(
                    _req(sale.option.id, sched.id),
                    current_user=make_user(role="user"), db=db,
                )
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert "verdict=agree" in line, line
        assert f"immediate={immediate}" in line, line
        assert f"schedule={sched.id}" in line, line

    def test_multiple_payment_options_for_one_series(
        self, db, sale, make_user, stripe_configured, shadow_on, shadow_lines,
    ):
        """Awaken / Activate / Empower — three tiers, three prices."""
        tiers = [("Awaken", 18000), ("Activate", 30600), ("Empower", 37800)]
        for i, (name, cents) in enumerate(tiers):
            opt = _option(
                db, sale.space, sale.series, name=name, position=i + 1,
            )
            sched = _full(db, opt, cents=cents)
            buyer = make_user(role="user")
            with shadow_lines.capture():
                with patch("stripe.checkout.Session.create") as m:
                    m.return_value = _mock_session()
                    create_unified_checkout_session(
                        _req(opt.id, sched.id), current_user=buyer, db=db,
                    )
            line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
            assert "verdict=agree" in line, (name, line)
            assert f"immediate={cents}" in line, (name, line)
            assert f"option={opt.id}" in line

    def test_a_non_aud_currency(
        self, db, make_user, make_space, stripe_configured, shadow_on,
        shadow_lines,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _creator_plan(db, creator)
        series = _series(db, space)
        opt = _option(db, space, series, currency="NZD")
        sched = _full(db, opt, cents=18000, currency="NZD")
        with shadow_lines.capture():
            with patch("stripe.checkout.Session.create") as m:
                m.return_value = _mock_session()
                create_unified_checkout_session(
                    _req(opt.id, sched.id),
                    current_user=make_user(role="user"), db=db,
                )
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert "verdict=agree" in line
        assert "currency=NZD" in line

    def test_the_legacy_identifiers_are_what_is_compared(
        self, db, sale, buy, stripe_configured, shadow_on, shadow_lines,
    ):
        with shadow_lines.capture():
            buy(sale, sale.full)
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert f"option={sale.option.id}" in line
        assert f"schedule={sale.full.id}" in line
        assert f"experience={sale.series.id}" in line

    def test_every_verdict_names_what_was_not_compared(
        self, db, sale, buy, stripe_configured, shadow_on, shadow_lines,
    ):
        """The point of the stage. ``agree`` must never be readable as
        "these two systems would make the same decision"."""
        with shadow_lines.capture():
            buy(sale, sale.full)
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert "not_compared=" in line
        for guard in ccs.NOT_COMPARED:
            assert guard in line, guard
        assert "member_already_holds_option" in line
        assert "creator_plan_eligibility" in line


# ---------------------------------------------------------------------------
# 3. Flag ON — disagreements. None may change the charge.
# ---------------------------------------------------------------------------


class TestDisagreements:
    """Each case patches the *resolver's* answer, never the legacy one —
    the legacy path must run exactly as it does in production, so the
    assertion that the charge is unchanged means something."""

    def _with_resolver(self, arrangement_patch):
        """Patch ``resolve_arrangement`` as the shadow sees it."""
        return patch(
            "app.services.purchase_arrangements.resolve_arrangement",
            **arrangement_patch,
        )

    def _arrangement(self, sale, **over):
        from app.services.purchase_arrangements import Arrangement

        base = dict(
            arrangement_id=f"option:{sale.option.id}:schedule:{sale.full.id}",
            source="payment_option",
            experience_kind="event_series",
            experience_id=sale.series.id,
            space_id=sale.space.id,
            payment_option_id=sale.option.id,
            payment_option_schedule_id=sale.full.id,
            name="EMBODY Term Pass",
            schedule_name="Pay in full",
            currency="AUD",
            schedule_type="pay_in_full",
            total_amount_cents=18000,
            upfront_amount_cents=18000,
            installment_amount_cents=None,
            installment_count=None,
            interval=None,
            is_bundle=False,
            included=(),
            available_for_new_purchase=True,
            unavailable_reason=None,
        )
        base.update(over)
        return Arrangement(**base)

    def _run(self, db, sale, shadow_lines, arrangement):
        with shadow_lines.capture():
            with patch(
                "app.services.purchase_arrangements.resolve_arrangement",
                return_value=arrangement,
            ):
                with patch("stripe.checkout.Session.create") as m:
                    m.return_value = _mock_session()
                    res = create_unified_checkout_session(
                        _req(sale.option.id, sale.full.id),
                        current_user=sale.buyer, db=db,
                    )
        return res, m

    def test_an_amount_difference_is_reported(
        self, db, sale, stripe_configured, shadow_on, shadow_lines,
    ):
        """The $5/$2 shape, at the moment of charge."""
        res, m = self._run(
            db, sale, shadow_lines,
            self._arrangement(sale, total_amount_cents=500,
                              upfront_amount_cents=500),
        )
        lines = shadow_lines.lines(logging.WARNING)
        assert any("verdict=disagree" in l for l in lines), lines
        assert any("immediate_charge_cents" in l for l in lines)
        # The member is still charged what the legacy path decided.
        assert m.call_args.kwargs["line_items"][0]["price_data"][
            "unit_amount"
        ] == 18000
        assert res.checkout_url == "https://checkout.stripe.test/x"

    def test_a_currency_difference_is_reported(
        self, db, sale, stripe_configured, shadow_on, shadow_lines,
    ):
        res, m = self._run(
            db, sale, shadow_lines, self._arrangement(sale, currency="USD"),
        )
        lines = shadow_lines.lines(logging.WARNING)
        assert any("verdict=disagree" in l for l in lines)
        assert any("currency" in l for l in lines)
        assert m.call_args.kwargs["line_items"][0]["price_data"][
            "currency"
        ] == "aud"
        assert res.checkout_url

    def test_a_schedule_identity_difference_is_reported(
        self, db, sale, stripe_configured, shadow_on, shadow_lines,
    ):
        """``resolve_arrangement`` raising ArrangementNotFound is the
        real mechanism — the shadow must report it, not fall back to
        another schedule."""
        from app.services.purchase_arrangements import ArrangementNotFound

        with shadow_lines.capture():
            with patch(
                "app.services.purchase_arrangements.resolve_arrangement",
                side_effect=ArrangementNotFound("nope"),
            ):
                with patch("stripe.checkout.Session.create") as m:
                    m.return_value = _mock_session()
                    res = create_unified_checkout_session(
                        _req(sale.option.id, sale.full.id),
                        current_user=sale.buyer, db=db,
                    )
        lines = shadow_lines.lines(logging.WARNING)
        assert any("verdict=disagree" in l for l in lines)
        assert any(
            "resolver_cannot_find_this_arrangement" in l for l in lines
        )
        assert res.checkout_url
        assert m.call_args.kwargs["line_items"][0]["price_data"][
            "unit_amount"
        ] == 18000

    def test_the_legacy_path_accepting_what_the_resolver_calls_unavailable(
        self, db, sale, stripe_configured, shadow_on, shadow_lines,
    ):
        res, m = self._run(
            db, sale, shadow_lines,
            self._arrangement(
                sale, available_for_new_purchase=False,
                unavailable_reason="unsupported_inclusion",
            ),
        )
        lines = shadow_lines.lines(logging.WARNING)
        assert any("verdict=disagree" in l for l in lines)
        assert any("arrangement_availability" in l for l in lines)
        assert any("unsupported_inclusion" in l for l in lines)
        # Still charged, still proceeding — the shadow does not veto.
        assert m.call_count == 1
        assert res.checkout_url

    def test_an_instalment_shape_difference_is_reported(
        self, db, sale, stripe_configured, shadow_on, plans_on, shadow_lines,
    ):
        with shadow_lines.capture():
            with patch(
                "app.services.purchase_arrangements.resolve_arrangement",
                return_value=self._arrangement(
                    sale,
                    payment_option_schedule_id=sale.plan.id,
                    schedule_type="recurring_installments",
                    total_amount_cents=18000,
                    upfront_amount_cents=1800,
                    installment_amount_cents=1800,
                    installment_count=12,      # wrong
                    interval="month",          # wrong
                ),
            ):
                with patch("stripe.checkout.Session.create") as m:
                    m.return_value = _mock_session()
                    res = create_unified_checkout_session(
                        _req(sale.option.id, sale.plan.id),
                        current_user=sale.buyer, db=db,
                    )
        lines = shadow_lines.lines(logging.WARNING)
        assert any("verdict=disagree" in l for l in lines)
        assert any("installment_count" in l for l in lines)
        assert any("interval" in l for l in lines)
        assert res.checkout_url
        # The plan the member actually committed to is the real one.
        db.expire_all()
        plan = db.query(PurchasePlan).filter(
            PurchasePlan.member_user_id == sale.buyer.id,
        ).one()
        assert plan.installments_expected == 10
        assert plan.installment_amount_cents == 1800

    def test_a_configured_upfront_is_not_treated_as_the_first_charge(
        self, db, sale, buy, stripe_configured, shadow_on, plans_on,
        shadow_lines,
    ):
        """The 7a21fab discrepancy, guarded at the point of charge.
        Stripe prices the subscription from the instalment amount, so
        the comparison must use that — a deposit nobody collects must
        not become the compared figure on either side."""
        sale.plan.upfront_amount_cents = 5000
        db.flush()

        with shadow_lines.capture():
            res, _m = buy(sale, sale.plan)
        line = next(l for l in shadow_lines.lines() if ccs.LOG_PREFIX in l)
        assert "verdict=agree" in line, line
        assert "immediate=1800" in line
        assert "immediate=5000" not in line
        assert res.checkout_url

    def test_a_discounted_purchase_is_not_comparable(
        self, db, sale, stripe_configured, shadow_on, shadow_lines,
    ):
        """A discount changes what Stripe charges without changing the
        arrangement. Comparing would report a false disagreement on
        every discounted checkout and bury the real ones."""
        authoritative = ccs.authoritative_from_pay_in_full(
            series_id=sale.series.id,
            resolved=SimpleNamespace(
                payment_option=sale.option, payment_schedule=sale.full,
                price_cents=18000, currency="AUD", space=sale.space,
            ),
        )
        comparison = ccs.not_comparable(authoritative, "discount_applied")
        assert comparison.verdict == ccs.VERDICT_NOT_COMPARABLE
        assert "discount_applied" in comparison.as_log()
        # And it is not filed as agreement.
        assert "verdict=agree" not in comparison.as_log()


# ---------------------------------------------------------------------------
# 4. Shadow failures must not reach the member
# ---------------------------------------------------------------------------


class TestShadowFailures:
    def test_a_raising_resolver_does_not_break_checkout(
        self, db, sale, buy, stripe_configured, shadow_on, shadow_lines,
    ):
        with shadow_lines.capture():
            with patch(
                "app.services.purchase_arrangements.resolve_arrangement",
                side_effect=RuntimeError("deliberate"),
            ):
                res, m = buy(sale, sale.full)
        assert res.checkout_url == "https://checkout.stripe.test/x"
        assert m.call_args.kwargs["line_items"][0]["price_data"][
            "unit_amount"
        ] == 18000
        lines = shadow_lines.lines(logging.WARNING)
        assert any("verdict=shadow_error" in l for l in lines), lines

    def test_a_broken_comparison_module_does_not_break_checkout(
        self, db, sale, buy, stripe_configured, shadow_on,
    ):
        with patch.object(
            ccs, "compare_checkout", side_effect=ValueError("boom"),
        ):
            res, m = buy(sale, sale.full)
        assert res.checkout_url
        assert m.call_count == 1

    def test_a_broken_scoping_query_does_not_break_checkout(
        self, db, sale, buy, stripe_configured, shadow_on,
    ):
        with patch.object(
            ccs, "series_id_for_option", side_effect=ValueError("boom"),
        ):
            res, m = buy(sale, sale.full)
        assert res.checkout_url
        assert m.call_count == 1

    def test_failing_logging_does_not_break_checkout(
        self, db, sale, buy, stripe_configured, shadow_on,
    ):
        with patch.object(
            ccs.CheckoutComparison, "log", side_effect=OSError("no log")
        ):
            res, m = buy(sale, sale.full)
        assert res.checkout_url
        assert m.call_count == 1

    def test_an_option_granting_no_series_is_skipped(
        self, db, sale, buy, stripe_configured, shadow_on, shadow_lines,
    ):
        """Out of this stage's scope, and skipped before a comparison
        is built rather than compared against nothing."""
        db.query(PaymentOptionGrant).filter(
            PaymentOptionGrant.payment_option_id == sale.option.id,
        ).delete()
        db.flush()
        with shadow_lines.capture():
            res, _m = buy(sale, sale.full)
        assert res.checkout_url
        assert shadow_lines.lines() == []

    def test_the_quiet_wrapper_swallows_everything(self, db, sale):
        authoritative = ccs.authoritative_from_pay_in_full(
            series_id=sale.series.id,
            resolved=SimpleNamespace(
                payment_option=sale.option, payment_schedule=sale.full,
                price_cents=18000, currency="AUD", space=sale.space,
            ),
        )
        with patch.object(
            ccs, "compare_checkout", side_effect=ValueError("boom"),
        ):
            ccs.compare_checkout_quietly(db, authoritative=authoritative)


# ---------------------------------------------------------------------------
# 5. Stripe safety and existing protections
# ---------------------------------------------------------------------------


class TestStripeAndGuardsUntouched:
    def test_the_shadow_makes_no_stripe_call_of_its_own(
        self, db, sale, buy, stripe_configured, shadow_on,
    ):
        """One Session, created by the authoritative path. The shadow
        adds none."""
        _res, m = buy(sale, sale.full)
        assert m.call_count == 1

    def test_the_stripe_parameters_are_identical_either_way(
        self, db, sale, make_user, stripe_configured,
    ):
        """The strongest statement available: the kwargs handed to
        Stripe are the same with the shadow off and on."""
        def _params(shadow: bool, buyer):
            with patch(
                "app.core.config.settings"
                ".purchase_arrangements_checkout_shadow", shadow,
            ):
                with patch("stripe.checkout.Session.create") as m:
                    m.return_value = _mock_session()
                    create_unified_checkout_session(
                        _req(sale.option.id, sale.full.id),
                        current_user=buyer, db=db,
                    )
            kw = dict(m.call_args.kwargs)
            # Per-purchase identifiers legitimately differ.
            for noisy in ("metadata", "payment_intent_data", "customer_email",
                          "success_url", "cancel_url", "expires_at"):
                kw.pop(noisy, None)
            return kw

        off = _params(False, make_user(role="user"))
        on = _params(True, make_user(role="user"))
        assert off == on

    def test_the_shadow_module_writes_nothing(self):
        import ast
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "services" / "checkout_arrangement_shadow.py"
        )
        tree = ast.parse(path.read_text())
        banned = {
            "commit", "flush", "add", "add_all", "delete", "merge",
            "with_for_update", "rollback",
        }
        found = sorted({
            n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and n.attr in banned
            and isinstance(n.value, ast.Name)
            and n.value.id == "db"
        })
        assert found == [], f"the checkout shadow may mutate: {found}"

    def test_the_shadow_module_imports_no_stripe(self):
        import ast
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "services" / "checkout_arrangement_shadow.py"
        )
        tree = ast.parse(path.read_text())
        names = {
            (n.module or "").lower()
            for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        } | {
            a.name.lower()
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in n.names
        }
        assert not any("stripe" in n for n in names), sorted(names)

    def test_the_duplicate_guard_still_refuses(
        self, db, sale, stripe_configured, shadow_on,
    ):
        """A member-specific guard the resolver never evaluates, still
        enforced with the shadow on.

        The pass is created directly rather than by a prior checkout: a
        pay-in-full purchase mints its AccessPass at *fulfilment*, in
        the webhook, so one checkout call leaves nothing for the guard
        to find. Granting the pass is what puts the member in the state
        the guard is about.
        """
        from fastapi import HTTPException

        from app.models.access_pass import (
            AccessPass,
            AccessPassSource,
            AccessPassStatus,
            AccessPassType,
        )

        db.add(AccessPass(
            id=_uid("ap"), user_id=sale.buyer.id, space_id=sale.space.id,
            payment_option_id=sale.option.id,
            eligible_series_id=sale.series.id,
            pass_type=AccessPassType.term_pass,
            status=AccessPassStatus.active,
            source=AccessPassSource.one_time_purchase,
            valid_from=datetime.utcnow(),
        ))
        db.flush()

        with pytest.raises(HTTPException) as exc:
            create_unified_checkout_session(
                _req(sale.option.id, sale.full.id),
                current_user=sale.buyer, db=db,
            )
        assert exc.value.status_code == 409, exc.value.detail

    def test_the_creator_plan_guard_still_refuses(
        self, db, make_user, make_space, stripe_configured, shadow_on,
    ):
        """No creator plan — refused before pricing, and no shadow
        comparison is reached."""
        from fastapi import HTTPException

        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _series(db, space)
        opt = _option(db, space, series)
        sched = _full(db, opt)
        with patch(
            "app.core.config.settings.creator_plan_guard_enabled", True,
        ):
            with pytest.raises(HTTPException) as exc:
                create_unified_checkout_session(
                    _req(opt.id, sched.id),
                    current_user=make_user(role="user"), db=db,
                )
        assert exc.value.status_code == 409

    def test_an_unpublished_schedule_is_still_refused(
        self, db, sale, stripe_configured, shadow_on,
    ):
        from fastapi import HTTPException

        draft = _full(db, sale.option, cents=9900, status="draft",
                      name="Draft", position=5)
        with pytest.raises(HTTPException):
            create_unified_checkout_session(
                _req(sale.option.id, draft.id),
                current_user=sale.buyer, db=db,
            )


# ---------------------------------------------------------------------------
# 6. Privacy and countability
# ---------------------------------------------------------------------------


class TestWhatIsLogged:
    def _line(self, sale):
        authoritative = ccs.authoritative_from_pay_in_full(
            series_id=sale.series.id,
            resolved=SimpleNamespace(
                payment_option=sale.option, payment_schedule=sale.full,
                price_cents=18000, currency="AUD", space=sale.space,
            ),
        )
        return ccs.CheckoutComparison(
            verdict=ccs.VERDICT_AGREE, authoritative=authoritative,
        ).as_log()

    def test_no_member_identity_reaches_the_log(self, db, sale):
        line = self._line(sale)
        assert sale.buyer.id not in line
        assert sale.buyer.email not in line
        for leak in ("@", "email", "token", "sk_", "whsec", "cus_", "pi_",
                     "cs_", "sub_"):
            assert leak not in line, f"{leak!r} in {line!r}"

    def test_no_member_is_in_the_comparison_signature(self):
        """Asserted on the signature: no user can be logged by accident
        because none is in scope."""
        import inspect

        params = set(inspect.signature(ccs.compare_checkout).parameters)
        assert params == {"db", "authoritative"}
        fields = set(ccs.AuthoritativeCheckout.__dataclass_fields__)
        for forbidden in ("user", "member", "payer", "email", "buyer"):
            assert not any(forbidden in f for f in fields), fields

    def test_every_line_is_countable_by_one_prefix(self, db, sale):
        assert self._line(sale).startswith(ccs.LOG_PREFIX)

    def test_agreement_is_logged_at_info_not_silently(
        self, db, sale, buy, stripe_configured, shadow_on, shadow_lines,
    ):
        """A window that produced nothing is not evidence of agreement
        — the same lesson as the display shadow."""
        with shadow_lines.capture():
            buy(sale, sale.full)
        infos = shadow_lines.lines(logging.INFO)
        assert infos, "an agreeing comparison produced no observable line"
        assert any("verdict=agree" in l for l in infos)

    def test_the_four_verdicts_are_distinct(self):
        verdicts = {
            ccs.VERDICT_AGREE, ccs.VERDICT_DISAGREE,
            ccs.VERDICT_NOT_COMPARABLE, ccs.VERDICT_SHADOW_ERROR,
        }
        assert len(verdicts) == 4
        # "not compared" and "broken" must never be filed as agreement.
        assert ccs.VERDICT_NOT_COMPARABLE != ccs.VERDICT_AGREE
        assert ccs.VERDICT_SHADOW_ERROR != ccs.VERDICT_AGREE
