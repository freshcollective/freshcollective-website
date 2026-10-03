"""The creator notification was emitted and never routed.

The production evidence
-----------------------
* ``evt_9daa81499954`` — a finite-plan creator purchase — has an
  ``in_app`` intent (sent) and an ``email_transactional`` intent to
  hello@freshcollective.au (delivered).
* ``evt_d0a9f021ecde`` — an ordinary one-off purchase — has no
  communication intents at all.
* ``evt_46ab472444d7`` and ``evt_65cc69adc3d3`` — the EMBODY purchases
  — likewise none.

A ``communication_events`` row with zero ``communication_intents`` is a
distinctive failure: the emit worked, the dedupe key is taken, and
nothing was ever sent. It is silent in logs and invisible to any check
that asks whether the event fired.

The cause
---------
Both paths emit the same event. Only one routes it:

* the finite-plan handler keeps the returned event, commits, then calls
  ``schedule_routing_if_needed(None, creator_event,
  "collective.purchase.received")``;
* the ordinary checkout path called ``emit_purchase_received_creator``
  and **discarded the return value**, then scheduled routing for the
  member's ``purchase.completed`` only.

Why the existing tests missed it
--------------------------------
There are two dedicated test files for this notification, and both say
so in their own docstrings. ``test_creator_purchase_notification.py``:
"No email is sent anywhere in this file … delivery is a separate layer
(``comms.rollout``) that these tests never enter."
``test_creator_notification_space_purchase.py``: "No email is sent:
these assert on the emitted ``CommunicationEvent`` row and never enter
the delivery layer."

Both assert the half that worked. The event row was never missing.

So this file is the one that enters the routing layer and asserts on
``communication_intents``, using the SAVEPOINT-scoped
``_run_route_event_bg`` harness the R2A/R2B comms tests established so
the routing wrapper and the in-app provider both see the test rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.models.community_care  # noqa: F401 — relationship bootstrap
import app.main  # noqa: F401 — bootstraps registries + providers
from app.checkout.schemas import UnifiedCheckoutRequest
from app.comms.categories import (
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
)
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.comms.rollout import _route_event_bg, is_event_live
from app.core.config import settings
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.purchase_lifecycle_emit import emit_purchase_received_creator


CREATOR_EVENT = "collective.purchase.received"
MEMBER_EVENT = "purchase.completed"
OPTION_NAME = "⚡ Activate — 2 Sessions per week"
AMOUNT_CENTS = 30600


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Routing harness — mirrors test_r2b_welcome_and_plan_activated.py
# ---------------------------------------------------------------------------


class _NoClose:
    """Keeps the routing wrapper and the in-app provider from tearing
    down the test's SAVEPOINT when they close their own session."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


def _routing_against_test_session(db):
    """Context manager: route inside the test's session, not a new one.

    ``schedule_routing_if_needed`` runs synchronously when there is no
    BackgroundTasks — which is the webhook case — and opens a fresh
    ``SessionLocal``. That session cannot see SAVEPOINT-scoped rows, so
    without this the intents would be created against data it believes
    does not exist.
    """
    from app.comms.providers import get as _get_provider

    inapp = _get_provider("in_app")

    class _Ctx:
        def __enter__(self):
            self._original = inapp._session_factory  # type: ignore[attr-defined]
            inapp._session_factory = lambda: _NoClose(db)  # type: ignore[attr-defined]
            self._patch = patch(
                "app.comms.rollout.SessionLocal",
                return_value=_NoClose(db),
            )
            self._patch.start()
            return self

        def __exit__(self, *exc):
            self._patch.stop()
            inapp._session_factory = self._original  # type: ignore[attr-defined]
            return False

    return _Ctx()


def _run_route_event_bg(db, event_id: str) -> None:
    with _routing_against_test_session(db):
        _route_event_bg(event_id, "live")


