"""Stage 5A.3b — the member's side of paid Collective membership.

What changed in the product, not just the code
----------------------------------------------
5A.3a made an omitted transition date mean "existing members carry on
as they are". That read as permanent free membership, and it was not
the decision: when a Collective starts charging, the people already in
it have to subscribe too, and the creator chooses the day. So omission
is no longer a way to grant an indefinite exemption by accident —
though it is still never a way to charge anybody, which is the line
this whole stage walks.

Run with::

    cd backend
    .venv/bin/python -m pytest \\
        tests/test_stage5a3b_membership_member_experience.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_creator_user, get_current_user, get_optional_user,
    get_verified_creator_user, get_verified_current_user,
)
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.models.user import User

NOW = datetime.utcnow()


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def free_space(db, make_space, make_user):
    """A Collective as it is before any of this: free, with members."""
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    space.pricing_type = "free"
    space.timezone = "Australia/Melbourne"
    db.flush()
    return space


@pytest.fixture
def paid_space(db, free_space):
    free_space.pricing_type = "paid_monthly"
    free_space.pricing_amount_cents = 2_900
    free_space.pricing_currency = "AUD"
    db.flush()
    return free_space


@pytest.fixture
def member(make_user):
    return make_user()


def _owner(db, space):
    return db.query(User).filter(User.id == space.creator_id).one()


def _join(db, space, user, status=SpaceMembershipStatus.active,
          source="joined", **kw):
    row = SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role="learner", status=status, source=source, joined_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


def _agreement(db, space, user, status, **kw):
    row = CollectiveMembership(
        id=_uid("cm"), space_id=space.id, user_id=user.id, status=status,
        interval="month", interval_count=1, amount_cents=2_900,
        currency="AUD", **kw,
    )
    db.add(row)
    db.flush()
    return row


def _as_owner(db, space):
    owner = _owner(db, space)
    for dep in (
        get_current_user, get_optional_user, get_verified_current_user,
        get_creator_user, get_verified_creator_user,
    ):
        app.dependency_overrides[dep] = lambda u=owner: u
    return owner


def _as_member(user):
    for dep in (get_current_user, get_optional_user, get_verified_current_user):
        app.dependency_overrides[dep] = lambda u=user: u
    return user


def _no_plan_guard(monkeypatch):
    monkeypatch.setattr(
        "app.creator.routes.guard_paid_offers_enabled",
        lambda user, db, pricing_type: None,
    )


def _patch(client, space, **fields):
    return client.patch(f"/api/creator/spaces/{space.slug}", json=fields)


# ===========================================================================
# §3 — Nobody is left free by omission
# ===========================================================================


class TestBecomingPaidRequiresADate:
    def test_turning_on_paid_with_members_demands_one(
        self, client, db, free_space, member, monkeypatch,
    ):
        """The reversal of 5A.3a's default, and the reason for it.

        Leaving the date empty used to mean "they carry on". It now
        means the creator has not finished the decision.
        """
        _no_plan_guard(monkeypatch)
        _join(db, free_space, member)
        _as_owner(db, free_space)
        res = _patch(
            client, free_space,
            pricing_type="paid_monthly", pricing_amount_cents=2_900,
        )
        assert res.status_code == 422, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "membership_transition_date_required"
        assert detail["members_needing_subscription"] == 1
        # Whether the rejected save persists is deliberately not
        # asserted. In production the request fails, ``get_db`` closes
        # the session and the transaction rolls back with nothing
        # committed. Here the test *is* the route's session, so there
        # is no teardown to roll anything back and the in-memory
        # object still carries the attempted value. Asserting on it
        # would be testing the harness, not the code.

    def test_the_same_save_with_a_date_is_accepted(
        self, client, db, free_space, member, monkeypatch,
    ):
        _no_plan_guard(monkeypatch)
        _join(db, free_space, member)
        _as_owner(db, free_space)
        res = _patch(
            client, free_space,
            pricing_type="paid_monthly", pricing_amount_cents=2_900,
            paid_membership_effective_on="2027-01-01",
        )
        assert res.status_code == 200, res.text
        db.refresh(free_space)
        assert free_space.pricing_type == "paid_monthly"
        assert free_space.paid_membership_effective_at is not None

    def test_with_nobody_to_convert_no_date_is_demanded(
        self, client, db, free_space, monkeypatch,
    ):
        """§3 — "If there are no existing members who need to convert,
        no transition date should be required"."""
        _no_plan_guard(monkeypatch)
        _as_owner(db, free_space)
        res = _patch(
            client, free_space,
            pricing_type="paid_monthly", pricing_amount_cents=2_900,
        )
        assert res.status_code == 200, res.text

    def test_the_owner_alone_is_nobody_to_convert(
        self, client, db, free_space, monkeypatch,
    ):
        _no_plan_guard(monkeypatch)
        owner = _as_owner(db, free_space)
        _join(db, free_space, owner)
        res = _patch(
            client, free_space,
            pricing_type="paid_monthly", pricing_amount_cents=2_900,
        )
        assert res.status_code == 200, res.text

    def test_members_who_already_pay_are_nobody_to_convert(
        self, client, db, free_space, member, monkeypatch,
    ):
        _no_plan_guard(monkeypatch)
        _join(db, free_space, member)
        _agreement(
            db, free_space, member, CollectiveMembershipStatus.active.value,
        )
        _as_owner(db, free_space)
        res = _patch(
            client, free_space,
            pricing_type="paid_monthly", pricing_amount_cents=2_900,
        )
        assert res.status_code == 200, res.text


