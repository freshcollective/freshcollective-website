"""Stage 1A — the purchase-arrangement resolver.

The resolver exists to replace a question, not an answer. "What
``pricing_mode`` is this Pathway in?" cannot describe a Pathway that is
legitimately sold two ways, and the one time two prices coexisted a
member was charged $5 for a $2 product. So every arrangement now gets
its own identity and its own price, and the price is re-derived from the
record that owns it.

What this file proves, in order of how much it matters:

1. **The $5/$2 incident, as two arrangements.** Both prices present,
   both distinct, neither inferred from a mode. ``TestTheMispricingIncident``.
2. **No price substitution.** Naming one arrangement never yields
   another's price, and an arrangement from a different experience or
   Collective is not found rather than silently repriced.
3. **Schedules stay attached to their Option.** EMBODY Awaken is $180
   in full *or* 10 × $18; a total and an instalment are never read as
   each other.
4. **Archived is not draft is not published.** An archived Option is
   reportable as a historical access source and refused for a new
   purchase — the distinction that keeps historical buyers whole
   without putting a retired price back on sale.
5. **It agrees with the till.** Cross-checked against
   ``_schedule_is_member_checkoutable`` on every shape, so Stage 1A
   cannot become the third opinion Stage 0 removed.
6. **Nothing calls it.** Asserted by scanning the source of every
   checkout, fulfilment and billing-lifecycle module.

Fixtures follow ``test_pathway_pricing_mode_adoption`` — the file that
records the original incident — so the two read as one story.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from unittest.mock import patch

import pytest

from app.models.offering import Offering, OfferingStatus
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import PaymentOptionGrant
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import EventSeries, Pathway, PathwayType
from app.services import purchase_arrangements as pa


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _pathway(
    db, space, *, price_cents: int | None = None, access_type: str = "one_time",
    pricing_mode: str = "legacy", status: str = "active",
    currency: str = "AUD", title: str = "Know Yourself — Human Design",
) -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id, slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status=status, access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode=pricing_mode, price_cents=price_cents, currency=currency,
    )
    db.add(p)
    db.flush()
    return p


def _series(db, space, *, title: str = "Term 4 2026") -> EventSeries:
    from datetime import datetime, timedelta
    s = EventSeries(
        id=_uid("es"), space_id=space.id, slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title, starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=70), status="published",
    )
    db.add(s)
    db.flush()
    return s


def _offering(db, space, *, price_cents: int = 1500) -> Offering:
    o = Offering(
        id=_uid("of"), space_id=space.id, slug=f"of-{uuid.uuid4().hex[:8]}",
        title="A Download", status=OfferingStatus.published.value,
        pricing_kind="one_time", price_cents=price_cents,
    )
    db.add(o)
    db.flush()
    return o


def _option(
    db, space, *, name: str = "Personal Leadership Bundle",
    status=PaymentOptionStatus.published, position: int = 0,
    currency: str = "AUD",
) -> PaymentOption:
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, attaches_to_kind="space",
        attaches_to_id=space.id, name=name,
        payment_type=PaymentOptionType.one_time, status=status,
        currency=currency, position=position,
    )
    db.add(opt)
    db.flush()
    return opt


def _pay_in_full(db, option, *, cents: int, currency: str = "AUD",
                 status: str = "published", name: str = "Pay in full",
                 position: int = 0) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="pay_in_full", status=status,
        total_amount_cents=cents, currency=currency, position=position,
    )
    db.add(s)
    db.flush()
    return s


def _instalments(db, option, *, each: int, count: int, interval: str = "week",
                 currency: str = "AUD", status: str = "published",
                 name: str = "Weekly payments", position: int = 1,
                 total: int | None = None) -> PaymentOptionSchedule:
    s = PaymentOptionSchedule(
        id=_uid("pos"), payment_option_id=option.id, name=name,
        schedule_type="recurring_installments", status=status,
        total_amount_cents=total if total is not None else each * count,
        installment_amount_cents=each, installment_count=count,
        interval=interval, stripe_interval=interval, stripe_interval_count=1,
        currency=currency, position=position,
    )
    db.add(s)
    db.flush()
    return s


def _grant(db, option, kind: str, target_id: str, **kw) -> PaymentOptionGrant:
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
def gate_on():
    with patch(
        "app.core.config.settings.finite_plan_member_checkout_enabled", True,
    ):
        yield


# ---------------------------------------------------------------------------
# 1. The incident
# ---------------------------------------------------------------------------


class TestTheMispricingIncident:
    """Pathway A at $5, Option B granting it at $2. The resolver must
    return two arrangements, not one answer.

    This constructs a state the production write rules deliberately
    prevent — linking a published Option flips ``pricing_mode`` and
    closes the direct door. That is the point: the resolver has to be
    correct about the state *before* Stage 2 makes it reachable, and
    proving it here is how we earn the right to make it reachable.
    Nothing in this file relaxes those write rules.
    """

    @pytest.fixture
    def scene(self, db, space):
        pathway = _pathway(db, space, price_cents=500)
        option = _option(db, space, name="$2 Option")
        _pay_in_full(db, option, cents=200)
        _grant(db, option, "pathway", pathway.id)
        # The production rule would have flipped this. Left on
        # ``legacy`` so the resolver is tested against the exact
        # ambiguous row the incident had.
        assert pathway.pricing_mode == "legacy"
        db.flush()
        return pathway, option

    def test_both_prices_are_present_and_distinct(self, db, scene):
        pathway, _option = scene
        found = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
        )
        assert found is not None
        prices = {a.arrangement_id: a.total_amount_cents for a in found.arrangements}
        assert len(prices) == 2
        assert prices[pa.direct_arrangement_id("pathway", pathway.id)] == 500
        option_arrangement = next(
            a for a in found.arrangements if a.source == pa.SOURCE_PAYMENT_OPTION
        )
        assert option_arrangement.total_amount_cents == 200

    def test_neither_price_is_inferred_from_pricing_mode(self, db, scene):
        """The resolver never reads the column that caused the bug."""
        pathway, _option = scene
        src = pathlib.Path(
            pa.__file__,
        ).read_text()
        tree = ast.parse(src)
        reads = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "pricing_mode"
        ]
        assert reads == [], "the resolver reads pricing_mode"

        # And behaviourally: the answer does not move when the mode does.
        before = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
        )
        pathway.pricing_mode = "payment_options"
        db.flush()
        after = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
        )
        assert before.arrangements == after.arrangements

    def test_the_direct_price_is_not_replaced_by_the_bundle_price(self, db, scene):
        pathway, _option = scene
        direct = pa.resolve_arrangement(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
            arrangement_id=pa.direct_arrangement_id("pathway", pathway.id),
        )
        assert direct.total_amount_cents == 500
        assert direct.source == pa.SOURCE_DIRECT
        assert direct.payment_option_id is None

    def test_the_bundle_price_is_not_replaced_by_the_direct_price(self, db, scene):
        pathway, option = scene
        found = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
        )
        bundle = next(
            a for a in found.arrangements if a.source == pa.SOURCE_PAYMENT_OPTION
        )
        again = pa.resolve_arrangement(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
            arrangement_id=bundle.arrangement_id,
        )
        assert again.total_amount_cents == 200
        assert again.payment_option_id == option.id

    def test_each_arrangement_has_its_own_identity(self, db, scene):
        pathway, _option = scene
        found = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
        )
        ids = [a.arrangement_id for a in found.arrangements]
        assert len(ids) == len(set(ids))
        # Derivable rather than opaque, so a client can hand one back.
        assert all(i.startswith(("direct:", "option:")) for i in ids)

    def test_the_individual_purchase_is_offered_first(self, db, scene):
        """The agreed presentation decision, as a stable order."""
        pathway, _option = scene
        found = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
        )
        assert found.arrangements[0].source == pa.SOURCE_DIRECT
        assert found.direct is not None


# ---------------------------------------------------------------------------
# 2. No substitution
# ---------------------------------------------------------------------------


class TestNoPriceSubstitution:
    def test_an_arrangement_from_another_pathway_is_not_found(self, db, space):
        a = _pathway(db, space, price_cents=500)
        b = _pathway(db, space, price_cents=900)
        with pytest.raises(pa.ArrangementNotFound):
            pa.resolve_arrangement(
                db, kind=pa.KIND_PATHWAY, experience_id=a.id,
                arrangement_id=pa.direct_arrangement_id("pathway", b.id),
            )

    def test_an_option_from_another_collective_is_not_found(self, db, space, make_space):
        """Scoped by Collective, so a corrupted grant row cannot leak
        one Collective's price onto another's experience."""
        mine = _pathway(db, space, price_cents=500)
        other_space = make_space()
        theirs = _option(db, other_space, name="Someone else's")
        s = _pay_in_full(db, theirs, cents=100)
        _grant(db, theirs, "pathway", mine.id)
        db.flush()
        with pytest.raises(pa.ArrangementNotFound):
            pa.resolve_arrangement(
                db, kind=pa.KIND_PATHWAY, experience_id=mine.id,
                arrangement_id=pa.option_arrangement_id(theirs.id, s.id),
            )

    def test_a_fabricated_arrangement_id_is_not_found(self, db, space):
        p = _pathway(db, space, price_cents=500)
        for bogus in (
            "option:po_nope:schedule:sc_nope",
            "direct:pathway:pw_nope",
            "", "direct:", "nonsense",
        ):
            with pytest.raises(pa.ArrangementNotFound):
                pa.resolve_arrangement(
                    db, kind=pa.KIND_PATHWAY, experience_id=p.id,
                    arrangement_id=bogus,
                )

    def test_resolve_raises_rather_than_returning_a_default(self, db, space):
        """A caller cannot fall through to a fallback price by
        forgetting to check a return value."""
        p = _pathway(db, space, price_cents=500)
        with pytest.raises(pa.ArrangementNotFound):
            pa.resolve_arrangement(
                db, kind=pa.KIND_PATHWAY, experience_id=p.id,
                arrangement_id="direct:pathway:somebody-else",
            )

    def test_a_missing_experience_raises(self, db):
        with pytest.raises(pa.ArrangementNotFound):
            pa.resolve_arrangement(
                db, kind=pa.KIND_PATHWAY, experience_id="pw_missing",
                arrangement_id="anything",
            )
        assert pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id="pw_missing",
        ) is None

    def test_an_unknown_kind_raises(self, db):
        with pytest.raises(pa.UnknownExperienceKind):
            pa.arrangements_for(db, kind="collective", experience_id="x")

    def test_two_options_at_different_prices_stay_apart(self, db, space):
        p = _pathway(db, space, access_type="included")
        cheap = _option(db, space, name="Cheap", position=0)
        _pay_in_full(db, cheap, cents=4900)
        _grant(db, cheap, "pathway", p.id)
        dear = _option(db, space, name="Dear", position=1)
        _pay_in_full(db, dear, cents=9900)
        _grant(db, dear, "pathway", p.id)
        db.flush()

        found = pa.arrangements_for(db, kind=pa.KIND_PATHWAY, experience_id=p.id)
        by_name = {a.name: a.total_amount_cents for a in found.arrangements}
        assert by_name == {"Cheap": 4900, "Dear": 9900}


# ---------------------------------------------------------------------------
# 3. Options and their schedules
# ---------------------------------------------------------------------------


class TestSchedulesStayAttachedToTheirOption:
    def test_pay_in_full_only(self, db, space):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=18000)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        found = pa.arrangements_for(db, kind=pa.KIND_PATHWAY, experience_id=p.id)
        assert len(found.arrangements) == 1
        a = found.arrangements[0]
        assert a.schedule_type == "pay_in_full"
        assert a.total_amount_cents == 18000
        assert a.upfront_amount_cents == 18000
        assert a.installment_amount_cents is None
        assert a.installment_count is None
        assert a.is_instalment_plan is False

    def test_instalments_only(self, db, space, gate_on):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        _instalments(db, opt, each=1800, count=10)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).arrangements[0]
        assert a.schedule_type == "recurring_installments"
        assert a.total_amount_cents == 18000
        assert a.installment_amount_cents == 1800
        assert a.installment_count == 10
        assert a.interval == "week"
        # What actually leaves the account first — not the total.
        assert a.upfront_amount_cents == 1800
        assert a.is_instalment_plan is True

    def test_the_embody_awaken_shape(self, db, space, gate_on):
        """One Option, two schedules, verified against production:
        $180 in full or 10 weekly payments of $18, granting a Series
        and two Pathways."""
        series = _series(db, space)
        home = _pathway(db, space, access_type="included", title="Home Practice")
        inperson = _pathway(db, space, access_type="included", title="In-Person Sessions")
        opt = _option(db, space, name="💫 Awaken — 1 Session per week")
        _pay_in_full(db, opt, cents=18000, position=0)
        _instalments(db, opt, each=1800, count=10, position=1)
        _grant(db, opt, "event_series", series.id, sessions_per_week=1, total_sessions=10)
        _grant(db, opt, "pathway", home.id)
        _grant(db, opt, "pathway", inperson.id)
        db.flush()

        found = pa.arrangements_for(
            db, kind=pa.KIND_SERIES, experience_id=series.id,
        )
        assert len(found.arrangements) == 2
        full, plan = found.arrangements
        # Two arrangements, one Option — the relationship preserved.
        assert full.payment_option_id == plan.payment_option_id == opt.id
        assert full.payment_option_schedule_id != plan.payment_option_schedule_id
        assert full.arrangement_id != plan.arrangement_id
        # Same commitment, two shapes. Never read as each other.
        assert full.total_amount_cents == plan.total_amount_cents == 18000
        assert full.installment_amount_cents is None
        assert plan.installment_amount_cents == 1800
        assert plan.installment_count == 10
        # Both are the same bundle.
        for a in (full, plan):
            assert a.is_bundle is True
            kinds = sorted(i.kind for i in a.included)
            assert kinds == ["event_series", "pathway", "pathway"]
            titles = {i.title for i in a.included}
            assert titles == {"Term 4 2026", "Home Practice", "In-Person Sessions"}

    def test_series_allowances_come_through_on_the_grant(self, db, space):
        series = _series(db, space)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=30600)
        _grant(db, opt, "event_series", series.id,
               sessions_per_week=2, total_sessions=20)
        db.flush()
        a = pa.arrangements_for(
            db, kind=pa.KIND_SERIES, experience_id=series.id,
        ).arrangements[0]
        inc = next(i for i in a.included if i.kind == "event_series")
        assert inc.sessions_per_week == 2
        assert inc.total_sessions == 20

    def test_one_pathway_is_not_a_bundle(self, db, space):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=4900)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).arrangements[0]
        assert a.is_bundle is False
        assert len(a.included) == 1

    def test_multiple_pathways_is_a_bundle(self, db, space):
        a_pw = _pathway(db, space, access_type="included", title="One")
        b_pw = _pathway(db, space, access_type="included", title="Two")
        c_pw = _pathway(db, space, access_type="included", title="Three")
        opt = _option(db, space, name="Personal Leadership Bundle")
        _pay_in_full(db, opt, cents=9900)
        for pw in (a_pw, b_pw, c_pw):
            _grant(db, opt, "pathway", pw.id)
        db.flush()
        found = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=a_pw.id,
        )
        arrangement = found.arrangements[0]
        assert arrangement.is_bundle is True
        assert {i.title for i in arrangement.included} == {"One", "Two", "Three"}
        # The bundle is found from any of its members.
        for pw in (b_pw, c_pw):
            other = pa.arrangements_for(
                db, kind=pa.KIND_PATHWAY, experience_id=pw.id,
            )
            assert other.arrangements[0].payment_option_id == opt.id

    def test_the_schedule_currency_wins_over_the_option_currency(self, db, space):
        """The Option's authoring fields are frequently NULL in
        production because the commerce UI treats schedules as the
        source of truth — the bug ``purchase_schedule_view`` fixed."""
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space, currency="AUD")
        _pay_in_full(db, opt, cents=5000, currency="USD")
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).arrangements[0]
        assert a.currency == "USD"

    def test_a_manual_schedule_is_reported_and_refused(self, db, space):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        s = PaymentOptionSchedule(
            id=_uid("pos"), payment_option_id=opt.id, name="Invoice me",
            schedule_type="manual", status="published",
            total_amount_cents=5000, currency="AUD",
        )
        db.add(s)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).arrangements[0]
        assert a.available_for_new_purchase is False
        assert a.unavailable_reason == pa.REASON_SCHEDULE_UNSUPPORTED


# ---------------------------------------------------------------------------
# 4. Availability, and the archived distinction
# ---------------------------------------------------------------------------


class TestAvailability:
    def _one(self, db, pathway):
        return pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=pathway.id,
        ).arrangements[0]

    def test_a_published_pay_in_full_option_is_purchasable(self, db, space):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=4900)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = self._one(db, p)
        assert a.available_for_new_purchase is True
        assert a.unavailable_reason is None
        assert a.is_historical_source is False

    def test_a_draft_option_is_not_purchasable(self, db, space):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space, status=PaymentOptionStatus.draft)
        _pay_in_full(db, opt, cents=4900)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = self._one(db, p)
        assert a.available_for_new_purchase is False
        assert a.unavailable_reason == pa.REASON_OPTION_DRAFT
        # A draft never unlocked anything, so it is not history either.
        assert a.is_historical_source is False

    def test_an_archived_option_is_history_not_a_new_sale(self, db, space):
        """The distinction the brief asks for explicitly. Archived
        Options keep unlocking what their buyers bought —
        ``unlock_option_ids_for_pathway`` accepts ``archived`` — and
        must not become newly purchasable."""
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space, status=PaymentOptionStatus.archived)
        _pay_in_full(db, opt, cents=4900)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = self._one(db, p)
        assert a.available_for_new_purchase is False
        assert a.unavailable_reason == pa.REASON_OPTION_ARCHIVED
        assert a.is_historical_source is True
        # And its price is still readable, so a historical purchase can
        # be explained rather than guessed at.
        assert a.total_amount_cents == 4900

    def test_an_archived_option_never_reaches_the_purchasable_list(self, db, space):
        p = _pathway(db, space, access_type="included")
        live = _option(db, space, name="Live", position=0)
        _pay_in_full(db, live, cents=4900)
        _grant(db, live, "pathway", p.id)
        gone = _option(db, space, name="Retired", status=PaymentOptionStatus.archived, position=1)
        _pay_in_full(db, gone, cents=1900)
        _grant(db, gone, "pathway", p.id)
        db.flush()
        found = pa.arrangements_for(db, kind=pa.KIND_PATHWAY, experience_id=p.id)
        assert len(found.arrangements) == 2
        assert [a.name for a in found.purchasable] == ["Live"]

    def test_a_draft_schedule_is_not_purchasable(self, db, space):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=4900, status="draft")
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = self._one(db, p)
        assert a.unavailable_reason == pa.REASON_SCHEDULE_DRAFT

    def test_instalments_hide_when_the_platform_gate_is_off(self, db, space):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        _instalments(db, opt, each=1800, count=10)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", False,
        ):
            a = self._one(db, p)
        assert a.available_for_new_purchase is False
        assert a.unavailable_reason == pa.REASON_INSTALMENTS_NOT_ENABLED

    def test_a_structurally_invalid_plan_is_refused(self, db, space, gate_on):
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space)
        _instalments(db, opt, each=1800, count=1)  # a plan needs 2+
        _grant(db, opt, "pathway", p.id)
        db.flush()
        a = self._one(db, p)
        assert a.unavailable_reason == pa.REASON_SCHEDULE_INVALID

    def test_the_reason_a_creator_can_act_on_wins(self, db, space):
        """An archived Option with a draft schedule is archived.
        Telling them to publish the schedule would be useless."""
        p = _pathway(db, space, access_type="included")
        opt = _option(db, space, status=PaymentOptionStatus.archived)
        _pay_in_full(db, opt, cents=4900, status="draft")
        _grant(db, opt, "pathway", p.id)
        db.flush()
        assert self._one(db, p).unavailable_reason == pa.REASON_OPTION_ARCHIVED


# ---------------------------------------------------------------------------
# 5. Stage 0's protection, reused not restated
# ---------------------------------------------------------------------------


class TestStage0ProtectionsIntact:
    def test_a_gathering_grant_makes_every_schedule_unavailable(self, db, space, gate_on, make_event):
        """Stage 0's rule, reached through the resolver. One Gathering
        spoils the bundle, on both payment methods."""
        p = _pathway(db, space, access_type="included")
        ev = make_event(space=space)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=4900, position=0)
        _instalments(db, opt, each=1000, count=5, position=1)
        _grant(db, opt, "pathway", p.id)
        _grant(db, opt, "gathering", ev.id)
        db.flush()
        found = pa.arrangements_for(db, kind=pa.KIND_PATHWAY, experience_id=p.id)
        assert len(found.arrangements) == 2
        for a in found.arrangements:
            assert a.available_for_new_purchase is False
            assert a.unavailable_reason == pa.REASON_UNSUPPORTED_INCLUSION
        assert found.purchasable == ()

    def test_a_gathering_experience_sees_its_own_option_as_unavailable(
        self, db, space, gate_on, make_event,
    ):
        """Asked about the Gathering itself, the Option is reported —
        a creator needs to see it — and refused."""
        ev = make_event(space=space)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=300000)
        _grant(db, opt, "gathering", ev.id)
        db.flush()
        found = pa.arrangements_for(db, kind=pa.KIND_GATHERING, experience_id=ev.id)
        option_arrangements = [
            a for a in found.arrangements if a.source == pa.SOURCE_PAYMENT_OPTION
        ]
        assert len(option_arrangements) == 1
        assert option_arrangements[0].unavailable_reason == pa.REASON_UNSUPPORTED_INCLUSION
        assert option_arrangements[0].available_for_new_purchase is False

    def test_the_resolver_agrees_with_the_till(self, db, space, make_event):
        """The cross-check that stops Stage 1A becoming a third
        opinion. For every Option arrangement, in both gate positions,
        the resolver's availability must equal
        ``_schedule_is_member_checkoutable``."""
        from app.spaces.routes import _schedule_is_member_checkoutable

        p = _pathway(db, space, access_type="included")
        series = _series(db, space)
        ev = make_event(space=space)

        shapes: list[tuple[str, PaymentOption]] = []
        for label, status, grants, scheds in (
            ("pathway/full", PaymentOptionStatus.published, [("pathway", p.id)], ["full"]),
            ("pathway/plan", PaymentOptionStatus.published, [("pathway", p.id)], ["plan"]),
            ("series/both", PaymentOptionStatus.published, [("event_series", series.id)], ["full", "plan"]),
            ("mixed/both", PaymentOptionStatus.published,
             [("pathway", p.id), ("event_series", series.id)], ["full", "plan"]),
            ("gathering/full", PaymentOptionStatus.published, [("gathering", ev.id)], ["full"]),
            ("gathering/plan", PaymentOptionStatus.published, [("gathering", ev.id)], ["plan"]),
            ("draft/full", PaymentOptionStatus.draft, [("pathway", p.id)], ["full"]),
            ("archived/full", PaymentOptionStatus.archived, [("pathway", p.id)], ["full"]),
            ("legacy/full", PaymentOptionStatus.published, [], ["full"]),
        ):
            opt = _option(db, space, name=label, status=status)
            for i, kind_id in enumerate(grants):
                _grant(db, opt, kind_id[0], kind_id[1])
            for i, s in enumerate(scheds):
                if s == "full":
                    _pay_in_full(db, opt, cents=5000, position=i)
                else:
                    _instalments(db, opt, each=1000, count=5, position=i)
            if not grants:
                # Legacy pre-grants shape, linked by the old column.
                opt.pathway_id = p.id
            shapes.append((label, opt))
        db.flush()

        for gate in (True, False):
            with patch(
                "app.core.config.settings."
                "finite_plan_member_checkout_enabled", gate,
            ):
                found = pa.arrangements_for(
                    db, kind=pa.KIND_PATHWAY, experience_id=p.id,
                )
                for a in found.arrangements:
                    if a.source != pa.SOURCE_PAYMENT_OPTION:
                        continue
                    option = db.get(PaymentOption, a.payment_option_id)
                    schedule = db.get(
                        PaymentOptionSchedule, a.payment_option_schedule_id,
                    )
                    till = _schedule_is_member_checkoutable(schedule, option)
                    # The till does not know about Option status, so
                    # compare only where the resolver's extra knowledge
                    # is not the deciding factor.
                    opt_status = getattr(option.status, "value", option.status)
                    if opt_status != "published":
                        assert a.available_for_new_purchase is False
                        continue
                    assert a.available_for_new_purchase is till, (
                        f"{a.name} {a.schedule_type} gate={gate}: "
                        f"resolver={a.available_for_new_purchase} till={till}"
                    )


# ---------------------------------------------------------------------------
# 6. Direct prices per experience kind
# ---------------------------------------------------------------------------


class TestDirectPrices:
    def test_a_free_pathway_has_no_direct_arrangement(self, db, space):
        p = _pathway(db, space, access_type="free")
        found = pa.arrangements_for(db, kind=pa.KIND_PATHWAY, experience_id=p.id)
        assert found.direct is None
        assert found.arrangements == ()

    def test_an_included_pathway_has_no_direct_arrangement(self, db, space):
        p = _pathway(db, space, access_type="included")
        assert pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).direct is None

    def test_a_subscription_pathway_has_no_direct_arrangement(self, db, space):
        """``access_type='subscription'`` is settable but
        ``/api/checkout/pathway`` refuses anything but ``one_time``, so
        an arrangement here would be one nothing can sell."""
        p = _pathway(db, space, access_type="subscription", price_cents=2900)
        assert pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).direct is None

    def test_a_one_time_pathway_with_no_price_is_reported_unavailable(self, db, space):
        p = _pathway(db, space, access_type="one_time", price_cents=None)
        d = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).direct
        assert d is not None
        assert d.available_for_new_purchase is False
        assert d.unavailable_reason == pa.REASON_PRICE_NOT_SET

    def test_a_zero_price_is_free_and_refused_as_a_sale(self, db, space):
        p = _pathway(db, space, access_type="one_time", price_cents=0)
        d = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).direct
        assert d.is_free is True
        assert d.unavailable_reason == pa.REASON_PRICE_INVALID

    def test_a_negative_price_is_refused(self, db, space):
        p = _pathway(db, space, access_type="one_time", price_cents=-100)
        d = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).direct
        assert d.unavailable_reason == pa.REASON_PRICE_INVALID

    def test_an_archived_pathway_is_not_newly_sellable(self, db, space):
        p = _pathway(db, space, access_type="one_time", price_cents=4900,
                     status="archived")
        d = pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).direct
        assert d.unavailable_reason == pa.REASON_EXPERIENCE_UNAVAILABLE

    def test_the_pathway_currency_is_preserved(self, db, space):
        p = _pathway(db, space, access_type="one_time", price_cents=4900,
                     currency="NZD")
        assert pa.arrangements_for(
            db, kind=pa.KIND_PATHWAY, experience_id=p.id,
        ).direct.currency == "NZD"

    def test_a_paid_gathering_ticket_is_a_direct_arrangement(self, db, space, make_event):
        ev = make_event(
            space=space, booking_access_type="paid_separately",
            ticket_price_cents=300000, ticket_currency="AUD",
            is_published=True,
        )
        db.flush()
        d = pa.arrangements_for(
            db, kind=pa.KIND_GATHERING, experience_id=ev.id,
        ).direct
        assert d is not None
        assert d.total_amount_cents == 300000
        assert d.currency == "AUD"
        assert d.available_for_new_purchase is True
        assert d.schedule_type == pa.SCHEDULE_DIRECT

    def test_a_free_gathering_has_no_direct_arrangement(self, db, space, make_event):
        """Every other ``booking_access_type`` is an access rule, not a
        price."""
        for access in (
            "included_with_collective", "included_with_pathway",
            "included_with_series", "invitation_only",
        ):
            ev = make_event(
                space=space, booking_access_type=access,
                ticket_price_cents=None, ticket_currency=None,
            )
            db.flush()
            assert pa.arrangements_for(
                db, kind=pa.KIND_GATHERING, experience_id=ev.id,
            ).direct is None

    def test_a_recurring_occurrence_is_priced_as_an_individual_gathering(
        self, db, space, make_event,
    ):
        """Recurrence is provenance, not a purchase concept. Each
        occurrence carries its own ticket price and resolves on its
        own."""
        tag = str(uuid.uuid4())
        a = make_event(
            space=space, booking_access_type="paid_separately",
            ticket_price_cents=2000, ticket_currency="AUD", is_published=True,
        )
        b = make_event(
            space=space, booking_access_type="paid_separately",
            ticket_price_cents=2000, ticket_currency="AUD", is_published=True,
        )
        a.recurrence_series_id = tag
        b.recurrence_series_id = tag
        db.flush()
        for ev in (a, b):
            found = pa.arrangements_for(
                db, kind=pa.KIND_GATHERING, experience_id=ev.id,
            )
            assert found.direct.total_amount_cents == 2000
            assert found.direct.experience_id == ev.id
        # Two occurrences, two identities — never one shared price.
        ids = {
            pa.arrangements_for(
                db, kind=pa.KIND_GATHERING, experience_id=ev.id,
            ).direct.arrangement_id
            for ev in (a, b)
        }
        assert len(ids) == 2

    def test_an_offering_has_no_separate_direct_arrangement(self, db, space):
        """Its Pricing tab provisions a mirror PaymentOption rather
        than a standalone price path, so emitting a direct arrangement
        as well would list the same price twice."""
        o = _offering(db, space, price_cents=1500)
        found = pa.arrangements_for(db, kind=pa.KIND_OFFERING, experience_id=o.id)
        assert found is not None
        assert found.direct is None

    def test_an_offering_is_found_through_its_provisioned_option(self, db, space):
        o = _offering(db, space, price_cents=1500)
        opt = _option(db, space, name=o.title)
        _pay_in_full(db, opt, cents=1500)
        _grant(db, opt, "offering", o.id)
        db.flush()
        found = pa.arrangements_for(db, kind=pa.KIND_OFFERING, experience_id=o.id)
        assert len(found.arrangements) == 1
        a = found.arrangements[0]
        assert a.total_amount_cents == 1500
        assert a.available_for_new_purchase is True
        assert [i.kind for i in a.included] == ["offering"]


# ---------------------------------------------------------------------------
# 7. Nothing calls it
# ---------------------------------------------------------------------------


APP_ROOT = pathlib.Path(__file__).resolve().parent.parent / "app"

#: The modules that must not consult the resolver during Stage 1A,
#: grouped by what they are responsible for. These are the services
#: that carry continuing payment obligations — if any of them read a
#: newly-resolved price, an existing agreement could change.
PROTECTED = {
    "live checkout": [
        "checkout/routes.py",
        "services/checkout_orchestration.py",
        "services/checkout_supersession.py",
        "services/discount_application.py",
        "services/discount_stripe_sessions.py",
    ],
    "fulfilment and access": [
        "services/purchase_fulfilment.py",
        "services/access_grant_records.py",
        "services/pathway_access.py",
        "services/series_access.py",
        "services/active_access.py",
    ],
    "instalment lifecycle": [
        "services/finite_plan_lifecycle.py",
        "services/finite_plan_orchestration.py",
        "services/finite_plan_reconciler.py",
        "services/finite_plan_release.py",
        "services/finite_plan_repair.py",
        "services/finite_plan_end_reconciliation.py",
        "services/stripe_finite_plan.py",
        "webhooks/finite_plan_handlers.py",
    ],
    "creator subscriptions": [
        "services/creator_subscription_lifecycle.py",
        "services/stripe_creator_billing.py",
        "webhooks/creator_billing_handlers.py",
    ],
    "gathering tickets and capacity": [
        "services/gathering_tickets.py",
        "services/gathering_booking_rules.py",
        "services/ticket_pricing.py",
    ],
    "refunds": [
        "services/refund_reconciliation.py",
        "services/refund_reversal.py",
        "services/stripe_refund_orchestration.py",
        "webhooks/refund_handlers.py",
    ],
}


def _mentions_resolver(path: pathlib.Path) -> bool:
    """Does this module import or call the resolver?

    Parsed rather than grepped, so a mention inside a docstring or a
    comment — which is how a future reader would legitimately refer to
    it — does not read as a call. Ban the use, not the word.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "purchase_arrangements" in node.module:
                return True
        if isinstance(node, ast.Import):
            if any("purchase_arrangements" in a.name for a in node.names):
                return True
        if isinstance(node, ast.Attribute) and node.attr in (
            "arrangements_for", "resolve_arrangement",
        ):
            return True
        if isinstance(node, ast.Name) and node.id in (
            "arrangements_for", "resolve_arrangement",
        ):
            return True
    return False


