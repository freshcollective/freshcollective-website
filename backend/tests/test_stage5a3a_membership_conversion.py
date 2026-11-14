"""Stage 5A.3a — membership settings, and converting an existing member.

The one idea being protected
----------------------------
**Belonging to a Collective and paying to belong are different facts.**

Every bug this stage fixes, and every rule it adds, comes from that
sentence. While the only way to be a member of a paid Collective was
to have paid for it, the two could share an answer; the free-to-paid
transition is what pulls them apart. A hundred existing members become
a hundred people who are *members* and who hold *nothing*, and the
system has to let each of them buy without leaving, without rejoining,
and without losing what they already have.

What is deliberately NOT tested here
------------------------------------
Charging anybody. Every test runs with Stripe mocked or not reached at
all, and ``paid_collective_membership_enabled`` is switched on per-test
rather than globally — the shipped default stays off, and the suite
would notice if that changed.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_stage5a3a_membership_conversion.py
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.auth.dependencies import (
    get_creator_user, get_current_user, get_optional_user,
    get_verified_creator_user, get_verified_current_user,
)
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.models.user import User
from app.services import collective_membership_access as access
from app.services import collective_membership_eligibility as elig
from app.services import collective_membership_lifecycle as lifecycle
from app.services import collective_membership_reconcile as reconcile
from app.spaces import membership_pricing

NOW = datetime.utcnow()


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    """Membership billing on for these tests, off everywhere else."""
    monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)


@pytest.fixture
def paid_space(db, make_space, make_user):
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    space.pricing_type = "paid_monthly"
    space.pricing_amount_cents = 2_900
    space.pricing_currency = "AUD"
    space.timezone = "Australia/Melbourne"
    db.flush()
    return space


@pytest.fixture
def member(make_user):
    return make_user()


def _owner(db, space):
    """``Space`` carries ``creator_id``, not a relationship."""
    return db.query(User).filter(User.id == space.creator_id).one()


def _join(
    db, space, user, status=SpaceMembershipStatus.active,
    source="joined", **kw,
):
    """An existing member — the person this whole stage is about."""
    row = SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role="learner", status=status, source=source, joined_at=NOW,
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _agreement(db, space, user, status, **kw):
    row = CollectiveMembership(
        id=_uid("cm"), space_id=space.id, user_id=user.id,
        status=status, interval="month", interval_count=1,
        amount_cents=2_900, currency="AUD", **kw,
    )
    db.add(row)
    db.flush()
    return row


# ===========================================================================
# §6 — Existing member conversion: the eligibility fix
# ===========================================================================


class TestAMemberIsNotASubscriber:
    """The distinction the stage exists to draw."""

    def test_an_existing_free_member_may_subscribe(
        self, db, paid_space, member,
    ):
        """§6 — the headline case, and the one that was broken.

        A Collective that was free, is now priced, and still has the
        members it gathered while it was free.
        """
        _join(db, paid_space, member)
        assert elig.refusal_for(db, user=member, space=paid_space) is None

    def test_they_do_not_have_to_leave_first(self, db, paid_space, member):
        """§6 — their membership row is untouched by being allowed in.

        Asking the question must not be what changes the answer.
        """
        row = _join(db, paid_space, member)
        joined_at, source, row_id = row.joined_at, row.source, row.id
        elig.refusal_for(db, user=member, space=paid_space)
        db.refresh(row)
        assert (row.id, row.source, row.joined_at) == (row_id, source, joined_at)
        assert row.status == SpaceMembershipStatus.active

    @pytest.mark.parametrize("status", [
        CollectiveMembershipStatus.active.value,
        CollectiveMembershipStatus.past_due.value,
        CollectiveMembershipStatus.cancel_scheduled.value,
    ])
    def test_but_someone_already_paying_is_refused(
        self, db, paid_space, member, status,
    ):
        """§6 — "no duplicate active subscriptions", in all three shapes.

        ``past_due`` is a renewal Stripe is still retrying and
        ``cancel_scheduled`` is a period still running: both are
        agreements that exist, and a second would charge twice for one
        place.
        """
        _join(db, paid_space, member)
        _agreement(db, paid_space, member, status)
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.ALREADY_SUBSCRIBED

    def test_a_pending_checkout_does_not_refuse(
        self, db, paid_space, member,
    ):
        """§7 — a checkout nobody has paid for is not a subscription.

        It must not bar the member: the billing layer hands back their
        own live Stripe Session, which is how someone who closed the
        tab picks up where they left off. Blocking here would strand
        them behind a row that grants nothing.
        """
        _join(db, paid_space, member)
        _agreement(db, paid_space, member, CollectiveMembershipStatus.pending.value)
        assert elig.refusal_for(db, user=member, space=paid_space) is None

    @pytest.mark.parametrize("status", [
        CollectiveMembershipStatus.failed.value,
        CollectiveMembershipStatus.ended.value,
        CollectiveMembershipStatus.cancelled.value,
    ])
    def test_a_finished_or_failed_attempt_does_not_refuse(
        self, db, paid_space, member, status,
    ):
        """§7 — a card that failed, or a membership that ended, leaves
        nothing behind that should stop them trying again."""
        _join(db, paid_space, member)
        _agreement(db, paid_space, member, status)
        assert elig.refusal_for(db, user=member, space=paid_space) is None

    def test_a_paused_member_may_buy_their_way_back(
        self, db, paid_space, member,
    ):
        """§8 — the group the transition sweep itself creates.

        Refusing them would mean the system paused people and then
        closed the only door back.
        """
        _join(db, paid_space, member, status=SpaceMembershipStatus.paused)
        assert elig.refusal_for(db, user=member, space=paid_space) is None

    def test_the_owner_does_not_buy_their_own_collective(
        self, db, paid_space, make_user,
    ):
        """Not in the brief as a rule, but implied by every part of it.

        The sweep never pauses the owner, so an owner holds nothing and
        needs nothing. Without this they would have been handed a
        checkout for their own Collective by the relaxation above.
        """
        owner = _owner(db, paid_space)
        refusal = elig.refusal_for(db, user=owner, space=paid_space)
        assert refusal is elig.OWN_COLLECTIVE


class TestPaymentStillOverturnsNothing:
    """§6 — the relaxation must not become a way in."""

    def test_a_banned_member_is_still_refused(
        self, db, paid_space, member, monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.membership_removal.is_banned",
            lambda db, *, user_id, space_id: True,
        )
        _join(db, paid_space, member)
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_ELIGIBLE

    def test_a_creator_removal_is_still_refused(
        self, db, paid_space, member,
    ):
        from app.services.membership_removal import REMOVAL_BY_CREATOR
        _join(
            db, paid_space, member,
            status=SpaceMembershipStatus.removed,
            removal_kind=REMOVAL_BY_CREATOR, removed_at=NOW,
            rejoin_blocked=True,
        )
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_ELIGIBLE

    def test_a_free_collective_still_sells_nothing(
        self, db, paid_space, member,
    ):
        paid_space.pricing_type = "free"
        db.flush()
        _join(db, paid_space, member)
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_PAID

    def test_the_flag_still_closes_the_door(
        self, db, paid_space, member, monkeypatch,
    ):
        """§14 — none of this is reachable in production today."""
        monkeypatch.setattr(
            settings, "paid_collective_membership_enabled", False,
        )
        _join(db, paid_space, member)
        assert elig.refusal_for(
            db, user=member, space=paid_space,
        ) is elig.NOT_AVAILABLE

    def test_an_invitation_is_not_a_waiver(self, db, paid_space, member):
        """§9 — an invitation grants eligibility to join, never a comp."""
        _join(db, paid_space, member, source="invited")
        # Still allowed to subscribe, and still has to: nothing about
        # the invitation removes the fee.
        assert elig.refusal_for(db, user=member, space=paid_space) is None
        assert not access.holds_satisfying_agreement(
            db, user_id=member.id, space_id=paid_space.id,
        )


# ===========================================================================
# §8 — Paying keeps the membership you already had
# ===========================================================================


def _activate(db, row, **kw):
    return lifecycle.activate_from_first_invoice(
        db,
        subscription=row,
        invoice_id=kw.pop("invoice_id", _uid("in")),
        invoice_amount_cents=kw.pop("amount", 2_900),
        invoice_currency=kw.pop("currency", "AUD"),
        stripe_subscription_id=kw.pop("sub_id", "sub_test_1"),
        charge_id=kw.pop("charge_id", "ch_test_1"),
        payment_intent_id=kw.pop("pi", "pi_test_1"),
        period_start=kw.pop("period_start", NOW),
        period_end=kw.pop("period_end", NOW + timedelta(days=30)),
        now=kw.pop("now", NOW),
    )


class TestConversionPreservesTheMembership:
    """§8 — "do not create another SpaceMembership", and the rest of it."""

    def test_an_existing_member_who_pays_keeps_the_same_row(
        self, db, paid_space, member,
    ):
        """The promise the whole stage rests on: converting is not
        leaving and rejoining. Same row, same id, same join date, same
        provenance — only an agreement is added beside it."""
        row = _join(db, paid_space, member)
        original = (row.id, row.joined_at, row.source, row.role)

        agreement = _agreement(
            db, paid_space, member,
            CollectiveMembershipStatus.pending.value,
        )
        out = _activate(db, agreement)

        assert out.applied is True
        # ``already_active`` is the right outcome here, not ``created``:
        # there was nothing to create, and that is the point.
        assert out.membership == "already_active"
        rows = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == paid_space.id,
            SpaceMembership.user_id == member.id,
        ).all()
        assert len(rows) == 1, "a second membership row was created"
        db.refresh(row)
        assert (row.id, row.joined_at, row.source, row.role) == original
        assert row.status == SpaceMembershipStatus.active

    def test_a_paused_member_who_pays_is_unpaused_in_place(
        self, db, paid_space, member,
    ):
        """§8 — the subscription-specific reactivation path, reached
        by a verified payment and by nothing else."""
        row = _join(db, paid_space, member, status=SpaceMembershipStatus.paused)
        original_id = row.id
        agreement = _agreement(
            db, paid_space, member,
            CollectiveMembershipStatus.pending.value,
        )
        out = _activate(db, agreement)
        assert out.membership == "unpaused"
        db.refresh(row)
        assert row.id == original_id
        assert row.status == SpaceMembershipStatus.active

    def test_a_removal_is_not_unpaused_by_paying(
        self, db, paid_space, member,
    ):
        """The same payment against a ``removed`` row admits nobody.
        Checkout refuses this up front; this is the fulfilment side
        holding the line when eligibility changed mid-Stripe."""
        from app.services.membership_removal import REMOVAL_BY_CREATOR
        row = _join(
            db, paid_space, member,
            status=SpaceMembershipStatus.removed,
            removal_kind=REMOVAL_BY_CREATOR, removed_at=NOW,
            rejoin_blocked=True,
        )
        agreement = _agreement(
            db, paid_space, member,
            CollectiveMembershipStatus.pending.value,
        )
        _activate(db, agreement)
        db.refresh(row)
        assert row.status == SpaceMembershipStatus.removed


class TestWhatAPauseDoesNotTouch:
    def test_a_separately_purchased_pathway_survives_the_transition(
        self, db, paid_space, member,
    ):
        """§5, §7 — "independently purchased experiences remain
        protected". Membership-derived access stops; property does
        not."""
        from app.models.platform import Pathway, PathwayEntitlement

        pathway = Pathway(
            id=_uid("pw"), space_id=paid_space.id, title="Bought separately",
            slug=_uid("slug"), status="active", access_type="paid",
        )
        db.add(pathway)
        db.flush()
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=member.id, space_id=paid_space.id,
            pathway_id=pathway.id, source="one_time_purchase",
            status="active", starts_at=NOW,
        ))
        _join(db, paid_space, member)
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()

        _sweep(db)

        assert _status(db, paid_space, member) == SpaceMembershipStatus.paused
        assert db.query(PathwayEntitlement).filter(
            PathwayEntitlement.user_id == member.id,
            PathwayEntitlement.pathway_id == pathway.id,
        ).count() == 1


# ===========================================================================
# §4 — The transition date
# ===========================================================================


class TestTheDateIsAnInstantInTheCollectivesOwnTime:
    def test_a_chosen_day_becomes_the_moment_it_begins_locally(self):
        """§4 — "the existing Collective timezone, authoritative UTC".

        1 January in Melbourne is not 1 January in UTC, and members
        must not be paused thirteen hours early or late.
        """
        got = membership_pricing.transition_instant(
            date(2027, 1, 1), "Australia/Melbourne",
        )
        assert got == datetime(2026, 12, 31, 13, 0)

    def test_the_creator_is_shown_back_the_day_they_chose(self):
        instant = membership_pricing.transition_instant(
            date(2027, 1, 1), "Australia/Melbourne",
        )
        assert membership_pricing.transition_date_in_timezone(
            instant, "Australia/Melbourne",
        ) == date(2027, 1, 1)

    def test_an_unknown_timezone_falls_back_rather_than_raising(self):
        assert membership_pricing.transition_instant(
            date(2027, 1, 1), "Not/AZone",
        ) is not None

    def test_no_date_is_a_complete_answer(self):
        assert membership_pricing.transition_instant(None, "UTC") is None
        assert membership_pricing.transition_date_in_timezone(None, "UTC") is None


# ===========================================================================
# §4, §5 — Configuring it through Collective Settings
# ===========================================================================


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def as_owner(db, paid_space):
    """Sign in as the Collective's owner, with the plan guard satisfied."""
    owner = _owner(db, paid_space)
    for dep in (
        get_current_user, get_optional_user, get_verified_current_user,
        get_creator_user, get_verified_creator_user,
    ):
        app.dependency_overrides[dep] = lambda u=owner: u
    return owner