class TestTheDemandLandsOnceAndOnlyWhereItShould:
    """§3 — "Do not require a new transition date simply because the
    creator edits their pricing note or another unrelated setting"."""

    def test_an_unrelated_edit_to_a_paid_collective_is_not_blocked(
        self, client, db, paid_space, member,
    ):
        _join(db, paid_space, member)
        _as_owner(db, paid_space)
        res = _patch(client, paid_space, pricing_note="Founding rate")
        assert res.status_code == 200, res.text

    def test_an_unrelated_edit_does_not_reset_an_existing_date(
        self, client, db, paid_space, member,
    ):
        _join(db, paid_space, member)
        _as_owner(db, paid_space)
        _patch(client, paid_space, paid_membership_effective_on="2027-01-01")
        res = _patch(client, paid_space, tagline="A new tagline")
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is not None

    def test_repricing_an_already_paid_collective_is_not_blocked(
        self, client, db, paid_space, member, monkeypatch,
    ):
        """It was already paid, so the decision was already made —
        even if whoever made it left the date empty."""
        _no_plan_guard(monkeypatch)
        _join(db, paid_space, member)
        _as_owner(db, paid_space)
        res = _patch(
            client, paid_space,
            pricing_type="paid_monthly", pricing_amount_cents=3_900,
        )
        assert res.status_code == 200, res.text

    def test_reverting_to_free_is_never_blocked(
        self, client, db, paid_space, member,
    ):
        """§3 — the escape hatch must stay open: a creator clearing a
        future transition by going back to Free cannot be held by a
        rule about becoming paid."""
        _join(db, paid_space, member)
        _as_owner(db, paid_space)
        _patch(client, paid_space, paid_membership_effective_on="2027-01-01")
        res = _patch(client, paid_space, pricing_type="free")
        assert res.status_code == 200, res.text
        db.refresh(paid_space)
        assert paid_space.paid_membership_effective_at is None

    def test_going_free_then_paid_again_asks_again(
        self, client, db, paid_space, member, monkeypatch,
    ):
        """Because the date was cleared on the way out, the decision is
        genuinely open again on the way back in."""
        _no_plan_guard(monkeypatch)
        _join(db, paid_space, member)
        _as_owner(db, paid_space)
        _patch(client, paid_space, pricing_type="free")
        res = _patch(client, paid_space, pricing_type="paid_monthly")
        assert res.status_code == 422, res.text
        assert res.json()["detail"]["code"] == (
            "membership_transition_date_required"
        )

    def test_an_immediate_transition_still_needs_acknowledging(
        self, client, db, free_space, member, monkeypatch,
    ):
        """Both rules at once: a date is demanded, and a past one is
        still not accepted silently."""
        _no_plan_guard(monkeypatch)
        _join(db, free_space, member)
        _as_owner(db, free_space)
        yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
        res = _patch(
            client, free_space,
            pricing_type="paid_monthly", pricing_amount_cents=2_900,
            paid_membership_effective_on=yesterday,
        )
        assert res.status_code == 422, res.text
        assert res.json()["detail"]["code"] == (
            "membership_transition_needs_acknowledgement"
        )


