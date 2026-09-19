"""A test send is the email the admin was just looking at.

The admin presses Send test while a rendered email is on screen. If the
two could differ, the button would be actively misleading — worse than
not offering it. So the contract asserted here is byte equality, not
resemblance: whatever the preview endpoint returned, the provider
received, with only the ``[TEST]`` subject prefix and the test banner
added on top.

That is proved by reconstructing the transformation with the module's
own constants rather than by hunting for a few substrings, so a change
to how the banner is injected fails these tests instead of slipping
past them.

The narrowings from Phase B are re-asserted here against the same
requests, because it is exactly when a body carries `mode`, `drafts`
and `variant` that it would be easiest to lose one of them: still one
recipient, still the session's admin, still nothing written to the
communications ledger.

No real email is sent anywhere in this file — the provider is stubbed
at its own boundary, so no code path from these tests reaches the
network.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app.comms.templates  # noqa: F401
import app.comms.routing.resolvers  # noqa: F401
from app.admin.email_templates import (
    TEST_BANNER_TEXT,
    TEST_SUBJECT_PREFIX,
    _inject_test_banner,
)
from app.auth.dependencies import get_admin_user
from app.comms.providers.base import ProviderResult
from app.comms.providers.resend import ResendProvider
from app.core.database import get_db
from app.main import app
from app.comms.models import (
    CommunicationDelivery,
    CommunicationEvent,
    CommunicationIntent,
)
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)

BASE = "/api/admin/communications/email-templates"
BOOKING = "gathering.booking.confirmed.email_transactional"
WELCOME = "account.welcome_after_signup.email_transactional"
PLAN = "creator.plan_activated.email_transactional"

# The booking heading must keep {{gathering_name}} — the API refuses an
# override that drops it. These render to "Saved: Morning Sit" and
# "Draft: Morning Sit" against the sample context.
SAVED_HEADING = "Saved: {{gathering_name}}"
SAVED_RENDERED = "Saved: Morning Sit"
DRAFT_HEADING = "Draft: {{gathering_name}}"
DRAFT_RENDERED = "Draft: Morning Sit"


@pytest.fixture
def admin(make_user):
    return make_user(role="admin", email_verified_at=datetime.utcnow())


@pytest.fixture
def client(db, admin):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sent(monkeypatch):
    """Stub the provider at its own boundary."""
    calls: list = []

    def _send(self, payload):
        calls.append(payload)
        return ProviderResult(accepted=True, provider_message_id="msg_match")

    monkeypatch.setattr(ResendProvider, "send", _send)
    return calls


def preview(client, key, **body):
    r = client.post(f"{BASE}/{key}/preview", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def send_test(client, key, **body):
    r = client.post(f"{BASE}/{key}/test-send", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def save(client, key, overrides):
    """Assert the save landed. A silently-refused override would make
    every "the modes differ" assertion below pass vacuously."""
    r = client.put(f"{BASE}/{key}", json={"overrides": overrides})
    assert r.status_code == 200, r.text
    return r.json()


def assert_matches(sent_payload, previewed, response) -> None:
    """The one contract: the test send *is* the preview, marked as a test."""
    assert sent_payload.subject == TEST_SUBJECT_PREFIX + previewed["subject"]
    assert response["subject"] == sent_payload.subject
    assert sent_payload.body_html == _inject_test_banner(
        previewed["html"], TEST_BANNER_TEXT,
    )
    assert sent_payload.body_text == (
        f"[TEST] {TEST_BANNER_TEXT}\n\n{previewed['text']}"
    )


class TestModesMatch:
    def test_current_mode_test_send_matches_current_preview(self, client, sent):
        """Saved overrides *and* unsaved drafts, exactly as rendered."""
        save(client, BOOKING, {"heading": SAVED_HEADING})
        body = {
            "mode": "effective",
            "drafts": {"cta_label": "Open the gathering"},
            "variant": {"booking_source": "self_booked"},
        }
        p = preview(client, BOOKING, **body)
        r = send_test(client, BOOKING, **body)

        assert len(sent) == 1
        assert_matches(sent[0], p, r)
        # And it really is the current version: the saved override and
        # the unsaved draft are both in the email that went out.
        assert SAVED_RENDERED in sent[0].body_html
        assert "Open the gathering" in sent[0].body_html

    def test_default_mode_test_send_matches_default_preview(self, client, sent):
        save(client, BOOKING, {"heading": SAVED_HEADING})
        body = {"mode": "default", "drafts": {}, "variant": {}}
        p = preview(client, BOOKING, **body)
        r = send_test(client, BOOKING, **body)

        assert len(sent) == 1
        assert_matches(sent[0], p, r)
        # Default means default — the saved override is not in it.
        assert SAVED_RENDERED not in sent[0].body_html

    def test_drafts_are_ignored_in_default_mode(self, client, sent):
        """Switching to the default view answers "what would reset give
        me?". A draft in the request would contradict the question."""
        save(client, BOOKING, {"heading": SAVED_HEADING})
        body = {"mode": "default", "drafts": {"heading": DRAFT_HEADING},
                "variant": {}}
        p = preview(client, BOOKING, **body)
        r = send_test(client, BOOKING, **body)

        # Neither the draft nor the saved override — and the Fresh
        # Collective default in place of both, so this is not merely
        # asserting that two strings are absent from an empty render.
        default_heading = next(
            s["default"] for s in client.get(f"{BASE}/{BOOKING}").json()["slots"]
            if s["slot_id"] == "heading"
        ).replace("{{gathering_name}}", "Morning Sit")
        assert DRAFT_RENDERED not in p["html"]
        assert SAVED_RENDERED not in p["html"]
        assert default_heading in p["html"]
        assert_matches(sent[0], p, r)
        assert DRAFT_RENDERED not in sent[0].body_html
        assert default_heading in sent[0].body_html

    def test_the_two_modes_really_do_differ(self, client, sent):
        """Otherwise every equality above would hold vacuously."""
        save(client, BOOKING, {"heading": SAVED_HEADING})
        current = preview(client, BOOKING, mode="effective")
        default = preview(client, BOOKING, mode="default")
        assert current["html"] != default["html"]

        send_test(client, BOOKING, mode="effective")
        send_test(client, BOOKING, mode="default")
        assert sent[0].body_html != sent[1].body_html

    def test_an_uncustomised_template_matches_in_both_modes(self, client, sent):
        """With nothing saved the two modes agree, and the test send
        agrees with both."""
        for mode in ("effective", "default"):
            p = preview(client, WELCOME, mode=mode)
            r = send_test(client, WELCOME, mode=mode)
            assert_matches(sent[-1], p, r)
        assert sent[0].body_html == sent[1].body_html


