"""Tests for the M3 provider layer.

Covers:
  * Registry: register / get / all / providers_for_channel / reset.
  * Protocol conformance for each shipped provider.
  * ResendProvider: config-missing → offline + reject; happy path
    dispatches through the ``resend`` module.
  * InAppProvider: persists a Notification row via the injected session.
  * MockProvider: records sends; reset clears history.
  * CaptureProvider: writes a file to the target dir.
  * ProviderHealth shape.
  * EmailService compatibility shim still works.
"""

from __future__ import annotations

import types
from datetime import datetime
from pathlib import Path

import pytest

from app.comms.categories import (
    CHANNEL_EMAIL_MARKETING,
    CHANNEL_EMAIL_TRANSACTIONAL,
    CHANNEL_IN_APP,
    CHANNEL_PUSH,
)
from app.comms.providers import (
    DeliveryProvider,
    HealthStatus,
    ProviderHealth,
    ProviderResult,
    RenderedPayload,
    _bootstrap,
    all_providers,
    get,
    production_providers_for_channel,
    providers_for_channel,
    register,
    reset_registry,
)
from app.comms.providers.capture import CaptureProvider
from app.comms.providers.inapp import InAppProvider
from app.comms.providers.mock import MockProvider
from app.comms.providers.resend import ResendProvider


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    """Every test in this class starts from a known-empty registry and
    restores the shipped bootstrap so no cross-test contamination
    escapes.
    """

    @pytest.fixture(autouse=True)
    def _isolate_registry(self):
        reset_registry()
        yield
        reset_registry()
        _bootstrap()

    def test_register_then_get(self):
        m = MockProvider()
        register(m)
        assert get("mock") is m

    def test_duplicate_key_raises(self):
        register(MockProvider())
        with pytest.raises(ValueError):
            register(MockProvider())

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            get("nope")

    def test_all_providers_returns_insertion_order(self):
        m = MockProvider()
        c = CaptureProvider(target_dir=Path("/tmp/does-not-exist"))
        register(m)
        register(c)
        keys = [p.key for p in all_providers()]
        assert keys == ["mock", "capture"]

    def test_providers_for_channel_filters_by_capability(self):
        register(MockProvider())
        register(CaptureProvider(target_dir=Path("/tmp/does-not-exist")))
        push = providers_for_channel(CHANNEL_PUSH)
        assert [p.key for p in push] == ["mock"]  # capture doesn't serve push
        email_tx = providers_for_channel(CHANNEL_EMAIL_TRANSACTIONAL)
        assert {p.key for p in email_tx} == {"mock", "capture"}

    def test_providers_for_channel_rejects_unknown(self):
        with pytest.raises(ValueError):
            providers_for_channel("totally-not-a-channel")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_bootstrap_registers_expected_providers(self):
        keys = {p.key for p in all_providers()}
        assert {"resend", "in_app", "mock", "capture"}.issubset(keys)


# ---------------------------------------------------------------------------
# Production eligibility — Mock + Capture must never route real traffic
# ---------------------------------------------------------------------------