def _patch(client, space, **fields):
    return client.patch(f"/api/creator/spaces/{space.slug}", json=fields)


class TestSettingTheDate:
    def test_a_future_date_is_stored_as_a_local_instant(
        self, client, db, paid_space, as_owner,
    ):
        res = _patch(
            client, paid_space, paid_membership_effective_on="2027-01-01",
        )
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at == datetime(2026, 12, 31, 13, 0)
        assert res.json()["paid_membership_effective_on"] == "2027-01-01"

    def test_a_future_date_may_be_moved(
        self, client, db, paid_space, as_owner,
    ):
        _patch(client, paid_space, paid_membership_effective_on="2027-01-01")
        res = _patch(
            client, paid_space, paid_membership_effective_on="2027-03-01",
        )
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert membership_pricing.transition_date_in_timezone(
            paid_space.paid_membership_effective_at, paid_space.timezone,
        ) == date(2027, 3, 1)

    def test_an_explicit_null_clears_it(
        self, client, db, paid_space, as_owner,
    ):
        _patch(client, paid_space, paid_membership_effective_on="2027-01-01")
        res = _patch(client, paid_space, paid_membership_effective_on=None)
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is None

    def test_a_save_that_does_not_mention_it_leaves_it_alone(
        self, client, db, paid_space, as_owner,
    ):
        """The form sends every pricing field on every save, so "absent"
        has to keep meaning "leave alone" — otherwise editing the
        pricing note would wipe a date set last week."""
        _patch(client, paid_space, paid_membership_effective_on="2027-01-01")
        res = _patch(client, paid_space, pricing_note="Founding rate")
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is not None

    def test_leaving_paid_pricing_clears_the_date(
        self, client, db, paid_space, as_owner,
    ):
        """A date on a free Collective would pause people out of
        something they cannot buy their way back into — eligibility
        answers NOT_PAID, so there is no checkout to open."""
        _patch(client, paid_space, paid_membership_effective_on="2027-01-01")
        res = _patch(client, paid_space, pricing_type="free")
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is None

    def test_an_invite_only_collective_holds_no_date_either(
        self, client, db, paid_space, as_owner, monkeypatch,
    ):
        monkeypatch.setattr(
            "app.creator.routes.guard_paid_offers_enabled",
            lambda user, db, pricing_type: None,
        )
        _patch(client, paid_space, paid_membership_effective_on="2027-01-01")
        res = _patch(client, paid_space, pricing_type="invite_only")
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is None

    @pytest.mark.parametrize("pricing_type", ["paid_monthly", "paid_annual", "paid_one_time"])
    def test_every_paid_type_may_carry_one(
        self, client, db, paid_space, as_owner, monkeypatch, pricing_type,
    ):
        monkeypatch.setattr(
            "app.creator.routes.guard_paid_offers_enabled",
            lambda user, db, pricing_type: None,
        )
        res = _patch(
            client, paid_space,
            pricing_type=pricing_type,
            paid_membership_effective_on="2027-01-01",
        )
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is not None


