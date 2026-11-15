"""Stage 5A.3c — the rest of the ways to pay to belong.

Three things, and the thread between them is that each closes a gap
where a member could reasonably believe something that was not true:

* a card they entered and never saw attached, because they closed the
  tab before coming back;
* an annual membership the settings page would have described in
  monthly terms;
* a one-off joining fee shown with a renewal date it will never have.

Run with::

    cd backend
    .venv/bin/python -m pytest \\
        tests/test_stage5a3c_membership_arrangements.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_user, get_optional_user, get_verified_current_user,
)
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import collective_membership_payment_method as pm

NOW = datetime.utcnow()


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def space(db, make_space, make_user):
    creator = make_user(role="creator")
    s = make_space(creator=creator)
    s.pricing_type = "paid_monthly"
    s.pricing_amount_cents = 2_900
    s.pricing_currency = "AUD"
    s.timezone = "Australia/Melbourne"
    db.flush()
    return s


@pytest.fixture
def member(make_user):
    return make_user()


def _as_member(user):
    for dep in (get_current_user, get_optional_user, get_verified_current_user):
        app.dependency_overrides[dep] = lambda u=user: u
    return user


def _join(db, sp, user, status=SpaceMembershipStatus.active, **kw):
    row = SpaceMembership(
        id=_uid("sm"), space_id=sp.id, user_id=user.id, role="learner",
        status=status, source="joined", joined_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


def _agreement(db, sp, user, status=None, **kw):
    kw.setdefault("stripe_customer_id", "cus_m")
    kw.setdefault("stripe_subscription_id", "sub_mine")
    kw.setdefault("interval", "month")
    kw.setdefault("interval_count", 1)
    kw.setdefault("amount_cents", 2_900)
    kw.setdefault("currency", "AUD")
    kw.setdefault("current_period_end", NOW + timedelta(days=20))
    row = CollectiveMembership(
        id=_uid("cm"), space_id=sp.id, user_id=user.id,
        status=status or CollectiveMembershipStatus.active.value, **kw,
    )
    db.add(row)
    db.flush()
    return row


def _setup_session(sub_id, *, session_id="cs_setup_1", customer="cus_m",
                   payment_method="pm_new", purchase_type=None):
    """A ``checkout.session.completed`` object for a card change."""
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": "setup",
        "customer": customer,
        "metadata": {
            "purchase_type": purchase_type or pm.METADATA_PURCHASE_TYPE,
            "collective_membership_id": sub_id,
        },
        "setup_intent": {"id": "seti_1", "payment_method": payment_method},
    }


@pytest.fixture
def stripe_calls(monkeypatch):
    """Records subscription modifications; nothing leaves the process."""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "stripe.Subscription.modify",
        lambda sid, **kw: calls.append((sid, kw)) or SimpleNamespace(id=sid),
    )
    monkeypatch.setattr(
        "stripe.Invoice.list", lambda **kw: SimpleNamespace(data=[]),
    )
    monkeypatch.setattr(
        "stripe.Subscription.delete",
        lambda sid, **kw: calls.append((sid, {"deleted": True}))
        or SimpleNamespace(id=sid, status="canceled"),
    )
    return calls


# ===========================================================================
# §3 — The card lands even if the member never comes back
# ===========================================================================


class TestThePaymentMethodWebhook:
    def _deliver(self, db, session_obj, event_id="evt_1"):
        from app.webhooks import collective_membership_handlers as h
        h.handle_payment_method_setup_completed(
            session_obj, db, event_id=event_id,
        )

    def test_it_claims_only_its_own_sessions(self, db):
        from app.webhooks import collective_membership_handlers as h
        assert h.owns_payment_method_event(_setup_session("cm_x")) is True
        # A membership *purchase* session is a different event with a
        # different consequence — one attaches a card, the other grants
        # membership. Conflating them would be the serious bug.
        assert h.owns_payment_method_event(
            _setup_session("cm_x", purchase_type="collective_membership"),
        ) is False
        assert h.owns_payment_method_event({"metadata": {}}) is False

    def test_a_member_who_closed_the_tab_still_gets_their_card_attached(
        self, db, space, member, stripe_calls,
    ):
        """The gap this stage exists to close."""
        sub = _agreement(db, space, member)
        self._deliver(db, _setup_session(sub.id))
        assert stripe_calls == [
            ("sub_mine", {"default_payment_method": "pm_new"}),
        ]
        db.refresh(sub)
        assert sub.payment_method_setup_session_id == "cs_setup_1"
        assert sub.payment_method_updated_at is not None

    def test_a_duplicate_webhook_changes_nothing(
        self, db, space, member, stripe_calls,
    ):
        sub = _agreement(db, space, member)
        self._deliver(db, _setup_session(sub.id), event_id="evt_1")
        self._deliver(db, _setup_session(sub.id), event_id="evt_1_again")
        assert len(stripe_calls) == 1, "Stripe was asked twice"

    def test_the_return_page_then_the_webhook_settles_once(
        self, db, space, member, stripe_calls, monkeypatch,
    ):
        sub = _agreement(db, space, member)
        session = _setup_session(sub.id)
        monkeypatch.setattr(
            "stripe.checkout.Session.retrieve",
            lambda sid, **kw: session,
        )
        pm.apply_collected_method(
            db, subscription=sub, session_id="cs_setup_1", now=NOW,
        )
        self._deliver(db, session)
        assert len(stripe_calls) == 1

    def test_the_webhook_then_the_return_page_settles_once(
        self, db, space, member, stripe_calls, monkeypatch,
    ):
        sub = _agreement(db, space, member)
        session = _setup_session(sub.id)
        self._deliver(db, session)
        monkeypatch.setattr(
            "stripe.checkout.Session.retrieve", lambda sid, **kw: session,
        )
        out = pm.apply_collected_method(
            db, subscription=sub, session_id="cs_setup_1", now=NOW,
        )
        assert out["already_applied"] is True
        assert len(stripe_calls) == 1

    def test_a_later_setup_supersedes_an_earlier_one(
        self, db, space, member, stripe_calls,
    ):
        """Last completed wins — see migration 190 for why that is the
        rule rather than ranking by when each Session was created."""
        sub = _agreement(db, space, member)
        self._deliver(db, _setup_session(sub.id, session_id="cs_old"))
        self._deliver(db, _setup_session(
            sub.id, session_id="cs_new", payment_method="pm_newer",
        ))
        assert stripe_calls[-1] == (
            "sub_mine", {"default_payment_method": "pm_newer"},
        )
        db.refresh(sub)
        assert sub.payment_method_setup_session_id == "cs_new"

    def test_a_session_for_another_customer_is_refused(
        self, db, space, member, stripe_calls,
    ):
        sub = _agreement(db, space, member)
        self._deliver(db, _setup_session(sub.id, customer="cus_other"))
        assert stripe_calls == []

    def test_a_session_naming_an_unknown_agreement_is_dropped(
        self, db, space, member, stripe_calls,
    ):
        _agreement(db, space, member)
        self._deliver(db, _setup_session("cm_does_not_exist"))
        assert stripe_calls == []

    @pytest.mark.parametrize("status", [
        CollectiveMembershipStatus.ended.value,
        CollectiveMembershipStatus.cancelled.value,
        CollectiveMembershipStatus.failed.value,
    ])
    def test_an_agreement_that_stopped_takes_no_card(
        self, db, space, member, stripe_calls, status,
    ):
        """A member who cancelled while inside Stripe's form. An
        ordinary race, not a fault — so nothing is attached and
        nothing raises."""
        sub = _agreement(db, space, member, status=status)
        self._deliver(db, _setup_session(sub.id))
        assert stripe_calls == []

    def test_no_other_subscription_is_touched(
        self, db, space, member, make_space, make_user, stripe_calls,
    ):
        """§3 — the isolation requirement, at the application layer.
        Provider-level isolation is verified separately against real
        Stripe test mode."""
        other_space = make_space(creator=make_user(role="creator"))
        other_space.pricing_type = "paid_monthly"
        other_space.pricing_amount_cents = 1_500
        db.flush()
        mine = _agreement(db, space, member)
        theirs = _agreement(
            db, other_space, member, stripe_subscription_id="sub_theirs",
        )
        self._deliver(db, _setup_session(mine.id))
        assert [sid for sid, _ in stripe_calls] == ["sub_mine"]
        db.refresh(theirs)
        assert theirs.payment_method_setup_session_id is None


# ===========================================================================
# §5, §6 — Annual, and a membership paid once
# ===========================================================================


@pytest.fixture
def stripe_sessions(monkeypatch):
    """Captures what checkout was asked to create."""
    created: list[dict] = []

    def _session(**kw):
        created.append(kw)
        n = len(created)
        return SimpleNamespace(id=f"cs_test_{n}", url=f"https://stripe.test/{n}")

    monkeypatch.setattr("stripe.checkout.Session.create", _session)
    monkeypatch.setattr(
        "stripe.Product.create", lambda **kw: SimpleNamespace(id="prod_1"),
    )
    monkeypatch.setattr(
        "stripe.Price.create", lambda **kw: SimpleNamespace(id="price_1"),
    )
    monkeypatch.setattr(
        "stripe.Customer.create", lambda **kw: SimpleNamespace(id="cus_new"),
    )
    return created


def _open_checkout(db, space, member):
    from app.services import collective_membership_billing as billing
    return billing.open_membership_checkout(
        db, space=space, member=member,
        success_url="https://ok/s", cancel_url="https://ok/c", now=NOW,
    )


class TestAnnualIsTheSameMachineryWithADifferentInterval:
    def test_it_opens_a_yearly_subscription(
        self, db, space, member, stripe_sessions,
    ):
        space.pricing_type = "paid_annual"
        space.pricing_amount_cents = 29_000
        db.flush()
        outcome = _open_checkout(db, space, member)
        assert outcome.subscription.interval == "year"
        assert outcome.subscription.amount_cents == 29_000
        assert stripe_sessions[0]["mode"] == "subscription"

    def test_the_agreed_year_is_frozen_against_a_reprice(
        self, db, space, member, stripe_sessions,
    ):
        """§5 — "changing a Collective from monthly to annual must not
        silently convert existing monthly subscribers"."""
        existing = _agreement(db, space, member)
        space.pricing_type = "paid_annual"
        space.pricing_amount_cents = 29_000
        db.flush()
        db.refresh(existing)
        assert existing.interval == "month"
        assert existing.amount_cents == 2_900