# ===========================================================================
# §9 — Resume and cancel were unreachable
# ===========================================================================


class TestManagingAnAgreementIsPossibleAtAll:
    """A defect found by reading the lookup, confirmed by calling it.

    ``_my_live_membership_subscription`` searched ``LIVE_STATUSES`` —
    ``pending``, ``active``, ``past_due``. ``cancel_scheduled`` is not
    in that set, by design: it cannot collide with a new agreement, so
    the partial unique index rightly ignores it. But it is the *only*
    status resume can act on. So the resume endpoint answered 404 for
    the single state it exists to serve, and "cancel again", which its
    own docstring promises is a no-op, answered 404 too.
    """

    def _cancelled(self, db, space, member):
        return _agreement(
            db, space, member,
            CollectiveMembershipStatus.cancel_scheduled.value,
            cancel_at_period_end=True,
            current_period_end=datetime.utcnow() + timedelta(days=20),
        )

    def test_resume_reaches_the_agreement(
        self, client, db, paid_space, member,
    ):
        self._cancelled(db, paid_space, member)
        _as_member(member)
        res = client.post(f"/api/spaces/{paid_space.slug}/membership/resume")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "active"
        assert res.json()["cancel_at_period_end"] is False

    def test_cancelling_twice_is_the_no_op_it_promises(
        self, client, db, paid_space, member,
    ):
        self._cancelled(db, paid_space, member)
        _as_member(member)
        res = client.post(f"/api/spaces/{paid_space.slug}/membership/cancel")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "cancel_scheduled"

    def test_an_agreement_that_ended_is_still_not_manageable(
        self, client, db, paid_space, member,
    ):
        """The widening is one status, not a general relaxation."""
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.ended.value,
        )
        _as_member(member)
        res = client.post(f"/api/spaces/{paid_space.slug}/membership/resume")
        assert res.status_code == 404, res.text

    def test_a_stranger_cannot_manage_somebody_elses(
        self, client, db, paid_space, member, make_user,
    ):
        self._cancelled(db, paid_space, member)
        _as_member(make_user())
        res = client.post(f"/api/spaces/{paid_space.slug}/membership/resume")
        assert res.status_code == 404, res.text


# ===========================================================================
# §12 — The read model
# ===========================================================================


