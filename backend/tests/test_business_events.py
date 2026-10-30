"""The history we stopped losing.

The regression that motivates all of this is one sequence: somebody
joins a Collective, leaves, and comes back. Reactivation clears
``removed_at``, so afterwards the row says they never left — and the
reporting that depends on it (churn, tenure, cohort retention) is wrong
in a way nothing in the database can reveal.

So the first test below is join → leave → rejoin → leave producing four
events, and most of the rest of this file exists to protect the
properties that make those four rows trustworthy: that they are written
in the same transaction as the thing they describe, that a webhook retry
does not duplicate them, that a rollback leaves none behind, and that
member-authored content cannot get into them.

Nothing here reaches Stripe or a mail provider. Payment and payout
behaviour is driven through the services that own it, with external
calls mocked at their boundary.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
from app.models.business_event import BusinessEvent
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import business_events as be
from app.services import business_event_reconciliation as recon


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def events(db, *, subject_id=None, event_type=None):
    q = db.query(BusinessEvent)
    if subject_id:
        q = q.filter(BusinessEvent.subject_id == subject_id)
    if event_type:
        q = q.filter(BusinessEvent.event_type == event_type)
    return q.order_by(BusinessEvent.sequence_number).all()


@pytest.fixture
def space_and_member(db, make_user, make_space):
    creator = make_user(role="creator")
    space = make_space(creator=creator)
    member = make_user()
    return space, creator, member


def _membership(db, space, user, *, joined_at=None):
    m = SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        source="joined", joined_at=joined_at or datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# The regression
# ---------------------------------------------------------------------------

class TestTheHistoryThatUsedToVanish:
    def test_join_leave_rejoin_leave_is_four_events(self, db, space_and_member):
        """The sequence the row cannot hold.

        After the second removal the columns look identical to a member
        who joined once and left once. These four rows are the only
        difference.
        """
        from app.services.membership_grant import reactivate

        space, _creator, member = space_and_member
        t0 = datetime.utcnow() - timedelta(days=40)
        m = _membership(db, space, member, joined_at=t0)
        be.membership_started(db, m, occurred_at=t0)

        t1 = t0 + timedelta(days=10)
        m.status = SpaceMembershipStatus.removed
        m.removed_at = t1
        m.removal_kind = "voluntary"
        be.membership_ended(db, m, occurred_at=t1)

        t2 = t1 + timedelta(days=10)
        reactivate(db, m, now=t2)

        t3 = t2 + timedelta(days=10)
        m.status = SpaceMembershipStatus.removed
        m.removed_at = t3
        m.removal_kind = "voluntary"
        be.membership_ended(db, m, occurred_at=t3)
        db.flush()

        got = [(e.event_type, e.occurred_at) for e in events(db, subject_id=m.id)]
        assert [t for t, _ in got] == [
            "membership.started",
            "membership.ended",
            "membership.reactivated",
            "membership.ended",
        ]
        # And in the right order, with the right dates — the whole point.
        assert [when for _, when in got] == [t0, t1, t2, t3]

        # Meanwhile the row itself has forgotten the first departure.
        assert m.removed_at == t3

    def test_the_row_alone_cannot_tell_you_this(self, db, space_and_member):
        """Proves the premise rather than assuming it."""
        from app.services.membership_grant import reactivate

        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        m.status = SpaceMembershipStatus.removed
        m.removed_at = datetime.utcnow()
        m.removal_kind = "creator"
        m.removal_reason = "member_requested"
        db.flush()

        reactivate(db, m, now=datetime.utcnow())
        db.flush()

        # Every trace of the departure is gone from the row.
        assert m.removed_at is None
        assert m.removal_kind is None
        assert m.removal_reason is None
        # But not from the history.
        assert [e.event_type for e in events(db, subject_id=m.id)] == [
            "membership.reactivated",
        ]

    def test_a_rejoin_is_not_counted_as_a_new_member(self, db, space_and_member):
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        be.membership_started(db, m, occurred_at=datetime.utcnow())
        be.membership_reactivated(db, m, occurred_at=datetime.utcnow() + timedelta(days=1))
        db.flush()
        starts = events(db, subject_id=m.id, event_type="membership.started")
        assert len(starts) == 1, "a rejoin must not add a second 'started'"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_the_same_transition_recorded_twice_is_one_row(self, db, space_and_member):
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        when = datetime.utcnow()
        assert be.membership_started(db, m, occurred_at=when) is True
        assert be.membership_started(db, m, occurred_at=when) is False
        db.flush()
        assert len(events(db, subject_id=m.id)) == 1

    def test_two_genuinely_separate_transitions_are_two_rows(
        self, db, space_and_member,
    ):
        """Microsecond precision in the key, so same-second is still two."""
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        t = datetime.utcnow()
        be.membership_ended(db, m, occurred_at=t)
        be.membership_ended(db, m, occurred_at=t + timedelta(microseconds=1))
        db.flush()
        assert len(events(db, subject_id=m.id, event_type="membership.ended")) == 2

    def test_a_stripe_retry_does_not_duplicate(self, db, make_user):
        """Provider-driven events key on the provider's own event id."""
        from app.models.creator_billing import (
            CreatorPlan,
            CreatorSubscription,
            CreatorSubscriptionStatus,
        )

        user = make_user(role="creator")
        plan = CreatorPlan(
            id=_uid("plan"), slug=f"p-{uuid.uuid4().hex[:6]}", name="P",
            monthly_price_cents=1000, currency="AUD", is_active=True,
            transaction_fee_basis_points=1000, collective_limit=1,
        )
        db.add(plan); db.flush()
        sub = CreatorSubscription(
            id=_uid("sub"), user_id=user.id, creator_plan_id=plan.id,
            status=CreatorSubscriptionStatus.active, starts_at=datetime.utcnow(),
            source="stripe_paid",
        )
        db.add(sub); db.flush()

        # Same Stripe event delivered twice, at different wall-clock moments.
        assert be.subscription_cancelled(
            db, sub, occurred_at=datetime.utcnow(),
            reason="provider", provider_event_id="evt_123",
        ) is True
        assert be.subscription_cancelled(
            db, sub, occurred_at=datetime.utcnow() + timedelta(seconds=30),
            reason="provider", provider_event_id="evt_123",
        ) is False
        db.flush()
        assert len(events(db, subject_id=sub.id)) == 1

    def test_a_second_refund_is_its_own_event(self, db, space_and_member):
        """Two partial refunds against one payment are two facts."""
        space, creator, member = space_and_member
        txn = _txn(db, space, creator, member)
        txn.refunded_amount_cents = 500
        be.payment_refunded(
            db, txn, occurred_at=datetime.utcnow(),
            refund_delta_cents=500, provider_event_id="evt_r1",
        )
        txn.refunded_amount_cents = 900
        be.payment_refunded(
            db, txn, occurred_at=datetime.utcnow(),
            refund_delta_cents=400, provider_event_id="evt_r2",
        )
        db.flush()
        got = events(db, subject_id=txn.id, event_type="payment.refunded")
        assert [e.payload["refund_delta_cents"] for e in got] == [500, 400]
        assert [e.payload["refunded_total_cents"] for e in got] == [500, 900]