class TestOneTimeIsNotASubscription:
    def _one_time_space(self, db, space):
        space.pricing_type = "paid_one_time"
        space.pricing_amount_cents = 19_900
        db.flush()
        return space

    def test_checkout_is_payment_mode_with_no_price_object(
        self, db, space, member, stripe_sessions,
    ):
        """§6 — "do not create a recurring Stripe subscription"."""
        self._one_time_space(db, space)
        outcome = _open_checkout(db, space, member)
        session = stripe_sessions[0]
        assert session["mode"] == "payment"
        assert "subscription_data" not in session
        # Priced inline: minting a recurring Price for something that
        # never recurs would leave a subscription-shaped object in
        # Stripe that nobody is subscribed to.
        assert session["line_items"][0]["price_data"]["unit_amount"] == 19_900
        assert outcome.subscription.stripe_price_id is None
        assert outcome.subscription.interval == "one_time"

    def test_a_paid_session_makes_them_a_member(
        self, db, space, member, stripe_calls,
    ):
        from app.webhooks import collective_membership_handlers as h
        self._one_time_space(db, space)
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        h.handle_one_time_completed(
            _paid_one_time_session(row.id), db, event_id="evt_1",
        )
        db.refresh(row)
        assert row.status == CollectiveMembershipStatus.active.value
        assert row.current_period_end is None, "a one-off fee has no period"
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
            SpaceMembership.status == SpaceMembershipStatus.active,
        ).count() == 1

    def test_it_is_recorded_as_a_purchase_not_a_subscription(
        self, db, space, member,
    ):
        """§10 — Payments received must be able to tell them apart."""
        from app.models.payment import (
            PaymentTransaction, PaymentTransactionType,
        )
        from app.webhooks import collective_membership_handlers as h
        self._one_time_space(db, space)
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        h.handle_one_time_completed(
            _paid_one_time_session(row.id), db, event_id="evt_1",
        )
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
            PaymentTransaction.payer_user_id == member.id,
        ).one()
        assert txn.transaction_type == (
            PaymentTransactionType.member_collective_purchase
        )
        assert txn.gross_amount_cents == 19_900
        assert txn.billing_period_start is None
        assert txn.billing_period_end is None

    def test_an_unpaid_session_grants_nothing(self, db, space, member):
        """Reaching the end of the form is not paying for it."""
        from app.webhooks import collective_membership_handlers as h
        self._one_time_space(db, space)
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        session = _paid_one_time_session(row.id)
        session["payment_status"] = "unpaid"
        h.handle_one_time_completed(session, db, event_id="evt_1")
        db.refresh(row)
        assert row.status == CollectiveMembershipStatus.pending.value
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
        ).count() == 0

    def test_a_duplicate_webhook_grants_and_charges_once(
        self, db, space, member,
    ):
        from app.models.payment import PaymentTransaction
        from app.webhooks import collective_membership_handlers as h
        self._one_time_space(db, space)
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        session = _paid_one_time_session(row.id)
        h.handle_one_time_completed(session, db, event_id="evt_1")
        h.handle_one_time_completed(session, db, event_id="evt_1_replay")
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
        ).count() == 1
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
        ).count() == 1

    def test_an_existing_member_converting_keeps_their_row(
        self, db, space, member,
    ):
        from app.webhooks import collective_membership_handlers as h
        self._one_time_space(db, space)
        existing = _join(db, space, member)
        original = (existing.id, existing.joined_at)
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        h.handle_one_time_completed(
            _paid_one_time_session(row.id), db, event_id="evt_1",
        )
        db.refresh(existing)
        assert (existing.id, existing.joined_at) == original
        assert existing.status == SpaceMembershipStatus.active

    def test_a_paused_member_is_unpaused_by_paying_once(
        self, db, space, member,
    ):
        from app.webhooks import collective_membership_handlers as h
        self._one_time_space(db, space)
        existing = _join(db, space, member, status=SpaceMembershipStatus.paused)
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        h.handle_one_time_completed(
            _paid_one_time_session(row.id), db, event_id="evt_1",
        )
        db.refresh(existing)
        assert existing.status == SpaceMembershipStatus.active

    def test_a_creator_removal_is_not_bought_past(self, db, space, member):
        from app.services.membership_removal import REMOVAL_BY_CREATOR
        from app.webhooks import collective_membership_handlers as h
        self._one_time_space(db, space)
        removed = _join(
            db, space, member, status=SpaceMembershipStatus.removed,
            removal_kind=REMOVAL_BY_CREATOR, removed_at=NOW,
            rejoin_blocked=True,
        )
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        h.handle_one_time_completed(
            _paid_one_time_session(row.id), db, event_id="evt_1",
        )
        db.refresh(removed)
        assert removed.status == SpaceMembershipStatus.removed

    def test_there_is_no_renewal_to_cancel(self, db, space, member):
        """§8, §12 — and the refusal is explicit, not an accident of
        a missing Stripe id."""
        from app.services import collective_membership_lifecycle as lifecycle
        self._one_time_space(db, space)
        row = _agreement(
            db, space, member, interval="one_time",
            stripe_subscription_id=None, current_period_end=None,
        )
        with pytest.raises(ValueError) as exc:
            lifecycle.schedule_cancellation(db, subscription=row, now=NOW)
        assert "no renewal to cancel" in str(exc.value)

    def test_there_is_no_card_to_keep_current(self, db, space, member):
        self._one_time_space(db, space)
        row = _agreement(
            db, space, member, interval="one_time",
            current_period_end=None,
        )
        with pytest.raises(pm.PaymentMethodUnavailable) as exc:
            pm.open_collection_session(
                subscription=row, space=space,
                success_url="https://ok/s", cancel_url="https://ok/c",
            )
        assert "no recurring payment" in str(exc.value)

    def test_the_member_is_shown_no_renewal_date(
        self, client, db, space, member,
    ):
        self._one_time_space(db, space)
        _join(db, space, member)
        _agreement(
            db, space, member, interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        _as_member(member)
        body = client.get(f"/api/spaces/{space.slug}/membership/state").json()
        sub = body["subscription"]
        assert sub["is_one_time"] is True
        assert sub["renews_at"] is None
        assert body["actions"]["can_cancel_renewal"] is False
        assert body["actions"]["can_resume"] is False
        assert body["actions"]["can_update_payment_method"] is False

    def test_leaving_ends_it_and_returning_needs_a_new_purchase(
        self, db, space, member,
    ):
        """§6's confirmed rule. The money already paid stays in the
        history; what it bought does not come back on its own."""
        from app.services import collective_membership_reconcile as reconcile
        self._one_time_space(db, space)
        row = _join(db, space, member)
        agreement = _agreement(
            db, space, member, interval="one_time",
            stripe_subscription_id=None, current_period_end=None,
        )
        # The member leaves.
        row.status = SpaceMembershipStatus.removed
        row.removal_kind = "voluntary"
        row.removed_at = NOW
        db.flush()

        report = reconcile.ReconcileReport()
        reconcile._sweep_billing_after_departure(
            db, now=datetime.utcnow(), report=report,
        )
        db.refresh(agreement)
        assert agreement.status not in (
            CollectiveMembershipStatus.active.value,
            CollectiveMembershipStatus.pending.value,
        ), "the one-time agreement should not outlive the membership"


def _paid_one_time_session(sub_id, *, session_id="cs_onetime_1"):
    from app.services.collective_membership_billing import (
        METADATA_ONE_TIME_TYPE,
    )
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": "payment",
        "payment_status": "paid",
        "amount_total": 19_900,
        "currency": "aud",
        "customer": "cus_m",
        "payment_intent": "pi_one_time_1",
        "metadata": {
            "purchase_type": METADATA_ONE_TIME_TYPE,
            "collective_membership_id": sub_id,
        },
    }