@pytest.fixture(autouse=True)
def _no_real_email():
    """Intents are the subject here; the provider round-trip is not.
    Stubbed so a missing RESEND_API_KEY cannot change an assertion."""
    with patch("resend.Emails.send", new_callable=MagicMock) as sdk, \
         patch("resend.api_key", create=True), \
         patch(
             "app.services.email_service.email_service.send",
             new_callable=MagicMock,
         ):
        yield sdk


@pytest.fixture
def stripe_configured(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_dummy")


@pytest.fixture
def live_shape(db, make_space, make_user, stripe_configured):
    """The live EMBODY shape: a space-attached one-time pass.

    Same fixture shape as ``test_creator_notification_space_purchase``,
    because that file already established this is what the real
    purchase looked like.
    """
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    buyer = make_user(name="Rosalind Franklin")
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="space", attaches_to_id=space.id,
        name=OPTION_NAME, payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=AMOUNT_CENTS, currency="AUD",
        sessions_per_week=2,
    )
    db.add(opt)
    db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id,
        name="Pay in full", schedule_type="pay_in_full",
        status="published", total_amount_cents=AMOUNT_CENTS, currency="AUD",
    )
    db.add(sched)
    db.flush()
    return SimpleNamespace(
        space=space, creator=creator, buyer=buyer, option=opt, schedule=sched,
    )


def _buy(db, s, session_id: str) -> dict:
    """Create the checkout session; return the metadata Stripe would
    hand back on completion."""
    from app.checkout.routes import create_unified_checkout_session

    with patch("stripe.checkout.Session.create") as m:
        m.return_value = SimpleNamespace(
            id=session_id, url="https://checkout.stripe.test/x",
        )
        create_unified_checkout_session(
            UnifiedCheckoutRequest(
                payment_option_id=s.option.id,
                payment_option_schedule_id=s.schedule.id,
                success_url="https://ok/s", cancel_url="https://ok/c",
            ),
            current_user=s.buyer, db=db,
        )
    return m.call_args.kwargs["metadata"]


class _RoutingCalls(list):
    """What the handler asked to be routed, in order.

    Each entry is ``(background_tasks, event, event_type)`` — exactly
    the arguments ``schedule_routing_if_needed`` received.
    """

    def for_type(self, event_type: str) -> list:
        return [c for c in self if c[2] == event_type]

    def events_for(self, event_type: str) -> list:
        return [c[1] for c in self.for_type(event_type) if c[1] is not None]


def _drive(db, call, *, creator_event=None) -> _RoutingCalls:
    """Run a handler and capture what it asked to route.

    Two harness facts make this the shape it is.

    **Routing cannot run in place.** In production
    ``schedule_routing_if_needed`` opens its own session, deliberately,
    because it runs after the commit and must read committed state. A
    SAVEPOINT-scoped test has no committed state to read, and pointing
    that session at the fixture's own collides with its
    savepoint-restart listener. ``schedule_routing_if_needed`` never
    raises by design, so the collision is swallowed and the test would
    report "no intents" for a harness fault — indistinguishable from
    the production bug.

    **The creator emit cannot return its event here.** ``comms.emit``
    wraps a dedupe-keyed insert in ``with db.begin_nested()``, which
    the fixture's listener breaks once anything in the session has
    committed — and the handler commits before this point. So inside
    this fixture ``emit_purchase_received_creator`` yields ``None`` even
    on a first emit, and routing is correctly skipped for a ``None``
    event. ``emit_purchase_completed`` passes no dedupe key, takes
    ``emit``'s fast path, and is unaffected — which is exactly why the
    member's half of this notification has always been testable and the
    creator's half has not.

    Pass ``creator_event`` to stand in for what the emit returns in
    production. The assertion then lands where the defect actually was:
    the handler must hand on whatever it got back.
    """
    calls = _RoutingCalls()

    def _capture(background_tasks, event, event_type):
        calls.append((background_tasks, event, event_type))

    stack = [patch(
        "app.comms.rollout.schedule_routing_if_needed", side_effect=_capture,
    )]
    if creator_event is not None:
        # Both call sites reach the emit through the module object
        # (``_r3.emit_purchase_received_creator``), so one patch covers
        # the ordinary checkout path and the finite-plan path alike.
        stack.append(patch(
            "app.services.purchase_lifecycle_emit.emit_purchase_received_creator",
            return_value=creator_event,
        ))
    try:
        for p in stack:
            p.start()
        call()
    finally:
        for p in reversed(stack):
            p.stop()
    return calls


