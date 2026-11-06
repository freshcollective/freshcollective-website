"""Stage 0 — the member surface and the till agree about what sells.

The defect
----------
``grant_kind='gathering'`` is a first-class part of the grant model and
the creator picker offers it, but standalone-Gathering PaymentOption
fulfilment is not activated: ``check_option_fulfillable_or_raise``
refuses with a 400 and ``resolve_intent_from_grants`` returns a fatal
error.

Two implementations of that one rule had drifted. The finite-plan
branch of ``_schedule_is_member_checkoutable`` consulted its own copy
and hid such plans correctly. The pay-in-full branch consulted
nothing and returned ``True`` unconditionally — so an Option granting
a Gathering was advertised to members as purchasable and then refused
at the till, the exact member-visible dead end that function's
docstring promises not to produce.

What this file pins
-------------------
*One* rule, in ``checkout_orchestration.unfulfillable_grant_reason``,
with two readers that cannot disagree: the guard that raises and the
flag that hides. Asserted as a cross-product — every supported bundle
shape against every schedule type — so a future change cannot fix one
reader and leave the other behind, and cannot quietly narrow what
sells.

Deliberately NOT tested here: that Gathering Payment Options work.
They do not, on purpose. Stage 0 removes the dead end; activating the
path is a later, higher-risk stage with booking, capacity and
instalment safeguards of its own.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES,
    GRANT_KIND_GATHERING,
    GRANT_KIND_OFFERING,
    GRANT_KIND_PATHWAY,
)
from app.services.checkout_orchestration import (
    UNFULFILLABLE_GATHERING_GRANT_DETAIL,
    check_option_fulfillable_or_raise,
    option_is_fulfillable,
    unfulfillable_grant_reason,
)
from app.spaces.routes import (
    _option_supports_finite_member_checkout,
    _schedule_is_member_checkoutable,
)


# ---------------------------------------------------------------------------
# Duck-typed rows. The predicates only read attributes, and a real row
# from the DB fixtures behaves identically — see
# ``test_fip4a_member_checkoutability``, which uses the same approach.
# ---------------------------------------------------------------------------


def _grant(kind: str) -> SimpleNamespace:
    return SimpleNamespace(grant_kind=kind)


def _opt(*kinds: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"po_{uuid.uuid4().hex[:8]}",
        grants=[_grant(k) for k in kinds],
    )


def _sched(schedule_type: str, *, status: str = "published") -> SimpleNamespace:
    """A structurally valid schedule of the given type, so a refusal is
    never an accident of malformed data."""
    return SimpleNamespace(
        id=f"sched_{uuid.uuid4().hex[:8]}",
        status=status,
        schedule_type=schedule_type,
        installment_amount_cents=2000,
        installment_count=3,
        stripe_interval="week",
        stripe_interval_count=1,
        interval="week",
        currency="AUD",
        total_amount_cents=6000,
    )


#: Bundle shapes that must stay sellable. ``()`` is a legacy pre-grants
#: option, which the legacy resolver still fulfils.
SUPPORTED_BUNDLES: list[tuple[str, tuple[str, ...]]] = [
    ("legacy, no grants",            ()),
    ("one Pathway",                  (GRANT_KIND_PATHWAY,)),
    ("one Series",                   (GRANT_KIND_EVENT_SERIES,)),
    ("one Offering",                 (GRANT_KIND_OFFERING,)),
    ("two Pathways",                 (GRANT_KIND_PATHWAY, GRANT_KIND_PATHWAY)),
    # The EMBODY shape, verified in production: a Series plus two
    # Pathways bought as one arrangement.
    ("EMBODY: Series + 2 Pathways",  (GRANT_KIND_EVENT_SERIES, GRANT_KIND_PATHWAY, GRANT_KIND_PATHWAY)),
]

#: Bundle shapes carrying the unsupported inclusion.
UNSUPPORTED_BUNDLES: list[tuple[str, tuple[str, ...]]] = [
    ("Gathering alone",              (GRANT_KIND_GATHERING,)),
    ("Pathway + Gathering",          (GRANT_KIND_PATHWAY, GRANT_KIND_GATHERING)),
    ("Series + Gathering",           (GRANT_KIND_EVENT_SERIES, GRANT_KIND_GATHERING)),
    ("Offering + Gathering",         (GRANT_KIND_OFFERING, GRANT_KIND_GATHERING)),
    ("two Gatherings",               (GRANT_KIND_GATHERING, GRANT_KIND_GATHERING)),
    ("the whole lot + Gathering",    (GRANT_KIND_PATHWAY, GRANT_KIND_EVENT_SERIES, GRANT_KIND_OFFERING, GRANT_KIND_GATHERING)),
]

SCHEDULE_TYPES = ["pay_in_full", "recurring_installments"]


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


class TestOneRule:
    @pytest.mark.parametrize("name,kinds", SUPPORTED_BUNDLES, ids=[n for n, _ in SUPPORTED_BUNDLES])
    def test_supported_bundles_are_fulfillable(self, name, kinds):
        assert unfulfillable_grant_reason(_opt(*kinds)) is None
        assert option_is_fulfillable(_opt(*kinds)) is True

    @pytest.mark.parametrize("name,kinds", UNSUPPORTED_BUNDLES, ids=[n for n, _ in UNSUPPORTED_BUNDLES])
    def test_a_gathering_grant_anywhere_makes_it_unfulfillable(self, name, kinds):
        """One Gathering spoils the bundle, wherever it sits in the
        list. Fulfilment is all-or-nothing — ``apply_intent`` writes
        every access record for a bundle or blocks the whole thing —
        so a partially-applicable bundle must not be sold."""
        assert unfulfillable_grant_reason(_opt(*kinds)) == (
            UNFULFILLABLE_GATHERING_GRANT_DETAIL
        )
        assert option_is_fulfillable(_opt(*kinds)) is False

    def test_a_missing_option_fails_closed(self):
        """A caller that cannot produce the Option has not checked its
        grants either. On a money surface, show less."""
        assert option_is_fulfillable(None) is False

    def test_the_guard_and_the_flag_read_the_same_rule(self):
        """The thing that drifted. Asserted as an equivalence over
        every shape rather than two independent expectations, so the
        two readers cannot be fixed apart."""
        for _name, kinds in SUPPORTED_BUNDLES + UNSUPPORTED_BUNDLES:
            opt = _opt(*kinds)
            try:
                check_option_fulfillable_or_raise(opt)
                guard_accepts = True
            except HTTPException:
                guard_accepts = False
            assert guard_accepts is option_is_fulfillable(opt), kinds

    def test_the_guard_still_raises_a_400_with_the_shared_message(self):
        with pytest.raises(HTTPException) as ex:
            check_option_fulfillable_or_raise(_opt(GRANT_KIND_GATHERING))
        assert ex.value.status_code == 400
        assert ex.value.detail == UNFULFILLABLE_GATHERING_GRANT_DETAIL

    def test_the_finite_helper_now_delegates(self):
        """``_option_supports_finite_member_checkout`` is kept for its
        existing callers and tests; it must not hold a second copy of
        the rule."""
        for _name, kinds in SUPPORTED_BUNDLES + UNSUPPORTED_BUNDLES:
            opt = _opt(*kinds)
            assert (
                _option_supports_finite_member_checkout(opt)
                is option_is_fulfillable(opt)
            ), kinds


# ---------------------------------------------------------------------------
# What a member is shown
# ---------------------------------------------------------------------------


class TestNoMemberVisibleDeadEnds:
    @pytest.mark.parametrize("schedule_type", SCHEDULE_TYPES)
    @pytest.mark.parametrize("name,kinds", UNSUPPORTED_BUNDLES, ids=[n for n, _ in UNSUPPORTED_BUNDLES])
    def test_every_schedule_type_hides_an_unsupported_bundle(
        self, name, kinds, schedule_type,
    ):
        """The headline. Before Stage 0, ``pay_in_full`` returned True
        here and then 400'd at the till."""
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", True,
        ):
            assert _schedule_is_member_checkoutable(
                _sched(schedule_type), _opt(*kinds),
            ) is False

    @pytest.mark.parametrize("schedule_type", SCHEDULE_TYPES)
    @pytest.mark.parametrize("name,kinds", UNSUPPORTED_BUNDLES, ids=[n for n, _ in UNSUPPORTED_BUNDLES])
    def test_hidden_with_the_finite_gate_off_too(self, name, kinds, schedule_type):
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", False,
        ):
            assert _schedule_is_member_checkoutable(
                _sched(schedule_type), _opt(*kinds),
            ) is False

    def test_whatever_is_shown_the_till_accepts(self):
        """The property worth having, stated as a property: there is no
        combination of bundle and schedule where the member surface
        says yes and checkout says no."""
        for _name, kinds in SUPPORTED_BUNDLES + UNSUPPORTED_BUNDLES:
            for schedule_type in SCHEDULE_TYPES:
                for gate in (True, False):
                    opt = _opt(*kinds)
                    with patch(
                        "app.core.config.settings."
                        "finite_plan_member_checkout_enabled", gate,
                    ):
                        shown = _schedule_is_member_checkoutable(
                            _sched(schedule_type), opt,
                        )
                    if not shown:
                        continue
                    check_option_fulfillable_or_raise(opt)  # must not raise


