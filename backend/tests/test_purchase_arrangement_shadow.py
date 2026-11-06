"""Stage 1B.2A — the resolver, measured against what members are served.

A shadow comparison earns the right to switch authority over. The
resolver has been correct in tests since Stage 1A and correct about
creator configuration since Stage 1B.1, but it has never priced a real
production Payment Option. This compares it against the projection that
actually serves members, with no consequence when it disagrees.

Two properties matter more than the comparison itself, and both are
pinned here:

* **It is off**, and off means no work — not "work whose result is
  discarded".
* **It cannot break the page it shadows.** A member asking how to join
  a Series must get the same answer whether the shadow runs, agrees,
  disagrees or raises.

The comparison is also where the normalisation rules live, so most of
these tests are about *not* reporting a difference that is only a
difference in shape: the projection returns options carrying schedules,
the resolver returns one arrangement per schedule, and it describes
draft and archived Options the projection filters out entirely.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_optional_user
from app.core.database import get_db
from app.main import app
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries, Pathway, PathwayType
from app.services.purchase_arrangement_shadow import (
    Difference,
    compare_series,
    compare_series_quietly,
)
from app.spaces._series_member_routes import (
    _member_purchasable_options_for_series,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _series(db, space, *, title="Term 4 2026", status="published") -> EventSeries:
    s = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title, starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=70), status=status,
    )
    db.add(s)
    db.flush()
    return s


def _pathway(db, space, *, title="Foundations") -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active", access_type="included_with_offer",
        pathway_type=PathwayType.guided_experience,
        pricing_mode="payment_options", currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _option(db, space, *, name="Term Pass",
            status=PaymentOptionStatus.published, position=0) -> PaymentOption:
    o = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name,
        payment_type=PaymentOptionType.one_time, status=status,
        currency="AUD", position=position,
    )
    db.add(o)
    db.flush()
    return o


def _pay_in_full(db, option, *, cents, status="published",
                 name="Pay in full", position=0) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="pay_in_full", status=status,
        total_amount_cents=cents, currency="AUD", position=position,
    )
    db.add(s)
    db.flush()
    return s


def _instalments(db, option, *, each, count, interval="week", total=None,
                 status="published", name="Payment plan",
                 position=1) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="recurring_installments", status=status,
        installment_amount_cents=each, installment_count=count,
        interval=interval, stripe_interval=interval, stripe_interval_count=1,
        total_amount_cents=total if total is not None else each * count,
        currency="AUD", position=position,
    )
    db.add(s)
    db.flush()
    return s


def _grant(db, option, kind, target_id, **kw) -> PaymentOptionGrant:
    cols = {
        "pathway": "pathway_id", "event_series": "series_id",
        "gathering": "event_id", "offering": "offering_id",
    }
    g = PaymentOptionGrant(
        id=_uid("pog"), payment_option_id=option.id, grant_kind=kind,
        **{cols[kind]: target_id}, **kw,
    )
    db.add(g)
    db.flush()
    return g


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def member(db, space, make_user):
    """An active member of the Collective.

    The Gatherings area is not reachable anonymously on a default
    Collective — ``require_area`` 404s rather than 403s so a private
    Collective's shape does not leak through its status codes — so the
    endpoint tests need a real viewer.
    """
    from app.models.platform import SpaceMembership

    user = make_user(role="user")
    db.add(SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        # ``learner`` is the stored role; "member" is the
        # member-facing word and is not a value of
        # ``space_role_enum``.
        role="learner", status="active",
    ))
    db.flush()
    return user


@pytest.fixture
def plans_on():
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


def _run(db, series, space):
    """Compare, against the projection's own output."""
    purchasable = _member_purchasable_options_for_series(series, space, db)
    return compare_series(
        db, series=series, space=space, purchasable=purchasable,
    )


# ---------------------------------------------------------------------------
# 1. Agreement on the shapes that sell today
# ---------------------------------------------------------------------------


