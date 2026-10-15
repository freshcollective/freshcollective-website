"""FC-API-7 — routing must not hand a silent intent to the dispatcher.

A silent-priority intent is created directly in ``recorded``: the
member has that channel turned off, so the row is the whole outcome
and there is nothing to send. ``RoutingResult`` has no bucket for that
case — it carries ``intent_ids``, ``suppressed_intent_ids`` and
``digest_item_ids``, and a silent intent has an id and no suppression
reason — so it arrived in the dispatchable list, and
``dispatch_specific_intent`` correctly refused it. Nine ValueErrors in
Sentry, none of which meant anything was lost.

The fix filters in the caller. These tests pin the three outcomes that
have to stay distinct:

* a silent intent is skipped **quietly** — it is expected;
* a queued intent still dispatches, even in the same batch;
* anything *else* unexpected is still reported, so the quiet path
  cannot become a place for real anomalies to hide.

That last one is the point of the whole exercise. A blanket
"skip anything not queued" would have fixed Sentry and thrown away
the signal with it.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.comms.intents import (
    DELIVERY_MODE_LIVE,
    STATE_DISPATCHING,
    STATE_QUEUED,
    STATE_RECORDED,
)
from app.comms.models import CommunicationEvent, CommunicationIntent
from app.comms.rollout import _route_event_bg
from app.comms.routing.routing import RoutingResult


ROLLOUT = "app.comms.rollout"


class _NoClose:
    """The background task closes its session; the test still needs it."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _event(db) -> CommunicationEvent:
    ev = CommunicationEvent(
        id=_uid("cev"), event_type="pathway.published",
        topic_key="pathways", category_key="pathways",
        source_type="creator", priority_hint="immediate",
        context={}, payload={},
    )
    db.add(ev); db.flush()
    return ev


def _intent(db, event, *, state, channel="email_transactional",
            priority="silent") -> CommunicationIntent:
    i = CommunicationIntent(
        id=_uid("cin"), event_id=event.id, recipient_user_id=None,
        recipient_address="someone@example.test",
        source_type="creator", category_key="pathways",
        topic_key="pathways", channel=channel, priority=priority,
        delivery_mode=DELIVERY_MODE_LIVE, provider_key="resend",
        human_reason="because", payload_subject="s",
        payload_body_text="b", payload_metadata={}, state=state,
    )
    db.add(i); db.flush()
    return i