class TestNothingSupportedBecameUnavailable:
    """The other half of Stage 0's contract. Tightening the predicate
    must not cost a single currently-sellable arrangement."""

    @pytest.mark.parametrize("name,kinds", SUPPORTED_BUNDLES, ids=[n for n, _ in SUPPORTED_BUNDLES])
    def test_pay_in_full_still_sells_regardless_of_the_finite_gate(
        self, name, kinds,
    ):
        for gate in (True, False):
            with patch(
                "app.core.config.settings."
                "finite_plan_member_checkout_enabled", gate,
            ):
                assert _schedule_is_member_checkoutable(
                    _sched("pay_in_full"), _opt(*kinds),
                ) is True

    @pytest.mark.parametrize("name,kinds", SUPPORTED_BUNDLES, ids=[n for n, _ in SUPPORTED_BUNDLES])
    def test_instalments_still_sell_when_the_gate_is_on(self, name, kinds):
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", True,
        ):
            assert _schedule_is_member_checkoutable(
                _sched("recurring_installments"), _opt(*kinds),
            ) is True

    @pytest.mark.parametrize("name,kinds", SUPPORTED_BUNDLES, ids=[n for n, _ in SUPPORTED_BUNDLES])
    def test_instalments_still_hide_when_the_gate_is_off(self, name, kinds):
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", False,
        ):
            assert _schedule_is_member_checkoutable(
                _sched("recurring_installments"), _opt(*kinds),
            ) is False

    def test_a_draft_schedule_is_still_refused_first(self):
        """Status is checked before the bundle, so a draft on a
        perfectly good bundle still hides."""
        assert _schedule_is_member_checkoutable(
            _sched("pay_in_full", status="draft"), _opt(GRANT_KIND_PATHWAY),
        ) is False

    def test_manual_schedules_are_still_never_checkoutable(self):
        assert _schedule_is_member_checkoutable(
            _sched("manual"), _opt(GRANT_KIND_PATHWAY),
        ) is False