class TestAnImmediateTransitionHasToBeMeant:
    """§5 — a dropdown is not consent to remove anybody's access."""

    def test_a_past_date_with_members_is_refused_unacknowledged(
        self, client, db, paid_space, member, as_owner,
    ):
        _join(db, paid_space, member)
        yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
        res = _patch(
            client, paid_space, paid_membership_effective_on=yesterday,
        )
        assert res.status_code == 422, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "membership_transition_needs_acknowledgement"
        assert detail["members_needing_subscription"] == 1
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is None

    def test_the_same_request_acknowledged_is_accepted(
        self, client, db, paid_space, member, as_owner,
    ):
        _join(db, paid_space, member)
        yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
        res = _patch(
            client, paid_space,
            paid_membership_effective_on=yesterday,
            paid_membership_transition_ack=True,
        )
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is not None

    def test_with_nobody_to_pause_there_is_nothing_to_acknowledge(
        self, client, db, paid_space, as_owner,
    ):
        """An empty Collective, or one whose members all subscribed.
        There is no warning to give, so none is demanded."""
        yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
        res = _patch(
            client, paid_space, paid_membership_effective_on=yesterday,
        )
        assert res.status_code == 200, res.text

    def test_members_who_already_pay_do_not_trigger_it(
        self, client, db, paid_space, member, as_owner,
    ):
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.active.value,
        )
        yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
        res = _patch(
            client, paid_space, paid_membership_effective_on=yesterday,
        )
        assert res.status_code == 200, res.text

    def test_the_owner_is_not_counted_as_someone_to_pause(
        self, client, db, paid_space, as_owner,
    ):
        """The owner is an active member who holds no agreement, and is
        never paused. Counting them would overstate the impact by one
        and name somebody with nothing to do."""
        _join(db, paid_space, as_owner)
        yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
        res = _patch(
            client, paid_space, paid_membership_effective_on=yesterday,
        )
        assert res.status_code == 200, res.text

    def test_a_future_date_never_needs_acknowledgement(
        self, client, db, paid_space, member, as_owner,
    ):
        _join(db, paid_space, member)
        res = _patch(
            client, paid_space, paid_membership_effective_on="2027-01-01",
        )
        assert res.status_code == 200, res.text

    def test_clearing_a_date_never_needs_acknowledgement(
        self, client, db, paid_space, member, as_owner,
    ):
        """Clearing pauses nobody — it stops the sweep, it does not run it."""
        _join(db, paid_space, member)
        res = _patch(client, paid_space, paid_membership_effective_on=None)
        assert res.status_code == 200, res.text


