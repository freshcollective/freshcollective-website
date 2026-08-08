"""Tests for the M6 inbound webhook framework.

Covers:
  * Svix signature verification — happy path, bad signature, missing
    headers, replay outside timestamp tolerance.
  * ReceiverOutcome ledger — persists on failure, sets processed_at
    on success, idempotent on duplicate provider_event_id.
  * Mapping semantics —
        delivered      → intent → STATE_DELIVERED
        bounced/hard   → intent → STATE_BOUNCED   + suppression
        bounced/soft   → intent → STATE_BOUNCED   (no suppression)
        complained     → intent → STATE_COMPLAINED + suppression
        unsubscribed   → suppression only, no state change
        opened/clicked → audit only, no state change
        sent           → audit only, no state change
  * Unknown provider_message_id → process_error, no crash.
  * Malformed JSON body → process_error, receiver returns 200.
  * Unknown provider_key → 404 (route-level).

Route functions are called directly (matching the pattern in
``test_comms_admin_events.py``); the receiver route is exercised via
``receive()`` since it takes ``(db, provider_key, headers, raw_body)``
and does not depend on FastAPI's ``Request`` type at that boundary.
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
    def test_bad_signature_still_persists_audit_row(self, db, resend_secret):
        body = _resend_body("email.delivered", email_id="re_1")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        headers["svix-signature"] = "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.signature_verified is False
        assert outcome.processed == 0
        # Ledger row persisted with the failure marker.
        rows = db.query(CommunicationWebhookEvent).all()
        assert len(rows) == 1
        assert rows[0].signature_verified is False
        assert rows[0].event_type == "signature_verification_failed"
        assert rows[0].process_error == "signature_verification_failed"

    def test_no_secret_configured_rejects(self, db, monkeypatch):
        monkeypatch.setattr(settings, "resend_webhook_secret", None)
        body = _resend_body("email.delivered", email_id="re_1")
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.signature_verified is False

    def test_unknown_provider_returns_empty_outcome(self, db, resend_secret):
        outcome = receive(
            db, provider_key="not_a_provider",
            headers={}, raw_body=b"{}",
        )
        assert outcome.signature_verified is False
        assert outcome.processed == 0
        assert outcome.persisted_ids == []


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


class TestMappingUnsubscribed:
    def test_unsubscribe_only_suppresses_no_state_change(
        self, db, make_user, resend_secret,
    ):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_u")
        body = _resend_body("email.unsubscribed", email_id="re_u", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        # Suppression recorded — future sends will be blocked.
        suppression = is_address_suppressed(
            db, address_type="email", address=u.email,
        )
        assert suppression is not None
        assert suppression.reason == "unsubscribed"

        # But the intent state DOES NOT flip on unsubscribe. Consent is
        # a member action captured through FC's own surfaces; webhooks
        # only carry a suppression signal.
        db.refresh(intent)
        assert intent.state == STATE_SENT


class TestMappingObservational:
    def test_opened_is_audit_only(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_o")
        body = _resend_body("email.opened", email_id="re_o", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        db.refresh(intent)
        assert intent.state == STATE_SENT
        assert is_address_suppressed(
            db, address_type="email", address=u.email,
        ) is None

    def test_clicked_is_audit_only(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_cl")
        body = _resend_body("email.clicked", email_id="re_cl", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        db.refresh(intent)
        assert intent.state == STATE_SENT

    def test_sent_is_audit_only(self, db, make_user, resend_secret):
        u = make_user()
        intent = _sent_delivery(db, u, provider_message_id="re_s")
        body = _resend_body("email.sent", email_id="re_s", to=u.email)
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.processed == 1

        db.refresh(intent)
        assert intent.state == STATE_SENT


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

    def test_malformed_json_does_not_crash(self, db, resend_secret):
        body = b"{ this is not json"
        headers = _svix_headers(secret=TEST_SECRET, body=body)
        # Should not raise. Parse returns [] so a single audit row
        # captures the empty-parse outcome.
        outcome = receive(db, provider_key="resend", headers=headers, raw_body=body)
        assert outcome.signature_verified is True
        assert outcome.processed == 0
        row = db.query(CommunicationWebhookEvent).one()
        assert row.process_error == "empty_parse"


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