def _complete(
    db, metadata: dict, session_id: str, *, creator_event=None,
) -> _RoutingCalls:
    """Drive the real webhook handler for an ordinary one-off purchase."""
    from app.webhooks.routes import _handle_checkout_completed

    return _drive(db, lambda: _handle_checkout_completed(
        {
            "id": session_id,
            "payment_status": "paid",
            "payment_intent": f"pi_{session_id}",
            "amount_total": AMOUNT_CENTS,
            "currency": "aud",
            "metadata": metadata,
        },
        db,
    ), creator_event=creator_event)


def _stand_in_event():
    """Stands in for the event the emit returns in production.

    Deliberately not a DB row. ``schedule_routing_if_needed`` reads
    only ``event.id``, and writing a real row before driving a handler
    that commits is fragile inside the SAVEPOINT fixture — the row and
    the handler's own rows fight over the savepoint. What these tests
    need from it is identity, so that is all it has.

    Whether routing that event produces real intents is proven
    separately, against a genuinely emitted row, in
    ``TestRoutingProducesBothChannels``.
    """
    return SimpleNamespace(id=f"evt_stand_in_{uuid.uuid4().hex[:10]}")


def _events(db, space_id: str, event_type: str) -> list[CommunicationEvent]:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == event_type,
            CommunicationEvent.source_id == space_id,
        )
        .all()
    )


def _intents(db, event_id: str) -> list[CommunicationIntent]:
    return (
        db.query(CommunicationIntent)
        .filter(CommunicationIntent.event_id == event_id)
        .all()
    )


def _channels(intents) -> set[str]:
    return {i.channel for i in intents}


# ---------------------------------------------------------------------------
# The test that would have caught it
# ---------------------------------------------------------------------------


class TestAnEventWithNoIntentsIsTheProductionFailure:
    """The exact signature from the report, reproduced deliberately.

    Every existing test of this notification stops at the event row, so
    this characterises the half that was missing: emitting writes the
    row and takes the dedupe key, and only routing turns it into
    anything a person receives. The two steps are independent, and a
    caller can do the first and forget the second — which is what
    happened.
    """

    def test_emitting_without_routing_leaves_an_event_and_no_intents(
        self, db, live_shape,
    ):
        s = live_shape
        event = emit_purchase_received_creator(
            db, space_id=s.space.id, buyer=s.buyer,
            experience_name=OPTION_NAME, payment_mode="single",
            amount_cents=AMOUNT_CENTS, currency="AUD",
            dedupe_key=f"purchase_received:txn:{_uid('txn')}",
        )
        db.flush()

        assert event is not None
        assert _intents(db, event.id) == [], (
            "the production shape: an event row with nothing to deliver"
        )

    def test_routing_is_what_creates_the_intents(self, db, live_shape):
        """The other half, so the first test is a statement about
        routing rather than about the emit being broken."""
        s = live_shape
        event = emit_purchase_received_creator(
            db, space_id=s.space.id, buyer=s.buyer,
            experience_name=OPTION_NAME, payment_mode="single",
            amount_cents=AMOUNT_CENTS, currency="AUD",
            dedupe_key=f"purchase_received:txn:{_uid('txn')}",
        )
        db.flush()
        assert _intents(db, event.id) == []

        _run_route_event_bg(db, event.id)

        assert _intents(db, event.id) != [], (
            "routing produced nothing — the notification cannot arrive"
        )

    def test_the_topic_is_live_so_routing_is_not_a_no_op(self):
        """``schedule_routing_if_needed`` returns early when the topic
        is not live. If ``collective.purchase.received`` were dormant,
        every assertion in this file would pass for the wrong reason."""
        assert is_event_live(CREATOR_EVENT), (
            f"{CREATOR_EVENT} is not in COMMS_LIVE_TOPICS"
        )