# ---------------------------------------------------------------------------
# Transaction integrity
# ---------------------------------------------------------------------------

def _txn(db, space, creator, member, **over):
    defaults = dict(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.pending,
        payer_user_id=member.id,
        creator_user_id=creator.id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=10000,
        platform_fee_basis_points=1000,
        platform_fee_cents=1000,
        net_creator_amount_cents=9000,
        stripe_mode="test",
    )
    defaults.update(over)
    t = PaymentTransaction(**defaults)
    db.add(t)
    db.flush()
    return t


class TestAtomicity:
    def test_an_event_travels_with_the_caller_transaction(
        self, db, space_and_member,
    ):
        """No second session, no background task."""
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        be.membership_started(db, m, occurred_at=datetime.utcnow())
        # Visible before any commit, because it is in this transaction.
        assert len(events(db, subject_id=m.id)) == 1

    def test_a_rolled_back_operation_leaves_no_event(self, db, space_and_member):
        """The inverse, which matters just as much: an event must never
        describe something that did not happen."""
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        db.flush()
        mid = m.id

        sp = db.begin_nested()
        be.membership_ended(db, m, occurred_at=datetime.utcnow())
        assert len(events(db, subject_id=mid, event_type="membership.ended")) == 1
        sp.rollback()

        assert events(db, subject_id=mid, event_type="membership.ended") == []

    def test_settlement_stamps_the_column_and_the_event_together(
        self, db, space_and_member,
    ):
        space, creator, member = space_and_member
        txn = _txn(db, space, creator, member)
        when = datetime.utcnow()
        be.mark_settled(db, txn, occurred_at=when, settlement_path="stripe_checkout")
        db.flush()
        assert txn.settled_at == when
        assert txn.settled_at_source == "observed"
        [e] = events(db, subject_id=txn.id, event_type="payment.settled")
        assert e.occurred_at == when
        assert e.payload["settlement_path"] == "stripe_checkout"