class TestWhatTheCreatorIsTold:
    def test_the_impact_count_is_reported(
        self, client, db, paid_space, member, make_user, as_owner,
    ):
        _join(db, paid_space, member)
        _join(db, paid_space, make_user())
        res = client.get(f"/api/creator/spaces/{paid_space.slug}")
        assert res.status_code == 200, res.text
        assert res.json()["members_needing_subscription"] == 2

    def test_subscribers_are_not_counted(
        self, client, db, paid_space, member, make_user, as_owner,
    ):
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.active.value,
        )
        _join(db, paid_space, make_user())
        res = client.get(f"/api/creator/spaces/{paid_space.slug}")
        assert res.json()["members_needing_subscription"] == 1

    def test_a_pending_checkout_does_not_count_as_covered(
        self, client, db, paid_space, member, as_owner,
    ):
        """§7 — abandoning Stripe must not look like having paid."""
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.pending.value,
        )
        res = client.get(f"/api/creator/spaces/{paid_space.slug}")
        assert res.json()["members_needing_subscription"] == 1

    def test_a_free_collective_reports_nothing_to_do(
        self, client, db, paid_space, member, as_owner,
    ):
        paid_space.pricing_type = "free"
        db.flush()
        _join(db, paid_space, member)
        res = client.get(f"/api/creator/spaces/{paid_space.slug}")
        assert res.json()["members_needing_subscription"] == 0