class TestTheyAgree:
    def test_a_pay_in_full_term_pass_matches(self, db, space):
        series = _series(db, space)
        opt = _option(db, space, name="Term Pass")
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        report = _run(db, series, space)
        assert report.agrees, [d.as_log() for d in report.differences]
        assert report.matched == 1

    def test_a_bundle_with_two_schedules_matches_both(
        self, db, space, plans_on,
    ):
        """The shape most likely to produce a false difference: one
        Option, two schedules, two prices. The projection returns one
        option; the resolver returns two arrangements. Flattening to
        pairs is what makes them comparable."""
        series = _series(db, space)
        opt = _option(db, space, name="Term Pass")
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)
        _instalments(db, opt, each=1800, count=10, total=18000)

        report = _run(db, series, space)
        assert report.agrees, [d.as_log() for d in report.differences]
        assert report.matched == 2

    def test_a_bundle_including_a_pathway_matches_its_included_set(
        self, db, space,
    ):
        """The projection lists the Series title plus included Pathway
        titles; the resolver lists one entry per grant. Compared as
        sets of titles, so order and duplication are not findings."""
        series = _series(db, space, title="Term 4 2026")
        pathway = _pathway(db, space, title="Foundations")
        opt = _option(db, space, name="Term Pass + Foundations")
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _grant(db, opt, "pathway", pathway.id)
        _pay_in_full(db, opt, cents=24000)

        report = _run(db, series, space)
        assert report.agrees, [d.as_log() for d in report.differences]
        assert report.matched == 1

    def test_several_options_all_match(self, db, space, plans_on):
        series = _series(db, space)
        for i, cents in enumerate((12000, 18000, 24000)):
            opt = _option(db, space, name=f"Pass {i}", position=i)
            _grant(db, opt, "event_series", series.id, sessions_per_week=1)
            _pay_in_full(db, opt, cents=cents)

        report = _run(db, series, space)
        assert report.agrees, [d.as_log() for d in report.differences]
        assert report.matched == 3


# ---------------------------------------------------------------------------
# 2. Differences in shape are normalised, not reported
# ---------------------------------------------------------------------------


class TestShapeIsNotAPricingDifference:
    def test_a_draft_option_is_not_a_difference(self, db, space):
        """The projection's query filters drafts out; the resolver
        returns them with a reason. Both refuse to sell it."""
        series = _series(db, space)
        opt = _option(db, space, status=PaymentOptionStatus.draft)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        report = _run(db, series, space)
        assert report.agrees
        assert report.matched == 0

    def test_an_archived_option_is_not_a_difference(self, db, space):
        series = _series(db, space)
        opt = _option(db, space, status=PaymentOptionStatus.archived)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        report = _run(db, series, space)
        assert report.agrees
        assert report.extra_in_resolver == []

    def test_a_draft_schedule_is_not_a_difference(self, db, space):
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000, status="draft")

        report = _run(db, series, space)
        assert report.agrees

    def test_an_instalment_schedule_behind_its_flag_is_not_a_difference(
        self, db, space,
    ):
        """With ``finite_plan_member_checkout_enabled`` off, both sides
        refuse the plan and sell the pay-in-full beside it. The
        resolver consults the same flag through the same predicate, so
        this is agreement rather than luck."""
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)
        _instalments(db, opt, each=1800, count=10, total=18000)

        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled",
            False,
        ):
            report = _run(db, series, space)
        assert report.agrees, [d.as_log() for d in report.differences]
        assert report.matched == 1

    def test_the_stage_0_gathering_rule_agrees_on_both_sides(self, db, space):
        """The projection drops an Option carrying a Gathering grant;
        the resolver marks its arrangements ``unsupported_inclusion``.
        Same refusal, two implementations — this is the evidence that
        consolidating them would be behaviour-preserving."""
        from app.models.platform import Event

        series = _series(db, space)
        event = Event(
            id=_uid("e"), space_id=space.id, created_by_id=space.creator_id,
            title="One-off", starts_at=datetime.utcnow() + timedelta(days=3),
            ends_at=datetime.utcnow() + timedelta(days=3, hours=1),
            location_type="zoom", is_published=True, status="active",
            booking_access_type="paid_separately", gathering_type="workshop",
            attendance_format="online", ticket_price_cents=2000,
            ticket_currency="AUD", requires_booking=True,
        )
        db.add(event)
        db.flush()

        opt = _option(db, space, name="Pass + a Gathering")
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _grant(db, opt, "gathering", event.id)
        _pay_in_full(db, opt, cents=20000)

        report = _run(db, series, space)
        assert report.agrees, [
            d.as_log() for d in (*report.differences, *report.extra_in_resolver)
        ]
        # Neither side sells it.
        assert report.matched == 0