class TestWhatTheMemberIsTold:
    def test_the_agreed_price_is_shown_not_the_list_price(
        self, client, db, paid_space, member,
    ):
        """§12 — "Do not rely on current Collective list pricing".

        The member joined at A$29. The creator has since moved to
        A$39. Quoting them the new number would be quoting a figure
        nobody will ever charge them.
        """
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member,
            CollectiveMembershipStatus.active.value,
            current_period_end=datetime.utcnow() + timedelta(days=20),
        )
        paid_space.pricing_amount_cents = 3_900
        db.flush()
        _as_member(member)
        res = client.get(f"/api/spaces/{paid_space.slug}/membership/state")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["subscription"]["amount_cents"] == 2_900
        assert body["offer"]["amount_cents"] == 3_900

    def test_no_stripe_identifiers_are_exposed(
        self, client, db, paid_space, member,
    ):
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member,
            CollectiveMembershipStatus.active.value,
            stripe_subscription_id="sub_secret",
            stripe_customer_id="cus_secret",
        )
        _as_member(member)
        res = client.get(f"/api/spaces/{paid_space.slug}/membership/state")
        assert "sub_secret" not in res.text
        assert "cus_secret" not in res.text

    def test_a_member_sees_only_their_own(
        self, client, db, paid_space, member, make_user,
    ):
        other = make_user()
        _join(db, paid_space, other)
        _agreement(
            db, paid_space, other, CollectiveMembershipStatus.active.value,
        )
        _as_member(member)
        res = client.get(f"/api/spaces/{paid_space.slug}/membership/state")
        assert res.status_code == 200, res.text
        assert res.json()["subscription"] is None

    def test_the_transition_is_reported_in_the_collectives_own_day(
        self, client, db, paid_space, member,
    ):
        from app.spaces import membership_pricing
        from datetime import date
        _join(db, paid_space, member)
        paid_space.paid_membership_effective_at = (
            membership_pricing.transition_instant(
                date(2027, 1, 1), "Australia/Melbourne",
            )
        )
        db.flush()
        _as_member(member)
        body = client.get(
            f"/api/spaces/{paid_space.slug}/membership/state",
        ).json()
        assert body["transition"]["effective_on"] == "2027-01-01"
        assert body["transition"]["action_needed"] is True

    def test_a_subscriber_has_nothing_to_act_on(
        self, client, db, paid_space, member,
    ):
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.active.value,
        )
        paid_space.paid_membership_effective_at = NOW + timedelta(days=30)
        db.flush()
        _as_member(member)
        body = client.get(
            f"/api/spaces/{paid_space.slug}/membership/state",
        ).json()
        assert body["transition"]["action_needed"] is False

    def test_the_owner_is_never_asked_to_subscribe(
        self, client, db, paid_space,
    ):
        owner = _owner(db, paid_space)
        paid_space.paid_membership_effective_at = NOW - timedelta(days=1)
        db.flush()
        _as_member(owner)
        body = client.get(
            f"/api/spaces/{paid_space.slug}/membership/state",
        ).json()
        assert body["is_owner"] is True
        assert body["transition"]["action_needed"] is False
        assert body["actions"]["can_subscribe"] is False
        assert body["actions"]["subscribe_refusal"] == "membership_own_collective"

    @pytest.mark.parametrize("status,expected", [
        (CollectiveMembershipStatus.active.value,
         {"can_cancel_renewal": True, "can_resume": False}),
        (CollectiveMembershipStatus.past_due.value,
         {"can_cancel_renewal": True, "can_resume": False}),
        (CollectiveMembershipStatus.cancel_scheduled.value,
         {"can_cancel_renewal": False, "can_resume": True}),
        (CollectiveMembershipStatus.pending.value,
         {"can_cancel_renewal": False, "can_resume": False}),
    ])
    def test_the_actions_match_the_state(
        self, client, db, paid_space, member, status, expected,
    ):
        _join(db, paid_space, member)
        _agreement(db, paid_space, member, status)
        _as_member(member)
        actions = client.get(
            f"/api/spaces/{paid_space.slug}/membership/state",
        ).json()["actions"]
        for key, value in expected.items():
            assert actions[key] is value, key