# ---------------------------------------------------------------------------
# 1 + 2 — the ordinary one-off purchase, and its redelivery
# ---------------------------------------------------------------------------


class TestTheOrdinaryOneOffPurchase:
    """The path from the report. Driven through the real webhook
    handler with the real EMBODY option shape."""

    def test_the_handler_routes_the_creator_event(self, db, live_shape):
        """The defect, named precisely: the return value of
        ``emit_purchase_received_creator`` was discarded, so nothing was
        ever handed to routing. The assertion is on the arguments
        routing received, because that call is what was missing."""
        s = live_shape
        session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
        metadata = _buy(db, s, session_id)
        stand_in = _stand_in_event()

        calls = _complete(db, metadata, session_id, creator_event=stand_in)

        routed = calls.events_for(CREATOR_EVENT)
        assert len(routed) == 1, (
            f"routing calls were {[c[2] for c in calls]}"
        )
        assert routed[0].id == stand_in.id, (
            "something other than the emitted event was routed"
        )

    def test_a_redelivered_webhook_routes_nothing_a_second_time(
        self, db, live_shape,
    ):
        """Proof 2. Stripe redelivers. The handler short-circuits on
        ``fulfilment_status == applied``, so the second delivery reaches
        neither the emit nor routing."""
        s = live_shape
        session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
        metadata = _buy(db, s, session_id)
        stand_in = _stand_in_event()

        first = _complete(db, metadata, session_id, creator_event=stand_in)
        assert len(first.events_for(CREATOR_EVENT)) == 1

        second = _complete(db, metadata, session_id, creator_event=stand_in)

        assert second.events_for(CREATOR_EVENT) == [], (
            "redelivery asked for the creator notification again"
        )
        assert second.for_type(MEMBER_EVENT) == []

    def test_a_repeat_emit_cannot_create_a_second_event(self, db, live_shape):
        """The second guard, below the handler: the partial unique index
        on ``(event_type, dedupe_key)``. Belt and braces, because a
        redelivery that somehow got past the short-circuit must still
        not notify twice."""
        s = live_shape
        key = f"purchase_received:txn:{uuid.uuid4().hex[:10]}"
        args = dict(
            space_id=s.space.id, buyer=s.buyer,
            experience_name=OPTION_NAME, payment_mode="single",
            amount_cents=AMOUNT_CENTS, currency="AUD", dedupe_key=key,
        )

        first = emit_purchase_received_creator(db, **args)
        db.flush()
        second = emit_purchase_received_creator(db, **args)
        db.flush()

        assert first is not None
        assert second is None, "the dedupe key did not hold"
        assert len(_events(db, s.space.id, CREATOR_EVENT)) == 1

    def test_the_member_still_gets_purchase_completed(self, db, live_shape):
        """Proof 3. The member's comms went through the one routing call
        that was already there; adding the creator's must not disturb
        it."""
        s = live_shape
        session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
        metadata = _buy(db, s, session_id)

        calls = _complete(db, metadata, session_id)

        member = calls.events_for(MEMBER_EVENT)
        assert len(member) == 1
        _run_route_event_bg(db, member[0].id)
        assert _intents(db, member[0].id), (
            "the member's purchase.completed stopped routing"
        )

    def test_both_sides_of_the_purchase_are_routed(self, db, live_shape):
        """One purchase, two audiences, two routing calls — asserted
        together, because the bug was precisely that one of them
        happened and the other did not."""
        s = live_shape
        session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
        metadata = _buy(db, s, session_id)
        stand_in = _stand_in_event()

        calls = _complete(db, metadata, session_id, creator_event=stand_in)

        assert {c[2] for c in calls} == {MEMBER_EVENT, CREATOR_EVENT}

    def test_routing_is_asked_for_after_the_commit(self, db, live_shape):
        """Ordering, as behaviour. Routing reads committed state in
        production, so asking before the commit could route an event
        the reader cannot see — and a rollback afterwards would announce
        a purchase that never happened.

        Asserted by what is still pending when routing is asked for:
        nothing.
        """
        s = live_shape
        session_id = f"cs_test_{uuid.uuid4().hex[:10]}"
        metadata = _buy(db, s, session_id)
        stand_in = _stand_in_event()
        pending: list[tuple[int, int]] = []

        def _capture(background_tasks, event, event_type):
            pending.append((len(db.new), len(db.dirty)))

        from app.webhooks.routes import _handle_checkout_completed

        with patch(
            "app.comms.rollout.schedule_routing_if_needed",
            side_effect=_capture,
        ), patch(
            "app.services.purchase_lifecycle_emit.emit_purchase_received_creator",
            return_value=stand_in,
        ):
            _handle_checkout_completed(
                {
                    "id": session_id,
                    "payment_status": "paid",
                    "payment_intent": f"pi_{session_id}",
                    "amount_total": AMOUNT_CENTS,
                    "currency": "aud",
                    "metadata": metadata,
                },
                db,
            )

        assert pending, "routing was never asked for"
        assert all(n == 0 and d == 0 for n, d in pending), (
            f"routing asked for with work still pending: {pending}"
        )

