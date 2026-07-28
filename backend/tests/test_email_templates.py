"""
Tests for the Fresh Collective shared email templates + delivery
wrapper. Nothing here hits Resend — the wrapper is tested with
monkeypatched settings.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import email_service as email_service_mod
from app.services.email_templates import (
    booking_confirmation_email,
    creator_announcement_email,
    invitation_email,
    new_pathway_email,
    password_reset_email,
    render_email,
    reply_notification_email,
)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_render_email_has_the_expected_shell():
    html = render_email(
        preheader="Preview line",
        heading="Hello",
        body_paragraphs=["A single quiet paragraph."],
    )
    assert "Fresh Collective" in html
    assert "Hello" in html
    assert "A single quiet paragraph." in html
    assert "Preview line" in html
    assert "Manage your Stay Connected preferences" in html
    # Preferences link points at the frontend origin (dev default is
    # http://localhost:3000).
    assert "/settings/stay-connected" in html


def test_render_email_escapes_user_supplied_text():
    html = render_email(
        preheader="<script>a</script>",
        heading="Sarah <b>replied</b>",
        body_paragraphs=["<img src=x onerror=alert(1) />"],
    )
    assert "<script>a</script>" not in html
    assert "Sarah <b>replied</b>" not in html
    assert "<img src=x" not in html
    # Escaped forms must be present.
    assert "&lt;script&gt;a&lt;/script&gt;" in html
    assert "&lt;b&gt;replied&lt;/b&gt;" in html


def test_render_email_renders_button_only_when_action_given():
    without = render_email(preheader="p", heading="h", body_paragraphs=["b"])
    with_btn = render_email(
        preheader="p", heading="h", body_paragraphs=["b"],
        action=("Continue", "https://example.com/x"),
    )
    assert "Continue" not in without
    assert "Continue" in with_btn
    assert "https://example.com/x" in with_btn


# ---------------------------------------------------------------------------
# Concrete templates — smoke tests on subject + content signals
# ---------------------------------------------------------------------------


def test_password_reset_template_contains_link_and_expiry_wording():
    subject, html = password_reset_email(
        reset_url="https://freshcollective.au/reset-password?token=X",
    )
    assert subject == "Reset your Fresh Collective password"
    assert "Reset password" in html
    assert "https://freshcollective.au/reset-password?token=X" in html
    assert "expires in 30 minutes" in html
    assert "ignore this email" in html


def test_invitation_template_names_inviter_and_collective():
    subject, html = invitation_email(
        inviter_name="Lindsey",
        collective_name="The Grove",
        accept_url="https://freshcollective.au/invites/abc",
    )
    assert subject == "Lindsey invited you to The Grove"
    assert "Lindsey" in html
    assert "The Grove" in html
    assert "Accept invitation" in html
    assert "https://freshcollective.au/invites/abc" in html


def test_booking_confirmation_shows_when_where_and_link():
    subject, html = booking_confirmation_email(
        member_name="Sarah",
        gathering_title="Thursday EMBODY",
        starts_when="Thursday 6 August 2026 at 7:00 PM",
        location_line="Zoom link — shared before the gathering",
        view_url="https://freshcollective.au/spaces/embody/events/e1",
    )
    assert "Booking confirmed: Thursday EMBODY" in subject
    assert "Thursday EMBODY" in html
    assert "Thursday 6 August 2026 at 7:00 PM" in html
    assert "Zoom link" in html
    assert "View gathering" in html


def test_creator_announcement_uses_creator_signoff():
    subject, html = creator_announcement_email(
        creator_name="Lindsey",
        collective_name="The Grove",
        title="A note before Sunday",
        message="See you there.",
        url="https://freshcollective.au/spaces/x",
    )
    assert subject == "A note before Sunday"
    assert "— Lindsey" in html
    assert "The Grove" in html
    assert "Open in Fresh Collective" in html


def test_new_pathway_defaults_lead_line_to_collective_name():
    subject, html = new_pathway_email(
        pathway_title="Life in Alignment",
        collective_name="The Grove",
        pathway_url="https://freshcollective.au/spaces/x/pathways/y",
    )
    assert subject == "New pathway: Life in Alignment"
    assert "The Grove" in html
    assert "Life in Alignment" in html
    assert "Open pathway" in html


def test_reply_notification_quotes_the_reply():
    subject, html = reply_notification_email(
        replier_name="Emma",
        quote="Landing so clearly for me.",
        reply_url="https://freshcollective.au/spaces/x/community/p",
        in_context="in your reflection",
    )
    assert subject == "Emma replied in your reflection"
    assert "\u201CLanding so clearly for me.\u201D" in html
    assert "Open the conversation" in html


# ---------------------------------------------------------------------------
# EmailService wrapper — env-driven behaviour
# ---------------------------------------------------------------------------


def test_send_skips_when_api_key_missing(monkeypatch):
    """Missing RESEND_API_KEY → skip without hitting the provider. Never raises."""
    monkeypatch.setattr(settings, "resend_api_key", None, raising=False)
    monkeypatch.setattr(settings, "email_from", "Fresh Collective <hello@freshcollective.au>", raising=False)

    called = {"n": 0}

    class _Blowup:
        api_key = None
        class Emails:
            @staticmethod
            def send(_payload):
                called["n"] += 1
    monkeypatch.setitem(__import__("sys").modules, "resend", _Blowup)

    # Must not raise, must not touch the provider.
    email_service_mod.email_service.send(
        to="dev@example.test", subject="X", html_body="<p>ok</p>",
    )
    assert called["n"] == 0


def test_send_fails_loudly_when_from_missing(monkeypatch):
    """Key present but EMAIL_FROM missing → skip without hitting the
    provider. Never silently falls back to a default domain."""
    monkeypatch.setattr(settings, "resend_api_key", "test_key", raising=False)
    monkeypatch.setattr(settings, "email_from", None, raising=False)

    called = {"n": 0, "payload": None}

    class _Blowup:
        api_key = None
        class Emails:
            @staticmethod
            def send(payload):
                called["n"] += 1
                called["payload"] = payload
    monkeypatch.setitem(__import__("sys").modules, "resend", _Blowup)

    email_service_mod.email_service.send(
        to="dev@example.test", subject="X", html_body="<p>ok</p>",
    )
    # The critical guarantee: nothing left the wrapper.
    assert called["n"] == 0
    assert called["payload"] is None


def test_send_passes_reply_to_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "test_key", raising=False)
    monkeypatch.setattr(settings, "email_from",
                        "Fresh Collective <hello@freshcollective.au>", raising=False)
    monkeypatch.setattr(settings, "email_reply_to", "hello@freshcollective.au", raising=False)

    captured: dict = {}

    class _StubEmails:
        @staticmethod
        def send(payload: dict) -> None:
            captured.update(payload)

    class _StubResend:
        api_key = None
        Emails = _StubEmails

    monkeypatch.setitem(__import__("sys").modules, "resend", _StubResend)

    email_service_mod.email_service.send(
        to="member@example.test", subject="Hello", html_body="<p>ok</p>",
    )
    assert captured["from"] == "Fresh Collective <hello@freshcollective.au>"
    assert captured["to"] == ["member@example.test"]
    assert captured["subject"] == "Hello"
    assert captured["reply_to"] == "hello@freshcollective.au"


def test_send_per_call_reply_to_wins_over_env(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "test_key", raising=False)
    monkeypatch.setattr(settings, "email_from",
                        "Fresh Collective <hello@freshcollective.au>", raising=False)
    monkeypatch.setattr(settings, "email_reply_to", "hello@freshcollective.au", raising=False)

    captured: dict = {}

    class _StubEmails:
        @staticmethod
        def send(payload: dict) -> None:
            captured.update(payload)

    class _StubResend:
        api_key = None
        Emails = _StubEmails

    monkeypatch.setitem(__import__("sys").modules, "resend", _StubResend)

    email_service_mod.email_service.send(
        to="member@example.test",
        subject="Hello",
        html_body="<p>ok</p>",
        reply_to="creator@example.test",
    )
    assert captured["reply_to"] == "creator@example.test"


def test_send_never_raises_on_provider_failure(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "test_key", raising=False)
    monkeypatch.setattr(settings, "email_from",
                        "Fresh Collective <hello@freshcollective.au>", raising=False)

    class _Bang:
        api_key = None
        class Emails:
            @staticmethod
            def send(_payload):
                raise RuntimeError("simulated provider fault")

    monkeypatch.setitem(__import__("sys").modules, "resend", _Bang)

    # The critical guarantee: exceptions from the provider must not
    # propagate — routes and background tasks are protected.
    email_service_mod.email_service.send(
        to="member@example.test", subject="Hello", html_body="<p>ok</p>",
    )
