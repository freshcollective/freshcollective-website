"""Stage 5A.0 — preparing paid Collective membership.

Three separate things, all of them preparation rather than billing.

**The gap.** ``Space.pricing_type`` advertises a membership price and
``Space.join_policy`` decides whether the free Join button works. They
are independent columns and ``POST /api/spaces/{slug}/join`` has only
ever read the second — so a Collective set to ``paid_monthly`` with the
default ``join_policy='open'`` advertises A$29/month and then admits
people for nothing. The pricing columns say as much about themselves:
"display/config only; payment processing is separate."

**Why the gate is flag-gated.** Refusing a free join is only honest once
there is somewhere to pay. One flag governs both this refusal and the
checkout Stage 5A.1 adds, so they cannot diverge: the gate is never live
without a way to pay, and the checkout is never live while the free door
stands open beside it. With the flag off — production, today — every
Collective joins exactly as it did.

**Why pricing and joining stay distinct.** They answer different
questions, and a Collective may legitimately want both a fee and an
invitation. Nothing here writes ``join_policy``, and the payment check
sits *after* the policy check rather than replacing it.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_stage5a0_membership_pricing.py
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.creator.schemas import (
    ALLOWED_PRICING_TYPES, RETIRED_PRICING_TYPES, SELECTABLE_PRICING_TYPES,
    SpaceUpdateRequest,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.spaces import join_policy
from app.spaces import membership_pricing as mp


def _press_join(db, space, user):
    from app.spaces.routes import join_space
    return join_space(space.slug, db=db, current_user=user,
                      background_tasks=None)


# ---------------------------------------------------------------------------
# Which pricing types mean "membership costs money"
# ---------------------------------------------------------------------------


class TestThePaidMembershipPredicate:
    @pytest.mark.parametrize("value", ["paid_monthly", "paid_annual", "paid_one_time"])
    def test_a_paid_type_is_paid(self, value):
        assert mp.is_paid_membership(value) is True

    def test_free_is_not(self):
        assert mp.is_paid_membership("free") is False

    def test_invite_only_restricts_who_not_what_it_costs(self):
        """It is enforced by the invitation flow, not by a fee."""
        assert mp.is_paid_membership("invite_only") is False

    def test_the_retired_type_never_meant_a_collectable_price(self):
        assert mp.is_paid_membership("coming_soon") is False

    @pytest.mark.parametrize("value", [None, "", "  ", 7, "nonsense"])
    def test_an_unexpected_value_answers_no_rather_than_raising(self, value):
        """Read on a public page, so a surprise value must not break it."""
        assert mp.is_paid_membership(value) is False

    def test_whitespace_does_not_defeat_it(self):
        assert mp.is_paid_membership("  paid_monthly  ") is True


# ---------------------------------------------------------------------------
# The join gate — prepared, inert
# ---------------------------------------------------------------------------


class TestTheJoinGateIsInertUntilBillingExists:
    def test_the_flag_is_off_by_default(self):
        assert settings.paid_collective_membership_enabled is False

    def test_with_billing_off_a_paid_collective_does_not_block(self):
        assert mp.free_join_blocked_by_payment("paid_monthly") is False

    def test_with_billing_on_a_paid_collective_blocks(self, monkeypatch):
        monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
        assert mp.free_join_blocked_by_payment("paid_monthly") is True

    def test_with_billing_on_a_free_collective_still_does_not_block(
        self, monkeypatch,
    ):
        monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
        assert mp.free_join_blocked_by_payment("free") is False

    def test_it_is_a_different_flag_from_discount_codes(self):
        """Stage 4's switch must not drag membership billing on with it."""
        import inspect
        src = inspect.getsource(mp)
        assert "universal_discount_codes_enabled" not in src