# ---------------------------------------------------------------------------
# What routing an event actually produces
# ---------------------------------------------------------------------------


class TestRoutingProducesBothChannels:
    """Proof 1, at the layer the production rows are missing from.

    Driven off a genuinely emitted event with no handler involved, so
    these assertions are about the routing layer rather than about the
    fixture's transaction state. The handler tests above prove the event
    reaches here; these prove what happens when it does.
    """

    def _emit(self, db, s, *, payment_mode="single", amount=AMOUNT_CENTS):
        event = emit_purchase_received_creator(
            db, space_id=s.space.id, buyer=s.buyer,
            experience_name=OPTION_NAME, payment_mode=payment_mode,
            amount_cents=amount, currency="AUD",
            dedupe_key=f"purchase_received:txn:{uuid.uuid4().hex[:10]}",
        )
        db.flush()
        assert event is not None
        return event

    def test_an_in_app_and_an_email_intent_are_created(self, db, live_shape):
        event = self._emit(db, live_shape)

        _run_route_event_bg(db, event.id)

        intents = _intents(db, event.id)
        assert intents, "no intents — the creator still hears nothing"
        assert _channels(intents) >= {
            CHANNEL_IN_APP, CHANNEL_EMAIL_TRANSACTIONAL,
        }, f"channels were {_channels(intents)}"

    def test_the_intents_are_addressed_to_the_collectives_leader(
        self, db, live_shape,
    ):
        """Not merely that intents exist: the creator is who they are
        for, and the buyer must not be told about their own purchase a
        second time."""
        s = live_shape
        event = self._emit(db, s)

        _run_route_event_bg(db, event.id)

        recipients = {i.recipient_user_id for i in _intents(db, event.id)}
        assert s.creator.id in recipients
        assert s.buyer.id not in recipients

    def test_the_plan_payment_mode_routes_the_same_way(self, db, live_shape):
        """The finite-plan path emits with ``payment_mode='plan'``. Same
        recipients, same channels — the two paths differ in when they
        fire, not in who hears."""
        s = live_shape
        event = self._emit(db, s, payment_mode="plan", amount=2000)

        _run_route_event_bg(db, event.id)

        intents = _intents(db, event.id)
        assert _channels(intents) >= {
            CHANNEL_IN_APP, CHANNEL_EMAIL_TRANSACTIONAL,
        }
        assert s.creator.id in {i.recipient_user_id for i in intents}


# ---------------------------------------------------------------------------
# 4 — the finite-plan path, which already worked
# ---------------------------------------------------------------------------