class TestVariantsRespected:
    @pytest.mark.parametrize("option,expected", [
        ("self_booked", "You're booked for"),
        ("added_by_creator", "You've been added to"),
    ])
    def test_variant_selection_is_respected_in_both(
        self, client, sent, option, expected,
    ):
        body = {"mode": "effective", "variant": {"booking_source": option}}
        p = preview(client, BOOKING, **body)
        r = send_test(client, BOOKING, **body)
        assert expected in p["text"]
        assert expected in sent[0].body_text
        assert_matches(sent[0], p, r)

    def test_variant_holds_in_default_mode_too(self, client, sent):
        save(client, BOOKING, {
            "body.added_by_creator":
                "A caretaker added you to {{gathering_name}}, "
                "starting {{gathering_when}}.",
        })
        body = {"mode": "default",
                "variant": {"booking_source": "added_by_creator"}}
        p = preview(client, BOOKING, **body)
        r = send_test(client, BOOKING, **body)
        assert "A caretaker added you" not in sent[0].body_html
        assert "You've been added to" in sent[0].body_text
        assert_matches(sent[0], p, r)

    def test_a_second_template_confirms_this_is_not_booking_specific(
        self, client, sent,
    ):
        for option, expected in (("fresh", "Set up your Collective"),
                                 ("returning", "Open Creator Studio")):
            body = {"mode": "effective", "variant": {"creator_state": option}}
            p = preview(client, PLAN, **body)
            r = send_test(client, PLAN, **body)
            assert expected in p["html"]
            assert_matches(sent[-1], p, r)


class TestNarrowingsSurvive:
    """Phase B's guarantees, re-asserted against a mode-carrying body."""

    def test_recipient_is_still_the_session_admin_only(
        self, client, sent, admin,
    ):
        r = send_test(client, BOOKING, mode="default",
                      **{"variant": {}})
        assert r["sent_to"] == admin.email
        assert sent[0].to == admin.email

    def test_a_recipient_in_the_body_is_still_ignored(
        self, client, sent, admin,
    ):
        client.post(f"{BASE}/{BOOKING}/test-send", json={
            "mode": "effective", "to": "member@example.test",
            "recipient": "member@example.test",
        })
        assert sent[0].to == admin.email

    def test_the_ledger_is_still_untouched_in_both_modes(self, client, sent, db):
        def counts():
            return (
                db.query(CommunicationEvent).count(),
                db.query(CommunicationIntent).count(),
                db.query(CommunicationDelivery).count(),
                db.query(CommunicationTemplateOverride).count(),
            )
        before = counts()
        send_test(client, BOOKING, mode="effective",
                  drafts={"heading": DRAFT_HEADING})
        send_test(client, BOOKING, mode="default")
        assert counts() == before
        assert len(sent) == 2

    def test_the_test_banner_never_reaches_stored_copy(self, client, sent):
        send_test(client, BOOKING, mode="effective")
        detail = client.get(f"{BASE}/{BOOKING}").json()
        for slot in detail["slots"]:
            assert TEST_SUBJECT_PREFIX not in slot["effective"]
            assert TEST_BANNER_TEXT not in slot["effective"]
            assert TEST_BANNER_TEXT not in slot["default"]
        # …nor the next preview.
        assert TEST_BANNER_TEXT not in preview(client, BOOKING)["html"]

    def test_invalid_drafts_refuse_the_send_rather_than_sending_something_else(
        self, client, sent,
    ):
        """The preview drops an invalid draft and says so. A test send
        must not quietly send the dropped-back version instead."""
        r = client.post(f"{BASE}/{BOOKING}/test-send", json={
            "mode": "effective", "drafts": {"heading": "<b>Markup</b>"},
        })
        assert r.status_code == 422
        assert sent == []
