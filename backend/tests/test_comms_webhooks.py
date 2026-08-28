"""Tests for the M6 inbound webhook framework (R4 semantics).

Covers:
  * Svix signature verification — happy path, bad signature, missing
    headers, replay outside timestamp tolerance.
  * ReceiverOutcome — R4 strict rejection (no audit row for
    unverified / malformed payloads); ``rejected_reason`` populated
    for those cases so the FastAPI route can pick 4xx.
  * Mapping semantics (R4 scope: delivered/bounced/complained only) —
        delivered      → intent → STATE_DELIVERED
        bounced/hard   → intent → STATE_BOUNCED   + suppression
        bounced/soft   → intent → STATE_BOUNCED   (no suppression)
        complained     → intent → STATE_COMPLAINED + suppression
        unsubscribed   → out of R4 scope → no audit row, no side effect
        opened/clicked → out of R4 scope → no audit row, no side effect
        sent           → out of R4 scope → no audit row, no side effect
  * Unknown provider_message_id → process_error, no crash.
  * Malformed JSON body → rejected (no audit row); route returns 400.
  * Bad signature       → rejected (no audit row); route returns 401.
  * Missing headers     → rejected (no audit row); route returns 400.
  * Unknown provider_key → 404 (route-level).
  * Out-of-order state regression (bounced → delivered) → audit row
    persisted with process_error; delivery + intent stay bounced.
  * Startup warning: RESEND_API_KEY set + RESEND_WEBHOOK_SECRET unset.

Route functions are called directly (matching the pattern in
``test_comms_admin_events.py``); the receiver route is also
exercised via the FastAPI TestClient to assert 4xx wire behaviour.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time as time_mod
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.comms.categories import (
    CATEGORY_COMMUNITY,
    Channel,
    Priority,
    Source,
    TOPIC_CONVERSATIONS,
)
from app.comms.intents import (
    DELIVERY_STATUS_ACCEPTED,
    STATE_BOUNCED,
    STATE_COMPLAINED,
    STATE_DELIVERED,
    STATE_DISPATCHING,
    STATE_SENT,
    create_intent,
    mark_intent_state,
    record_delivery,
)
from app.comms.models import CommunicationIntent, CommunicationWebhookEvent
from app.comms.providers.resend import ResendProvider
from app.comms.routes import get_webhook_event, list_webhook_events
from app.comms.suppressions import hash_address, is_address_suppressed
from app.comms.webhooks import (
    SIGNATURE_TIMESTAMP_TOLERANCE_SECONDS,
    receive,
    sign_svix_payload,
    verify_svix_signature,
)
from app.core.config import settings


# A base64-encoded "correct-horse-battery-staple-secret-value-32b"
# used only in tests. Length is intentional — Svix secrets are
# base64-decoded before HMAC.
TEST_SECRET_RAW = b"correct-horse-battery-staple-32b"
TEST_SECRET = "whsec_" + base64.b64encode(TEST_SECRET_RAW).decode("ascii")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _svix_headers(*, secret: str, body: bytes, ts: int | None = None, svix_id: str | None = None) -> dict:
    """Build valid svix-* headers for the given body + secret."""
    svix_id = svix_id or f"msg_{uuid.uuid4().hex[:16]}"
    svix_ts = ts if ts is not None else int(time_mod.time())
    sig = sign_svix_payload(
        secret=secret, svix_id=svix_id, svix_ts=svix_ts, raw_body=body,
    )
    return {
        "svix-id": svix_id,
        "svix-timestamp": str(svix_ts),
        "svix-signature": sig,
    }


def _resend_body(
    event_type: str,
    *,
    email_id: str,
    to: str = "someone@example.test",
    bounce_type: str | None = None,
) -> bytes:
    payload: dict = {
        "type": event_type,
        "created_at": datetime.now(UTC).isoformat(),
        "data": {
            "email_id": email_id,
            "to": [to],
        },
    }
    if bounce_type is not None:
        payload["data"]["bounce"] = {"type": bounce_type}
    return json.dumps(payload).encode("utf-8")


def _base_intent_kwargs(u) -> dict:
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
        payload_subject="Test",
        payload_body_html="<p>x</p>",
    )


def _sent_delivery(db, u, *, provider_message_id: str):
    """Create an intent, walk it to STATE_SENT, attach a delivery row
    with the given provider_message_id.
    """
    intent = create_intent(db, **_base_intent_kwargs(u))
    mark_intent_state(db, intent, STATE_DISPATCHING)
    mark_intent_state(db, intent, STATE_SENT)
    record_delivery(
        db, intent=intent, provider_key="resend",
        status=DELIVERY_STATUS_ACCEPTED,
        request_snapshot={}, response_snapshot={"id": provider_message_id},
        provider_message_id=provider_message_id,
    )
    db.flush()
    return intent


@pytest.fixture
def resend_secret(monkeypatch):
    """Configure a known secret for all tests in this module."""
    monkeypatch.setattr(settings, "resend_webhook_secret", TEST_SECRET)
    return TEST_SECRET


# ---------------------------------------------------------------------------
# Signature verification (unit)
# ---------------------------------------------------------------------------


class TestSvixSignature:
    def test_valid_signature_accepted(self):
        body = b'{"type":"email.delivered"}'
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        assert verify_svix_signature(headers, body, secret=TEST_SECRET) is True

    def test_bad_signature_rejected(self):
        body = b'{"type":"email.delivered"}'
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        headers["svix-signature"] = "v1,AAAA" + headers["svix-signature"][2:]
        assert verify_svix_signature(headers, body, secret=TEST_SECRET) is False

    def test_missing_headers_rejected(self):
        assert verify_svix_signature({}, b"{}", secret=TEST_SECRET) is False

    def test_stale_timestamp_rejected(self):
        body = b'{"type":"email.delivered"}'
        old_ts = int(time_mod.time()) - (SIGNATURE_TIMESTAMP_TOLERANCE_SECONDS + 10)
        headers = _svix_headers(secret=TEST_SECRET, body=body, ts=old_ts)
        assert verify_svix_signature(headers, body, secret=TEST_SECRET) is False

    def test_tampered_body_rejected(self):
        body = b'{"type":"email.delivered"}'
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        tampered = b'{"type":"email.bounced"}'
        assert verify_svix_signature(headers, tampered, secret=TEST_SECRET) is False

    def test_wrong_secret_rejected(self):
        body = b'{"type":"email.delivered"}'
        other_secret = "whsec_" + base64.b64encode(b"a-different-32b-secret-value-xxxx").decode("ascii")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        assert verify_svix_signature(headers, body, secret=other_secret) is False


# ---------------------------------------------------------------------------
# Provider parse
# ---------------------------------------------------------------------------


class TestResendParse:
    def test_delivered_maps_to_delivered(self):
        body = _resend_body("email.delivered", email_id="re_abc")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        events = ResendProvider().parse_webhook(headers, body)
        assert len(events) == 1
        assert events[0].event_type == "delivered"
        assert events[0].provider_message_id == "re_abc"
        assert events[0].recipient_address == "someone@example.test"

    def test_bounced_hard_carries_bounce_class(self):
        body = _resend_body(
            "email.bounced", email_id="re_bh", bounce_type="hard",
        )
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        events = ResendProvider().parse_webhook(headers, body)
        assert events[0].event_type == "bounced"
        assert events[0].bounce_class == "hard"

    def test_bounced_soft_carries_soft(self):
        body = _resend_body(
            "email.bounced", email_id="re_bs", bounce_type="soft",
        )
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        events = ResendProvider().parse_webhook(headers, body)
        assert events[0].event_type == "bounced"
        assert events[0].bounce_class == "soft"

    def test_unknown_event_type_maps_to_other(self):
        body = _resend_body("email.unknown_new_thing", email_id="re_x")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        events = ResendProvider().parse_webhook(headers, body)
        assert events[0].event_type == "other"

    def test_malformed_json_returns_empty(self):
        body = b"{not json"
        events = ResendProvider().parse_webhook({}, body)
        assert events == []


# ---------------------------------------------------------------------------
# Receiver — verification + persistence
# ---------------------------------------------------------------------------


class TestReceiverVerification:
    def test_bad_signature_rejected_no_audit_row(self, db, resend_secret):
        """R4 — untrusted payloads never touch the audit ledger."""
        body = _resend_body("email.delivered", email_id="re_1")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        headers["svix-signature"] = "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.signature_verified is False
        assert outcome.rejected_reason == "invalid_signature"
        assert outcome.processed == 0
        # R4 — no ledger row for unverified payloads.
        assert db.query(CommunicationWebhookEvent).count() == 0

    def test_missing_signature_headers_rejected(self, db, resend_secret):
        """R4 — missing Svix headers → rejected before any persistence."""
        body = _resend_body("email.delivered", email_id="re_1")
        outcome = receive(
            db, provider_key="resend", headers={}, raw_body=body,
        )
        assert outcome.signature_verified is False
        assert outcome.rejected_reason == "missing_signature_headers"
        assert db.query(CommunicationWebhookEvent).count() == 0

    def test_malformed_json_rejected(self, db, resend_secret):
        """R4 — malformed body → rejected with malformed_payload, no ledger row."""
        body = b"{ this is not json"
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        # Signature was valid (HMAC is over bytes), but body isn't JSON.
        assert outcome.signature_verified is True
        assert outcome.rejected_reason == "malformed_payload"
        assert db.query(CommunicationWebhookEvent).count() == 0

    def test_no_secret_configured_rejects(self, db, monkeypatch):
        monkeypatch.setattr(settings, "resend_webhook_secret", None)
        body = _resend_body("email.delivered", email_id="re_1")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.signature_verified is False
        # Headers present, secret unset → invalid_signature (401), not
        # missing_headers (400).
        assert outcome.rejected_reason == "invalid_signature"
        assert db.query(CommunicationWebhookEvent).count() == 0

    def test_unknown_provider_returns_empty_outcome(self, db, resend_secret):
        outcome = receive(
            db, provider_key="not_a_provider",
            headers={}, raw_body=b"{}",
        )
        assert outcome.signature_verified is False
        assert outcome.processed == 0
        assert outcome.persisted_ids == []
        assert outcome.rejected_reason == "unknown_provider"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_duplicate_svix_id_short_circuits(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_dup")

        body = _resend_body("email.delivered", email_id="re_dup", to=u.email)
        svix_id = f"msg_{uuid.uuid4().hex[:16]}"
        headers = _svix_headers(secret=TEST_SECRET, body=body, svix_id=svix_id)

        first = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert first.processed == 1
        assert first.duplicate_skipped == 0

        # Replay same svix-id (Resend/Svix guarantee svix-id is unique
        # per event so this is the canonical retry shape).
        second = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert second.duplicate_skipped == 1
        assert second.processed == 0

        # Only one ledger row survived — intent state didn't flip twice.
        rows = db.query(CommunicationWebhookEvent).filter_by(
            provider_event_id=svix_id,
        ).all()
        assert len(rows) == 1
        db.refresh(intent)
        assert intent.state == STATE_DELIVERED


# ---------------------------------------------------------------------------
# Mapping — happy paths
# ---------------------------------------------------------------------------


class TestMappingDelivered:
    def test_delivered_advances_state(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_d")
        body = _resend_body("email.delivered", email_id="re_d", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        db.refresh(intent)
        assert intent.state == STATE_DELIVERED
        assert intent.terminal_at is not None
        # No suppression from a plain delivered event.
        assert is_address_suppressed(
            db, address_type="email", address=u.email,
        ) is None


class TestMappingBounced:
    def test_hard_bounce_advances_state_and_suppresses(
        self, db, make_user, resend_secret,
    ):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_b")
        body = _resend_body(
            "email.bounced", email_id="re_b", to=u.email, bounce_type="hard",
        )
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        db.refresh(intent)
        assert intent.state == STATE_BOUNCED

        suppression = is_address_suppressed(
            db, address_type="email", address=u.email,
        )
        assert suppression is not None
        assert suppression.reason == "bounced"

    def test_soft_bounce_advances_state_without_suppression(
        self, db, make_user, resend_secret,
    ):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_bs")
        body = _resend_body(
            "email.bounced", email_id="re_bs", to=u.email, bounce_type="soft",
        )
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        db.refresh(intent)
        assert intent.state == STATE_BOUNCED
        # Soft bounces DO NOT populate the suppression list.
        assert is_address_suppressed(
            db, address_type="email", address=u.email,
        ) is None


class TestMappingComplained:
    def test_complaint_advances_state_and_suppresses(
        self, db, make_user, resend_secret,
    ):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_c")
        body = _resend_body("email.complained", email_id="re_c", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        db.refresh(intent)
        assert intent.state == STATE_COMPLAINED

        suppression = is_address_suppressed(
            db, address_type="email", address=u.email,
        )
        assert suppression is not None
        assert suppression.reason == "complained"


class TestOutOfScopeEvents:
    """R4 — only delivered/bounced/complained are in scope.
    Other verified event types must not persist an audit row and must
    not mutate delivery / intent / suppression state.
    """

    def _assert_no_side_effect(self, db, intent, address: str) -> None:
        db.refresh(intent)
        assert intent.state == STATE_SENT
        assert db.query(CommunicationWebhookEvent).count() == 0
        assert is_address_suppressed(
            db, address_type="email", address=address,
        ) is None

    def test_unsubscribed_is_out_of_scope(
        self, db, make_user, resend_secret,
    ):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_u")
        body = _resend_body("email.unsubscribed", email_id="re_u", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 0
        assert outcome.rejected_reason is None
        self._assert_no_side_effect(db, intent, u.email)

    def test_opened_is_out_of_scope(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_o")
        body = _resend_body("email.opened", email_id="re_o", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 0
        self._assert_no_side_effect(db, intent, u.email)

    def test_clicked_is_out_of_scope(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_cl")
        body = _resend_body("email.clicked", email_id="re_cl", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 0
        self._assert_no_side_effect(db, intent, u.email)

    def test_sent_is_out_of_scope(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_s")
        body = _resend_body("email.sent", email_id="re_s", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 0
        self._assert_no_side_effect(db, intent, u.email)


# ---------------------------------------------------------------------------
# Mapping — error paths
# ---------------------------------------------------------------------------


class TestMappingErrors:
    def test_unknown_message_id_records_process_error(
        self, db, resend_secret,
    ):
        body = _resend_body(
            "email.delivered", email_id="re_orphan", to="ghost@example.test",
        )
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        # Persisted as a webhook event but processing failed — no
        # matching delivery row means we can't advance state.
        assert outcome.process_errors == 1
        row = db.query(CommunicationWebhookEvent).one()
        assert row.process_error is not None
        assert "no delivery" in row.process_error

    def test_out_of_order_regression_does_not_overwrite(
        self, db, make_user, resend_secret,
    ):
        """R4 — intent already terminal in BOUNCED; a later DELIVERED
        for the same message must not silently overwrite the outcome.
        The audit row is persisted with a process_error; delivery +
        intent stay bounced. No exception is raised.
        """
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_ord")

        # First — hard bounce lands.
        b_body = _resend_body(
            "email.bounced", email_id="re_ord", to=u.email, bounce_type="hard",
        )
        receive(
            db, provider_key="resend",
            headers=_svix_headers(secret=TEST_SECRET, body=b_body),
            raw_body=b_body,
        )
        db.refresh(intent)
        assert intent.state == STATE_BOUNCED

        # Second — a late delivered arrives for the same message.
        d_body = _resend_body("email.delivered", email_id="re_ord", to=u.email)
        outcome = receive(
            db, provider_key="resend",
            headers=_svix_headers(secret=TEST_SECRET, body=d_body),
            raw_body=d_body,
        )
        # Audit row persisted, but processing failed — invalid transition.
        assert outcome.process_errors == 1

        db.refresh(intent)
        assert intent.state == STATE_BOUNCED

        # Delivery row's terminal_outcome must NOT have been overwritten.
        from app.comms.models import CommunicationDelivery
        delivery = db.query(CommunicationDelivery).filter_by(
            provider_message_id="re_ord",
        ).one()
        assert delivery.terminal_outcome == "bounced"


# ---------------------------------------------------------------------------
# Admin ledger surface
# ---------------------------------------------------------------------------


class TestAdminLedger:
    def test_list_returns_webhook_rows(
        self, db, make_user, resend_secret,
    ):
        admin = make_user(role="admin")
        u = make_user()
        _sent_delivery(db, u, provider_message_id="re_L1")
        body = _resend_body("email.delivered", email_id="re_L1", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        receive(db, provider_key="resend", headers=headers, raw_body=body)

        resp = list_webhook_events(db=db, _=admin)  # type: ignore[arg-type]
        assert resp.total >= 1
        assert any(r.event_type == "delivered" for r in resp.items)

    def test_list_filter_unprocessed(self, db, make_user, resend_secret):
        admin = make_user(role="admin")
        # Unknown-message-id run → process_error, still unprocessed.
        body = _resend_body(
            "email.delivered", email_id="re_no_such", to="x@example.test",
        )
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        receive(db, provider_key="resend", headers=headers, raw_body=body)

        resp = list_webhook_events(
            unprocessed=True, db=db, _=admin,  # type: ignore[arg-type]
        )
        assert resp.total >= 1
        for row in resp.items:
            assert row.processed_at is None

    def test_detail_endpoint_returns_raw_payload(
        self, db, make_user, resend_secret,
    ):
        admin = make_user(role="admin")
        u = make_user()
        _sent_delivery(db, u, provider_message_id="re_det")
        body = _resend_body("email.delivered", email_id="re_det", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        receive(db, provider_key="resend", headers=headers, raw_body=body)

        row = db.query(CommunicationWebhookEvent).order_by(
            CommunicationWebhookEvent.received_at.desc(),
        ).first()
        detail = get_webhook_event(event_id=row.id, db=db, _=admin)  # type: ignore[arg-type]
        assert detail.raw_payload["type"] == "email.delivered"
        assert detail.raw_payload["data"]["email_id"] == "re_det"

    def test_detail_404_when_missing(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as exc:
            get_webhook_event(
                event_id="cwe_missing", db=db, _=admin,  # type: ignore[arg-type]
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# R4 — FastAPI route surface (4xx wire behaviour)
# ---------------------------------------------------------------------------


class _FakeRequest:
    """Minimal stand-in for ``fastapi.Request`` — the route only uses
    ``.headers`` (a Mapping) and ``await request.body()``.
    """

    def __init__(self, headers: dict, body: bytes) -> None:
        self.headers = headers
        self._body = body

    async def body(self) -> bytes:
        return self._body


def _call_receive_webhook(*, provider_key: str, headers: dict, body: bytes, db):
    """Drive the async ``receive_webhook`` route from a sync test.

    ``pytest-asyncio`` isn't in the dev deps for this backend (see
    pytest.ini), so we bounce through ``asyncio.run`` per call.
    """
    import asyncio

    from app.comms.routes import receive_webhook
    req = _FakeRequest(headers=headers, body=body)
    return asyncio.run(receive_webhook(
        provider_key=provider_key, request=req, db=db,  # type: ignore[arg-type]
    ))


class TestReceiveWebhookRouteR4:
    """The FastAPI route translates ReceiverOutcome.rejected_reason
    into HTTP 400 / 401 / 404. Verified successes stay 200.
    """

    def test_missing_signature_headers_returns_400(
        self, db, resend_secret,
    ):
        body = _resend_body("email.delivered", email_id="re_r_missing")
        with pytest.raises(HTTPException) as exc:
            _call_receive_webhook(
                provider_key="resend", headers={}, body=body, db=db,
            )
        assert exc.value.status_code == 400
        assert exc.value.detail == {"error": "missing_signature_headers"}
        assert db.query(CommunicationWebhookEvent).count() == 0

    def test_bad_signature_returns_401(self, db, resend_secret):
        body = _resend_body("email.delivered", email_id="re_r_bad")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        headers["svix-signature"] = "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        with pytest.raises(HTTPException) as exc:
            _call_receive_webhook(
                provider_key="resend", headers=headers, body=body, db=db,
            )
        assert exc.value.status_code == 401
        assert exc.value.detail == {"error": "invalid_signature"}
        assert db.query(CommunicationWebhookEvent).count() == 0

    def test_malformed_body_returns_400(self, db, resend_secret):
        body = b"{ not json"
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        with pytest.raises(HTTPException) as exc:
            _call_receive_webhook(
                provider_key="resend", headers=headers, body=body, db=db,
            )
        assert exc.value.status_code == 400
        assert exc.value.detail == {"error": "malformed_payload"}
        assert db.query(CommunicationWebhookEvent).count() == 0

    def test_unknown_provider_returns_404(self, db):
        with pytest.raises(HTTPException) as exc:
            _call_receive_webhook(
                provider_key="does-not-exist", headers={},
                body=b"{}", db=db,
            )
        assert exc.value.status_code == 404

    def test_verified_in_scope_event_returns_200(
        self, db, make_user, resend_secret,
    ):
        u = make_user()
        _sent_delivery(db, u, provider_message_id="re_r_ok")
        body = _resend_body("email.delivered", email_id="re_r_ok", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        resp = _call_receive_webhook(
            provider_key="resend", headers=headers, body=body, db=db,
        )
        assert resp.processed == 1
        assert resp.signature_verified is True

    def test_verified_unknown_message_id_returns_200(
        self, db, resend_secret,
    ):
        """Verified event whose provider_message_id doesn't match any
        delivery still returns 200 — the audit row records the
        process_error, no state is mutated. R4 kept this behaviour."""
        body = _resend_body(
            "email.delivered", email_id="re_r_orphan",
            to="ghost@example.test",
        )
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        resp = _call_receive_webhook(
            provider_key="resend", headers=headers, body=body, db=db,
        )
        assert resp.process_errors == 1
        # Audit row IS persisted (it was verified + in-scope).
        assert db.query(CommunicationWebhookEvent).count() == 1

    def test_verified_out_of_scope_returns_200_no_audit(
        self, db, make_user, resend_secret,
    ):
        """email.opened is verified but out of R4 scope — 200 with no
        audit row and no side effect."""
        u = make_user()
        _sent_delivery(db, u, provider_message_id="re_r_opened")
        body = _resend_body("email.opened", email_id="re_r_opened", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        resp = _call_receive_webhook(
            provider_key="resend", headers=headers, body=body, db=db,
        )
        assert resp.processed == 0
        assert db.query(CommunicationWebhookEvent).count() == 0


# ---------------------------------------------------------------------------
# R4 — startup warning for the missing webhook secret
# ---------------------------------------------------------------------------


class TestStartupWarning:
    """The FastAPI lifespan handler logs a single WARNING when the
    outbound Resend key is configured but the webhook secret is not.
    Neither configuration prevents startup.

    Uses a per-test :class:`logging.Handler` attached directly to
    ``app.main``'s logger so the assertion doesn't depend on
    propagation to caplog (which can be disrupted by other tests
    that reconfigure logging at import time).
    """

    def _run_lifespan(self) -> list:
        import asyncio
        import logging

        from app.main import app, lifespan, logger as main_logger

        captured: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        sink = _Sink(level=logging.WARNING)
        prior_level = main_logger.level
        prior_disabled = main_logger.disabled
        main_logger.setLevel(logging.WARNING)
        main_logger.disabled = False
        main_logger.addHandler(sink)

        async def _drive() -> None:
            async with lifespan(app):
                pass

        try:
            asyncio.run(_drive())
        finally:
            main_logger.removeHandler(sink)
            main_logger.setLevel(prior_level)
            main_logger.disabled = prior_disabled

        return [
            r for r in captured
            if "RESEND_WEBHOOK_SECRET" in r.getMessage()
        ]

    def test_warns_when_api_key_set_but_secret_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "resend_api_key", "re_test_xxx")
        monkeypatch.setattr(settings, "resend_webhook_secret", None)
        records = self._run_lifespan()
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "outbound sending" in msg
        assert "still works" in msg or "still work" in msg
        assert records[0].levelname == "WARNING"

    def test_silent_when_both_set(self, monkeypatch):
        monkeypatch.setattr(settings, "resend_api_key", "re_test_xxx")
        monkeypatch.setattr(settings, "resend_webhook_secret", "whsec_x")
        records = self._run_lifespan()
        assert records == []

    def test_silent_when_api_key_absent(self, monkeypatch):
        # Neither outbound nor inbound is configured — no warning.
        monkeypatch.setattr(settings, "resend_api_key", None)
        monkeypatch.setattr(settings, "resend_webhook_secret", None)
        records = self._run_lifespan()
        assert records == []