# ===========================================================================
# §9 — Pricing and joining stay independent
# ===========================================================================


class TestPricingDoesNotRewriteTheDoor:
    @pytest.mark.parametrize("join_policy", ["open", "purchase_required"])
    def test_changing_pricing_leaves_join_policy_alone(
        self, client, db, paid_space, as_owner, monkeypatch, join_policy,
    ):
        monkeypatch.setattr(
            "app.creator.routes.guard_paid_offers_enabled",
            lambda user, db, pricing_type: None,
        )
        paid_space.join_policy = join_policy
        db.flush()
        res = _patch(
            client, paid_space,
            pricing_type="paid_annual",
            paid_membership_effective_on="2027-01-01",
        )
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.join_policy == join_policy

    def test_eligibility_never_consults_the_join_policy(
        self, db, paid_space, member,
    ):
        """Both conditions hold at once: the route asks the door, this
        asks the fee. An invite-only paid Collective requires an
        invitation *and* payment."""
        paid_space.join_policy = "purchase_required"
        db.flush()
        _join(db, paid_space, member)
        assert elig.refusal_for(db, user=member, space=paid_space) is None


# ===========================================================================
# §10 — An agreed price is agreed
# ===========================================================================


class TestRepricingTheCollectiveRepricesNobody:
    def test_an_existing_agreement_keeps_its_amount(
        self, client, db, paid_space, member, as_owner, monkeypatch,
    ):
        monkeypatch.setattr(
            "app.creator.routes.guard_paid_offers_enabled",
            lambda user, db, pricing_type: None,
        )
        _join(db, paid_space, member)
        agreement = _agreement(
            db, paid_space, member, CollectiveMembershipStatus.active.value,
        )
        _patch(
            client, paid_space,
            pricing_type="paid_monthly", pricing_amount_cents=3_900,
        )
        db.refresh(agreement)
        db.refresh(paid_space)
        assert paid_space.pricing_amount_cents == 3_900
        assert agreement.amount_cents == 2_900
        assert agreement.interval == "month"

    def test_repricing_does_not_pause_a_paying_member(
        self, db, paid_space, member,
    ):
        """§10's "Important" — a price change on an already-paid
        Collective must not sweep its existing subscribers."""
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.active.value,
        )
        paid_space.paid_membership_effective_at = NOW - timedelta(days=30)
        paid_space.pricing_amount_cents = 3_900
        db.flush()
        reconcile._sweep_paid_transitions(
            db, now=datetime.utcnow(), report=reconcile.ReconcileReport(),
        )
        row = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == paid_space.id,
            SpaceMembership.user_id == member.id,
        ).one()
        assert row.status == SpaceMembershipStatus.active