# ===========================================================================
# §10, §11 — Verification, not construction
# ===========================================================================


def _txn(db, space, member, *, ttype, gross=2_900, **kw):
    from app.models.payment import (
        PaymentProvider, PaymentTransaction, PaymentTransactionStatus,
        PayoutStatus,
    )
    row = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=ttype,
        status=kw.pop("status", PaymentTransactionStatus.succeeded),
        payment_provider=PaymentProvider.stripe,
        payer_user_id=member.id,
        creator_user_id=space.creator_id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=gross,
        platform_fee_basis_points=kw.pop("fee_bps", 500),
        platform_fee_cents=kw.pop("fee_cents", gross * 5 // 100),
        net_creator_amount_cents=kw.pop(
            "net_cents", gross - (gross * 5 // 100),
        ),
        payout_status=kw.pop("payout_status", PayoutStatus.pending),
        created_at=NOW, updated_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


class TestPaymentsReceivedShowsMembershipMoney:
    """§10 — verification. Both membership transaction types were
    already in the Payments received scope before this stage; these
    tests hold that, and hold the distinction between them."""

    def _as_creator(self, db, space):
        from app.auth.dependencies import (
            get_creator_user, get_verified_creator_user,
        )
        from app.models.user import User
        owner = db.query(User).filter(User.id == space.creator_id).one()
        for dep in (
            get_current_user, get_optional_user, get_verified_current_user,
            get_creator_user, get_verified_creator_user,
        ):
            app.dependency_overrides[dep] = lambda u=owner: u
        return owner

    def test_every_membership_payment_kind_is_reported(
        self, client, db, space, member,
    ):
        from app.models.payment import PaymentTransactionType as T
        # A monthly first payment, its renewal, an annual, and a
        # one-off joining fee.
        _txn(db, space, member, ttype=T.member_collective_subscription,
             gross=2_900, billing_period_start=NOW,
             billing_period_end=NOW + timedelta(days=30))
        _txn(db, space, member, ttype=T.member_collective_subscription,
             gross=2_900, billing_period_start=NOW + timedelta(days=30),
             billing_period_end=NOW + timedelta(days=60))
        _txn(db, space, member, ttype=T.member_collective_subscription,
             gross=29_000, billing_period_start=NOW,
             billing_period_end=NOW + timedelta(days=365))
        _txn(db, space, member, ttype=T.member_collective_purchase,
             gross=19_900)
        self._as_creator(db, space)

        res = client.get(f"/api/creator/payments?space_slug={space.slug}")
        assert res.status_code == 200, res.text
        rows = res.json()
        kinds = [r["transaction_type"] for r in rows]
        assert kinds.count("member_collective_subscription") == 3
        assert kinds.count("member_collective_purchase") == 1

    def test_the_summary_counts_fees_and_creator_earnings(
        self, client, db, space, member,
    ):
        from app.models.payment import PaymentTransactionType as T
        _txn(db, space, member, ttype=T.member_collective_subscription,
             gross=2_900, fee_cents=145, net_cents=2_755)
        _txn(db, space, member, ttype=T.member_collective_purchase,
             gross=19_900, fee_cents=995, net_cents=18_905)
        self._as_creator(db, space)

        res = client.get(
            f"/api/creator/payments/summary?space_slug={space.slug}",
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total_gross_amount_cents"] == 22_800
        assert body["total_platform_fee_cents"] == 1_140
        # The creator's own arrangement decides the split; this stage
        # introduced no membership commission of its own.
        assert body["total_creator_net_amount_cents"] == 21_660

    def test_a_one_time_payment_carries_no_billing_period(
        self, client, db, space, member,
    ):
        """What makes a one-off fee legible as one in the ledger."""
        from app.models.payment import PaymentTransactionType as T
        _txn(db, space, member, ttype=T.member_collective_purchase,
             gross=19_900)
        self._as_creator(db, space)
        row = client.get(
            f"/api/creator/payments?space_slug={space.slug}",
        ).json()[0]
        assert row["transaction_type"] == "member_collective_purchase"
        assert row.get("billing_period_start") is None


class TestRefundsReachMembershipPayments:
    """§11 — verification, and one decision deliberately left open."""

    def test_a_membership_payment_is_refundable_on_the_usual_terms(
        self, db, space, member,
    ):
        from app.creator.refund_routes import refund_eligibility
        from app.models.payment import PaymentTransactionType as T
        txn = _txn(
            db, space, member, ttype=T.member_collective_subscription,
        )
        allowed, reason = refund_eligibility(txn, actor_is_admin=False)
        assert allowed is True, reason

    def test_a_one_time_membership_payment_is_too(
        self, db, space, member,
    ):
        """``transaction_type`` plays no part in the gate — the same
        rule a Gathering ticket gets."""
        from app.creator.refund_routes import refund_eligibility
        from app.models.payment import PaymentTransactionType as T
        txn = _txn(
            db, space, member, ttype=T.member_collective_purchase,
            gross=19_900,
        )
        allowed, reason = refund_eligibility(txn, actor_is_admin=False)
        assert allowed is True, reason

    def test_nothing_is_refundable_twice_over(self, db, space, member):
        from app.creator.refund_routes import refund_eligibility
        from app.models.payment import PaymentTransactionType as T
        txn = _txn(
            db, space, member, ttype=T.member_collective_purchase,
            gross=19_900,
        )
        txn.refunded_amount_cents = 19_900
        db.flush()
        allowed, reason = refund_eligibility(txn, actor_is_admin=False)
        assert allowed is False
        assert reason == "nothing_left"

    def test_a_refund_does_not_end_the_membership_by_itself(
        self, db, space, member,
    ):
        """The open decision, pinned so it cannot change by accident.

        Refund and access-revocation are deliberately separate — a
        partial or goodwill refund must not throw somebody out. The
        consequence, which belongs in a report rather than in a silent
        rule: a creator who fully refunds a membership payment and
        does **not** also revoke has a member who still belongs and,
        on a subscription, will be charged again next period. There is
        no single "refund and end it" action, and this stage did not
        invent one.
        """
        from app.models.payment import PaymentTransactionType as T
        membership = _join(db, space, member)
        agreement = _agreement(db, space, member)
        txn = _txn(
            db, space, member, ttype=T.member_collective_subscription,
        )
        txn.refunded_amount_cents = txn.gross_amount_cents
        db.flush()

        db.refresh(membership)
        db.refresh(agreement)
        assert membership.status == SpaceMembershipStatus.active
        assert agreement.status == CollectiveMembershipStatus.active.value

    def test_revoking_access_is_what_stops_the_billing(
        self, db, space, member, stripe_calls,
    ):
        """And when a creator does revoke, the existing departure
        sweep stops the agreement — so the two halves do join up, just
        not inside the refund itself."""
        from app.services import collective_membership_reconcile as reconcile
        membership = _join(db, space, member)
        agreement = _agreement(db, space, member)
        membership.status = SpaceMembershipStatus.removed
        membership.removal_kind = "creator"
        membership.removed_at = NOW
        db.flush()

        report = reconcile.ReconcileReport()
        reconcile._sweep_billing_after_departure(
            db, now=datetime.utcnow(), report=report,
        )
        db.refresh(agreement)
        assert agreement.status != CollectiveMembershipStatus.active.value


# ===========================================================================
# §13 — A fee paid once must not be described as renewing
# ===========================================================================


class TestWhatTheMemberIsToldTheyBought:
    def _payload(self, db, sub):
        from app.services import collective_membership_emit as emit
        return emit._base_payload(db, sub)

    def test_a_monthly_agreement_says_per_month(self, db, space, member):
        sub = _agreement(db, space, member)
        ctx = self._payload(db, sub)
        assert ctx["interval_label"] == "per month"
        assert ctx["one_time"] is False

    def test_an_annual_agreement_says_per_year(self, db, space, member):
        sub = _agreement(
            db, space, member, interval="year", amount_cents=29_000,
        )
        ctx = self._payload(db, sub)
        assert ctx["interval_label"] == "per year"
        assert ctx["one_time"] is False

    def test_a_one_time_agreement_says_once_and_marks_itself(
        self, db, space, member,
    ):
        """``one_time`` was hard-coded False while a one-off fee could
        not be bought. Deriving it is what stops the purchase message
        telling somebody who paid once that their membership
        "continues until you cancel it"."""
        sub = _agreement(
            db, space, member, interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        ctx = self._payload(db, sub)
        assert ctx["interval_label"] == "once"
        assert ctx["one_time"] is True

    def test_the_purchase_message_promises_no_renewal(
        self, db, space, member,
    ):
        """Rendered, not just resolved — the sentence a member reads."""
        from app.comms.templates import collective_membership as tpl
        sub = _agreement(
            db, space, member, interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        ctx = self._payload(db, sub)
        rendered = tpl.MembershipPurchasedEmail().render(
            db,
            SimpleNamespace(event_type="collective.membership.purchased"),
            SimpleNamespace(template_context=ctx),
        )
        body = " ".join(rendered.paragraphs) if hasattr(rendered, "paragraphs") else str(rendered)
        assert "no renewal" in body
        assert "until you cancel" not in body


# ===========================================================================
# §18 / 5A.4a — A membership bought once survives a change to recurring
# ===========================================================================


class TestOneTimeMembershipSurvivesARepricing:
    """The confirmed rule, which had no test of its own until now.

    Someone paid once for *ongoing* membership. The creator later
    decides membership should be monthly. The question that rule
    answers is whether the earlier purchase still buys what it said it
    bought — and it does: new members meet the new terms, and the
    person who already paid is not re-charged, re-subscribed or
    quietly paused.

    It follows from the shared predicate rather than from a special
    case: a one-time agreement is ``active``, and ``active`` satisfies
    the transition sweep whatever the Collective's pricing has since
    become. Written down here so that reasoning cannot be refactored
    away by accident.
    """

    def _bought_once(self, db, space, member):
        from app.webhooks import collective_membership_handlers as h
        space.pricing_type = "paid_one_time"
        space.pricing_amount_cents = 19_900
        db.flush()
        row = _agreement(
            db, space, member,
            status=CollectiveMembershipStatus.pending.value,
            interval="one_time", amount_cents=19_900,
            stripe_subscription_id=None, current_period_end=None,
        )
        h.handle_one_time_completed(
            _paid_one_time_session(row.id), db, event_id="evt_once",
        )
        db.refresh(row)
        assert row.status == CollectiveMembershipStatus.active.value
        return row

    def test_the_member_who_paid_once_is_not_paused_by_the_transition(
        self, db, space, member,
    ):
        from app.services import collective_membership_reconcile as reconcile
        from app.models.payment import PaymentTransaction

        agreement = self._bought_once(db, space, member)
        membership = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
        ).one()
        joined_at, membership_id = membership.joined_at, membership.id

        # The creator moves to monthly and sets a deadline that passes.
        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 2_900
        space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()

        report = reconcile.ReconcileReport()
        reconcile._sweep_paid_transitions(
            db, now=datetime.utcnow(), report=report,
        )

        db.refresh(membership)
        db.refresh(agreement)
        assert membership.status == SpaceMembershipStatus.active
        assert report.transitions_paused == 0
        # Their agreement is untouched: still one-time, still the
        # amount they agreed, still active.
        assert agreement.interval == "one_time"
        assert agreement.amount_cents == 19_900
        assert agreement.status == CollectiveMembershipStatus.active.value
        # Nothing was created on their behalf and nothing was charged.
        assert db.query(CollectiveMembership).filter(
            CollectiveMembership.space_id == space.id,
            CollectiveMembership.user_id == member.id,
        ).count() == 1
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
            PaymentTransaction.payer_user_id == member.id,
        ).count() == 1
        # And their history is the history they had.
        assert (membership.id, membership.joined_at) == (membership_id, joined_at)

    def test_a_member_who_never_paid_is_still_paused(
        self, db, space, member, make_user,
    ):
        """The control. If the sweep spared everybody the first
        assertion would pass for the wrong reason."""
        from app.services import collective_membership_reconcile as reconcile

        self._bought_once(db, space, member)
        freeloader = make_user()
        _join(db, space, freeloader)

        space.pricing_type = "paid_monthly"
        space.pricing_amount_cents = 2_900
        space.paid_membership_effective_at = NOW - timedelta(minutes=1)
        db.flush()

        reconcile._sweep_paid_transitions(
            db, now=datetime.utcnow(), report=reconcile.ReconcileReport(),
        )
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == freeloader.id,
        ).one().status == SpaceMembershipStatus.paused

    def test_leaving_ends_the_entitlement_so_returning_costs_again(
        self, db, space, member, stripe_calls,
    ):
        """§18's second half. The payment stays in history; what it
        bought does not follow them back in."""
        from app.services import collective_membership_access as access
        from app.services import collective_membership_reconcile as reconcile
        from app.models.payment import PaymentTransaction

        agreement = self._bought_once(db, space, member)
        membership = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
        ).one()

        membership.status = SpaceMembershipStatus.removed
        membership.removal_kind = "voluntary"
        membership.removed_at = NOW
        db.flush()
        reconcile._sweep_billing_after_departure(
            db, now=datetime.utcnow(), report=reconcile.ReconcileReport(),
        )

        db.refresh(agreement)
        assert agreement.status != CollectiveMembershipStatus.active.value
        # The old purchase no longer satisfies anything…
        assert not access.holds_satisfying_agreement(
            db, user_id=member.id, space_id=space.id,
        )
        # …but it is still on the record.
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
            PaymentTransaction.payer_user_id == member.id,
        ).count() == 1