#: Modules authorised to call the resolver, newest last.
#:
#: Stage 1A's defining property was that this list was empty — a
#: tested, unused service. Stage 1B integrates it one surface at a
#: time, and each entry here is a deliberate authorisation rather than
#: a relaxation: the protected modules below stay protected, and a
#: caller appearing anywhere else still fails.
AUTHORISED_CALLERS: frozenset[str] = frozenset({
    # Stage 1B.1 — the creator-facing, read-only purchase preview.
    # Reads arrangements for one experience the caller already manages.
    # Buys nothing, writes nothing, and is not reachable by a member.
    "services/creator_purchase_preview.py",
    # Stage 1B.2A — the shadow comparison. Reads arrangements purely to
    # compare them against the projection that actually serves members,
    # behind a flag that is off by default. Its result is a log line:
    # it cannot shape a response, and the member endpoint that calls it
    # does so after its own response is built and swallows anything it
    # raises.
    "services/purchase_arrangement_shadow.py",
})


class TestTheResolverHasNoProductionCallers:
    """Who may call the resolver, and who may not.

    The list of permitted callers is explicit and short. Everything
    that carries a continuing payment obligation is on the protected
    list and must never appear on it.
    """

    @pytest.mark.parametrize(
        "area,rel",
        [(area, rel) for area, rels in PROTECTED.items() for rel in rels],
        ids=[rel for rels in PROTECTED.values() for rel in rels],
    )
    def test_protected_module_does_not_call_the_resolver(self, area, rel):
        path = APP_ROOT / rel
        assert path.exists(), f"{rel} has moved; update PROTECTED"
        assert not _mentions_resolver(path), (
            f"{rel} ({area}) now calls the purchase-arrangement resolver. "
            "Stage 1A is explicitly not authorised to change live "
            "payment behaviour."
        )

    def test_only_authorised_modules_call_it(self):
        """Broader than the list above: every module in ``app/`` that
        calls the resolver must be a named, authorised caller.

        The protected list names the areas worth a specific failure
        message; this catches a caller appearing anywhere else at all —
        which is how an unreviewed integration would arrive.
        """
        callers = {
            p.relative_to(APP_ROOT).as_posix()
            for p in APP_ROOT.rglob("*.py")
            if p.name != "purchase_arrangements.py" and _mentions_resolver(p)
        }
        unexpected = sorted(callers - AUTHORISED_CALLERS)
        assert unexpected == [], (
            f"unauthorised resolver callers: {unexpected}. Integration is "
            "staged deliberately — add the module to AUTHORISED_CALLERS "
            "only as part of a stage that authorises it."
        )

    def test_every_authorised_caller_still_exists(self):
        """A stale entry would silently widen the permission above."""
        missing = sorted(
            rel for rel in AUTHORISED_CALLERS if not (APP_ROOT / rel).exists()
        )
        assert missing == [], f"AUTHORISED_CALLERS is stale: {missing}"

    @pytest.mark.parametrize(
        "rel",
        sorted(AUTHORISED_CALLERS),
        ids=lambda r: r.rsplit("/", 1)[-1],
    )
    def test_an_authorised_caller_cannot_mutate_or_bill(self, rel):
        """Reading arrangements is permitted; becoming a way to buy one
        is not. Asserted on the AST of every authorised caller rather
        than on its docstring: no session mutation, and no Stripe."""
        path = APP_ROOT / rel
        tree = ast.parse(path.read_text())
        banned = {
            "commit", "flush", "add", "add_all", "delete", "merge",
            "with_for_update", "rollback", "bulk_save_objects",
        }
        found = sorted({
            n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and n.attr in banned
            and isinstance(n.value, ast.Name)
            and n.value.id == "db"
        })
        assert found == [], f"{rel} may mutate the session: {found}"

        identifiers = {
            n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)
        } | {
            n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        } | {
            alias.name.lower()
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for alias in n.names
        } | {
            (n.module or "").lower()
            for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        }
        stripe_refs = sorted(i for i in identifiers if "stripe" in i)
        assert stripe_refs == [], f"{rel} touches Stripe: {stripe_refs}"

    def test_the_authorised_caller_is_not_a_payment_path(self):
        """The preview is allowed to read arrangements; it is not
        allowed to become a way to buy one. Asserted on the AST rather
        than by trusting the docstring: no session mutation, and no
        Stripe."""
        path = APP_ROOT / "services" / "creator_purchase_preview.py"
        tree = ast.parse(path.read_text())
        banned = {
            "commit", "flush", "add", "add_all", "delete", "merge",
            "with_for_update", "rollback", "bulk_save_objects",
        }
        found = sorted({
            n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and n.attr in banned
            and isinstance(n.value, ast.Name)
            and n.value.id == "db"
        })
        assert found == [], f"the preview may mutate the session: {found}"

        # No Stripe, asserted on identifiers rather than on the text:
        # the module's docstring explains the two-key *Stripe live
        # mode* guard at length, and a substring check on the source
        # flags that explanation. Ban the use, not the word.
        identifiers = {
            n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)
        } | {
            n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        } | {
            alias.name.lower()
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for alias in n.names
        } | {
            (n.module or "").lower()
            for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        }
        stripe_refs = sorted(i for i in identifiers if "stripe" in i)
        assert stripe_refs == [], f"the preview touches Stripe: {stripe_refs}"

    def test_the_resolver_writes_nothing(self):
        """No commit, flush, add, delete or lock on the session. A
        pricing read that can mutate is a pricing read that can
        corrupt.

        Matched against calls *on the session* specifically. An earlier
        version banned the method names outright and tripped on
        ``set().add`` — the blunt-check trap this codebase keeps
        relearning. Ban the use, not the word.
        """
        tree = ast.parse(
            (APP_ROOT / "services" / "purchase_arrangements.py").read_text(),
        )
        banned = {
            "commit", "flush", "add", "add_all", "delete", "merge",
            "with_for_update", "rollback", "bulk_save_objects",
        }
        found = sorted({
            n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and n.attr in banned
            and isinstance(n.value, ast.Name)
            and n.value.id == "db"
        })
        assert found == [], f"the resolver may mutate the session: {found}"