# ---------------------------------------------------------------------------
# 3. Real differences are reported
# ---------------------------------------------------------------------------


class TestRealDifferencesAreCaught:
    """Constructed by comparing against a deliberately altered
    baseline. The point is that the comparison would not stay silent if
    the two implementations ever diverged on money — a shadow that
    cannot fail is not evidence of anything.
    """

    def test_a_price_difference_is_reported(self, db, space):
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        purchasable = _member_purchasable_options_for_series(series, space, db)
        with patch(
            "app.services.purchase_arrangement_shadow._candidate_pairs",
        ) as fake:
            key = (opt.id, purchasable[0].schedules[0].id)
            fake.return_value = {
                key: {
                    "schedule_type": "pay_in_full", "currency": "AUD",
                    "total_amount_cents": 500,   # the $5/$2 shape
                    "installment_amount_cents": None,
                    "installment_count": None, "interval": None,
                    "included_titles": [series.title],
                },
            }
            report = compare_series(
                db, series=series, space=space, purchasable=purchasable,
            )
        assert not report.agrees
        assert report.matched == 0
        fields = {d.field_name for d in report.differences}
        assert "total_amount_cents" in fields
        found = next(
            d for d in report.differences
            if d.field_name == "total_amount_cents"
        )
        assert (found.baseline, found.candidate) == (18000, 500)

    def test_a_currency_difference_is_reported(self, db, space):
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        purchasable = _member_purchasable_options_for_series(series, space, db)
        key = (opt.id, purchasable[0].schedules[0].id)
        with patch(
            "app.services.purchase_arrangement_shadow._candidate_pairs",
            return_value={
                key: {
                    "schedule_type": "pay_in_full", "currency": "USD",
                    "total_amount_cents": 18000,
                    "installment_amount_cents": None,
                    "installment_count": None, "interval": None,
                    "included_titles": [series.title],
                },
            },
        ):
            report = compare_series(
                db, series=series, space=space, purchasable=purchasable,
            )
        assert not report.agrees
        assert {d.field_name for d in report.differences} == {"currency"}

    def test_an_arrangement_the_resolver_would_not_sell_is_reported(
        self, db, space,
    ):
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        purchasable = _member_purchasable_options_for_series(series, space, db)
        with patch(
            "app.services.purchase_arrangement_shadow._candidate_pairs",
            return_value={},
        ):
            report = compare_series(
                db, series=series, space=space, purchasable=purchasable,
            )
        assert not report.agrees
        assert len(report.missing_from_resolver) == 1
        assert report.missing_from_resolver[0].kind == (
            "sellable_to_members_but_not_to_resolver"
        )

    def test_an_instalment_cadence_difference_is_reported(
        self, db, space, plans_on,
    ):
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        sched = _instalments(db, opt, each=1800, count=10, total=18000)

        purchasable = _member_purchasable_options_for_series(series, space, db)
        with patch(
            "app.services.purchase_arrangement_shadow._candidate_pairs",
            return_value={
                (opt.id, sched.id): {
                    "schedule_type": "recurring_installments",
                    "currency": "AUD", "total_amount_cents": 18000,
                    "installment_amount_cents": 1800,
                    "installment_count": 12,       # wrong count
                    "interval": "month",           # wrong cadence
                    "included_titles": [series.title],
                },
            },
        ):
            report = compare_series(
                db, series=series, space=space, purchasable=purchasable,
            )
        assert {d.field_name for d in report.differences} == {
            "installment_count", "interval",
        }