class TestTheSubscriptionsList:
    def test_an_ended_agreement_is_still_listed(
        self, client, db, paid_space, member,
    ):
        """§8 — "Your paid membership has ended" cannot be said about
        a Collective the list silently drops."""
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.ended.value,
        )
        _as_member(member)
        res = client.get("/api/auth/me/membership-subscriptions")
        assert res.status_code == 200, res.text
        slugs = [r["space"]["slug"] for r in res.json()]
        assert paid_space.slug in slugs

    def test_a_member_who_must_convert_is_listed_without_an_agreement(
        self, client, db, paid_space, member,
    ):
        _join(db, paid_space, member)
        paid_space.paid_membership_effective_at = NOW + timedelta(days=30)
        db.flush()
        _as_member(member)
        rows = client.get("/api/auth/me/membership-subscriptions").json()
        assert len(rows) == 1
        assert rows[0]["subscription"] is None
        assert rows[0]["transition"]["action_needed"] is True

    def test_a_free_collective_is_not_listed(
        self, client, db, free_space, member,
    ):
        _join(db, free_space, member)
        _as_member(member)
        assert client.get("/api/auth/me/membership-subscriptions").json() == []

    def test_the_owner_is_not_billed_for_their_own(
        self, client, db, paid_space,
    ):
        owner = _owner(db, paid_space)
        _join(db, paid_space, owner)
        _as_member(owner)
        assert client.get("/api/auth/me/membership-subscriptions").json() == []

    def test_one_row_per_collective_across_several(
        self, client, db, paid_space, member, make_space, make_user,
    ):
        second = make_space(creator=make_user(role="creator"))
        second.pricing_type = "paid_monthly"
        second.pricing_amount_cents = 1_500
        db.flush()
        _join(db, paid_space, member)
        _agreement(
            db, paid_space, member, CollectiveMembershipStatus.active.value,
        )
        _join(db, second, member)
        _agreement(
            db, second, member, CollectiveMembershipStatus.past_due.value,
        )
        _as_member(member)
        rows = client.get("/api/auth/me/membership-subscriptions").json()
        assert len(rows) == 2
        by_slug = {r["space"]["slug"]: r for r in rows}
        assert by_slug[paid_space.slug]["subscription"]["amount_cents"] == 2_900
        assert by_slug[second.slug]["subscription"]["status"] == "past_due"


# ===========================================================================
# §10 — Changing the card on one membership, and only that one
# ===========================================================================


class _StripeDouble:
    """Records what Stripe was asked to do, and answers plausibly."""

    def __init__(self, *, session_meta=None, customer="cus_m", pm="pm_new"):
        self.modified: list[tuple[str, dict]] = []
        self.sessions_created: list[dict] = []
        self.invoices_paid: list[str] = []
        self.open_invoices: list[SimpleNamespace] = []
        self._session_meta = session_meta if session_meta is not None else {}
        self._customer = customer
        self._pm = pm

    # checkout.Session.create
    def create_session(self, **kw):
        self.sessions_created.append(kw)
        return SimpleNamespace(id="cs_setup_1", url="https://stripe.test/pm")

    # checkout.Session.retrieve
    def retrieve_session(self, session_id, **kw):
        return SimpleNamespace(
            id=session_id,
            customer=self._customer,
            metadata=self._session_meta,
            setup_intent=SimpleNamespace(payment_method=self._pm),
        )

    # Subscription.modify
    def modify_subscription(self, sub_id, **kw):
        self.modified.append((sub_id, kw))
        return SimpleNamespace(id=sub_id, **kw)

    def list_invoices(self, **kw):
        return SimpleNamespace(data=self.open_invoices)

    def pay_invoice(self, invoice_id, **kw):
        self.invoices_paid.append(invoice_id)
        return SimpleNamespace(id=invoice_id, status="paid")