class TestProductionEligibility:
    def test_mock_and_capture_not_production_eligible(self):
        assert MockProvider().production_eligible is False
        assert CaptureProvider(target_dir=Path("/tmp/no")).production_eligible is False

    def test_resend_and_inapp_are_production_eligible(self):
        assert ResendProvider().production_eligible is True
        assert InAppProvider().production_eligible is True

    def test_production_providers_for_channel_excludes_mock_and_capture(self):
        # With the shipped bootstrap:
        #   email_transactional: resend (prod), mock (dev), capture (dev)
        prod = production_providers_for_channel(CHANNEL_EMAIL_TRANSACTIONAL)
        keys = {p.key for p in prod}
        assert "resend" in keys
        assert "mock" not in keys
        assert "capture" not in keys

    def test_production_providers_for_push_returns_empty_when_only_mock(self):
        # Only the mock provider serves push in the shipped bootstrap;
        # a production routing call therefore returns an empty tuple
        # (delivery should hold, not route to Mock).
        prod = production_providers_for_channel(CHANNEL_PUSH)
        assert prod == ()


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Every shipped provider satisfies the runtime protocol check."""

    @pytest.mark.parametrize(
        "factory",
        [
            ResendProvider,
            InAppProvider,
            MockProvider,
            lambda: CaptureProvider(target_dir=Path("/tmp/does-not-exist")),
        ],
    )
    def test_conforms(self, factory):
        assert isinstance(factory(), DeliveryProvider)


# ---------------------------------------------------------------------------
# ResendProvider
# ---------------------------------------------------------------------------


class TestResendProvider:
    def test_health_offline_when_api_key_missing(self, monkeypatch):
        from app.core import config as _cfg
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "", raising=False)
        h = ResendProvider().health()
        assert h.status == HealthStatus.OFFLINE
        assert "RESEND_API_KEY" in (h.detail or "")

    def test_health_offline_when_email_from_missing(self, monkeypatch):
        from app.core import config as _cfg
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "test-key", raising=False)
        monkeypatch.setattr(_cfg.settings, "email_from", "", raising=False)
        h = ResendProvider().health()
        assert h.status == HealthStatus.OFFLINE
        assert "EMAIL_FROM" in (h.detail or "")

    def test_health_healthy_when_configured(self, monkeypatch):
        from app.core import config as _cfg
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "test-key", raising=False)
        monkeypatch.setattr(_cfg.settings, "email_from", "from@example.test", raising=False)
        h = ResendProvider().health()
        assert h.status == HealthStatus.HEALTHY

    def test_send_config_missing_returns_reject(self, monkeypatch):
        from app.core import config as _cfg
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "", raising=False)
        r = ResendProvider().send(
            RenderedPayload(to="a@b.test", subject="s", body_html="<p>x</p>"),
        )
        assert r.accepted is False
        assert r.error_class == "config_missing"

    def test_send_empty_body_rejected(self, monkeypatch):
        from app.core import config as _cfg
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "test-key", raising=False)
        monkeypatch.setattr(_cfg.settings, "email_from", "from@example.test", raising=False)
        r = ResendProvider().send(
            RenderedPayload(to="a@b.test", subject="s"),
        )
        assert r.accepted is False
        assert r.error_class == "empty_body"

    def test_send_happy_path_stubs_resend(self, monkeypatch):
        """The provider hands the request to resend.Emails.send. We
        inject a stub module so the test never talks to the network."""
        from app.core import config as _cfg
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "test-key", raising=False)
        monkeypatch.setattr(_cfg.settings, "email_from", "from@example.test", raising=False)

        captured: dict = {}

        def _stub_send(req):
            captured["req"] = req
            return {"id": "re_stubid"}

        stub = types.SimpleNamespace(
            api_key=None,
            Emails=types.SimpleNamespace(send=_stub_send),
        )
        monkeypatch.setitem(__import__("sys").modules, "resend", stub)

        r = ResendProvider().send(
            RenderedPayload(
                to="a@b.test",
                subject="Hello",
                body_html="<p>hi</p>",
                reply_to="rep@example.test",
            ),
        )
        assert r.accepted is True
        assert r.provider_message_id == "re_stubid"
        assert captured["req"]["from"] == "from@example.test"
        assert captured["req"]["to"] == ["a@b.test"]
        assert captured["req"]["subject"] == "Hello"
        assert captured["req"]["html"] == "<p>hi</p>"
        assert captured["req"]["reply_to"] == "rep@example.test"

    def test_send_provider_exception_captured(self, monkeypatch):
        from app.core import config as _cfg
        monkeypatch.setattr(_cfg.settings, "resend_api_key", "test-key", raising=False)
        monkeypatch.setattr(_cfg.settings, "email_from", "from@example.test", raising=False)

        def _boom(_req):
            raise RuntimeError("upstream fell over")

        stub = types.SimpleNamespace(
            api_key=None,
            Emails=types.SimpleNamespace(send=_boom),
        )
        monkeypatch.setitem(__import__("sys").modules, "resend", stub)

        r = ResendProvider().send(
            RenderedPayload(to="a@b.test", subject="s", body_html="<p>x</p>"),
        )
        assert r.accepted is False
        assert r.error_class == "RuntimeError"
        assert "upstream fell over" in (r.error_detail or "")


# ---------------------------------------------------------------------------
# InAppProvider
# ---------------------------------------------------------------------------


class TestInAppProvider:
    def test_send_persists_notification(self, db, make_user):
        u = make_user()
        provider = InAppProvider(session_factory=lambda: db)
        r = provider.send(
            RenderedPayload(
                to=u.id,
                subject="You have a reply",
                body_text="Someone replied to your post.",
                metadata={
                    "notification_type": "comment_reply",
                    "url": "/spaces/x/community/p1",
                },
            ),
        )
        assert r.accepted is True
        assert r.provider_message_id is not None

        from app.models.notification import Notification
        row = db.get(Notification, r.provider_message_id)
        assert row is not None
        assert row.user_id == u.id
        assert row.notification_type == "comment_reply"
        assert row.title == "You have a reply"
        assert row.message == "Someone replied to your post."
        assert row.url == "/spaces/x/community/p1"

    def test_send_rejects_missing_notification_type(self, db, make_user):
        u = make_user()
        provider = InAppProvider(session_factory=lambda: db)
        r = provider.send(
            RenderedPayload(to=u.id, subject="Anything"),
        )
        assert r.accepted is False
        assert r.error_class == "metadata_missing"

    def test_health_healthy(self):
        h = InAppProvider().health()
        assert h.status == HealthStatus.HEALTHY


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


class TestMockProvider:
    def test_records_sends_in_order(self):
        m = MockProvider()
        m.send(RenderedPayload(to="a@b.test", subject="1"))
        m.send(RenderedPayload(to="c@d.test", subject="2"))
        assert [p.subject for p in m.sent] == ["1", "2"]

    def test_reset_clears(self):
        m = MockProvider()
        m.send(RenderedPayload(to="a@b.test", subject="1"))
        m.reset()
        assert m.sent == []

    def test_serves_every_channel(self):
        m = MockProvider()
        for ch in (
            CHANNEL_IN_APP,
            CHANNEL_EMAIL_TRANSACTIONAL,
            CHANNEL_EMAIL_MARKETING,
            CHANNEL_PUSH,
        ):
            assert ch in m.capabilities


# ---------------------------------------------------------------------------
# CaptureProvider
# ---------------------------------------------------------------------------


class TestCaptureProvider:
    def test_writes_file(self, tmp_path):
        provider = CaptureProvider(target_dir=tmp_path)
        r = provider.send(
            RenderedPayload(
                to="a@b.test",
                subject="Booking confirmed — Sunday Sit",
                body_html="<h1>You're booked</h1>",
            ),
        )
        assert r.accepted is True
        assert r.provider_message_id is not None

        file = tmp_path / r.provider_message_id
        assert file.exists()
        assert "You're booked" in file.read_text()
        # Slug contains subject words, timestamp is at the start.
        assert "booking-confirmed" in r.provider_message_id
        assert r.provider_message_id.endswith(".html")

    def test_slug_from_empty_subject(self, tmp_path):
        provider = CaptureProvider(target_dir=tmp_path)
        r = provider.send(
            RenderedPayload(to="a@b.test", subject="", body_text="hi"),
        )
        assert r.accepted is True
        assert "untitled" in (r.provider_message_id or "")

    def test_health_healthy_when_writable(self, tmp_path):
        h = CaptureProvider(target_dir=tmp_path).health()
        assert h.status == HealthStatus.HEALTHY


# ---------------------------------------------------------------------------
# ProviderHealth shape
# ---------------------------------------------------------------------------


class TestProviderHealthShape:
    def test_health_has_expected_fields(self):
        h = MockProvider().health()
        assert isinstance(h, ProviderHealth)
        assert isinstance(h.status, HealthStatus)
        assert isinstance(h.checked_at, datetime)
        assert h.checked_at.tzinfo is not None  # timezone-aware
        assert h.metrics == {} or isinstance(h.metrics, dict)


# ---------------------------------------------------------------------------
# EmailService compatibility shim
# ---------------------------------------------------------------------------


class TestEmailServiceShim:
    def test_send_delegates_to_resend_provider(self, monkeypatch):
        """The legacy public path still works — it now flows through
        the provider registry.
        """
        from app.services.email_service import email_service

        # Swap the registered resend provider for a mock so we can
        # observe the delegation without touching the network.
        reset_registry()
        register(ResendProvider())  # keep for other tests / bootstrap parity
        register(InAppProvider())
        register(MockProvider())
        register(CaptureProvider(target_dir=Path("/tmp/does-not-exist")))
        # Replace resend with a stub that records the payload.
        reset_registry()
        captured: dict = {}

        class _StubResend:
            key = "resend"
            capabilities = frozenset({CHANNEL_EMAIL_TRANSACTIONAL})

            def send(self, payload):
                captured["payload"] = payload
                return ProviderResult(accepted=True, provider_message_id="stub")

            def health(self):
                from app.comms.providers.base import now_utc as _now
                return ProviderHealth(status=HealthStatus.HEALTHY, checked_at=_now())

        register(_StubResend())

        email_service.send(
            to="a@b.test",
            subject="Hi",
            html_body="<p>body</p>",
            reply_to="rep@example.test",
        )

        assert "payload" in captured
        p: RenderedPayload = captured["payload"]
        assert p.to == "a@b.test"
        assert p.subject == "Hi"
        assert p.body_html == "<p>body</p>"
        assert p.reply_to == "rep@example.test"

        # Restore the shipped bootstrap so subsequent tests see the
        # real registered providers.
        reset_registry()
        _bootstrap()

    def test_notification_email_html_still_renders(self):
        from app.services.email_service import notification_email_html
        html = notification_email_html(
            title="A reply", message="Someone replied.", url="/x",
        )
        assert "A reply" in html
        assert "Someone replied" in html