# ---------------------------------------------------------------------------
# 4. It is off, and it cannot break anything
# ---------------------------------------------------------------------------


class TestIsolationFromMemberPurchasing:
    def test_the_flag_is_off_by_default(self):
        from app.core.config import Settings

        assert Settings.model_fields[
            "purchase_arrangements_shadow"
        ].default is False

    def test_nothing_is_computed_when_disabled(
        self, db, space, member,
    ):
        """Off must mean no work, not discarded work. Asserted by
        watching the comparison entry point while serving the real
        endpoint with the flag off."""
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: member
        client = TestClient(app)
        try:
            with patch(
                "app.core.config.settings.purchase_arrangements_shadow", False,
            ), patch(
                "app.services.purchase_arrangement_shadow"
                ".compare_series_quietly",
            ) as shadow:
                r = client.get(
                    f"/api/spaces/{space.slug}/gathering-series/"
                    f"{series.slug}/payment-options"
                )
            assert r.status_code == 200, r.text
            shadow.assert_not_called()
        finally:
            app.dependency_overrides.clear()

    def test_the_member_response_is_identical_either_way(
        self, db, space, member, plans_on,
    ):
        """The property that matters most: a member asking how to join
        gets the same answer whether or not the shadow runs."""
        series = _series(db, space)
        opt = _option(db, space, name="Term Pass")
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)
        _instalments(db, opt, each=1800, count=10, total=18000)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: member
        client = TestClient(app)
        url = (
            f"/api/spaces/{space.slug}/gathering-series/"
            f"{series.slug}/payment-options"
        )
        try:
            with patch(
                "app.core.config.settings.purchase_arrangements_shadow", False,
            ):
                off = client.get(url)
            with patch(
                "app.core.config.settings.purchase_arrangements_shadow", True,
            ):
                on = client.get(url)
        finally:
            app.dependency_overrides.clear()

        assert off.status_code == on.status_code == 200
        assert off.json() == on.json()

    def test_a_shadow_that_raises_does_not_reach_the_member(
        self, db, space, member,
    ):
        """A comparison bug must not turn a working page into a 500 to
        report a discrepancy nobody asked it to report."""
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: member
        client = TestClient(app)
        try:
            with patch(
                "app.core.config.settings.purchase_arrangements_shadow", True,
            ), patch(
                "app.services.purchase_arrangement_shadow.compare_series",
                side_effect=RuntimeError("deliberate"),
            ):
                r = client.get(
                    f"/api/spaces/{space.slug}/gathering-series/"
                    f"{series.slug}/payment-options"
                )
            assert r.status_code == 200, r.text
            assert len(r.json()) == 1
        finally:
            app.dependency_overrides.clear()

    def test_the_quiet_wrapper_swallows_everything(self, db, space):
        """Including a bug in the comparison module itself."""
        series = _series(db, space)
        with patch(
            "app.services.purchase_arrangement_shadow.compare_series",
            side_effect=ValueError("boom"),
        ):
            compare_series_quietly(
                db, series=series, space=space, purchasable=[],
            )  # must not raise

    def test_the_shadow_writes_nothing(self, db, space):
        """A comparison that mutated anything would be a write
        pretending to be a measurement."""
        import ast
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "services" / "purchase_arrangement_shadow.py"
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
        assert found == [], f"the shadow may mutate the session: {found}"


# ---------------------------------------------------------------------------
# 5. What it writes to the log
# ---------------------------------------------------------------------------