# ---------------------------------------------------------------------------
# Settlement provenance
# ---------------------------------------------------------------------------

class TestSettlementProvenance:
    def test_this_release_only_ever_records_observed(self, db, space_and_member):
        space, creator, member = space_and_member
        txn = _txn(db, space, creator, member)
        be.mark_settled(db, txn, occurred_at=datetime.utcnow(), settlement_path="x")
        db.flush()
        assert txn.settled_at_source == "observed"

    def test_history_is_left_null_rather_than_estimated(self, db, space_and_member):
        """The explicit instruction: no estimate presented as fact.

        A transaction that settled before BI-1 has no settlement date,
        and the column says so instead of quietly inheriting
        ``created_at``.
        """
        space, creator, member = space_and_member
        old = _txn(
            db, space, creator, member,
            status=PaymentTransactionStatus.succeeded,
            created_at=datetime.utcnow() - timedelta(days=200),
        )
        db.flush()
        assert old.settled_at is None
        assert old.settled_at_source is None

    def test_the_source_column_refuses_anything_else(self, db, space_and_member):
        from sqlalchemy.exc import IntegrityError

        space, creator, member = space_and_member
        txn = _txn(db, space, creator, member)
        txn.settled_at = datetime.utcnow()
        txn.settled_at_source = "guessed"
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

class TestPrivacy:
    def test_an_undeclared_key_is_refused(self, db, space_and_member):
        """Shape errors raise — they are programming errors, and the
        payload keys are static literals, so a test sees them first."""
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        with pytest.raises(be.BusinessEventPayloadError):
            be.record(
                db,
                event_type=be.BusinessEventType.membership_started,
                occurred_at=datetime.utcnow(),
                subject_type=be.SubjectType.membership,
                subject_id=m.id,
                dedupe_key="k1",
                payload={"removal_note": "something a creator typed"},
            )

    def test_a_long_value_is_truncated_not_refused(self, db, space_and_member):
        """Size is data, not a bug.

        Raising here would let a reporting concern roll back a payment or
        a payout, which is never an acceptable trade — so the value is
        clipped and the event is still recorded. This is not theoretical:
        the payout cancellation path carries an operator-typed reason,
        and an over-long one must not undo the cancellation.
        """
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        be.record(
            db,
            event_type=be.BusinessEventType.membership_started,
            occurred_at=datetime.utcnow(),
            subject_type=be.SubjectType.membership,
            subject_id=m.id,
            dedupe_key="long-value",
            payload={"source": "x" * 400, "role": "learner"},
        )
        db.flush()
        [e] = events(db, subject_id=m.id)
        assert len(e.payload["source"]) == be._MAX_STRING
        assert e.payload["role"] == "learner"

    def test_a_removal_reason_never_reaches_the_event(self, db, space_and_member):
        """Free text a creator wrote about a person stays on the row."""
        space, creator, member = space_and_member
        m = _membership(db, space, member)
        m.removal_kind = "creator"
        m.removal_reason = "inappropriate_behaviour"
        m.removal_note = "A private note about this member."
        be.membership_ended(db, m, occurred_at=datetime.utcnow())
        db.flush()
        [e] = events(db, subject_id=m.id, event_type="membership.ended")
        assert "removal_reason" not in e.payload
        assert "removal_note" not in e.payload
        assert e.payload["removal_kind"] == "creator"
        blob = str(e.payload)
        assert "private note" not in blob.lower()

    def test_no_payload_carries_a_user_id(self, db, space_and_member):
        """User ids live in the SET NULL columns, so deleting an account
        removes the identity — a payload copy would survive it."""
        space, creator, member = space_and_member
        m = _membership(db, space, member)
        be.membership_started(db, m, occurred_at=datetime.utcnow())
        txn = _txn(db, space, creator, member)
        be.mark_settled(db, txn, occurred_at=datetime.utcnow(), settlement_path="x")
        db.flush()
        for e in db.query(BusinessEvent).all():
            blob = str(e.payload)
            assert member.id not in blob
            assert creator.id not in blob

    def test_declared_keys_are_an_allowlist_for_every_event_type(self):
        """Every type has a declared payload shape — no type can slip
        through with an unchecked payload."""
        for t in be.BusinessEventType:
            assert t in be._PAYLOAD_KEYS, f"{t.value} has no declared payload keys"


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------

