"""R1 — Resend provider path proof.

Covers the requirements stated in the R1 brief:

* event → intent → provider dispatch path
* HTML + text payload
* configured sender + reply-to behaviour
* deterministic Resend Idempotency-Key is supplied on the SDK call
* provider failure leaves product/business state untouched
* retry of the same intent does not create a duplicate send

Every test uses either the built-in ``MockProvider`` or a stubbed
``resend.Emails.send`` — nothing here ever contacts the real Resend
API.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

# Register SQLAlchemy relationships used by transitive imports.
import app.models.community_care  # noqa: F401
import app.main  # noqa: F401 — bootstraps registries + providers

from app.comms.categories import (
    CATEGORY_ACCOUNT,
    CHANNEL_EMAIL_TRANSACTIONAL,
    PRIORITY_IMMEDIATE,
    SOURCE_FRESH_COLLECTIVE,
    TOPIC_ACCOUNT,
)
from app.comms.intents import (
    DELIVERY_MODE_LIVE,
    STATE_FAILED,
    STATE_SENT,
    create_intent,
)
from app.comms.models import CommunicationDelivery, CommunicationIntent
from app.comms.providers import get as get_provider
from app.comms.providers.base import ProviderResult, RenderedPayload
from app.comms.providers.resend import ResendProvider
from app.comms.worker import (
    _payload_from_intent,
    dispatch_specific_intent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_diagnostic_intent(
    db,
    *,
    user_id: str,
    to_email: str,
    provider_key: str = "mock",
) -> CommunicationIntent:
    """Create a queued live intent that looks like the diagnostic
    provider probe. Uses TOPIC_ACCOUNT / CATEGORY_ACCOUNT — the same
    topic the real diagnostic event registers under."""
    return create_intent(
        db,
        recipient_user_id=user_id,
        recipient_address=to_email,
        source_type=SOURCE_FRESH_COLLECTIVE,
        source_id=None,
        category_key=CATEGORY_ACCOUNT,
        topic_key=TOPIC_ACCOUNT,
        channel=CHANNEL_EMAIL_TRANSACTIONAL,
        priority=PRIORITY_IMMEDIATE,
        provider_key=provider_key,
        template_key="test.diagnostic.v1",
        template_version="v1",
        human_reason="R1 provider path proof",
        payload_subject="Test subject",
        payload_body_html="<p>Test body</p>",
        payload_body_text="Test body",
        payload_metadata={},
        delivery_mode=DELIVERY_MODE_LIVE,
    )


# ---------------------------------------------------------------------------
# Full event → intent → provider dispatch with MockProvider
# ---------------------------------------------------------------------------


def test_full_dispatch_via_mock_provider_records_send(db, make_user):
    """The end-to-end pipeline hands the rendered payload to the
    registered provider, records a delivery row and transitions the
    intent to ``sent``.
    """
    user = make_user(email=f"r1-{uuid.uuid4().hex[:8]}@example.test")

    intent = _make_diagnostic_intent(
        db, user_id=user.id, to_email=user.email, provider_key="mock",
    )
    db.commit()

    mock = get_provider("mock")
    before = len(mock.sent)  # type: ignore[attr-defined]

    result = dispatch_specific_intent(db, intent.id)

    assert result.accepted is True
    assert result.provider_message_id is not None

    # Reload intent + delivery from the DB.
    reloaded = db.query(CommunicationIntent).filter(
        CommunicationIntent.id == intent.id
    ).one()
    assert reloaded.state == STATE_SENT

    delivery = db.query(CommunicationDelivery).filter(
        CommunicationDelivery.intent_id == intent.id
    ).one()
    assert delivery.status == "accepted"
    assert delivery.provider_key == "mock"
    assert delivery.provider_message_id == result.provider_message_id

    # The mock provider actually received the payload — HTML + text
    # both present as constructed.
    assert len(mock.sent) == before + 1  # type: ignore[attr-defined]
    delivered = mock.sent[-1]  # type: ignore[attr-defined]
    assert delivered.to == user.email
    assert delivered.subject == "Test subject"
    assert delivered.body_html == "<p>Test body</p>"
    assert delivered.body_text == "Test body"


# ---------------------------------------------------------------------------
# Worker propagates intent.id as the idempotency key
# ---------------------------------------------------------------------------


def test_payload_from_intent_injects_idempotency_key_default_intent_id(db, make_user):
    """The worker sets ``metadata['idempotency_key']`` to the intent's
    id so providers that support network-level idempotency have a
    stable key. Any caller-supplied override in metadata wins.
    """
    user = make_user(email=f"r1-{uuid.uuid4().hex[:8]}@example.test")
    intent = _make_diagnostic_intent(db, user_id=user.id, to_email=user.email)

    payload = _payload_from_intent(intent)
    assert payload.metadata["idempotency_key"] == intent.id


def test_payload_from_intent_preserves_caller_supplied_idempotency_key(db, make_user):
    """If the intent stored a specific key in metadata, the worker
    does not overwrite it. Kept as a light forward-compat guarantee
    for cases where a caller wants an event-scoped natural key rather
    than the intent id."""
    user = make_user(email=f"r1-{uuid.uuid4().hex[:8]}@example.test")

    intent = create_intent(
        db,
        recipient_user_id=user.id,
        recipient_address=user.email,
        source_type=SOURCE_FRESH_COLLECTIVE,
        source_id=None,
        category_key=CATEGORY_ACCOUNT,
        topic_key=TOPIC_ACCOUNT,
        channel=CHANNEL_EMAIL_TRANSACTIONAL,
        priority=PRIORITY_IMMEDIATE,
        provider_key="mock",
        human_reason="R1 stable-key test",
        payload_subject="s",
        payload_body_html="<p>x</p>",
        payload_body_text="x",
        payload_metadata={"idempotency_key": "custom-key-abc"},
        delivery_mode=DELIVERY_MODE_LIVE,
    )
    payload = _payload_from_intent(intent)
    assert payload.metadata["idempotency_key"] == "custom-key-abc"


# ---------------------------------------------------------------------------
# ResendProvider — the SDK receives the idempotency key
# ---------------------------------------------------------------------------


def _fake_settings(**overrides):
    """Create an object exposing the two settings attributes the
    provider reads. Applied via patch.object() below."""
    defaults = {"resend_api_key": "test-key", "email_from": "Fresh <hello@test.local>",
                "email_reply_to": None}
    defaults.update(overrides)
    return type("S", (), defaults)()


def test_resend_provider_passes_idempotency_key_to_sdk():
    """The provider must forward ``metadata['idempotency_key']`` to
    ``resend.Emails.send`` via SendOptions. The key protects retries
    of the *same intent* only — separate intents get separate keys
    and legitimately produce separate sends. Durable business-event
    dedupe is at the DB layer (event dedupe_key + intent uniqueness).
    """
    provider = ResendProvider()
    payload = RenderedPayload(
        to="r1@example.test",
        subject="Hi",
        body_html="<p>x</p>",
        body_text="x",
        metadata={"idempotency_key": "intent-xyz-1"},
    )
    fake_settings = _fake_settings()
    with patch("app.comms.providers.resend.settings", fake_settings), \
         patch("resend.Emails.send", return_value={"id": "rmsg_1"}) as spy, \
         patch("resend.api_key", create=True):
        result = provider.send(payload)

    assert result.accepted is True
    assert result.provider_message_id == "rmsg_1"

    # send() was called with (params, options); options carries the key.
    args, kwargs = spy.call_args
    assert len(args) == 2, "provider should pass options as 2nd positional arg when key present"
    params, options = args
    assert params["from"] == "Fresh <hello@test.local>"
    assert params["to"] == ["r1@example.test"]
    assert params["html"] == "<p>x</p>"
    assert params["text"] == "x"
    assert options == {"idempotency_key": "intent-xyz-1"}


def test_resend_provider_omits_options_when_no_idempotency_key():
    """When no key is supplied, the provider must call send() with
    params only — do not send an empty SendOptions dict."""
    provider = ResendProvider()
    payload = RenderedPayload(
        to="r1@example.test", subject="Hi",
        body_html="<p>x</p>", body_text="x",
        metadata={},  # no idempotency_key
    )
    fake_settings = _fake_settings()
    with patch("app.comms.providers.resend.settings", fake_settings), \
         patch("resend.Emails.send", return_value={"id": "rmsg_2"}) as spy, \
         patch("resend.api_key", create=True):
        provider.send(payload)

    args, _ = spy.call_args
    assert len(args) == 1, "provider should call send(params) only when no key present"


# ---------------------------------------------------------------------------
# Sender + Reply-To behaviour
# ---------------------------------------------------------------------------


def test_resend_provider_uses_configured_sender():
    provider = ResendProvider()
    payload = RenderedPayload(
        to="r1@example.test", subject="s", body_text="body",
    )
    fake = _fake_settings(email_from="Fresh Collective <hello@freshcollective.au>")
    with patch("app.comms.providers.resend.settings", fake), \
         patch("resend.Emails.send", return_value={"id": "rm"}) as spy, \
         patch("resend.api_key", create=True):
        provider.send(payload)
    params, *_ = spy.call_args.args
    assert params["from"] == "Fresh Collective <hello@freshcollective.au>"


def test_resend_provider_reply_to_falls_back_to_settings():
    provider = ResendProvider()
    payload = RenderedPayload(
        to="r1@example.test", subject="s", body_text="body",
        # no reply_to on the payload
    )
    fake = _fake_settings(email_reply_to="hello@freshcollective.au")
    with patch("app.comms.providers.resend.settings", fake), \
         patch("resend.Emails.send", return_value={"id": "rm"}) as spy, \
         patch("resend.api_key", create=True):
        provider.send(payload)
    params, *_ = spy.call_args.args
    assert params.get("reply_to") == "hello@freshcollective.au"


def test_resend_provider_payload_reply_to_wins_over_settings():
    provider = ResendProvider()
    payload = RenderedPayload(
        to="r1@example.test", subject="s", body_text="body",
        reply_to="ops@freshcollective.au",
    )
    fake = _fake_settings(email_reply_to="hello@freshcollective.au")
    with patch("app.comms.providers.resend.settings", fake), \
         patch("resend.Emails.send", return_value={"id": "rm"}) as spy, \
         patch("resend.api_key", create=True):
        provider.send(payload)
    params, *_ = spy.call_args.args
    assert params.get("reply_to") == "ops@freshcollective.au"


# ---------------------------------------------------------------------------
# Fail-closed when config is missing
# ---------------------------------------------------------------------------


def test_resend_provider_returns_config_missing_when_api_key_absent():
    provider = ResendProvider()
    payload = RenderedPayload(
        to="r1@example.test", subject="s", body_text="body",
    )
    fake = _fake_settings(resend_api_key=None)
    with patch("app.comms.providers.resend.settings", fake):
        result = provider.send(payload)
    assert result.accepted is False
    assert result.error_class == "config_missing"


def test_resend_provider_returns_config_missing_when_sender_absent():
    provider = ResendProvider()
    payload = RenderedPayload(
        to="r1@example.test", subject="s", body_text="body",
    )
    fake = _fake_settings(email_from=None)
    with patch("app.comms.providers.resend.settings", fake):
        result = provider.send(payload)
    assert result.accepted is False
    assert result.error_class == "config_missing"


# ---------------------------------------------------------------------------
# Provider failure isolation + retry safety
# ---------------------------------------------------------------------------


class _AlwaysFailProvider:
    """A provider that raises on every send — mimics a broken
    third-party SDK. The worker must record the failure and mark the
    intent ``failed`` without letting the exception escape."""

    key = "test_always_fail"
    capabilities = frozenset({CHANNEL_EMAIL_TRANSACTIONAL})
    production_eligible = False

    def send(self, payload):
        raise RuntimeError("simulated provider blowup")

    def health(self):
        # Minimal — never queried in this test.
        from app.comms.providers.base import HealthStatus, ProviderHealth, now_utc
        return ProviderHealth(status=HealthStatus.OFFLINE, checked_at=now_utc())


def test_provider_exception_leaves_intent_failed_without_raising(db, make_user):
    """A provider that throws must be captured and result in a
    ``failed`` intent + a delivery row with the exception recorded.
    Business state (the calling function's other DB writes) must
    remain intact — dispatch_specific_intent never raises."""
    user = make_user(email=f"r1-{uuid.uuid4().hex[:8]}@example.test")

    # Register the failing provider under a fresh key. Not calling
    # reset_registry() so the built-in providers remain available
    # for the other tests in the module.
    from app.comms.providers import register, _REGISTRY  # type: ignore[attr-defined]
    key = "test_always_fail"
    if key in _REGISTRY:
        _REGISTRY.pop(key)
    register(_AlwaysFailProvider())

    intent = _make_diagnostic_intent(
        db, user_id=user.id, to_email=user.email, provider_key=key,
    )
    db.commit()

    # Must not raise.
    result = dispatch_specific_intent(db, intent.id)
    assert result.accepted is False
    assert result.error_class == "RuntimeError"

    reloaded = db.query(CommunicationIntent).filter(
        CommunicationIntent.id == intent.id
    ).one()
    assert reloaded.state == STATE_FAILED

    deliveries = db.query(CommunicationDelivery).filter(
        CommunicationDelivery.intent_id == intent.id
    ).all()
    assert len(deliveries) == 1
    assert deliveries[0].status == "failed"
    assert deliveries[0].error_class == "RuntimeError"

    # Cleanup — remove the fake provider so it doesn't leak.
    _REGISTRY.pop(key, None)


def test_second_dispatch_of_same_intent_raises_without_second_send(db, make_user):
    """After the first dispatch marks the intent terminal (sent or
    failed), a second call to ``dispatch_specific_intent`` must refuse
    to run the send again. This DB-state guard is the authoritative
    protection against re-dispatching the same intent id. The Resend
    network idempotency key is a redundant network-layer safety net
    for the narrow window between a partial crash and a retry of the
    same intent; it never covers legitimate separate emits."""
    user = make_user(email=f"r1-{uuid.uuid4().hex[:8]}@example.test")

    intent = _make_diagnostic_intent(
        db, user_id=user.id, to_email=user.email, provider_key="mock",
    )
    db.commit()

    mock = get_provider("mock")
    before = len(mock.sent)  # type: ignore[attr-defined]

    # First dispatch — succeeds.
    first = dispatch_specific_intent(db, intent.id)
    assert first.accepted is True

    after_first = len(mock.sent)  # type: ignore[attr-defined]
    assert after_first == before + 1

    # Second dispatch — must refuse (intent is now ``sent``, not
    # ``queued``) and must NOT invoke the provider a second time.
    with pytest.raises(ValueError):
        dispatch_specific_intent(db, intent.id)

    after_second = len(mock.sent)  # type: ignore[attr-defined]
    assert after_second == after_first  # no additional send happened