class TestWhatIsLogged:
    def test_a_difference_logs_ids_amounts_and_nothing_else(self):
        """Option and schedule ids, the field, and the two values.
        Amounts are the subject of the comparison and are already
        public on the page being rendered; there is no member in the
        comparison at all, so there is no identity to leak."""
        line = Difference(
            kind="field_mismatch", option_id="po_1", schedule_id="pos_1",
            field_name="total_amount_cents", baseline=18000, candidate=500,
        ).as_log()
        assert "po_1" in line
        assert "pos_1" in line
        assert "18000" in line and "500" in line
        for leak in ("@", "email", "user_id", "cus_", "sub_", "cs_", "pi_"):
            assert leak not in line, f"{leak!r} in {line!r}"

    def test_no_member_identity_can_reach_the_comparison(self):
        """Asserted on the signature: ``compare_series`` takes no user,
        so no member field is in scope to log by accident."""
        import inspect

        params = set(inspect.signature(compare_series).parameters)
        assert params == {"db", "series", "space", "purchasable"}
        for forbidden in ("user", "current_user", "member", "viewer"):
            assert forbidden not in params

    def test_agreement_is_observable_not_silent(
        self, db, space, caplog,
    ):
        """The trap this avoids: a clean 48-hour window that produced no
        log output at all would be indistinguishable from the flag
        never having been switched on. Agreement therefore logs at
        INFO, with ``matched=`` so the lines can be counted and summed.
        """
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)
        purchasable = _member_purchasable_options_for_series(series, space, db)

        name = "app.services.purchase_arrangement_shadow"
        with caplog.at_level(logging.INFO, logger=name):
            logging.getLogger(name).disabled = False
            compare_series_quietly(
                db, series=series, space=space, purchasable=purchasable,
            )

        lines = [
            r.getMessage() for r in caplog.records
            if r.name == name and r.levelno == logging.INFO
        ]
        assert lines, "an agreeing comparison produced no observable line"
        assert any("agrees" in line for line in lines)
        assert any("matched=1" in line for line in lines)
        # Countable by a log scan.
        assert all(
            line.startswith("purchase_arrangements_shadow") for line in lines
        )

    def test_a_disagreement_is_a_warning_not_a_debug_line(
        self, db, space, caplog,
    ):
        """A price difference must not sit silently in a debug stream.

        ``caplog`` is given an explicit level and logger because
        alembic's ``fileConfig`` silences ``app.*`` under pytest — a
        naive assertion here would pass vacuously.
        """
        series = _series(db, space)
        opt = _option(db, space)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, opt, cents=18000)
        purchasable = _member_purchasable_options_for_series(series, space, db)

        logger_name = "app.services.purchase_arrangement_shadow"
        with caplog.at_level(logging.WARNING, logger=logger_name):
            logging.getLogger(logger_name).disabled = False
            with patch(
                "app.services.purchase_arrangement_shadow._candidate_pairs",
                return_value={},
            ):
                compare_series_quietly(
                    db, series=series, space=space, purchasable=purchasable,
                )

        warnings = [
            r for r in caplog.records
            if r.name == logger_name and r.levelno >= logging.WARNING
        ]
        assert warnings, "a disagreement produced no warning"
        assert any("DISAGREES" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# 6. The equivalence sweep
# ---------------------------------------------------------------------------
#
# Every Option/schedule shape this system can hold, compared in both
# states of the instalment flag. This is the evidence that earns the
# resolver the right to influence a member surface in Stage 1B.2B: not
# "it works on the happy path" but "it agrees on all of them, including
# the ones neither side sells".


SHAPES = []

def shape(name):
    def deco(fn):
        SHAPES.append((name, fn))
        return fn
    return deco


@shape("pay_in_full only")
def s1(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _pay_in_full(db, o, cents=18000)

@shape("instalments only")
def s2(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _instalments(db, o, each=1800, count=10, total=18000)

@shape("both schedules")
def s3(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _pay_in_full(db, o, cents=18000); _instalments(db, o, each=1800, count=10, total=18000)

@shape("fortnightly cadence")
def s4(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    s = _instalments(db, o, each=3000, count=6, total=18000, interval="week")
    s.stripe_interval_count = 2; db.flush()

@shape("monthly cadence")
def s5(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _instalments(db, o, each=6000, count=3, total=18000, interval="month")

@shape("bundle with pathway")
def s6(db, space, series):
    pw = _pathway(db, space, title="Foundations")
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _grant(db, o, "pathway", pw.id); _pay_in_full(db, o, cents=24000)

@shape("two pathways + series")
def s7(db, space, series):
    a = _pathway(db, space, title="A"); b = _pathway(db, space, title="B")
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _grant(db, o, "pathway", a.id); _grant(db, o, "pathway", b.id)
    _pay_in_full(db, o, cents=30000)

@shape("draft option")
def s8(db, space, series):
    o = _option(db, space, status=PaymentOptionStatus.draft)
    _grant(db, o, "event_series", series.id, sessions_per_week=1); _pay_in_full(db, o, cents=18000)

@shape("archived option")
def s9(db, space, series):
    o = _option(db, space, status=PaymentOptionStatus.archived)
    _grant(db, o, "event_series", series.id, sessions_per_week=1); _pay_in_full(db, o, cents=18000)

@shape("draft schedule only")
def s10(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _pay_in_full(db, o, cents=18000, status="draft")

@shape("gathering grant (Stage 0)")
def s11(db, space, series):
    from app.models.platform import Event
    from datetime import datetime, timedelta
    import uuid as u
    e = Event(id=f"e_{u.uuid4().hex[:10]}", space_id=space.id, created_by_id=space.creator_id,
              title="X", starts_at=datetime.utcnow()+timedelta(days=3),
              ends_at=datetime.utcnow()+timedelta(days=3, hours=1), location_type="zoom",
              is_published=True, status="active", booking_access_type="paid_separately",
              gathering_type="workshop", attendance_format="online",
              ticket_price_cents=2000, ticket_currency="AUD", requires_booking=True)
    db.add(e); db.flush()
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _grant(db, o, "gathering", e.id); _pay_in_full(db, o, cents=20000)

@shape("total != each*count (invalid)")
def s12(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _instalments(db, o, each=1800, count=10, total=99999)

@shape("zero-priced pay_in_full")
def s13(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    _pay_in_full(db, o, cents=0)

@shape("null total pay_in_full")
def s14(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    s = _pay_in_full(db, o, cents=18000); s.total_amount_cents = None; db.flush()

@shape("instalments with configured upfront")
def s15(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    s = _instalments(db, o, each=1800, count=10, total=18000)
    s.upfront_amount_cents = 5000; db.flush()

@shape("USD option")
def s16(db, space, series):
    o = _option(db, space); o.currency = "USD"; db.flush()
    _grant(db, o, "event_series", series.id, sessions_per_week=1)
    s = _pay_in_full(db, o, cents=18000); s.currency = "USD"; db.flush()

@shape("three options mixed")
def s17(db, space, series):
    for i, c in enumerate((12000, 18000, 24000)):
        o = _option(db, space, name=f"P{i}", position=i)
        _grant(db, o, "event_series", series.id, sessions_per_week=1)
        _pay_in_full(db, o, cents=c)
        if i == 1:
            _instalments(db, o, each=1800, count=10, total=18000)

@shape("manual schedule")
def s18(db, space, series):
    o = _option(db, space); _grant(db, o, "event_series", series.id, sessions_per_week=1)
    s = _pay_in_full(db, o, cents=18000); s.schedule_type = "manual"; db.flush()



@pytest.mark.parametrize("plans_enabled", [True, False], ids=["plans_on", "plans_off"])
@pytest.mark.parametrize("name,build", SHAPES, ids=[n for n, _ in SHAPES])
def test_the_resolver_agrees_on_every_shape(
    db, make_space, name, build, plans_enabled,
):
    """One assertion, run across the whole matrix.

    A disagreement here names the shape, the Option, the schedule and
    the field — which is the whole reason the comparison reports
    structured differences rather than a boolean.
    """
    space = make_space()
    series = _series(db, space)
    build(db, space, series)
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled",
        plans_enabled,
    ):
        report = _run(db, series, space)
    assert report.agrees, [
        d.as_log() for d in (
            *report.differences,
            *report.missing_from_resolver,
            *report.extra_in_resolver,
        )
    ]
