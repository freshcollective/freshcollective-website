"""Rule E — don't take money for access membership would have to carry.

Nothing else in checkout consults membership status. Rules A–D are
about duplicate purchases and in-flight plans, so before this a member
a creator had removed could complete Stripe Checkout and only then be
refused what they bought: ``membership_grant.may_rejoin`` declines to
restore a membership somebody else ended, which is the moderation
protection removal provenance exists for.

The guard is deliberately two questions, both of which must be yes:

  1. can this buyer be given membership?   (``_membership_readmission_block``)
  2. does this purchase need membership?   (``_purchase_needs_membership``)

So the tests come in pairs — the refusal, and the purchases that must
keep working. The second half matters more: a creator-removed person
buying a ``one_time`` Pathway, an Offering or a Gathering ticket gets
exactly what they paid for, because none of that access reads
membership, and refusing it would invent a punishment the product never
had.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_grant import (
    GRANT_KIND_PATHWAY,
    PaymentOptionGrant,
)
from app.models.platform import (
    Pathway,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import membership_removal
from app.services.checkout_orchestration import (
    check_membership_deliverable_or_raise,
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def space(make_space):
    return make_space(status="active", is_public=True)


@pytest.fixture
def buyer(make_user):
    return make_user()


def _membership(db, space, user, *, status, removal_kind=None,
                role=SpaceRole.learner, source="joined",
                rejoin_blocked=False):
    row = SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role=role, status=status, source=source,
        removal_kind=removal_kind,
        rejoin_blocked=rejoin_blocked,
        removal_note="Pinned by the test." if rejoin_blocked else None,
    )
    db.add(row)
    db.flush()
    return row


def _pathway(db, space, *, access_type):
    p = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}", title="A Pathway",
        status="active", access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode="payment_options", currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _option(db, space, *, joining=False, pathway=None, grant=True):
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        pathway_id=pathway.id if pathway else None,
        attaches_to_kind="pathway" if pathway else "space",
        attaches_to_id=pathway.id if pathway else space.id,
        name="An Option",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=5000, currency="AUD",
        is_joining_option=joining,
    )
    db.add(opt)
    db.flush()
    if pathway is not None and grant:
        db.add(PaymentOptionGrant(
            id=_uid("pog"), payment_option_id=opt.id,
            grant_kind=GRANT_KIND_PATHWAY, pathway_id=pathway.id,
        ))
        db.flush()
    return opt


def _check(db, buyer, option, space):
    return check_membership_deliverable_or_raise(
        db, user=buyer, payment_option=option, space=space,
    )


# ---------------------------------------------------------------------------
# 1. Membership itself
# ---------------------------------------------------------------------------


class TestBuyingMembership:
    """A joining Option on a ``purchase_required`` Collective. Membership
    IS the product, so a buyer who cannot be readmitted is buying
    nothing."""

    @pytest.fixture
    def paid_join_space(self, make_space):
        return make_space(
            status="active", is_public=True,
            join_policy="purchase_required",
        )

    def test_a_banned_buyer_is_refused(
        self, db, paid_join_space, buyer,
    ):
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_CREATOR,
            rejoin_blocked=True,
        )
        opt = _option(db, paid_join_space, joining=True)
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, paid_join_space)
        assert exc.value.status_code == 402

    def test_an_ordinary_creator_removal_is_allowed(
        self, db, paid_join_space, buyer,
    ):
        """The behaviour the reason/ban split buys. A creator removal
        with no block is administrative, so the purchase readmits them
        and the money buys something — Rule E must not refuse it."""
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_CREATOR,
            rejoin_blocked=False,
        )
        opt = _option(db, paid_join_space, joining=True)
        assert _check(db, buyer, opt, paid_join_space) is None

    def test_an_admin_revoked_buyer_is_refused(
        self, db, paid_join_space, buyer,
    ):
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_ADMIN,
            source="purchase",
        )
        opt = _option(db, paid_join_space, joining=True)
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, paid_join_space)
        assert exc.value.status_code == 402

    def test_a_historical_removal_is_refused(
        self, db, paid_join_space, buyer,
    ):
        """Unknown provenance. ``may_rejoin`` refuses it, so taking
        payment would promise access the fulfilment path declines."""
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed, removal_kind=None,
        )
        opt = _option(db, paid_join_space, joining=True)
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, paid_join_space)
        assert exc.value.status_code == 402

    def test_a_paused_membership_is_refused(
        self, db, paid_join_space, buyer,
    ):
        """The grant service leaves ``paused`` alone, so a purchase
        cannot restore it either."""
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.paused,
        )
        opt = _option(db, paid_join_space, joining=True)
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, paid_join_space)
        assert exc.value.status_code == 402

    def test_the_refusal_does_not_disclose_the_moderation(
        self, db, paid_join_space, buyer,
    ):
        """A checkout error is not the place to tell somebody a creator
        removed them."""
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_ADMIN,
        )
        opt = _option(db, paid_join_space, joining=True)
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, paid_join_space)
        detail = str(exc.value.detail).lower()
        assert "removed" not in detail
        assert "creator" in detail

    # -- who is NOT refused ---------------------------------------------

    def test_a_brand_new_buyer_is_allowed(
        self, db, paid_join_space, buyer,
    ):
        """No membership row at all — nothing to readmit."""
        opt = _option(db, paid_join_space, joining=True)
        assert _check(db, buyer, opt, paid_join_space) is None

    def test_a_voluntary_departer_is_allowed(
        self, db, paid_join_space, buyer,
    ):
        """They left of their own accord, so the purchase restores them
        — ``may_rejoin`` says yes and the money buys something."""
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_VOLUNTARY,
        )
        opt = _option(db, paid_join_space, joining=True)
        assert _check(db, buyer, opt, paid_join_space) is None

    def test_an_active_member_is_allowed(
        self, db, paid_join_space, buyer,
    ):
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.active,
        )
        opt = _option(db, paid_join_space, joining=True)
        assert _check(db, buyer, opt, paid_join_space) is None

    def test_creator_readmission_clears_the_refusal(
        self, db, paid_join_space, buyer,
    ):
        """Requirement: authorised readmission makes eligible purchases
        work again. No special case — the row is simply active."""
        from app.services import membership_grant

        row = _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_ADMIN,
        )
        opt = _option(db, paid_join_space, joining=True)
        with pytest.raises(HTTPException):
            _check(db, buyer, opt, paid_join_space)

        membership_grant.reactivate(row, now=datetime.utcnow())
        db.flush()
        assert _check(db, buyer, opt, paid_join_space) is None

    def test_an_open_collective_is_not_affected(
        self, db, space, buyer,
    ):
        """``is_joining_option`` means nothing on a Collective anyone
        may join for free — membership is not the product there."""
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_ADMIN,
        )
        opt = _option(db, space, joining=True)
        assert _check(db, buyer, opt, space) is None

    def test_a_non_joining_option_on_a_paid_collective_is_not_affected(
        self, db, paid_join_space, buyer,
    ):
        """A Collective may sell many things; only the nominated
        joining doors are membership."""
        _membership(
            db, paid_join_space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_ADMIN,
        )
        pw = _pathway(db, paid_join_space, access_type="one_time")
        opt = _option(db, paid_join_space, joining=False, pathway=pw)
        assert _check(db, buyer, opt, paid_join_space) is None


# ---------------------------------------------------------------------------
# 2. Membership-dependent Pathway offers
# ---------------------------------------------------------------------------


class TestBuyingAnOfferThatIncludesAPathway:
    """``included_with_offer`` is the one access type whose gate reads
    an active membership alongside the unlock, so without membership the
    Pathway stays shut however much was paid."""

    def _removed(self, db, space, buyer):
        """Not readmittable. An admin revocation rather than a creator
        removal, because an ordinary creator removal now lets the buyer
        back — and a ban is refused earlier by Rule F."""
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_ADMIN,
        )

    def test_it_is_refused_via_the_grant_row(self, db, space, buyer):
        self._removed(db, space, buyer)
        pw = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, pathway=pw)
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, space)
        assert exc.value.status_code == 402

    def test_it_is_refused_via_the_legacy_pathway_column(
        self, db, space, buyer,
    ):
        """An Option written before grants existed still fulfils through
        the legacy resolver, so the guard has to read that shape too."""
        self._removed(db, space, buyer)
        pw = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, pathway=pw, grant=False)
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, space)
        assert exc.value.status_code == 402

    def test_a_one_time_pathway_offer_is_allowed(self, db, space, buyer):
        """The purchase that must keep working. ``one_time`` reads the
        entitlement and never asks about membership, so this buyer gets
        exactly what they pay for."""
        self._removed(db, space, buyer)
        pw = _pathway(db, space, access_type="one_time")
        opt = _option(db, space, pathway=pw)
        assert _check(db, buyer, opt, space) is None

    def test_a_free_pathway_offer_is_allowed(self, db, space, buyer):
        self._removed(db, space, buyer)
        pw = _pathway(db, space, access_type="free")
        opt = _option(db, space, pathway=pw)
        assert _check(db, buyer, opt, space) is None

    def test_an_option_granting_nothing_pathway_shaped_is_allowed(
        self, db, space, buyer,
    ):
        """A Series or Gathering Option. Neither reads membership for
        delivery."""
        self._removed(db, space, buyer)
        opt = _option(db, space)
        assert _check(db, buyer, opt, space) is None

    def test_a_voluntary_departer_may_buy_it(self, db, space, buyer):
        """They will be readmitted by the purchase, so the Pathway will
        open."""
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_VOLUNTARY,
        )
        pw = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, pathway=pw)
        assert _check(db, buyer, opt, space) is None

    def test_a_mixed_option_is_refused(self, db, space, buyer):
        """One membership-dependent Pathway among several is enough —
        part of what was bought could not be delivered."""
        self._removed(db, space, buyer)
        ok = _pathway(db, space, access_type="one_time")
        gated = _pathway(db, space, access_type="included_with_offer")
        opt = _option(db, space, pathway=ok)
        db.add(PaymentOptionGrant(
            id=_uid("pog"), payment_option_id=opt.id,
            grant_kind=GRANT_KIND_PATHWAY, pathway_id=gated.id,
        ))
        db.flush()
        with pytest.raises(HTTPException) as exc:
            _check(db, buyer, opt, space)
        assert exc.value.status_code == 402


# ---------------------------------------------------------------------------
# 3. Auto-managed Collectives
# ---------------------------------------------------------------------------


class TestAutoManagedCollectivesAreNotThisGuardsBusiness:

    def test_the_guard_declines_to_judge(self, db, make_space, buyer):
        """``membership_grant`` skips these Collectives entirely —
        membership is computed from platform eligibility, not bought —
        so the guard must not refuse on their behalf."""
        space = make_space(status="active", auto_grant_role="creator")
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_AUTO_ROLE,
            source="auto_role",
        )
        opt = _option(db, space, joining=True)
        assert _check(db, buyer, opt, space) is None


# ---------------------------------------------------------------------------
# 4. Every paid entry point runs the guard
# ---------------------------------------------------------------------------


class TestEveryCheckoutEntryPointIsCovered:
    """Three functions open a paid PaymentOption flow. Each must run
    Rule E, or choosing a different payment shape is a way past it."""

    def test_the_paid_orchestrator_runs_it_first(self):
        import inspect

        from app.services.checkout_orchestration import (
            orchestrate_paid_checkout,
        )

        src = inspect.getsource(orchestrate_paid_checkout)
        # The call, not the mention: the first occurrence that is a
        # statement rather than part of the prose above it.
        call = src.index("check_membership_deliverable_or_raise(\n")
        assert call > 0
        # Before the provider is reached. ``orchestrate_paid_checkout``
        # delegates Session creation to ``_create_stripe_session_and_txn``,
        # which is also where the PaymentTransaction is written — so
        # that call is the point of no return.
        assert call < src.index("_create_stripe_session_and_txn(")

    def test_the_free_orchestrator_runs_it_before_any_write(self):
        import inspect

        from app.services.checkout_orchestration import (
            orchestrate_free_checkout,
        )

        src = inspect.getsource(orchestrate_free_checkout)
        call = src.index("check_membership_deliverable_or_raise(\n")
        assert call < src.index("resolve_intent_for_option(")

    def test_the_instalment_path_runs_it(self):
        """The one that would otherwise have been a bypass: paying by
        instalments goes through its own orchestrator."""
        import inspect

        from app.services.finite_plan_orchestration import (
            start_finite_plan_setup,
        )

        src = inspect.getsource(start_finite_plan_setup)
        call = src.index("check_membership_deliverable_or_raise(\n")
        assert call < src.index("PurchasePlan(")

    def test_the_guard_reads_the_same_predicate_as_fulfilment(self):
        """Guard and fulfilment must not disagree about who may be let
        in, so both read ``membership_grant.may_rejoin``."""
        import inspect

        from app.services import checkout_orchestration

        src = inspect.getsource(
            checkout_orchestration._membership_readmission_block,
        )
        assert "may_rejoin" in src


# ---------------------------------------------------------------------------
# 5. Nothing unrelated was touched
# ---------------------------------------------------------------------------


class TestTheGuardChangesNoPaymentBehaviour:

    def test_it_makes_no_provider_call(self):
        import inspect
        import re

        from app.services import checkout_orchestration

        src = inspect.getsource(
            checkout_orchestration.check_membership_deliverable_or_raise,
        )
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert "stripe" not in code.lower()

    def test_it_writes_nothing(self):
        import inspect
        import re

        from app.services import checkout_orchestration

        for fn in (
            checkout_orchestration.check_membership_deliverable_or_raise,
            checkout_orchestration._membership_readmission_block,
            checkout_orchestration._purchase_needs_membership,
        ):
            code = re.sub(
                r'"""[\s\S]*?"""', "", inspect.getsource(fn),
            )
            assert "db.add" not in code
            assert "db.commit" not in code
            assert ".status =" not in code

    def test_a_gathering_ticket_path_does_not_consult_it(self):
        """Ticket delivery never reads membership, and the retained
        reservation exception keeps it reachable — so it is deliberately
        not guarded."""
        import inspect

        from app.services import gathering_tickets

        assert "check_membership_deliverable_or_raise" not in (
            inspect.getsource(gathering_tickets)
        )

    def test_the_offering_path_does_not_consult_it(self):
        import inspect

        from app.services import offering_acquisition

        assert "check_membership_deliverable_or_raise" not in (
            inspect.getsource(offering_acquisition)
        )


# ---------------------------------------------------------------------------
# 6. The residual race, after checkout has begun
# ---------------------------------------------------------------------------


class TestEligibilityChangingMidCheckout:
    """Rule E closes the front door. The same rule is asked again at
    fulfilment, which closes the window behind it.

    A creator can still ban somebody while they are inside Stripe
    Checkout — nothing can prevent that. What the second check prevents
    is the outcome: instead of taking the money and then refusing the
    access, the handler writes **no grants** and marks the transaction
    ``fulfilment_status='blocked'``, the state this platform already
    uses for every other purchase it cannot fulfil, and which
    operational tooling already surfaces.

    No Stripe call, no cancellation, no refund. The state is
    recoverable: lift the restriction and a Stripe re-delivery or a
    manual replay fulfils it.
    """

    def test_one_predicate_serves_both_moments(self):
        """Guard and handler must not drift. Both read
        ``membership_undeliverable_reason``."""
        import inspect

        from app.services import checkout_orchestration as co
        from app.webhooks import finite_plan_handlers, routes

        assert "membership_undeliverable_reason" in inspect.getsource(
            co.check_membership_deliverable_or_raise,
        )
        assert "membership_undeliverable_reason" in inspect.getsource(routes)
        assert "membership_undeliverable_reason" in inspect.getsource(
            finite_plan_handlers,
        )

    def test_the_predicate_reports_a_ban(self, db, space, buyer):
        from app.services.checkout_orchestration import (
            membership_undeliverable_reason,
        )

        space.join_policy = "purchase_required"
        db.flush()
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_CREATOR,
            rejoin_blocked=True,
        )
        opt = _option(db, space, joining=True)
        assert membership_undeliverable_reason(
            db, user_id=buyer.id, space_id=space.id, payment_option=opt,
        ) == "rejoin_blocked"

    def test_it_reports_nothing_for_a_deliverable_purchase(
        self, db, space, buyer,
    ):
        """The half that must keep working: a ``one_time`` Pathway does
        not read membership, so a banned buyer still receives what they
        paid for. Blocking it would create the charged-and-given-nothing
        outcome this check exists to prevent."""
        from app.services.checkout_orchestration import (
            membership_undeliverable_reason,
        )

        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_CREATOR,
            rejoin_blocked=True,
        )
        pw = _pathway(db, space, access_type="one_time")
        opt = _option(db, space, pathway=pw)
        assert membership_undeliverable_reason(
            db, user_id=buyer.id, space_id=space.id, payment_option=opt,
        ) is None

    def test_it_reports_nothing_for_an_eligible_buyer(
        self, db, space, buyer,
    ):
        from app.services.checkout_orchestration import (
            membership_undeliverable_reason,
        )

        space.join_policy = "purchase_required"
        db.flush()
        opt = _option(db, space, joining=True)
        assert membership_undeliverable_reason(
            db, user_id=buyer.id, space_id=space.id, payment_option=opt,
        ) is None

    def test_a_missing_option_reports_nothing(self, db, space, buyer):
        """A purchase with no Payment Option behind it cannot be a
        membership purchase, so there is nothing to refuse."""
        from app.services.checkout_orchestration import (
            membership_undeliverable_reason,
        )

        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_ADMIN,
        )
        assert membership_undeliverable_reason(
            db, user_id=buyer.id, space_id=space.id, payment_option=None,
        ) is None

    def test_the_handler_blocks_rather_than_granting(self):
        """Source-level, because driving a Stripe webhook end to end
        needs a Session fixture this suite does not have. The ordering
        is the claim: the refusal sits before ``apply_intent``, so no
        grant is written."""
        import inspect

        from app.webhooks import routes

        src = inspect.getsource(routes)
        check = src.index("_co.membership_undeliverable_reason")
        apply_call = src.index("result = apply_intent(", check)
        assert check < apply_call
        between = src[check:apply_call]
        assert "PaymentFulfilmentStatus.blocked" in between
        assert "return" in between

    def test_the_instalment_handler_does_the_same(self):
        import inspect

        from app.webhooks import finite_plan_handlers

        src = inspect.getsource(finite_plan_handlers)
        check = src.index("_co.membership_undeliverable_reason")
        apply_call = src.index("result = apply_intent(", check)
        assert check < apply_call
        assert "PaymentFulfilmentStatus.blocked" in src[check:apply_call]

    def test_neither_handler_calls_stripe_in_that_branch(self):
        import inspect
        import re

        from app.webhooks import finite_plan_handlers, routes

        for mod in (routes, finite_plan_handlers):
            src = inspect.getsource(mod)
            check = src.index("_co.membership_undeliverable_reason")
            branch = src[check:src.index("result = apply_intent(", check)]
            branch = re.sub(r'"[^"\n]*"', '""', branch)
            branch = re.sub(r"'[^'\n]*'", "''", branch)
            branch = re.sub(r"#.*$", "", branch, flags=re.M)
            assert "stripe" not in branch.lower()
            assert "refund" not in branch.lower()

    def test_blocked_is_a_recoverable_state(self):
        """Not a dead end: the status exists precisely so a replay can
        retry once the underlying reason is fixed."""
        from app.models.payment import PaymentFulfilmentStatus

        assert PaymentFulfilmentStatus.blocked.value == "blocked"
        doc = PaymentFulfilmentStatus.__doc__ or ""
        assert "recoverable" in doc

    def test_the_free_path_needs_no_second_check(self):
        """Nothing was charged, and eligibility cannot change inside a
        synchronous call — so the pre-payment guard is the whole
        story."""
        import inspect

        from app.services import checkout_orchestration as co

        src = inspect.getsource(co.orchestrate_free_checkout)
        assert "check_membership_deliverable_or_raise" in src
        assert "membership_undeliverable_reason" not in src

    def test_fulfilment_still_refuses_the_membership(
        self, db, space, buyer,
    ):
        from app.services import membership_grant

        # A ban imposed while the buyer was inside Stripe Checkout —
        # the race Rule E and Rule F cannot close, because they ran
        # before it happened.
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed,
            removal_kind=membership_removal.REMOVAL_BY_CREATOR,
            source="purchase",
            rejoin_blocked=True,
        )
        outcome = membership_grant.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is False
        assert outcome.skipped_reason == "rejoin_blocked"

    def test_the_refusal_is_reported_as_an_error(self):
        """Asserted on the source rather than on captured output:
        ``alembic``'s ``fileConfig`` silences every ``app.*`` logger
        under pytest, so a log assertion would pass vacuously."""
        import inspect

        from app.services import membership_grant

        src = inspect.getsource(
            membership_grant.ensure_membership_for_purchase,
        )
        assert "logger.error" in src
        assert "PAID BUT NOT ADMITTED" in src

    def test_nothing_is_refunded_automatically(self):
        """Bans the action, not the word. The error message names a
        refund deliberately — it is telling a human what their options
        are — so this asserts there is no call, no import and no
        provider reference outside string literals."""
        import inspect
        import re

        from app.services import membership_grant

        code = inspect.getsource(membership_grant)
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        # Strip string literals: an operator-facing message is not an
        # action.
        code = re.sub(r'"[^"\n]*"', '""', code)
        code = re.sub(r"'[^'\n]*'", "''", code)
        assert "refund" not in code.lower()
        assert "stripe" not in code.lower()
