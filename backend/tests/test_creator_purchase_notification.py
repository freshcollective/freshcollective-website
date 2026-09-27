"""The creator hears, once, when a paid signup succeeds.

The first real EMBODY client completed a purchase and the creator was
told nothing: the generic checkout path — which Series, Pathway and
Collective purchases all take — emitted only the member-facing
``purchase.completed``. A standalone Gathering ticket had an in-app-only
hook; nothing else had anything at all.

``collective.purchase.received`` is one notification per meaningful
purchase. The hard part is what it must NOT do: a Term pass fans out into
dozens of ``EventBooking`` rows and is still one sale, and Stripe
redelivers webhooks.

No email is sent anywhere in this file. Every test asserts on the emitted
``CommunicationEvent`` row or calls the resolver directly; delivery is a
separate layer (``comms.rollout``) that these tests never enter.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

import app.models.community_care  # noqa: F401
import app.main  # noqa: F401 — bootstraps the comms registries
from app.comms.models import CommunicationEvent
from app.comms.registry import get_event_definition
from app.comms.routing.resolver import get_resolver_for
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole
from app.services.purchase_lifecycle_emit import emit_purchase_received_creator

EVENT = "collective.purchase.received"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _events(db, space_id: str) -> list[CommunicationEvent]:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == EVENT,
            CommunicationEvent.source_id == space_id,
        )
        .all()
    )


@pytest.fixture
def collective(db, make_user, make_space):
    """A Collective whose owner also holds a leader membership row."""
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    buyer = make_user(name="Rosalind Franklin")
    db.flush()
    return space, creator, buyer


# ---------------------------------------------------------------------------
# One purchase, one notification
# ---------------------------------------------------------------------------

class TestOnePurchaseOneNotification:
    def test_a_pay_in_full_purchase_emits_once(self, db, collective):
        space, _creator, buyer = collective

        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer,
            experience_name="Term 4 2026", payment_mode="single",
            amount_cents=25000, currency="AUD",
            dedupe_key="purchase_received:txn:txn_1",
        )
        db.flush()

        assert len(_events(db, space.id)) == 1

    def test_a_series_purchase_with_many_bookings_still_emits_once(
        self, db, collective
    ):
        """The constraint that shaped the design: a Term pass creates a
        booking per Gathering, and the Creator wants one piece of news."""
        space, _creator, buyer = collective

        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer,
            experience_name="Term 4 2026", payment_mode="single",
            amount_cents=25000, currency="AUD",
            dedupe_key="purchase_received:txn:txn_series",
            session_count=31,
        )
        db.flush()

        events = _events(db, space.id)
        assert len(events) == 1
        # The fan-out is described, not repeated.
        assert events[0].payload["session_count"] == 31

    def test_a_webhook_redelivery_does_not_duplicate_it(self, db, collective):
        """Same dedupe key twice. The partial unique index on
        ``(event_type, dedupe_key)`` makes the second a no-op."""
        space, _creator, buyer = collective
        args = dict(
            space_id=space.id, buyer=buyer, experience_name="Term 4 2026",
            payment_mode="single", amount_cents=25000, currency="AUD",
            dedupe_key="purchase_received:txn:txn_replay",
        )

        first = emit_purchase_received_creator(db, **args)
        db.flush()
        second = emit_purchase_received_creator(db, **args)
        db.flush()

        assert first is not None
        assert second is None, "a redelivery must not produce a second event"
        assert len(_events(db, space.id)) == 1

    def test_two_genuinely_different_purchases_both_emit(self, db, collective):
        """The dedupe key must not swallow a real second sale."""
        space, _creator, buyer = collective
        for txn in ("txn_a", "txn_b"):
            emit_purchase_received_creator(
                db, space_id=space.id, buyer=buyer,
                experience_name="Term 4 2026", payment_mode="single",
                amount_cents=25000, currency="AUD",
                dedupe_key=f"purchase_received:txn:{txn}",
            )
            db.flush()

        assert len(_events(db, space.id)) == 2

    def test_a_payment_plan_emits_with_its_own_mode(self, db, collective):
        space, _creator, buyer = collective

        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer,
            experience_name="Term 4 2026", payment_mode="plan",
            amount_cents=8400, currency="AUD",
            dedupe_key="purchase_received:plan:plan_1",
        )
        db.flush()

        events = _events(db, space.id)
        assert len(events) == 1
        assert events[0].payload["payment_mode"] == "plan"

    def test_a_plan_and_a_single_purchase_use_different_key_spaces(
        self, db, collective
    ):
        """``plan:`` and ``txn:`` prefixes — an id collision between the
        two tables must not silently suppress a notification."""
        space, _creator, buyer = collective
        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer, experience_name="A",
            payment_mode="single", amount_cents=100, currency="AUD",
            dedupe_key="purchase_received:txn:same_id")
        db.flush()
        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer, experience_name="A",
            payment_mode="plan", amount_cents=100, currency="AUD",
            dedupe_key="purchase_received:plan:same_id")
        db.flush()

        assert len(_events(db, space.id)) == 2


# ---------------------------------------------------------------------------
# What it says
# ---------------------------------------------------------------------------

class TestWhatTheNotificationCarries:
    def test_the_buyer_is_named_through_the_canonical_ladder(
        self, db, make_user, collective
    ):
        """Never an email local part — the same rule as every other
        member-facing surface."""
        space, _creator, _buyer = collective
        unnamed = make_user(name=None, email="private.person.1985@example.test")
        db.flush()

        emit_purchase_received_creator(
            db, space_id=space.id, buyer=unnamed, experience_name="Term 4",
            payment_mode="single", amount_cents=25000, currency="AUD",
            dedupe_key="purchase_received:txn:unnamed")
        db.flush()

        payload = _events(db, space.id)[0].payload
        assert payload["buyer_name"] == "Member"
        assert "private.person" not in str(payload)

    def test_the_amount_is_rendered_for_the_copy(self, db, collective):
        space, _creator, buyer = collective

        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer, experience_name="Term 4",
            payment_mode="single", amount_cents=25000, currency="AUD",
            dedupe_key="purchase_received:txn:money")
        db.flush()

        assert _events(db, space.id)[0].payload["amount_display"] == "A$250"

    def test_the_event_is_registered_under_purchases(self):
        definition = get_event_definition(EVENT)
        assert definition is not None, "event must be registered to route at all"
        assert definition.topic == "purchases"

    def test_it_is_event_locked_like_its_siblings(self):
        """A sale in your own Collective is a money notification, so it
        carries the same lock as every purchase event beside it. Pinned
        because it is a real trade-off, not an accident: a Creator cannot
        quieten these today, and changing that should be deliberate."""
        from app.comms.registry import TRANSACTIONAL_EVENT_TYPES, is_transactional_event

        assert EVENT in TRANSACTIONAL_EVENT_TYPES
        assert is_transactional_event(EVENT) is True


# ---------------------------------------------------------------------------
# Who hears it
# ---------------------------------------------------------------------------

class TestWhoIsNotified:
    def _resolve(self, db, space, buyer, **kw):
        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer, experience_name="Term 4",
            payment_mode="single", amount_cents=25000, currency="AUD",
            dedupe_key=kw.get("dedupe_key", _uid("dk")))
        db.flush()
        event = _events(db, space.id)[-1]
        resolver = get_resolver_for(EVENT)
        assert resolver is not None, "no resolver — the event would reach nobody"
        return {r.user_id for r in resolver.resolve(db, event)}

    def test_the_collective_leader_is_notified(self, db, collective):
        space, creator, buyer = collective

        assert creator.id in self._resolve(db, space, buyer)

    def test_a_moderator_is_notified_too(self, db, make_user, collective):
        space, _creator, buyer = collective
        mod = make_user(name="Mod")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=mod.id, space_id=space.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
        ))
        db.flush()

        assert mod.id in self._resolve(db, space, buyer)

    def test_an_owner_without_a_membership_row_is_still_notified(
        self, db, make_user, make_space
    ):
        """The canonical creator rule (``_get_managed_space``,
        ``SpaceViewer.is_leader``) is owner OR leader membership. The older
        booking hook reads membership rows alone, so for a Collective whose
        owner holds no row it notifies nobody — the legacy case
        ``space_viewer`` documents. This resolver follows the canonical
        rule instead.
        """
        owner = make_user(role="creator", name="Owner Only")
        space = make_space(creator=owner)   # no SpaceMembership row
        buyer = make_user(name="Buyer")
        db.flush()

        assert owner.id in self._resolve(db, space, buyer)

    def test_a_learner_is_not_notified(self, db, make_user, collective):
        space, _creator, buyer = collective
        learner = make_user(name="Learner")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=learner.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.flush()

        assert learner.id not in self._resolve(db, space, buyer)

    def test_a_creator_buying_from_their_own_collective_is_not_told(
        self, db, collective
    ):
        space, creator, _buyer = collective

        assert creator.id not in self._resolve(db, space, creator)

    def test_each_leader_is_addressed_once(self, db, collective):
        """The owner also holds a creator membership row in this fixture —
        the union must not produce two notifications for one person."""
        space, creator, buyer = collective
        event = None
        emit_purchase_received_creator(
            db, space_id=space.id, buyer=buyer, experience_name="Term 4",
            payment_mode="single", amount_cents=1, currency="AUD",
            dedupe_key="purchase_received:txn:dedupe_leader")
        db.flush()
        event = _events(db, space.id)[-1]
        ids = [r.user_id for r in get_resolver_for(EVENT).resolve(db, event)]

        assert ids.count(creator.id) == 1


# ---------------------------------------------------------------------------
# The paid Gathering path must not notify twice
# ---------------------------------------------------------------------------

class TestNoDuplicateOnPaidGatherings:
    def test_the_paid_ticket_path_no_longer_calls_the_booking_hook(self):
        """A paid standalone Gathering used to fire the in-app-only
        ``trigger_event_booking_creator`` as well. Routing it through the
        shared purchase event instead means that hook must not also run,
        or the Creator gets two notifications for one sale.

        Asserted on the parsed AST rather than the source text, because
        the file *mentions* the function in a comment explaining exactly
        this — a substring check would pass on the prose and miss a real
        call.
        """
        source = Path("app/webhooks/routes.py").read_text()
        tree = ast.parse(source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        assert "trigger_event_booking_creator" not in called
        assert "trigger_event_booking_creator" in source, (
            "the explanatory comment should stay — this test is about calls"
        )

    def test_the_free_booking_path_keeps_its_creator_notification(self):
        """Only the *purchase* moved. A free or creator-added booking has
        no sale to announce and keeps the original hook."""
        source = Path("app/spaces/routes.py").read_text()
        tree = ast.parse(source)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Name):
                        names.append(arg.id)
                if isinstance(node.func, ast.Name):
                    names.append(node.func.id)

        assert "trigger_event_booking_creator" in names