class TestAccountDeletion:
    def test_deleting_a_user_keeps_the_financial_history(
        self, db, space_and_member,
    ):
        """The balance the platform needs: the identity goes, the fact
        that money moved does not."""
        space, creator, member = space_and_member
        txn = _txn(db, space, creator, member)
        be.mark_settled(
            db, txn, occurred_at=datetime.utcnow(), settlement_path="stripe_checkout",
        )
        db.flush()
        [e] = events(db, subject_id=txn.id, event_type="payment.settled")
        assert e.user_id == member.id
        gross = e.payload["gross_amount_cents"]

        db.execute(
            __import__("sqlalchemy").text("DELETE FROM users WHERE id = :i"),
            {"i": member.id},
        )
        db.flush()
        db.expire_all()

        [e2] = events(db, subject_id=txn.id, event_type="payment.settled")
        assert e2.user_id is None, "the identity must be dropped"
        assert e2.payload["gross_amount_cents"] == gross, (
            "the financial history must survive"
        )


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

class TestTimestamps:
    def test_occurred_at_is_the_business_fact_not_the_write_time(
        self, db, space_and_member,
    ):
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        long_ago = datetime.utcnow() - timedelta(days=90)
        be.membership_ended(db, m, occurred_at=long_ago)
        db.flush()
        [e] = events(db, subject_id=m.id)
        assert e.occurred_at == long_ago
        # recorded_at is now, which is what makes a late arrival visible.
        assert e.recorded_at > long_ago

    def test_tenure_is_computed_from_the_two_dates(self, db, space_and_member):
        space, _creator, member = space_and_member
        joined = datetime.utcnow() - timedelta(days=30)
        m = _membership(db, space, member, joined_at=joined)
        be.membership_ended(db, m, occurred_at=joined + timedelta(days=30))
        db.flush()
        [e] = events(db, subject_id=m.id)
        assert e.payload["tenure_days"] == 30


# ---------------------------------------------------------------------------
# Scoping — the foundation Creator Studio will need
# ---------------------------------------------------------------------------

class TestScoping:
    def test_collective_events_carry_the_space_and_the_creator(
        self, db, space_and_member,
    ):
        """Creator-scoped reporting resolves on these two columns."""
        space, creator, member = space_and_member
        m = _membership(db, space, member)
        be.membership_started(
            db, m, occurred_at=datetime.utcnow(), creator_user_id=creator.id,
        )
        txn = _txn(db, space, creator, member)
        be.mark_settled(db, txn, occurred_at=datetime.utcnow(), settlement_path="x")
        db.flush()
        # Scoped to this test's own subjects. Querying the whole table
        # would also pick up any committed leftovers in ``fc_test``.
        mine = (
            db.query(BusinessEvent)
            .filter(BusinessEvent.subject_id.in_([m.id, txn.id]))
            .all()
        )
        assert len(mine) == 2
        for e in mine:
            assert e.space_id == space.id
            assert e.creator_user_id == creator.id

    def test_one_creator_cannot_see_another(self, db, make_user, make_space):
        """A scoped query returns only the creator's own Collectives."""
        a_creator = make_user(role="creator")
        b_creator = make_user(role="creator")
        a_space = make_space(creator=a_creator)
        b_space = make_space(creator=b_creator)
        for sp, cr in ((a_space, a_creator), (b_space, b_creator)):
            m = _membership(db, sp, make_user())
            be.membership_started(
                db, m, occurred_at=datetime.utcnow(), creator_user_id=cr.id,
            )
        db.flush()

        mine = (
            db.query(BusinessEvent)
            .filter(BusinessEvent.creator_user_id == a_creator.id)
            .all()
        )
        assert len(mine) == 1
        assert mine[0].space_id == a_space.id


# ---------------------------------------------------------------------------
# The feature flag
# ---------------------------------------------------------------------------

