"""Tests for the M4 intent + delivery layer.

Covers:
  * create_intent — validation, defaults, silent → recorded shortcut.
  * State machine — valid transitions + rejection of invalid.
  * claim_next_batch — respects scheduled_for, marks dispatching,
    SKIP LOCKED.
  * record_delivery — attempt numbering + uniqueness.
  * Worker dispatch — happy path, provider failure, unknown provider,
    silent intents ignored.
  * History endpoint scoping + admin endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.comms.categories import (
    CATEGORY_COMMUNITY,
    CATEGORY_MESSAGES,
    Channel,
    Priority,
    Source,
    TOPIC_CONVERSATIONS,
    TOPIC_DIRECT_MESSAGES,
)
from app.comms.intents import (
    DELIVERY_STATUS_ACCEPTED,
    DELIVERY_STATUS_FAILED,
    InvalidIntentError,
    InvalidSourceError,
    InvalidStateTransitionError,
    STATE_DISPATCHING,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RECORDED,
    STATE_SENT,
    STATE_SUPPRESSED,
    UnknownStateError,
    claim_next_batch,
    create_intent,
    mark_intent_state,
    record_delivery,
)
from app.comms.models import CommunicationDelivery, CommunicationIntent
from app.comms.providers import (
    ProviderHealth,
    ProviderResult,
    RenderedPayload,
    _bootstrap,
    register,
    reset_registry,
)
from app.comms.providers.base import HealthStatus, now_utc
from app.comms.providers.inapp import InAppProvider
from app.comms.providers.mock import MockProvider
from app.comms.providers.resend import ResendProvider
from app.comms.routes import (
    dispatch_due_endpoint,
    get_intent as admin_get_intent,
    get_my_history,
    list_deliveries,
    list_intents,
)
from app.comms.worker import dispatch_due


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_kwargs(u) -> dict:
    return dict(
        recipient_user_id=u.id,
        recipient_address=u.email or f"{u.id}@example.test",
        source_type=Source.CREATOR,
        source_id=u.id,
        category_key=CATEGORY_COMMUNITY,
        topic_key=TOPIC_CONVERSATIONS,
        channel=Channel.EMAIL_TRANSACTIONAL,
        priority=Priority.IMMEDIATE,
        provider_key="resend",
        human_reason="You subscribed to Updates from this collective.",
        payload_subject="Two threads from this week",
        payload_body_html="<p>hello</p>",
    )


# ---------------------------------------------------------------------------
# create_intent
# ---------------------------------------------------------------------------


class TestCreateIntent:
    def test_defaults_and_state(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        assert intent.id.startswith("cin_")
        assert intent.state == STATE_QUEUED
        assert intent.queued_at is not None
        assert intent.terminal_at is None
        assert intent.sent_at is None
        assert intent.recipient_user_id == u.id
        assert intent.payload_metadata == {}

    def test_silent_priority_goes_straight_to_recorded(self, db, make_user):
        u = make_user()
        intent = create_intent(
            db, **{**_base_kwargs(u), "priority": Priority.SILENT},
        )
        assert intent.state == STATE_RECORDED
        assert intent.terminal_at is not None
        assert intent.queued_at is None

    def test_rejects_unknown_category(self, db, make_user):
        u = make_user()
        with pytest.raises(InvalidIntentError):
            create_intent(db, **{**_base_kwargs(u), "category_key": "made_up"})

    def test_rejects_empty_body(self, db, make_user):
        u = make_user()
        kwargs = _base_kwargs(u)
        kwargs["payload_body_html"] = None
        kwargs["payload_body_text"] = None
        with pytest.raises(InvalidIntentError):
            create_intent(db, **kwargs)

    def test_rejects_creator_source_without_id(self, db, make_user):
        u = make_user()
        kwargs = _base_kwargs(u)
        kwargs["source_id"] = None
        with pytest.raises(InvalidSourceError):
            create_intent(db, **kwargs)

    def test_fresh_collective_source_forbids_id(self, db, make_user):
        u = make_user()
        kwargs = _base_kwargs(u)
        kwargs["source_type"] = Source.FRESH_COLLECTIVE
        kwargs["source_id"] = "not-null"
        with pytest.raises(InvalidSourceError):
            create_intent(db, **kwargs)

    def test_template_provenance_persisted(self, db, make_user):
        u = make_user()
        intent = create_intent(
            db,
            **{
                **_base_kwargs(u),
                "template_key": "community.new_post.email_transactional",
                "template_version": "v1",
                "template_context": {"collective": "River Weaving", "count": 2},
            },
        )
        assert intent.template_key == "community.new_post.email_transactional"
        assert intent.template_version == "v1"
        assert intent.template_context == {"collective": "River Weaving", "count": 2}


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_queued_to_dispatching_ok(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        mark_intent_state(db, intent, STATE_DISPATCHING)
        assert intent.state == STATE_DISPATCHING
        assert intent.dispatching_at is not None

    def test_dispatching_to_sent(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        mark_intent_state(db, intent, STATE_DISPATCHING)
        mark_intent_state(db, intent, STATE_SENT)
        assert intent.sent_at is not None
        # Not yet terminal (waiting for webhook to confirm delivery).
        assert intent.terminal_at is None

    def test_queued_to_sent_rejected(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        with pytest.raises(InvalidStateTransitionError):
            mark_intent_state(db, intent, STATE_SENT)

    def test_terminal_states_have_no_outgoing_edge(self, db, make_user):
        u = make_user()
        intent = create_intent(
            db, **{**_base_kwargs(u), "priority": Priority.SILENT},
        )
        # already RECORDED (terminal); nothing should transition out
        with pytest.raises(InvalidStateTransitionError):
            mark_intent_state(db, intent, STATE_SENT)

    def test_unknown_state_rejected(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        with pytest.raises(UnknownStateError):
            mark_intent_state(db, intent, "nope")

    def test_suppression_reason_recorded(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        mark_intent_state(
            db, intent, STATE_SUPPRESSED,
            suppression_reason="hard_bounce",
        )
        assert intent.state == STATE_SUPPRESSED
        assert intent.suppression_reason == "hard_bounce"
        assert intent.terminal_at is not None


# ---------------------------------------------------------------------------
# claim_next_batch
# ---------------------------------------------------------------------------


class TestClaimNextBatch:
    def test_claims_queued_and_marks_dispatching(self, db, make_user):
        u = make_user()
        i1 = create_intent(db, **_base_kwargs(u))
        i2 = create_intent(db, **_base_kwargs(u))
        db.flush()
        ids = claim_next_batch(db, limit=10)
        assert set(ids) == {i1.id, i2.id}
        for intent in (i1, i2):
            db.refresh(intent)
            assert intent.state == STATE_DISPATCHING
            assert intent.dispatching_at is not None

    def test_respects_scheduled_for(self, db, make_user):
        u = make_user()
        future = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        i1 = create_intent(db, **_base_kwargs(u))
        i2 = create_intent(
            db, **{**_base_kwargs(u), "scheduled_for": future},
        )
        db.flush()
        ids = claim_next_batch(db, limit=10)
        assert i1.id in ids
        assert i2.id not in ids

    def test_ignores_recorded_state(self, db, make_user):
        u = make_user()
        create_intent(db, **{**_base_kwargs(u), "priority": Priority.SILENT})
        db.flush()
        ids = claim_next_batch(db, limit=10)
        assert ids == []

    def test_limit_respected(self, db, make_user):
        u = make_user()
        for _ in range(5):
            create_intent(db, **_base_kwargs(u))
        db.flush()
        ids = claim_next_batch(db, limit=2)
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# record_delivery
# ---------------------------------------------------------------------------


class TestRecordDelivery:
    def test_first_attempt_numbered_one(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        d = record_delivery(
            db,
            intent=intent,
            provider_key="resend",
            status=DELIVERY_STATUS_ACCEPTED,
            request_snapshot={"to": u.email},
            response_snapshot={"accepted": True},
            provider_message_id="re_1",
        )
        assert d.attempt_number == 1
        assert d.settled_at is not None

    def test_second_attempt_increments(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        record_delivery(
            db, intent=intent, provider_key="resend",
            status=DELIVERY_STATUS_FAILED,
            request_snapshot={}, response_snapshot={"accepted": False},
        )
        d2 = record_delivery(
            db, intent=intent, provider_key="resend",
            status=DELIVERY_STATUS_ACCEPTED,
            request_snapshot={}, response_snapshot={"accepted": True},
        )
        assert d2.attempt_number == 2

    def test_unknown_status_rejected(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        with pytest.raises(ValueError):
            record_delivery(
                db, intent=intent, provider_key="resend",
                status="weird",
                request_snapshot={}, response_snapshot={},
            )


# ---------------------------------------------------------------------------
# Worker (dispatch_due)
# ---------------------------------------------------------------------------


class _CollectingProvider:
    """Test provider that records payloads and returns a configurable
    ProviderResult. Registered under 'test_ok' or 'test_fail' as needed.
    """

    def __init__(self, key: str, *, accept: bool):
        self.key = key
        self.capabilities = frozenset({"email_transactional", "in_app"})
        self.production_eligible = True
        self._accept = accept
        self.sent: list[RenderedPayload] = []

    def send(self, payload: RenderedPayload) -> ProviderResult:
        self.sent.append(payload)
        if self._accept:
            return ProviderResult(accepted=True, provider_message_id=f"{self.key}-{len(self.sent)}")
        return ProviderResult(
            accepted=False,
            error_class="rejected_by_test",
            error_detail="stub failure",
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(status=HealthStatus.HEALTHY, checked_at=now_utc())


class TestWorker:
    @pytest.fixture(autouse=True)
    def _isolated_registry(self):
        reset_registry()
        yield
        reset_registry()
        _bootstrap()

    def test_happy_path_marks_sent_and_records_delivery(self, db, make_user):
        u = make_user()
        provider = _CollectingProvider("test_ok", accept=True)
        register(provider)

        intent = create_intent(
            db, **{**_base_kwargs(u), "provider_key": "test_ok"},
        )
        db.flush()

        processed = dispatch_due(db, limit=10)
        assert processed == [intent.id]

        db.refresh(intent)
        assert intent.state == STATE_SENT
        assert intent.sent_at is not None
        assert len(provider.sent) == 1
        assert provider.sent[0].to == intent.recipient_address

        from sqlalchemy import select
        deliveries = db.execute(
            select(CommunicationDelivery).where(
                CommunicationDelivery.intent_id == intent.id,
            )
        ).scalars().all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "accepted"
        assert deliveries[0].provider_message_id == "test_ok-1"

    def test_provider_rejection_marks_failed(self, db, make_user):
        u = make_user()
        provider = _CollectingProvider("test_fail", accept=False)
        register(provider)

        intent = create_intent(
            db, **{**_base_kwargs(u), "provider_key": "test_fail"},
        )
        db.flush()
        dispatch_due(db, limit=10)

        db.refresh(intent)
        assert intent.state == STATE_FAILED
        assert intent.terminal_at is not None

        from sqlalchemy import select
        deliveries = db.execute(
            select(CommunicationDelivery).where(
                CommunicationDelivery.intent_id == intent.id,
            )
        ).scalars().all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "failed"
        assert deliveries[0].error_class == "rejected_by_test"

    def test_unknown_provider_marks_failed(self, db, make_user):
        # Empty registry — no providers registered at all.
        u = make_user()
        intent = create_intent(
            db, **{**_base_kwargs(u), "provider_key": "does_not_exist"},
        )
        db.flush()
        dispatch_due(db, limit=10)

        db.refresh(intent)
        assert intent.state == STATE_FAILED

        from sqlalchemy import select
        deliveries = db.execute(
            select(CommunicationDelivery).where(
                CommunicationDelivery.intent_id == intent.id,
            )
        ).scalars().all()
        assert len(deliveries) == 1
        assert deliveries[0].error_class == "UnknownProvider"

    def test_provider_raising_is_caught(self, db, make_user):
        class _Bad:
            key = "raiser"
            capabilities = frozenset({"email_transactional"})
            production_eligible = True

            def send(self, payload):
                raise RuntimeError("oops")

            def health(self):
                return ProviderHealth(status=HealthStatus.HEALTHY, checked_at=now_utc())

        register(_Bad())
        u = make_user()
        intent = create_intent(
            db, **{**_base_kwargs(u), "provider_key": "raiser"},
        )
        db.flush()
        dispatch_due(db, limit=10)

        db.refresh(intent)
        assert intent.state == STATE_FAILED

    def test_silent_intents_are_not_claimed(self, db, make_user):
        u = make_user()
        # No providers needed — should never be dispatched.
        intent = create_intent(
            db, **{**_base_kwargs(u), "priority": Priority.SILENT},
        )
        db.flush()
        assert dispatch_due(db, limit=10) == []
        db.refresh(intent)
        assert intent.state == STATE_RECORDED


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------


class TestHistoryEndpoint:
    def test_returns_current_user_only(self, db, make_user):
        me = make_user()
        other = make_user()
        my_intent = create_intent(db, **_base_kwargs(me))
        other_intent = create_intent(db, **_base_kwargs(other))
        db.flush()

        resp = get_my_history(db=db, current_user=me)  # type: ignore[arg-type]
        ids = {row.id for row in resp.items}
        assert my_intent.id in ids
        assert other_intent.id not in ids

    def test_ordered_desc_and_paginated(self, db, make_user):
        u = make_user()
        ids = []
        for _ in range(3):
            ids.append(create_intent(db, **_base_kwargs(u)).id)
        db.flush()

        resp = get_my_history(limit=2, db=db, current_user=u)  # type: ignore[arg-type]
        assert len(resp.items) == 2
        assert resp.total >= 3
        # Newest first
        assert resp.items[0].id == ids[-1]

    def test_deliveries_attached(self, db, make_user):
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        record_delivery(
            db, intent=intent, provider_key="resend",
            status="accepted",
            request_snapshot={}, response_snapshot={"accepted": True},
            provider_message_id="re_1",
        )
        db.flush()
        resp = get_my_history(db=db, current_user=u)  # type: ignore[arg-type]
        row = next(r for r in resp.items if r.id == intent.id)
        assert len(row.deliveries) == 1
        assert row.deliveries[0].provider_message_id == "re_1"

    def test_bad_limit_rejected(self, db, make_user):
        u = make_user()
        with pytest.raises(HTTPException) as exc:
            get_my_history(limit=999, db=db, current_user=u)  # type: ignore[arg-type]
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


class TestAdminEndpoints:
    def test_list_intents_filters(self, db, make_user):
        admin = make_user(role="admin")
        u = make_user()
        i_email = create_intent(db, **_base_kwargs(u))
        i_dm = create_intent(
            db,
            **{
                **_base_kwargs(u),
                "category_key": CATEGORY_MESSAGES,
                "topic_key": TOPIC_DIRECT_MESSAGES,
                "channel": Channel.IN_APP,
                "provider_key": "in_app",
            },
        )
        db.flush()
        # Filter by category — should exclude the DM one.
        resp = list_intents(category=CATEGORY_COMMUNITY, db=db, _=admin)  # type: ignore[arg-type]
        ids = {r.id for r in resp.items}
        assert i_email.id in ids
        assert i_dm.id not in ids

    def test_get_intent_returns_deliveries(self, db, make_user):
        admin = make_user(role="admin")
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        record_delivery(
            db, intent=intent, provider_key="resend",
            status="accepted",
            request_snapshot={"to": u.email}, response_snapshot={"accepted": True},
            provider_message_id="re_1",
        )
        db.flush()
        detail = admin_get_intent(intent_id=intent.id, db=db, _=admin)  # type: ignore[arg-type]
        assert detail.id == intent.id
        assert len(detail.deliveries) == 1
        assert detail.deliveries[0].provider_message_id == "re_1"

    def test_get_intent_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as exc:
            admin_get_intent(intent_id="cin_missing", db=db, _=admin)  # type: ignore[arg-type]
        assert exc.value.status_code == 404

    def test_list_deliveries_filters_by_provider(self, db, make_user):
        admin = make_user(role="admin")
        u = make_user()
        intent = create_intent(db, **_base_kwargs(u))
        record_delivery(
            db, intent=intent, provider_key="resend",
            status="accepted",
            request_snapshot={}, response_snapshot={"accepted": True},
        )
        record_delivery(
            db, intent=intent, provider_key="in_app",
            status="accepted",
            request_snapshot={}, response_snapshot={"accepted": True},
        )
        db.flush()
        resp = list_deliveries(provider_key="resend", db=db, _=admin)  # type: ignore[arg-type]
        assert all(r.provider_key == "resend" for r in resp.items)


# ---------------------------------------------------------------------------
# Internal dispatch endpoint
# ---------------------------------------------------------------------------


class TestInternalDispatchEndpoint:
    @pytest.fixture(autouse=True)
    def _isolated_registry(self):
        reset_registry()
        yield
        reset_registry()
        _bootstrap()

    def test_requires_internal_token(self, db):
        with pytest.raises(HTTPException) as exc:
            dispatch_due_endpoint(x_internal_token=None, db=db)
        assert exc.value.status_code == 401

    def test_wrong_token_rejected(self, db):
        with pytest.raises(HTTPException) as exc:
            dispatch_due_endpoint(x_internal_token="nope", db=db)
        assert exc.value.status_code == 401

    def test_valid_token_dispatches(self, db, make_user, monkeypatch):
        # SEC-007: dispatch endpoint now authenticates against
        # ``INTERNAL_COMMS_SECRET`` (not ``JWT_SECRET``).
        from app.core.config import settings as app_settings
        monkeypatch.setattr(
            app_settings, "internal_comms_secret", "shared-internal-comms-secret",
            raising=False,
        )

        register(_CollectingProvider("test_ok", accept=True))
        u = make_user()
        intent = create_intent(
            db, **{**_base_kwargs(u), "provider_key": "test_ok"},
        )
        db.flush()

        resp = dispatch_due_endpoint(
            x_internal_token="shared-internal-comms-secret",
            db=db,
        )
        assert resp.count == 1
        assert intent.id in resp.processed

    def test_jwt_secret_is_no_longer_accepted_as_internal_token(
        self, db, monkeypatch,
    ):
        """SEC-007 regression: after migration, the JWT signing key
        must NOT authenticate ``/api/internal/comms/dispatch-due``.
        Prevents a partial-migration mistake where a stray comparison
        against ``jwt_secret`` accidentally survives."""
        from app.core.config import settings as app_settings
        monkeypatch.setattr(
            app_settings, "jwt_secret", "session-signing-key",
            raising=False,
        )
        monkeypatch.setattr(
            app_settings, "internal_comms_secret", "distinct-internal-comms-secret",
            raising=False,
        )
        with pytest.raises(HTTPException) as exc:
            dispatch_due_endpoint(
                x_internal_token="session-signing-key",  # the OLD credential
                db=db,
            )
        assert exc.value.status_code == 401