# ===========================================================================
# §11 — The existing reconciler, unchanged in intent
# ===========================================================================


def _sweep(db):
    report = reconcile.ReconcileReport()
    reconcile._sweep_paid_transitions(db, now=datetime.utcnow(), report=report)
    return report


def _status(db, space, user):
    return db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space.id,
        SpaceMembership.user_id == user.id,
    ).one().status


class TestTheTransitionSweep:
    def test_a_future_date_is_ignored(self, db, paid_space, member):
        _join(db, paid_space, member)
        paid_space.paid_membership_effective_at = NOW + timedelta(days=30)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, member) == SpaceMembershipStatus.active

    def test_a_due_date_pauses_a_member_who_did_not_subscribe(
        self, db, paid_space, member,
    ):
        _join(db, paid_space, member)
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, member) == SpaceMembershipStatus.paused

    @pytest.mark.parametrize("status", [
        CollectiveMembershipStatus.active.value,
        CollectiveMembershipStatus.past_due.value,
        CollectiveMembershipStatus.cancel_scheduled.value,
    ])
    def test_a_valid_agreement_keeps_a_member_active(
        self, db, paid_space, member, status,
    ):
        _join(db, paid_space, member)
        _agreement(db, paid_space, member, status)
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, member) == SpaceMembershipStatus.active

    def test_a_pending_checkout_does_not_save_them(
        self, db, paid_space, member,
    ):
        """§7 — "a pending checkout does not count as a completed paid
        subscription"."""
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.pending.value,
        )
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, member) == SpaceMembershipStatus.paused

    def test_the_owner_is_never_paused(self, db, paid_space):
        owner = _owner(db, paid_space)
        _join(db, paid_space, owner)
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, owner) == SpaceMembershipStatus.active

    def test_an_invited_member_is_not_exempt(self, db, paid_space, member):
        """§9 — an invitation is eligibility to join, not a free pass."""
        _join(db, paid_space, member, source="invited")
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, member) == SpaceMembershipStatus.paused

    def test_running_it_again_changes_nothing(self, db, paid_space, member):
        _join(db, paid_space, member)
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        first = _sweep(db)
        second = _sweep(db)
        assert first.transitions_paused == 1
        assert second.transitions_paused == 0
        assert _status(db, paid_space, member) == SpaceMembershipStatus.paused

    def test_nobody_is_charged_and_no_agreement_is_written(
        self, db, paid_space, member,
    ):
        """§5, §11 — the sweep pauses. It does not subscribe anybody,
        and it does not reach Stripe."""
        _join(db, paid_space, member)
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        _sweep(db)
        assert db.query(CollectiveMembership).filter(
            CollectiveMembership.space_id == paid_space.id,
        ).count() == 0

    def test_a_free_collective_with_a_stale_date_is_skipped(
        self, db, paid_space, member,
    ):
        """Pausing somebody out of a Collective that sells nothing
        leaves them with no way back: eligibility answers NOT_PAID, so
        there is no checkout to open. The settings route clears the
        date; this is the other half of the same guard."""
        _join(db, paid_space, member)
        paid_space.pricing_type = "free"
        paid_space.paid_membership_effective_at = NOW - timedelta(days=1)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, member) == SpaceMembershipStatus.active

    def test_a_paused_member_can_then_subscribe(self, db, paid_space, member):
        """The whole arc, end to end: swept, paused, and still able to
        buy their way back without leaving or rejoining."""
        row = _join(db, paid_space, member)
        original_id, joined_at = row.id, row.joined_at
        paid_space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()
        _sweep(db)
        assert _status(db, paid_space, member) == SpaceMembershipStatus.paused
        assert elig.refusal_for(db, user=member, space=paid_space) is None
        db.refresh(row)
        assert (row.id, row.joined_at) == (original_id, joined_at)