class TestRecordingCanBeDisabled:
    def test_it_defaults_to_on(self):
        """An absent configuration must record, not lose."""
        from app.core.config import Settings

        assert Settings().business_events_enabled is True

    def test_disabled_writes_nothing_and_says_so(
        self, db, space_and_member, monkeypatch,
    ):
        """Nothing written, and the drop announced.

        The warning is asserted by patching the module logger rather than
        with ``caplog``: alembic's ``fileConfig`` runs during test setup
        and silences every ``app.*`` logger, so a caplog assertion here
        would pass vacuously whether the log line existed or not.
        """
        from app.core.config import settings

        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        monkeypatch.setattr(settings, "business_events_enabled", False)

        said: list[str] = []
        monkeypatch.setattr(
            be.logger, "warning",
            lambda msg, *a, **k: said.append(msg % a if a else msg),
        )
        assert be.membership_started(db, m, occurred_at=datetime.utcnow()) is False
        db.flush()
        assert events(db, subject_id=m.id) == []
        assert any("business_events disabled" in line for line in said)

    def test_the_business_operation_still_works_when_disabled(
        self, db, space_and_member, monkeypatch,
    ):
        """A disabled recorder must never break a membership change."""
        from app.core.config import settings
        from app.services.membership_grant import reactivate

        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        m.status = SpaceMembershipStatus.removed
        m.removed_at = datetime.utcnow()
        db.flush()
        monkeypatch.setattr(settings, "business_events_enabled", False)
        reactivate(db, m, now=datetime.utcnow())
        db.flush()
        assert m.status == SpaceMembershipStatus.active


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class TestReconciliation:
    def test_before_activation_it_reports_not_started(self, db):
        """Not "everything is broken" — recording has not begun."""
        db.execute(__import__("sqlalchemy").text("DELETE FROM business_events"))
        db.flush()
        report = recon.reconcile(db)
        assert report.activation_floor is None
        assert report.checks == []
        assert report.ok is True

    def test_history_predating_activation_is_not_an_exception(
        self, db, space_and_member,
    ):
        """The safeguard that stops misleading alarms."""
        space, creator, member = space_and_member
        # An old membership and an old payment, both from before anything
        # was recorded.
        _membership(db, space, member, joined_at=datetime.utcnow() - timedelta(days=300))
        _txn(
            db, space, creator, member,
            status=PaymentTransactionStatus.succeeded,
            created_at=datetime.utcnow() - timedelta(days=300),
        )
        # Activation happens now.
        other = _membership(db, space, make_other(db, space), joined_at=datetime.utcnow())
        be.membership_started(db, other, occurred_at=datetime.utcnow())
        db.flush()

        report = recon.reconcile(db)
        assert report.activation_floor is not None
        by_name = {c.name: c for c in report.checks}
        starts = by_name["memberships_without_a_start_event"]
        assert starts.missing == 0, "old memberships must not be exceptions"
        assert starts.pre_activation >= 1, "but they should be counted"
        settle = by_name["succeeded_payments_without_a_settlement"]
        assert settle.missing == 0
        assert settle.pre_activation >= 1

    def test_a_missing_producer_after_activation_is_an_exception(
        self, db, space_and_member,
    ):
        """What catches a thirty-fifth write site added later."""
        space, _creator, member = space_and_member
        seed = _membership(db, space, member, joined_at=datetime.utcnow())
        be.membership_started(db, seed, occurred_at=datetime.utcnow())
        db.flush()

        # A membership created by an imaginary uninstrumented path.
        _membership(
            db, space, make_other(db, space),
            joined_at=datetime.utcnow() + timedelta(seconds=5),
        )
        db.flush()

        report = recon.reconcile(db)
        starts = {c.name: c for c in report.checks}[
            "memberships_without_a_start_event"
        ]
        assert starts.missing == 1
        assert starts.ok is False
        assert report.ok is False

    def test_a_departure_with_no_event_is_caught(self, db, space_and_member):
        space, _creator, member = space_and_member
        seed = _membership(db, space, member, joined_at=datetime.utcnow())
        be.membership_started(db, seed, occurred_at=datetime.utcnow())
        db.flush()

        m2 = _membership(db, space, make_other(db, space))
        be.membership_started(db, m2, occurred_at=datetime.utcnow())
        m2.status = SpaceMembershipStatus.removed
        m2.removed_at = datetime.utcnow() + timedelta(seconds=10)
        db.flush()

        ends = {c.name: c for c in recon.reconcile(db).checks}[
            "departures_without_an_end_event"
        ]
        assert ends.missing == 1

    def test_a_settled_payment_with_no_settlement_is_caught(
        self, db, space_and_member,
    ):
        """The eight-settlement-path safety net."""
        space, creator, member = space_and_member
        m = _membership(db, space, member, joined_at=datetime.utcnow())
        be.membership_started(db, m, occurred_at=datetime.utcnow())
        db.flush()

        _txn(
            db, space, creator, member,
            status=PaymentTransactionStatus.succeeded,
            created_at=datetime.utcnow() + timedelta(seconds=10),
        )
        db.flush()
        settle = {c.name: c for c in recon.reconcile(db).checks}[
            "succeeded_payments_without_a_settlement"
        ]
        assert settle.missing == 1

    def test_a_paid_payout_with_no_event_is_caught(self, db, space_and_member):
        space, creator, member = space_and_member
        m = _membership(db, space, member, joined_at=datetime.utcnow())
        be.membership_started(db, m, occurred_at=datetime.utcnow())
        db.flush()

        txn = _txn(
            db, space, creator, member,
            status=PaymentTransactionStatus.succeeded,
            payout_status=PayoutStatus.paid,
        )
        txn.payout_marked_at = datetime.utcnow() + timedelta(seconds=10)
        txn.settled_at = datetime.utcnow()
        txn.settled_at_source = "observed"
        db.flush()
        payouts = {c.name: c for c in recon.reconcile(db).checks}[
            "paid_payouts_without_an_event"
        ]
        assert payouts.missing == 1

    def test_there_are_never_duplicates(self, db, space_and_member):
        space, _creator, member = space_and_member
        m = _membership(db, space, member)
        when = datetime.utcnow()
        be.membership_started(db, m, occurred_at=when)
        be.membership_started(db, m, occurred_at=when)
        db.flush()
        dupes = {c.name: c for c in recon.reconcile(db).checks}["duplicate_dedupe_keys"]
        assert dupes.missing == 0

    def test_counts_by_type_name_every_declared_event(self, db):
        counts = recon.event_counts_by_type(db)
        for t in be.BusinessEventType:
            assert t.value in counts, f"{t.value} missing from the monitoring view"