@pytest.fixture
def stripe_double(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    double = _StripeDouble()
    monkeypatch.setattr(
        "stripe.checkout.Session.create", lambda **kw: double.create_session(**kw),
    )
    monkeypatch.setattr(
        "stripe.checkout.Session.retrieve",
        lambda sid, **kw: double.retrieve_session(sid, **kw),
    )
    monkeypatch.setattr(
        "stripe.Subscription.modify",
        lambda sid, **kw: double.modify_subscription(sid, **kw),
    )
    monkeypatch.setattr(
        "stripe.Invoice.list", lambda **kw: double.list_invoices(**kw),
    )
    monkeypatch.setattr(
        "stripe.Invoice.pay", lambda iid, **kw: double.pay_invoice(iid, **kw),
    )
    return double


def _subscribed(db, space, member, status=None, **kw):
    _join(db, space, member)
    return _agreement(
        db, space, member,
        status or CollectiveMembershipStatus.active.value,
        stripe_customer_id="cus_m",
        stripe_subscription_id="sub_mine",
        current_period_end=datetime.utcnow() + timedelta(days=20),
        **kw,
    )


class TestChangingTheCard:
    def test_a_hosted_session_is_opened_for_the_members_customer(
        self, client, db, paid_space, member, stripe_double,
    ):
        _subscribed(db, paid_space, member)
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method",
            json={"success_url": "https://ok/s", "cancel_url": "https://ok/c"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["checkout_url"] == "https://stripe.test/pm"
        created = stripe_double.sessions_created[0]
        assert created["mode"] == "setup"
        assert created["customer"] == "cus_m"
        # The API version in use 400s a setup Session without this.
        assert created["currency"] == "aud"
        assert created["metadata"]["collective_membership_id"]

    def test_the_card_lands_on_that_subscription_only(
        self, client, db, paid_space, member, stripe_double,
    ):
        """§10 — the requirement the whole module exists for.

        Provider-level isolation was verified separately against real
        Stripe test mode; this asserts the application asks for the
        subscription-scoped change rather than a customer-level one.
        """
        sub = _subscribed(db, paid_space, member)
        stripe_double._session_meta = {
            "purchase_type": "collective_membership_payment_method",
            "collective_membership_id": sub.id,
        }
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method/confirm",
            json={"session_id": "cs_setup_1"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["updated"] is True
        assert stripe_double.modified == [
            ("sub_mine", {"default_payment_method": "pm_new"}),
        ]

    def test_a_session_naming_another_agreement_is_refused(
        self, client, db, paid_space, member, stripe_double,
    ):
        _subscribed(db, paid_space, member)
        stripe_double._session_meta = {
            "purchase_type": "collective_membership_payment_method",
            "collective_membership_id": "cm_somebody_else",
        }
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method/confirm",
            json={"session_id": "cs_setup_1"},
        )
        assert res.status_code == 409, res.text
        assert stripe_double.modified == []

    def test_a_session_on_another_customer_is_refused(
        self, client, db, paid_space, member, stripe_double,
    ):
        """Metadata alone is not enough — it is a value we wrote."""
        sub = _subscribed(db, paid_space, member)
        stripe_double._customer = "cus_someone_else"
        stripe_double._session_meta = {
            "purchase_type": "collective_membership_payment_method",
            "collective_membership_id": sub.id,
        }
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method/confirm",
            json={"session_id": "cs_setup_1"},
        )
        assert res.status_code == 409, res.text
        assert stripe_double.modified == []

    def test_a_subscription_purchase_session_cannot_be_replayed_here(
        self, client, db, paid_space, member, stripe_double,
    ):
        sub = _subscribed(db, paid_space, member)
        stripe_double._session_meta = {
            "purchase_type": "collective_membership",
            "collective_membership_id": sub.id,
        }
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method/confirm",
            json={"session_id": "cs_setup_1"},
        )
        assert res.status_code == 409, res.text

    def test_an_unfinished_session_changes_nothing(
        self, client, db, paid_space, member, stripe_double,
    ):
        sub = _subscribed(db, paid_space, member)
        stripe_double._session_meta = {
            "purchase_type": "collective_membership_payment_method",
            "collective_membership_id": sub.id,
        }
        stripe_double._pm = None
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method/confirm",
            json={"session_id": "cs_setup_1"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["updated"] is False
        assert stripe_double.modified == []

    def test_a_stranger_cannot_open_one(
        self, client, db, paid_space, member, make_user, stripe_double,
    ):
        _subscribed(db, paid_space, member)
        _as_member(make_user())
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method",
            json={"success_url": "https://ok/s", "cancel_url": "https://ok/c"},
        )
        assert res.status_code == 404, res.text
        assert stripe_double.sessions_created == []