# ---------------------------------------------------------------------------
# What the creator is told
# ---------------------------------------------------------------------------


class TestCreatorIsWarned:
    """``_derive_purchasability`` feeds the editor banner, the
    per-option badge in Creator Studio and the notes under each row.
    It reads the same rule, so the creator's warning cannot disagree
    with the member's experience either."""

    def _derive(self, opt, schedules):
        from app.creator._space_payment_options_routes import (
            _derive_purchasability,
        )
        opt._schedules_cache = schedules
        return _derive_purchasability(opt)

    def _opt_with_status(self, status: str, *kinds: str) -> SimpleNamespace:
        o = _opt(*kinds)
        o.status = status
        return o

    @pytest.mark.parametrize("schedule_type", SCHEDULE_TYPES)
    def test_a_gathering_inclusion_reports_unsupported_inclusion(
        self, schedule_type,
    ):
        state, notes = self._derive(
            self._opt_with_status("published", GRANT_KIND_PATHWAY, GRANT_KIND_GATHERING),
            [_sched(schedule_type)],
        )
        assert state == "unsupported_inclusion"
        assert len(notes) == 1
        assert "individual Gathering" in notes[0]
        assert "coming soon" in notes[0]
        # Tells them what to do instead, not just what is wrong.
        assert "Gathering editor" in notes[0]

    def test_the_warning_arrives_before_publication(self):
        """A draft reports it too. The point of the warning is to be
        read before anybody publishes and wonders why nobody buys."""
        state, notes = self._derive(
            self._opt_with_status("draft", GRANT_KIND_GATHERING),
            [_sched("pay_in_full")],
        )
        assert state == "unsupported_inclusion"
        assert notes

    def test_it_outranks_a_missing_payment_method(self):
        """No amount of further authoring fixes the inclusion, so the
        advice must not be "add a payment method"."""
        state, notes = self._derive(
            self._opt_with_status("draft", GRANT_KIND_GATHERING), [],
        )
        assert state == "unsupported_inclusion"
        assert not any("payment method" in n for n in notes)

    def test_archived_still_wins(self):
        """An archived Option is history; it is not asking to be sold,
        so it should not be scolded."""
        state, _notes = self._derive(
            self._opt_with_status("archived", GRANT_KIND_GATHERING),
            [_sched("pay_in_full")],
        )
        assert state == "archived"

    def test_a_supported_bundle_is_unaffected(self):
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", True,
        ):
            state, notes = self._derive(
                self._opt_with_status("published", GRANT_KIND_EVENT_SERIES, GRANT_KIND_PATHWAY),
                [_sched("pay_in_full")],
            )
        assert state == "ready"
        assert notes == []

    def test_the_gated_plan_state_is_unaffected(self):
        """The pre-existing ``configured_not_yet_checkoutable`` case
        must still read as "your work is done, a platform gate is
        off" — different problem, different advice."""
        with patch(
            "app.core.config.settings.finite_plan_member_checkout_enabled", False,
        ):
            state, notes = self._derive(
                self._opt_with_status("published", GRANT_KIND_PATHWAY),
                [_sched("recurring_installments")],
            )
        assert state == "configured_not_yet_checkoutable"
        assert any("not currently enabled" in n for n in notes)

    def test_no_grants_still_needs_attention(self):
        state, notes = self._derive(
            self._opt_with_status("published"), [],
        )
        assert state == "needs_attention"
        assert any("No experiences included" in n for n in notes)