def make_other(db, space):
    """A second member, so a test can create an uninstrumented row."""
    from app.models.user import User

    u = User(
        id=_uid("u"),
        email=f"other-{uuid.uuid4().hex[:8]}@example.test",
        name="Other",
        role="user",
        password_hash="$2b$12$0000000000000000000000000000000000000000000000000000",
        email_verified_at=datetime.utcnow(),
    )
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# Coverage of the real write paths
# ---------------------------------------------------------------------------

class TestEveryProducerIsReachedByRealCode:
    """A structural check, not a behavioural one.

    Thirty-four call sites is too many to exercise end to end here, and
    the domain suites already drive those paths. What this guards is the
    thing a behavioural test cannot: that no declared event type has
    been left without a caller, which is how an event quietly becomes
    decorative.
    """

    def test_each_event_type_is_emitted_somewhere_in_the_module(self):
        """Every declared type is referenced by a producer, not just the
        enum — which is how an event quietly becomes decorative."""
        import pathlib

        src = pathlib.Path(be.__file__).read_text()
        for t in be.BusinessEventType:
            member = t.name  # e.g. collective_published
            uses = src.count(f"BusinessEventType.{member}")
            assert uses >= 2, (
                f"{t.value} is declared but never emitted "
                f"(referenced {uses}x; expected the enum plus a producer)"
            )

    def test_every_settlement_path_is_named_by_a_real_call_site(self):
        """The eight paths found in the audit, each with a producer call."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        found: set[str] = set()
        for path in root.rglob("*.py"):
            # Balanced-paren tolerant: a call like
            # ``mark_settled(db, txn, occurred_at=datetime.utcnow(),
            # settlement_path="…")`` contains a nested ``()``.
            for m in re.finditer(
                r'mark_settled\((?:[^()]|\([^()]*\))*settlement_path="([a-z_]+)"',
                path.read_text(), re.S,
            ):
                found.add(m.group(1))
        assert found == {
            "stripe_checkout",
            "instalment_first",
            "instalment_later",
            "instalment_recovery",
            "gathering_ticket",
            "free_purchase",
            "manual_payment_option",
            "manual_pass_grant",
        }, f"settlement paths drifted: {sorted(found)}"