class TestTheFinitePlanPathIsUnchanged:
    """The path the production evidence shows working. Re-pinned here
    rather than taken on trust, because the fix makes the two paths
    identical in shape and a later edit could now break both at once.
    """

    def test_the_first_instalment_routes_the_creator_notification(
        self, db, make_user, make_space,
    ):
        from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
        from app.services.purchase_fulfilment import (
            AccessPassIntent,
            AccessPassType,
            FulfilmentIntent,
            serialise_intent,
        )
        from app.models.platform import EventSeries
        from app.webhooks.finite_plan_handlers import (
            handle_invoice_payment_succeeded,
        )

        member = make_user(name="Rosalind Franklin")
        creator = make_user(role="creator", name="Ada Leader")
        space = make_space(creator=creator)
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        starts = datetime.utcnow()
        series = EventSeries(
            id=_uid("es"), space_id=space.id,
            slug=f"es-{uuid.uuid4().hex[:8]}", title="Term",
            starts_at=starts, status="published", published_at=starts,
        )
        db.add(series)
        db.flush()
        opt = PaymentOption(
            id=_uid("po"), space_id=space.id,
            attaches_to_kind="event_series", attaches_to_id=series.id,
            name="Awaken", payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.published,
            calculated_total_cents=20000, currency="AUD",
        )
        db.add(opt)
        sched = PaymentOptionSchedule(
            id=_uid("sched"), payment_option_id=opt.id,
            name="Weekly x 10", schedule_type="recurring_installments",
            status="published",
            installment_amount_cents=2000, installment_count=10,
            stripe_interval="week", stripe_interval_count=1,
            total_amount_cents=20000, currency="AUD",
        )
        db.add(sched)
        db.flush()

        subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
        intent = FulfilmentIntent(
            access_passes=(
                AccessPassIntent(
                    pass_type=AccessPassType.term_pass,
                    valid_from=datetime.utcnow(),
                    valid_until=None,
                    total_credits=10,
                    credits_per_week=1,
                    eligible_pathway_id=None,
                    eligible_series_id=series.id,
                    grants_pathway_id=None,
                ),
            ),
        )
        plan = PurchasePlan(
            id=_uid("pplan"),
            member_user_id=member.id,
            payment_option_id=opt.id,
            payment_option_schedule_id=sched.id,
            space_id=space.id,
            creator_user_id=creator.id,
            status=PurchasePlanStatus.pending_setup,
            currency="AUD",
            installment_amount_cents=2000,
            installments_expected=10,
            installments_paid=0,
            total_expected_cents=20000,
            stripe_interval="week",
            stripe_interval_count=1,
            platform_fee_basis_points=800,
            provider_setup_session_id=f"cs_test_{uuid.uuid4().hex[:8]}",
            provider_customer_id=f"cus_test_{uuid.uuid4().hex[:8]}",
            provider_payment_method_id=f"pm_test_{uuid.uuid4().hex[:8]}",
            provider_subscription_schedule_id=f"sub_sched_{uuid.uuid4().hex[:8]}",
            provider_subscription_id=subscription_id,
            stripe_mode="test",
            snapshot_grants_json=serialise_intent(intent),
        )
        db.add(plan)
        db.flush()

        invoice = {
            "id": f"in_{uuid.uuid4().hex[:12]}",
            "status": "paid",
            "subscription": subscription_id,
            "total": 2000,
            "amount_paid": 2000,
            "currency": "aud",
            "charge": None,
            "payment_intent": None,
        }
        stand_in = _stand_in_event()

        calls = _drive(db, lambda: handle_invoice_payment_succeeded(
            invoice, db,
            provider_event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_livemode=False,
        ), creator_event=stand_in)

        routed = calls.events_for(CREATOR_EVENT)
        assert len(routed) == 1, (
            f"the finite-plan path stopped routing; calls were "
            f"{[c[2] for c in calls]}"
        )
        assert routed[0].id == stand_in.id

    def test_the_two_paths_cannot_collide_on_a_dedupe_key(self):
        """Both now route the same event type, so their dedupe keys are
        what keep one purchase from suppressing another's notification.
        They are namespaced by kind: ``:txn:`` and ``:plan:``."""
        from app.webhooks import routes as _routes
        from app.webhooks import finite_plan_handlers as _fp
        import inspect

        assert 'dedupe_key=f"purchase_received:txn:{txn.id}"' in (
            inspect.getsource(_routes)
        )
        assert 'dedupe_key=f"purchase_received:plan:{plan.id}"' in (
            inspect.getsource(_fp)
        )