class TestRecovery:
    def test_a_failed_payment_is_retried_once_there_is_a_card(
        self, client, db, paid_space, member, stripe_double,
    ):
        """§11 — recovery of the same agreement, not a new one."""
        sub = _subscribed(
            db, paid_space, member,
            status=CollectiveMembershipStatus.past_due.value,
            grace_expires_at=datetime.utcnow() + timedelta(days=5),
        )
        stripe_double._session_meta = {
            "purchase_type": "collective_membership_payment_method",
            "collective_membership_id": sub.id,
        }
        stripe_double.open_invoices = [SimpleNamespace(id="in_open_1")]
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method/confirm",
            json={"session_id": "cs_setup_1"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["payment_retried"] is True
        assert stripe_double.invoices_paid == ["in_open_1"]
        # The same agreement throughout — no second row anywhere.
        assert db.query(CollectiveMembership).filter(
            CollectiveMembership.space_id == paid_space.id,
            CollectiveMembership.user_id == member.id,
        ).count() == 1

    def test_a_healthy_subscription_is_not_charged_early(
        self, client, db, paid_space, member, stripe_double,
    ):
        """Paying an invoice that is not open would be inventing a
        charge, which is the one thing a card update must not do."""
        sub = _subscribed(db, paid_space, member)
        stripe_double._session_meta = {
            "purchase_type": "collective_membership_payment_method",
            "collective_membership_id": sub.id,
        }
        stripe_double.open_invoices = [SimpleNamespace(id="in_open_1")]
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method/confirm",
            json={"session_id": "cs_setup_1"},
        )
        assert res.json()["payment_retried"] is False
        assert stripe_double.invoices_paid == []

    def test_the_member_keeps_access_while_recovery_runs(
        self, client, db, paid_space, member,
    ):
        _subscribed(
            db, paid_space, member,
            status=CollectiveMembershipStatus.past_due.value,
            grace_expires_at=datetime.utcnow() + timedelta(days=5),
        )
        _as_member(member)
        body = client.get(
            f"/api/spaces/{paid_space.slug}/membership/state",
        ).json()
        assert body["is_member"] is True
        assert body["subscription"]["grace_expires_at"] is not None


# ===========================================================================
# §17 — The flag opens doors; it does not trap anybody behind them
# ===========================================================================


class TestTheFlagAsymmetry:
    def test_no_new_subscription_may_be_opened(
        self, client, db, paid_space, member, monkeypatch,
    ):
        monkeypatch.setattr(
            settings, "paid_collective_membership_enabled", False,
        )
        _join(db, paid_space, member)
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/checkout",
            json={"success_url": "https://ok/s", "cancel_url": "https://ok/c"},
        )
        assert res.status_code == 409, res.text
        assert res.json()["detail"]["code"] == "membership_billing_unavailable"

    def test_the_read_model_says_so_rather_than_offering_a_button(
        self, client, db, paid_space, member, monkeypatch,
    ):
        monkeypatch.setattr(
            settings, "paid_collective_membership_enabled", False,
        )
        _join(db, paid_space, member)
        _as_member(member)
        body = client.get(
            f"/api/spaces/{paid_space.slug}/membership/state",
        ).json()
        assert body["actions"]["can_subscribe"] is False
        assert body["actions"]["subscribe_refusal"] == (
            "membership_billing_unavailable"
        )

    def test_an_existing_agreement_can_still_be_cancelled(
        self, client, db, paid_space, member, monkeypatch, stripe_double,
    ):
        """A switch that could trap somebody in a subscription would
        be the wrong kind of switch."""
        monkeypatch.setattr(
            settings, "paid_collective_membership_enabled", False,
        )
        _subscribed(db, paid_space, member)
        _as_member(member)
        res = client.post(f"/api/spaces/{paid_space.slug}/membership/cancel")
        assert res.status_code == 200, res.text

    def test_an_existing_card_can_still_be_changed(
        self, client, db, paid_space, member, monkeypatch, stripe_double,
    ):
        monkeypatch.setattr(
            settings, "paid_collective_membership_enabled", False,
        )
        _subscribed(db, paid_space, member)
        _as_member(member)
        res = client.post(
            f"/api/spaces/{paid_space.slug}/membership/payment-method",
            json={"success_url": "https://ok/s", "cancel_url": "https://ok/c"},
        )
        assert res.status_code == 200, res.text
