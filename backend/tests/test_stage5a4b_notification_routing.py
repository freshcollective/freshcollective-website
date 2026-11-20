"""Stage 5A.4b — membership messages are scheduled after the commit.

The first live membership payment produced a ``CommunicationEvent``
that was created, committed, and never delivered. ``emit()`` writes the
event; ``schedule_routing_if_needed`` is what turns it into intents,
and it is, in its own words, "the single call every trigger site makes
after ``emit()``". Twenty-four modules made it. The membership path
made it nowhere, so no membership message of any kind had ever been
deliverable — not purchased, renewed, failed, cancelled, ended or
reactivated.

Order is the whole problem. ``_route_event_bg`` opens its **own**
session and looks the event up by id, so scheduling before the commit
hands the delivery layer a row no other session can see. These tests
pin the order, not just the call.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models.collective_membership import (
    CollectiveMembership, CollectiveMembershipStatus,
)
from app.models.payment import PaymentTransaction
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import collective_membership_emit as emit_mod
from app.webhooks import collective_membership_handlers as handlers

NOW = datetime.utcnow()


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "paid_collective_membership_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")


@pytest.fixture
def space(db, make_space, make_user):
    creator = make_user(role="creator")
    s = make_space(creator=creator)
    s.pricing_type = "paid_monthly"
    s.pricing_amount_cents = 599
    s.pricing_currency = "AUD"
    db.flush()
    return s


@pytest.fixture
def member(make_user):
    return make_user()


@pytest.fixture
def routed(monkeypatch):
    """Records what was scheduled for routing, and when."""
    seen: list[dict] = []

    def _spy(background_tasks, event, event_type):
        seen.append({
            "event_type": event_type,
            # Read through the ORM: if the object were unusable after
            # the commit this raises, which is the failure the real
            # delivery layer would hit.
            "event_id": event.id,
        })

    monkeypatch.setattr(
        "app.comms.rollout.schedule_routing_if_needed", _spy,
    )
    return seen


def _pending(db, space, member, **kw):
    kw.setdefault("interval", "month")
    kw.setdefault("interval_count", 1)
    kw.setdefault("amount_cents", 599)
    kw.setdefault("currency", "AUD")
    kw.setdefault("platform_fee_basis_points", 800)
    row = CollectiveMembership(
        id=f"cmem_route_{len(db.query(CollectiveMembership).all())}",
        space_id=space.id, user_id=member.id,
        creator_user_id=space.creator_id,
        status=CollectiveMembershipStatus.pending.value,
        created_at=NOW, updated_at=NOW, **kw,
    )
    db.add(row)
    db.flush()
    return row


def _paid_invoice(row, *, invoice_id="in_route_1"):
    return {
        "id": invoice_id, "amount_paid": 599, "total": 599, "currency": "aud",
        "charge": "ch_r", "payment_intent": "pi_r",
        "subscription": "sub_stripe_r",
        "metadata": {"collective_membership_id": row.id},
        "lines": {"data": [{"period": {
            "start": int(NOW.timestamp()),
            "end": int((NOW + timedelta(days=30)).timestamp()),
        }}]},
    }


# ===========================================================================
# 1-3. Scheduled, and scheduled in the right order
# ===========================================================================


class TestRoutingIsScheduledAfterTheCommit:

    def test_a_purchase_routes_through_its_real_caller(
        self, db, space, member, routed,
    ):
        row = _pending(db, space, member)
        handlers.handle_invoice_payment_succeeded(
            _paid_invoice(row), db, event_id="evt_r1",
        )
        assert [r["event_type"] for r in routed] == [
            "collective.membership.purchased",
        ]
        assert routed[0]["event_id"]

    def test_the_commit_happens_first(self, db, space, member, monkeypatch):
        """The ordering defect, pinned.

        Routing opens its own session, so an event scheduled before the
        commit is invisible to it — delivered nowhere and logged as
        "vanished before routing". Nothing about the call *looks*
        wrong, which is why the order is asserted rather than assumed.
        """
        order: list[str] = []
        real_commit = db.commit
        monkeypatch.setattr(
            db, "commit",
            lambda *a, **k: (order.append("commit"), real_commit(*a, **k))[1],
        )
        monkeypatch.setattr(
            "app.comms.rollout.schedule_routing_if_needed",
            lambda *a, **k: order.append("route"),
        )
        row = _pending(db, space, member)
        handlers.handle_invoice_payment_succeeded(
            _paid_invoice(row), db, event_id="evt_r2",
        )
        assert order == ["commit", "route"], order

    def test_the_event_is_still_readable_when_routing_is_scheduled(
        self, db, space, member, routed,
    ):
        """Routing needs the id *after* the commit expired the object.

        A detached or unusable instance here would raise inside the
        spy, which reads ``event.id`` exactly as the real scheduler
        does.
        """
        row = _pending(db, space, member)
        handlers.handle_invoice_payment_succeeded(
            _paid_invoice(row), db, event_id="evt_r3",
        )
        from app.comms.models import CommunicationEvent
        assert db.get(CommunicationEvent, routed[0]["event_id"]) is not None


# ===========================================================================
# 4. All six, not just the one that was noticed
# ===========================================================================


class TestEverySixMembershipMessageIsRouted:

    ALL_SIX = [
        "emit_membership_purchased",
        "emit_membership_renewed",
        "emit_membership_payment_failed",
        "emit_membership_cancellation_scheduled",
        "emit_membership_ended",
        "emit_membership_reactivated",
    ]

    @pytest.mark.parametrize("name", ALL_SIX)
    def test_each_emit_queues_itself_for_routing(
        self, db, space, member, name,
    ):
        """Queued by the shared decorator, so no call site can forget —
        and a seventh notification cannot be added without it."""
        row = _pending(db, space, member,
                       stripe_subscription_id="sub_x",
                       current_period_end=NOW + timedelta(days=30))
        row.status = CollectiveMembershipStatus.active.value
        db.flush()
        fn = getattr(emit_mod, name)
        kwargs = {"sub": row}
        if name == "emit_membership_renewed":
            kwargs["invoice_id"] = f"in_{name}"
        fn(db, **kwargs)
        assert db.info.get("collective_membership_pending_routing"), name

    def test_every_emit_is_wrapped_by_the_queueing_decorator(self):
        source = Path(emit_mod.__file__).read_text()
        for name in self.ALL_SIX:
            assert re.search(rf"@_safe_emit\s*\ndef {name}\(", source), name


# ===========================================================================
# 5-6. Failure cannot cost money
# ===========================================================================


class TestFailureIsContained:

    def test_a_failed_commit_schedules_nothing(
        self, db, space, member, routed, monkeypatch,
    ):
        row = _pending(db, space, member)
        monkeypatch.setattr(
            "app.webhooks.collective_membership_handlers"
            ".activate_from_first_invoice",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
        )
        with pytest.raises(RuntimeError):
            handlers.handle_invoice_payment_succeeded(
                _paid_invoice(row), db, event_id="evt_r4",
            )
        assert routed == []
        assert not db.info.get("collective_membership_pending_routing")

    def test_a_routing_failure_leaves_the_money_and_the_membership(
        self, db, space, member, monkeypatch,
    ):
        """A message that cannot be scheduled must not turn a collected
        payment into a failed one."""
        monkeypatch.setattr(
            "app.comms.rollout.schedule_routing_if_needed",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("comms down")),
        )
        row = _pending(db, space, member)
        handlers.handle_invoice_payment_succeeded(
            _paid_invoice(row), db, event_id="evt_r5",
        )
        db.expire_all()
        assert db.query(CollectiveMembership).filter(
            CollectiveMembership.id == row.id,
        ).one().status == CollectiveMembershipStatus.active.value
        txn = db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
        ).one()
        assert (txn.gross_amount_cents, txn.platform_fee_cents,
                txn.net_creator_amount_cents) == (599, 48, 551)
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id,
            SpaceMembership.user_id == member.id,
        ).one().status == SpaceMembershipStatus.active


# ===========================================================================
# 7-8. Never twice
# ===========================================================================


class TestNoDuplicateMessages:

    def test_the_queue_is_drained_so_routing_cannot_repeat(
        self, db, space, member, routed,
    ):
        row = _pending(db, space, member)
        handlers.handle_invoice_payment_succeeded(
            _paid_invoice(row), db, event_id="evt_r6",
        )
        assert len(routed) == 1
        # Draining is what stops a later commit in the same session
        # re-scheduling messages somebody has already received.
        assert emit_mod.route_pending(db) == 0
        assert len(routed) == 1

    def test_a_replayed_invoice_sends_nothing_a_second_time(
        self, db, space, member, routed,
    ):
        """Recovery depends on this: replay is safe precisely because
        the dedupe key means the second emit returns nothing to route."""
        row = _pending(db, space, member)
        invoice = _paid_invoice(row)
        handlers.handle_invoice_payment_succeeded(invoice, db, event_id="e1")
        handlers.handle_invoice_payment_succeeded(invoice, db, event_id="e2")
        assert len(routed) == 1, routed
        db.expire_all()
        assert db.query(PaymentTransaction).filter(
            PaymentTransaction.space_id == space.id,
        ).count() == 1

    def test_one_intent_per_event_and_channel_is_a_database_rule(self):
        """The second half of duplicate protection is not in this code.

        ``create_intent`` documents it: one intent per event x recipient
        x channel, enforced by a partial unique index. Named here so
        that whoever changes routing knows the guarantee exists and
        where it lives.
        """
        from app.comms import models
        source = Path(models.__file__).read_text()
        assert "uq_comm_delivery_intent_attempt" in source


# ===========================================================================
# The guard against the next omission
# ===========================================================================


class TestNoCommitSiteForgetsToRoute:

    def test_every_module_that_commits_membership_events_routes_them(self):
        """The defect was an omission, so this is a test about omissions.

        Any module that both emits a membership message and commits must
        also drain the queue. Matched on the calls themselves, never on
        prose, so a comment mentioning routing cannot satisfy it.
        """
        root = Path(handlers.__file__).resolve().parents[1]
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "collective_membership_emit.py":
                continue
            text = path.read_text()
            emits = re.search(r"emit_membership_\w+\(\s*db", text)
            commits = "db.commit()" in text
            if emits and commits and "route_pending(db)" not in text:
                offenders.append(path.relative_to(root).as_posix())
        assert offenders == [], (
            f"these commit membership events without routing them: {offenders}"
        )