class TestJoiningThroughTheRealEndpoint:
    def test_a_free_collective_still_joins_today(self, db, make_user, make_space):
        space = make_space()
        space.pricing_type = "free"
        db.flush()
        _press_join(db, space, make_user())

    def test_a_paid_collective_still_joins_while_billing_is_off(
        self, db, make_user, make_space,
    ):
        """Today's behaviour, preserved on purpose: blocking here before
        a checkout exists would make a paid Collective unjoinable by any
        route, which is worse than the gap it closes."""
        space = make_space()
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 2_900
        db.flush()
        user = make_user()
        _press_join(db, space, user)
        row = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == space.id,
                    SpaceMembership.user_id == user.id)
            .one()
        )
        assert row.status is SpaceMembershipStatus.active

    def test_a_paid_collective_refuses_free_joining_once_billing_is_on(
        self, db, make_user, make_space, monkeypatch,
    ):
        monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
        space = make_space()
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 2_900
        db.flush()
        user = make_user()

        with pytest.raises(HTTPException) as exc:
            _press_join(db, space, user)

        assert exc.value.status_code == 402
        assert exc.value.detail["code"] == (
            mp.REASON_MEMBERSHIP_PAYMENT_REQUIRED
        )
        # And nothing was written — a refused join grants nothing.
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == user.id,
        ).count() == 0

    def test_a_free_collective_is_unaffected_with_billing_on(
        self, db, make_user, make_space, monkeypatch,
    ):
        monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
        space = make_space()
        space.pricing_type = "free"
        db.flush()
        _press_join(db, space, make_user())

    def test_the_payment_check_runs_after_the_policy_check(self):
        """Order matters: the policy's 403 is about who may ask and the
        payment 402 is about what it costs. A Collective can require
        both, and neither may shadow the other."""
        import inspect
        from app.spaces.routes import join_space
        src = inspect.getsource(join_space)
        assert src.index("allows_free_join") < src.index(
            "free_join_blocked_by_payment"
        )

    def test_nothing_here_rewrites_the_join_policy(self):
        """The ban is on *touching* the column, not on naming it — the
        module's docstring explains at length why the two stay distinct,
        so a blunt substring check would fail on its own reasoning."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(mp))
        assigned = {
            t.attr for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Attribute)
        }
        assert "join_policy" not in assigned
        imported = {
            alias.name for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "join_policy" not in imported


class TestExistingRestrictionsStillRun:
    def test_a_purchase_required_collective_still_refuses_with_its_own_code(
        self, db, make_user, make_space, monkeypatch,
    ):
        """The policy refusal is unchanged and still comes first, with
        its own stable reason code."""
        monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
        space = make_space()
        space.pricing_type = "paid_monthly"
        space.join_policy = join_policy.JOIN_PURCHASE_REQUIRED
        db.flush()

        with pytest.raises(HTTPException) as exc:
            _press_join(db, space, make_user())

        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == join_policy.REASON_PURCHASE_REQUIRED

    def test_the_rejoin_guard_is_still_consulted_by_the_handler(self):
        """Who may come back is ``membership_grant.may_rejoin``, which
        reads ``removal_kind`` and ``rejoin_blocked``. The handler calls
        it rather than restating the rule, so that call is what there is
        to assert."""
        import inspect
        from app.services import membership_grant
        from app.spaces.routes import join_space
        assert "may_rejoin(" in inspect.getsource(join_space)
        rule = inspect.getsource(membership_grant.may_rejoin)
        assert "rejoin_blocked" in rule
        assert "removal_kind" in rule


# ---------------------------------------------------------------------------
# Retiring "Paid — coming soon"
# ---------------------------------------------------------------------------


class TestTheRetiredPricingType:
    def test_it_is_no_longer_selectable(self):
        assert "coming_soon" not in SELECTABLE_PRICING_TYPES

    def test_it_is_still_accepted_on_the_wire(self):
        """The settings form resends ``pricing_type`` on every save from
        the Collective's own stored value, so refusing it at the schema
        would lock a creator holding it out of saving anything at all —
        including the pricing change that would move them off it."""
        assert "coming_soon" in ALLOWED_PRICING_TYPES
        assert SpaceUpdateRequest(pricing_type="coming_soon").pricing_type == (
            "coming_soon"
        )

    @pytest.mark.parametrize("value", [
        "free", "paid_one_time", "paid_monthly", "paid_annual", "invite_only",
    ])
    def test_every_live_pricing_type_is_untouched(self, value):
        assert value in SELECTABLE_PRICING_TYPES
        assert SpaceUpdateRequest(pricing_type=value).pricing_type == value

    def test_the_two_sets_do_not_overlap(self):
        assert not (SELECTABLE_PRICING_TYPES & RETIRED_PRICING_TYPES)
        assert ALLOWED_PRICING_TYPES == (
            SELECTABLE_PRICING_TYPES | RETIRED_PRICING_TYPES
        )


class TestAdoptingTheRetiredTypeIsRefused:
    def _check(self, *, incoming, stored):
        from app.creator.routes import _refuse_retired_pricing_change
        _refuse_retired_pricing_change(incoming=incoming, stored=stored)

    def test_choosing_it_afresh_is_refused(self):
        with pytest.raises(HTTPException) as exc:
            self._check(incoming="coming_soon", stored="free")
        assert exc.value.status_code == 422
        assert "no longer available" in exc.value.detail

    def test_keeping_it_is_allowed(self):
        """So a creator holding it can still save their tagline."""
        self._check(incoming="coming_soon", stored="coming_soon")

    def test_moving_off_it_is_allowed(self):
        self._check(incoming="paid_monthly", stored="coming_soon")
        self._check(incoming="free", stored="coming_soon")

    @pytest.mark.parametrize("stored", [None, ""])
    def test_a_collective_with_no_stored_value_cannot_adopt_it(self, stored):
        with pytest.raises(HTTPException):
            self._check(incoming="coming_soon", stored=stored)

    def test_a_live_type_is_never_refused(self):
        for value in SELECTABLE_PRICING_TYPES:
            self._check(incoming=value, stored="coming_soon")
            self._check(incoming=value, stored="free")


# ---------------------------------------------------------------------------
# Nothing happens to anybody
# ---------------------------------------------------------------------------


class TestNoMemberIsTouched:
    def test_no_membership_status_is_changed_anywhere_in_this_stage(self):
        """§7 — the transition is designed, not activated. Nothing in
        5A.0 may pause, convert or enrol anybody."""
        import inspect
        src = inspect.getsource(mp)
        for forbidden in (
            "SpaceMembershipStatus", "paused", "ensure_membership_for_purchase",
            "db.add", "db.commit", "Stripe", "stripe",
        ):
            assert forbidden not in src, forbidden

    def test_an_existing_member_of_a_newly_paid_collective_keeps_access(
        self, db, make_user, make_space, monkeypatch,
    ):
        """The creator switches to paid; the member who was already
        inside is not paused, charged or removed."""
        space = make_space()
        space.pricing_type = "free"
        db.flush()
        member = make_user()
        _press_join(db, space, member)

        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 2_900
        db.flush()
        monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)

        row = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == space.id,
                    SpaceMembership.user_id == member.id)
            .one()
        )
        assert row.status is SpaceMembershipStatus.active