class TestItDoesNotWeakenExistingGuards:
    def test_stage_0_rule_is_still_the_single_source(self):
        """The resolver calls ``unfulfillable_grant_reason`` rather
        than re-deriving the gathering-grant rule."""
        src = (APP_ROOT / "services" / "purchase_arrangements.py").read_text()
        assert "unfulfillable_grant_reason" in src

        # And does not re-derive the rule by testing a grant kind
        # against the Gathering constant. Narrowed to that comparison:
        # selecting grants *by* kind is how the resolver finds the
        # Options for an experience at all, and banning the column
        # outright flagged that legitimate query filter.
        tree = ast.parse(src)
        offenders = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.Compare):
                continue
            names = {
                x.id for x in ast.walk(n) if isinstance(x, ast.Name)
            } | {
                x.attr for x in ast.walk(n) if isinstance(x, ast.Attribute)
            }
            if "grant_kind" in names and (
                "GRANT_KIND_GATHERING" in names or "KIND_GATHERING" in names
            ):
                offenders.append(ast.dump(n))
        assert offenders == [], (
            "the resolver re-derives the gathering-grant rule instead of "
            f"calling the shared one: {offenders}"
        )

    def test_pricing_mode_is_untouched_on_the_row(self, db, space):
        """Reading arrangements must not write anything — least of all
        the column whose one-way switch is the current protection."""
        p = _pathway(db, space, access_type="one_time", price_cents=500)
        opt = _option(db, space)
        _pay_in_full(db, opt, cents=200)
        _grant(db, opt, "pathway", p.id)
        db.flush()
        before = p.pricing_mode
        pa.arrangements_for(db, kind=pa.KIND_PATHWAY, experience_id=p.id)
        db.refresh(p)
        assert p.pricing_mode == before == "legacy"

    def test_with_reason_marks_without_changing_the_price(self):
        """Stage 1B's hook for member-specific refusals. It must not be
        a way to alter a price."""
        a = pa.Arrangement(
            arrangement_id="direct:pathway:x", source=pa.SOURCE_DIRECT,
            experience_kind="pathway", experience_id="x", space_id="s",
            payment_option_id=None, payment_option_schedule_id=None,
            name="n", schedule_name=None, currency="AUD",
            schedule_type=pa.SCHEDULE_DIRECT, total_amount_cents=4900,
            upfront_amount_cents=4900, installment_amount_cents=None,
            installment_count=None, interval=None, is_bundle=False,
            included=(), available_for_new_purchase=True,
            unavailable_reason=None,
        )
        b = pa.with_reason(a, "already_owned")
        assert b.available_for_new_purchase is False
        assert b.unavailable_reason == "already_owned"
        assert b.total_amount_cents == a.total_amount_cents
        assert b.currency == a.currency
        assert b.arrangement_id == a.arrangement_id