# ---------------------------------------------------------------------------
# The standalone paid Gathering ticket — the third call site
# ---------------------------------------------------------------------------


class TestTheStandaloneGatheringTicket:
    """The same defect, on the paid-Gathering ticket path.

    ``_handle_gathering_ticket_completed`` also discarded the emit's
    return value, and the omission was hidden twice over. Its emit runs
    *after* the handler's own ``db.commit()``, so the event row had no
    commit of its own: it survived only because
    ``emit_booking_confirmed`` a few lines below commits internally.
    That made the row look durable while nothing ever routed it — and
    on a ticket with no booking row, nothing committed it either and it
    vanished at session close.

    Fixed the same way as the other two paths: keep the event, commit
    it, route it. ``emit_booking_confirmed`` is left exactly as it was.
    """

    @staticmethod
    def _fee_defaults():
        return dict(fee_bps=0, creator_plan_id=None, creator_subscription_id=None)

    def _hold(self, db, *, event, buyer, make_pending_txn, session_id):
        """A live hold with a Stripe Session recorded, as the endpoint
        leaves it. Same shape as ``test_gathering_hold_race._hold_for``."""
        from app.services import gathering_tickets as gt

        txn, _ = make_pending_txn(space=event.space, event=event, payer=buyer)
        txn.provider_checkout_session_id = session_id
        offer = gt.load_and_validate_offer(db, event.space.slug, event.id)
        outcome = gt.create_or_reuse_hold(
            db, offer=offer, buyer=buyer, hold_ttl_minutes=30,
            **self._fee_defaults(),
        )
        outcome.booking.payment_transaction_id = txn.id
        db.commit()
        return outcome.booking, txn

    @pytest.fixture
    def ticket(self, db, make_user, make_space, make_event, make_pending_txn):
        """A paid Gathering in a Collective whose creator holds a leader
        membership, plus a buyer holding a seat."""
        creator = make_user(role="creator", name="Ada Leader")
        space = make_space(creator=creator)
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        buyer = make_user(name="Rosalind Franklin")
        gathering = make_event(space=space, capacity=5)
        db.flush()
        booking, txn = self._hold(
            db, event=gathering, buyer=buyer,
            make_pending_txn=make_pending_txn, session_id="cs_ticket",
        )
        return SimpleNamespace(
            space=space, creator=creator, buyer=buyer,
            gathering=gathering, booking=booking, txn=txn,
        )

    @staticmethod
    def _payload(t):
        return (
            {
                "id": "cs_ticket",
                "payment_status": "paid",
                "amount_total": t.txn.gross_amount_cents,
                "currency": "aud",
                "payment_intent": "pi_ticket",
            },
            {
                "purchase_type": "standalone_gathering",
                "transaction_id": t.txn.id,
                "event_id": t.gathering.id,
                "payer_user_id": t.buyer.id,
            },
        )

    def _fulfil(self, db, t, *, creator_event=None):
        from app.webhooks.routes import _handle_gathering_ticket_completed

        session, metadata = self._payload(t)
        return _drive(
            db,
            lambda: _handle_gathering_ticket_completed(session, db, metadata),
            creator_event=creator_event,
        )

    def test_the_ticket_sale_routes_the_creator_event(self, db, ticket):
        """The defect. Before this, the sale of a paid Gathering seat
        told the Collective's leaders nothing."""
        stand_in = _stand_in_event()

        calls = self._fulfil(db, ticket, creator_event=stand_in)

        routed = calls.events_for(CREATOR_EVENT)
        assert len(routed) == 1, (
            f"routing calls were {[c[2] for c in calls]}"
        )
        assert routed[0].id == stand_in.id

    def test_the_ticket_is_still_confirmed(self, db, ticket):
        """Fulfilment semantics unchanged — the notification work sits
        after the sale and must not touch it."""
        from app.models.platform import BookingStatus

        self._fulfil(db, ticket, creator_event=_stand_in_event())

        db.refresh(ticket.booking)
        assert ticket.booking.status == BookingStatus.confirmed

    def test_the_member_booking_confirmation_still_runs(self, db, ticket):
        """The sibling emit on the same path. It commits and routes
        itself, and this change left it alone."""
        from app.webhooks.routes import _handle_gathering_ticket_completed

        session, metadata = self._payload(ticket)
        with patch(
            "app.services.gathering_booking_emit.emit_booking_confirmed",
        ) as booking_emit, patch(
            "app.comms.rollout.schedule_routing_if_needed",
        ):
            _handle_gathering_ticket_completed(session, db, metadata)

        booking_emit.assert_called_once()
        assert booking_emit.call_args.kwargs["booking"].id == ticket.booking.id

    def test_the_creator_notification_no_longer_depends_on_the_booking_emit(
        self, db, ticket,
    ):
        """The hidden half. The creator event used to reach the database
        only because ``emit_booking_confirmed`` committed afterwards. It
        now commits and routes on its own, so a booking-confirmation
        failure cannot take it down with it.

        Driven by making that sibling raise — which the surrounding
        ``except`` absorbs, as it must.
        """
        stand_in = _stand_in_event()
        routed: list[str] = []

        from app.webhooks.routes import _handle_gathering_ticket_completed

        session, metadata = self._payload(ticket)
        with patch(
            "app.comms.rollout.schedule_routing_if_needed",
            side_effect=lambda bg, ev, et: routed.append(et),
        ), patch(
            "app.services.purchase_lifecycle_emit.emit_purchase_received_creator",
            return_value=stand_in,
        ), patch(
            "app.services.gathering_booking_emit.emit_booking_confirmed",
            side_effect=RuntimeError("resend is down"),
        ):
            _handle_gathering_ticket_completed(session, db, metadata)

        assert CREATOR_EVENT in routed, (
            "the creator notification was lost with the booking email"
        )

    def test_a_notification_failure_never_blocks_the_sale(self, db, ticket):
        """Best-effort preserved. The seat stays confirmed even when
        every piece of the notification work raises."""
        from app.models.platform import BookingStatus
        from app.webhooks.routes import _handle_gathering_ticket_completed

        session, metadata = self._payload(ticket)
        with patch(
            "app.services.purchase_lifecycle_emit.emit_purchase_received_creator",
            side_effect=RuntimeError("comms is down"),
        ):
            _handle_gathering_ticket_completed(session, db, metadata)

        db.refresh(ticket.booking)
        assert ticket.booking.status == BookingStatus.confirmed

    def test_a_redelivered_ticket_webhook_routes_nothing_again(
        self, db, ticket,
    ):
        """Redelivery short-circuits on ``already_fulfilled`` before the
        notification block, so the creator is not told twice."""
        stand_in = _stand_in_event()

        first = self._fulfil(db, ticket, creator_event=stand_in)
        assert len(first.events_for(CREATOR_EVENT)) == 1

        second = self._fulfil(db, ticket, creator_event=stand_in)

        assert second.events_for(CREATOR_EVENT) == []

    def test_all_three_paths_now_route_the_same_event(self):
        """The shape, stated once. Each of the three call sites keeps
        the emitted event and hands it to routing under the same key.

        Matched as code — an assignment and a routing call — rather than
        by searching for the event name, which appears in prose in all
        three files.
        """
        import inspect
        from app.webhooks import routes as _routes
        from app.webhooks import finite_plan_handlers as _fp

        checkout = inspect.getsource(_routes._handle_checkout_completed)
        ticket = inspect.getsource(_routes._handle_gathering_ticket_completed)
        plan = inspect.getsource(_fp._do_first_invoice_applied) if hasattr(
            _fp, "_do_first_invoice_applied",
        ) else inspect.getsource(_fp)

        for name, src in (
            ("checkout", checkout), ("ticket", ticket), ("plan", plan),
        ):
            assert "creator_event = " in src, f"{name} discards the emit"
            assert 'None, creator_event, "collective.purchase.received"' in src, (
                f"{name} never routes the creator event"
            )
