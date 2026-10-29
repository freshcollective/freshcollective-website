"""The email a member actually receives when a creator writes to them.

Two defects shipped together and are fixed together:

* **The link went nowhere.** Every caller in ``notification_service``
  passes an app-relative path — ``/spaces/{slug}/messages/{id}`` and
  its siblings — which is right for an in-app notification and useless
  in an email. The button had nothing to resolve against and the
  visible fallback line underneath showed a bare path.
* **It never said which Collective.** "Message from Lindsey Hilliard",
  with nothing to distinguish one Collective from another in an inbox
  holding several.

Nothing is sent from these tests: they render HTML and inspect it, and
the one that exercises the notification path replaces the send.
"""
from __future__ import annotations

import re

import pytest

from app.services.email_service import _absolute, notification_email_html
from app.services.email_templates import render_email

THREAD_PATH = "/spaces/moonlit-circle/messages/mt_abc123"


def _hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


@pytest.fixture
def public_host(monkeypatch):
    """Pin the member-facing origin, as production sets it."""
    from app.core import config as config_mod

    monkeypatch.setattr(
        config_mod.settings, "public_app_url", "https://freshcollective.au",
        raising=False,
    )
    return "https://freshcollective.au"


# ---------------------------------------------------------------------------
# The link
# ---------------------------------------------------------------------------

class TestEveryLinkIsAbsolute:
    def test_a_relative_path_becomes_the_member_facing_url(self, public_host):
        assert _absolute(THREAD_PATH) == f"{public_host}{THREAD_PATH}"

    def test_an_absolute_url_is_left_alone(self, public_host):
        assert _absolute("https://example.org/x") == "https://example.org/x"

    def test_it_is_idempotent(self, public_host):
        once = _absolute(THREAD_PATH)
        assert _absolute(once) == once

    def test_none_stays_none(self):
        assert _absolute(None) is None

    def test_the_button_points_at_the_conversation(self, public_host):
        html = notification_email_html(
            title="Message from Ada Leader", message="Hello there.",
            url=THREAD_PATH,
        )
        assert f"{public_host}{THREAD_PATH}" in _hrefs(html)

    def test_the_visible_fallback_shows_the_whole_url(self, public_host):
        """The line under the button, for clients that strip buttons.

        It used to read ``/spaces/…`` — a path a reader cannot use.
        """
        html = notification_email_html(
            title="Message from Ada Leader", message="Hello there.",
            url=THREAD_PATH,
        )
        assert f">{public_host}{THREAD_PATH}<" in re.sub(r"\s+", "", html).replace(
            "</span>", "</span>\n"
        ) or f"{public_host}{THREAD_PATH}" in re.sub(r"<[^>]+>", " ", html)

    def test_no_bare_app_path_survives_anywhere_in_the_email(self, public_host):
        html = notification_email_html(
            title="Message from Ada Leader", message="Hello there.",
            url=THREAD_PATH,
        )
        # Every occurrence of the path must be preceded by the origin.
        for match in re.finditer(re.escape(THREAD_PATH), html):
            start = match.start()
            assert html[start - len(public_host):start] == public_host

    def test_every_link_in_the_email_is_https_in_production(self, public_host):
        html = notification_email_html(
            title="Message from Ada Leader", message="Hello there.",
            url=THREAD_PATH,
        )
        for href in _hrefs(html):
            assert href.startswith("https://") or href.startswith("mailto:"), href


# ---------------------------------------------------------------------------
# The Collective
# ---------------------------------------------------------------------------

class TestItSaysWhichCollective:
    def test_the_heading_names_the_sender_and_the_subheading_the_collective(
        self, public_host,
    ):
        html = notification_email_html(
            title="Message from Lindsey Hilliard",
            message="Hello there.",
            url=THREAD_PATH,
            subheading="Moonlit Circle",
        )
        text = re.sub(r"<[^>]+>", " ", html)
        assert "Message from Lindsey Hilliard" in text
        assert "Moonlit Circle" in text
        # Under the heading, not over it.
        assert html.index("Message from Lindsey Hilliard") < html.index("Moonlit Circle")

    def test_the_collective_is_not_an_eyebrow(self, public_host):
        """Fresh Collective does not put small uppercase labels above
        headings. The Collective belongs under the sender's name."""
        html = notification_email_html(
            title="Message from Lindsey Hilliard", message="Hi.",
            url=THREAD_PATH, subheading="Moonlit Circle",
        )
        heading_at = html.index("Message from Lindsey Hilliard")
        assert "text-transform:uppercase" not in html[:heading_at]

    def test_a_template_without_a_subheading_is_unchanged(self, public_host):
        with_sub = notification_email_html(
            title="T", message="M", url=THREAD_PATH, subheading="Moonlit Circle")
        without = notification_email_html(title="T", message="M", url=THREAD_PATH)
        assert "Moonlit Circle" not in without
        assert len(without) < len(with_sub)

    def test_the_name_is_escaped(self, public_host):
        html = render_email(
            preheader="p", heading="h", body_paragraphs=["b"],
            subheading='Evil <script>alert(1)</script>',
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# What the message notification asks for
# ---------------------------------------------------------------------------

class TestTheDirectMessageNotification:
    def _capture(self, monkeypatch):
        calls: list[dict] = []
        import app.services.notification_service as svc

        monkeypatch.setattr(
            svc, "send_notification", lambda **kw: calls.append(kw), raising=True,
        )
        return calls

    def test_the_subject_carries_sender_and_collective(self, monkeypatch):
        calls = self._capture(monkeypatch)
        from app.messages.routes import _notify_direct_message

        _notify_direct_message(
            recipient_id="u_1", sender_name="Lindsey Hilliard",
            space_id="sp_1", space_name="Moonlit Circle",
            thread_url=THREAD_PATH, preview="Hello.",
        )
        assert len(calls) == 1
        kw = calls[0]
        assert kw["email_subject"] == "New message from Lindsey Hilliard · Moonlit Circle"
        assert kw["email_subheading"] == "Moonlit Circle"
        # The in-app title stays as it was: the member is already inside
        # the Collective when they read it.
        assert kw["title"] == "Message from Lindsey Hilliard"
        assert kw["url"] == THREAD_PATH
        assert kw["pref_key"] == "direct_message_email"

    def test_without_a_collective_name_it_degrades_quietly(self, monkeypatch):
        calls = self._capture(monkeypatch)
        from app.messages.routes import _notify_direct_message

        _notify_direct_message(
            recipient_id="u_1", sender_name="Ada", space_id="sp_1",
            thread_url=THREAD_PATH, preview="Hi.",
        )
        assert calls[0]["email_subject"] == "New message from Ada"
        assert calls[0]["email_subheading"] is None

    def test_both_individual_and_collective_wide_sends_use_this_path(self):
        """Both go through ``_deliver_to_member``, which notifies once.

        An individual send and a Collective-wide send are the same
        function, so the Collective name cannot reach one and miss the
        other.
        """
        from pathlib import Path

        src = Path("app/messages/routes.py").read_text()
        deliver = src[src.index("def _deliver_to_member("):src.index("def _active_member_ids(")]
        assert deliver.count("_notify_direct_message,") == 1
        assert "space_name=space.name," in deliver

    def test_the_member_reply_notification_is_left_alone(self):
        """A member replying to the creator is a different direction and
        out of scope — it still notifies, without a Collective name."""
        from pathlib import Path

        src = Path("app/messages/routes.py").read_text()
        reply = src[src.index("def member_reply("):]
        reply = reply[:reply.index("def ", 10)]
        assert "_notify_direct_message," in reply
        assert "space_name" not in reply