class _RecordingLogger:
    """Stands in for the module logger.

    ``caplog`` cannot be used here: the ``db`` fixture runs Alembic,
    whose ``fileConfig`` call disables every logger that already
    exists in the process, so records never reach a handler. That is a
    harness artefact — production never runs Alembic in-process — but
    it would make a ``caplog`` assertion pass no matter what the code
    did, which is precisely the failure these tests exist to catch.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg, *args, **kw):
        self.errors.append(msg % args if args else str(msg))

    def warning(self, msg, *args, **kw):
        self.warnings.append(msg % args if args else str(msg))

    def exception(self, msg, *args, **kw):
        self.errors.append(msg % args if args else str(msg))

    def info(self, msg, *args, **kw):
        pass


def _run(db, event, intent_ids, *, log=None):
    """Drive ``_route_event_bg`` with a routing result we control.

    Patching ``route_event`` is what makes the *loop* the subject:
    these cases are about which ids get handed to the dispatcher, not
    about how routing chose them.
    """
    result = RoutingResult(
        event_id=event.id, event_type=event.event_type,
        delivery_mode=DELIVERY_MODE_LIVE, intent_ids=list(intent_ids),
    )
    recorder = log if log is not None else _RecordingLogger()
    with patch(f"{ROLLOUT}.SessionLocal", return_value=_NoClose(db)), \
         patch(f"{ROLLOUT}.logger", recorder), \
         patch("app.comms.routing.route_event", return_value=result), \
         patch("app.comms.worker.dispatch_specific_intent") as dispatch:
        _route_event_bg(event.id, DELIVERY_MODE_LIVE)
    return dispatch


# ---------------------------------------------------------------------------
# 1 · The reported bug
# ---------------------------------------------------------------------------

class TestASilentIntentIsNotDispatched:
    def test_a_recorded_intent_is_never_handed_to_the_dispatcher(self, db):
        event = _event(db)
        silent = _intent(db, event, state=STATE_RECORDED)
        db.commit()

        dispatch = _run(db, event, [silent.id])

        assert dispatch.call_args_list == [], (
            "the recorded intent was passed to the dispatcher — the "
            "FC-API-7 ValueError"
        )

    def test_it_is_skipped_quietly(self, db):
        """Expected silence must not be reported. An ERROR here would
        reach Sentry and reproduce the original noise by another
        route."""
        event = _event(db)
        silent = _intent(db, event, state=STATE_RECORDED)
        db.commit()
        log = _RecordingLogger()

        _run(db, event, [silent.id], log=log)

        assert log.errors == [] and log.warnings == []

    def test_the_intent_is_left_exactly_as_it_was(self, db):
        event = _event(db)
        silent = _intent(db, event, state=STATE_RECORDED)
        db.commit()

        _run(db, event, [silent.id])
        db.refresh(silent)

        assert silent.state == STATE_RECORDED
        assert silent.queued_at is None and silent.sent_at is None


# ---------------------------------------------------------------------------
# 2 · Queued intents still go — including beside a silent one
# ---------------------------------------------------------------------------

class TestQueuedIntentsStillDispatch:
    def test_a_queued_intent_dispatches_normally(self, db):
        event = _event(db)
        queued = _intent(
            db, event, state=STATE_QUEUED, channel="in_app",
            priority="immediate",
        )
        db.commit()

        dispatch = _run(db, event, [queued.id])

        assert dispatch.call_count == 1
        assert dispatch.call_args.args[1] == queued.id

    def test_a_silent_intent_does_not_suppress_its_queued_sibling(self, db):
        """The mixed case, and the one that proves nothing is lost: a
        member with email off but in-app on still gets the bell."""
        event = _event(db)
        silent = _intent(db, event, state=STATE_RECORDED)
        queued = _intent(
            db, event, state=STATE_QUEUED, channel="in_app",
            priority="immediate",
        )
        db.commit()

        dispatch = _run(db, event, [silent.id, queued.id])

        dispatched = [c.args[1] for c in dispatch.call_args_list]
        assert dispatched == [queued.id]

    def test_order_does_not_matter(self, db):
        """Silent first or last, the queued one still goes."""
        event = _event(db)
        silent = _intent(db, event, state=STATE_RECORDED)
        queued = _intent(
            db, event, state=STATE_QUEUED, channel="in_app",
            priority="immediate",
        )
        db.commit()

        for order in ([silent.id, queued.id], [queued.id, silent.id]):
            dispatch = _run(db, event, order)
            assert [c.args[1] for c in dispatch.call_args_list] == [queued.id], (
                f"order {order} changed the outcome"
            )


# ---------------------------------------------------------------------------
# 3 · Real anomalies are still reported
# ---------------------------------------------------------------------------

class TestUnexpectedStatesAreNotHidden:
    """The filter exists to skip *expected* silence. Everything else
    must still surface, or this fix becomes a place for genuine faults
    to disappear into."""

    def test_a_vanished_intent_is_reported(self, db):
        event = _event(db)
        db.commit()
        log = _RecordingLogger()

        dispatch = _run(db, event, ["cin_does_not_exist"], log=log)

        assert dispatch.call_args_list == []
        assert log.errors, "a missing intent was skipped silently"
        assert "vanished" in log.errors[0]

    @pytest.mark.parametrize("state", [STATE_DISPATCHING, "sent", "failed"])
    def test_an_unexpected_state_is_reported(self, db, state):
        event = _event(db)
        odd = _intent(db, event, state=state, priority="immediate")
        db.commit()
        log = _RecordingLogger()

        dispatch = _run(db, event, [odd.id], log=log)

        assert dispatch.call_args_list == [], (
            "a non-queued intent reached the dispatcher"
        )
        assert log.errors, f"state {state!r} was skipped silently"
        assert "unexpected state" in log.errors[0]

    def test_only_recorded_gets_the_quiet_path(self, db):
        """Stated as one assertion so the distinction cannot erode:
        recorded is silent, every other skip is loud."""
        event = _event(db)
        silent = _intent(db, event, state=STATE_RECORDED)
        odd = _intent(db, event, state="sent", priority="immediate")
        db.commit()
        log = _RecordingLogger()

        _run(db, event, [silent.id, odd.id], log=log)

        assert len(log.errors) == 1
        assert odd.id in log.errors[0]
        assert silent.id not in log.errors[0]


# ---------------------------------------------------------------------------
# 4 · The dispatcher's own guard is untouched
# ---------------------------------------------------------------------------

class TestTheWorkerGuardIsUnchanged:
    """The fix belongs in the caller. The dispatcher's guard is
    correct and its other caller — the operator test-send endpoint —
    relies on it raising."""

    def test_the_worker_still_refuses_a_recorded_intent(self, db):
        from app.comms.worker import dispatch_specific_intent

        event = _event(db)
        silent = _intent(db, event, state=STATE_RECORDED)
        db.commit()

        with pytest.raises(ValueError, match="only queued intents"):
            dispatch_specific_intent(db, silent.id)

    def test_the_worker_still_refuses_a_missing_intent(self, db):
        from app.comms.worker import dispatch_specific_intent

        with pytest.raises(ValueError, match="not found"):
            dispatch_specific_intent(db, "cin_nope")
