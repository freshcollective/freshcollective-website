"""The announcement emails carry a link somebody can press.

What went wrong
---------------
A member received the Pathway publication email and found no button,
and a fallback line reading

    or copy this link:
    /spaces/moonlit-circle/pathways/daring-heart

One root cause for both. The resolver builds a *path*, deliberately —
it stays free of origin concerns — and the Gathering and Series
templates join that path to the member-facing origin before handing it
to the shell. The Pathway template skipped that step and passed the
path straight through, so the anchor's ``href`` was root-relative. An
email has no base URL, so a mail client has nothing to resolve it
against: the anchor is dropped, its inline styles go with it, and the
pill button disappears. The same value printed under "or copy this
link" is where the bare path came from.

Why these tests look at rendered output
---------------------------------------
The existing coverage asserted the path appeared *somewhere* in the
HTML. An absolute URL contains the path as a substring, so that
assertion passed either way and the defect shipped. These tests parse
the anchor and the fallback out of the finished HTML, compare them to
each other, and require both to be absolute — the shape a reader
actually receives.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_publication_email_cta.py
"""

from __future__ import annotations

import pathlib
import re

import pytest

import app.comms.templates  # noqa: F401 — registers every template
from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.templates.registry import get_template_for, registered_templates
from app.core.config import settings

PUBLIC = "https://freshcollective.au"
FRONTEND = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend"
APP = FRONTEND / "src" / "app"

COLLECTIVE_SLUG = "moonlit-circle"
PATHWAY_SLUG = "daring-heart"
PATHWAY_PATH = f"/spaces/{COLLECTIVE_SLUG}/pathways/{PATHWAY_SLUG}"


@pytest.fixture
def production_like(monkeypatch):
    """The public domain for links, as production resolves it."""
    monkeypatch.setattr(settings, "public_app_url", PUBLIC, raising=False)
    return settings


def _recipient(**ctx) -> ResolvedRecipient:
    return ResolvedRecipient(
        user_id="u_1",
        role_in_event="member_of_collective",
        human_reason="You're a member of Moonlit Circle.",
        template_context=ctx,
    )


# The CTA pill, as the shell writes it: an anchor carrying the
# background gradient. Matched on the gradient rather than on position
# so the footer's preferences link cannot be mistaken for the button.
_CTA_RE = re.compile(
    r'<a href="([^"]*)"\s+style="[^"]*linear-gradient[^"]*">\s*([^<]+?)\s*</a>',
    re.S,
)
# The "or copy this link" line underneath it.
_FALLBACK_RE = re.compile(
    r"or copy this link:<br />\s*<span[^>]*>([^<]*)</span>", re.S,
)


def cta(html: str) -> tuple[str, str] | None:
    """``(href, label)`` of the button, or ``None`` if there isn't one."""
    match = _CTA_RE.search(html)
    return (match.group(1), match.group(2).strip()) if match else None


def fallback(html: str) -> str | None:
    match = _FALLBACK_RE.search(html)
    return match.group(1).strip() if match else None


def pathway_email(**overrides):
    ctx = {
        "collective_name": "Moonlit Circle",
        "pathway_title": "Daring Heart",
        "pathway_id": "pw_1",
        "space_id": "sp_1",
        "pathway_url": PATHWAY_PATH,
    }
    ctx.update(overrides)
    template = get_template_for("pathway.published", CHANNEL_EMAIL_TRANSACTIONAL)
    return template.render(None, None, _recipient(**ctx))


# ---------------------------------------------------------------------------
# 1 — a published Pathway produces the expected email template
# ---------------------------------------------------------------------------


class TestTheRegisteredTemplate:
    def test_pathway_published_has_an_email_template(self):
        template = get_template_for(
            "pathway.published", CHANNEL_EMAIL_TRANSACTIONAL,
        )
        assert template is not None
        assert template.key == "pathway.published.email_transactional"

    def test_the_button_label_is_editable_copy(self):
        """Declared as a slot, so the label is admin-editable like the
        Gathering and Series labels beside it — and so this test
        describes where the wording lives."""
        from app.comms.templates.editable import get_declaration

        decl = get_declaration("pathway.published.email_transactional")
        slot = decl.slot("cta_label")
        assert slot is not None, "no cta_label slot"
        assert slot.default == "Explore Pathway"

    def test_the_link_is_declared_as_generated(self):
        """An admin can rewrite the voice, never the destination. The
        reason a stored override cannot reintroduce the old link."""
        from app.comms.templates.editable import get_declaration

        decl = get_declaration("pathway.published.email_transactional")
        slot_ids = {s.slot_id for s in decl.slots}
        assert not any("url" in s or "link" in s for s in slot_ids), slot_ids
        field_keys = {f.source_key for f in decl.merge_fields}
        assert "pathway_url" not in field_keys, (
            "the destination became an admin-reachable merge field"
        )


# ---------------------------------------------------------------------------
# 2-6 — the button, the fallback, and that they agree
# ---------------------------------------------------------------------------


class TestThePathwayEmailCta:
    def test_there_is_a_button(self, production_like):
        assert cta(pathway_email().body_html) is not None, (
            "no CTA in the rendered email"
        )

    def test_it_says_explore_pathway(self, production_like):
        _href, label = cta(pathway_email().body_html)
        assert label == "Explore Pathway", label

    def test_its_url_is_absolute(self, production_like):
        href, _label = cta(pathway_email().body_html)
        assert href == f"{PUBLIC}{PATHWAY_PATH}", href
        assert href.startswith("https://"), href

    def test_the_fallback_is_the_complete_url(self, production_like):
        """The line a reader copies when the button will not open."""
        shown = fallback(pathway_email().body_html)
        assert shown == f"{PUBLIC}{PATHWAY_PATH}", shown

    def test_the_button_and_the_fallback_agree(self, production_like):
        html = pathway_email().body_html
        href, _label = cta(html)
        assert href == fallback(html)

    def test_the_url_carries_both_slugs(self, production_like):
        href, _label = cta(pathway_email().body_html)
        assert f"/spaces/{COLLECTIVE_SLUG}/" in href
        assert href.endswith(f"/pathways/{PATHWAY_SLUG}")

    def test_the_plain_text_body_carries_the_same_url(self, production_like):
        """A text-only client gets the link too, and the same one."""
        rendered = pathway_email()
        href, label = cta(rendered.body_html)
        assert href in rendered.body_text
        assert label in rendered.body_text
        assert PATHWAY_PATH not in rendered.body_text.replace(href, ""), (
            "a bare path survives alongside the absolute URL"
        )

    def test_it_uses_the_canonical_domain(self, production_like):
        rendered = pathway_email()
        whole = f"{rendered.body_html} {rendered.body_text}"
        assert "freshcollective.com.au" not in whole, (
            "the retired .com.au domain"
        )
        assert "onrender.com" not in whole
        assert "localhost" not in whole


# ---------------------------------------------------------------------------
# 7 — the destination is a page that exists
# ---------------------------------------------------------------------------


class TestTheDestinationExists:
    def test_the_pathway_route_is_on_disk(self, production_like):
        """Asserted against the frontend tree, because a correct-looking
        URL to a renamed route is still a 404. This check is what caught
        ``[pathway-slug]`` being hyphenated where the sibling routes are
        camelCase."""
        href, _label = cta(pathway_email().body_html)
        assert href.startswith(PUBLIC)
        path = href[len(PUBLIC):]
        segments = path.strip("/").split("/")
        assert segments[0] == "spaces" and segments[2] == "pathways", path

        route = APP / "spaces" / "[slug]" / "pathways" / "[pathway-slug]"
        assert (route / "page.tsx").exists(), f"no Next route — {route}"

    def test_the_signed_out_journey_is_still_in_place(self):
        """Email → button → login → the Pathway. The redirect lives in
        the Collective layout; this fails if it is removed, so the fix
        above cannot be declared working on a route that bounces."""
        layout = (APP / "spaces" / "[slug]" / "layout.tsx").read_text()
        assert "loginReturnFor" in layout, (
            "the signed-out return-to-destination redirect is gone"
        )


# ---------------------------------------------------------------------------
# 8 — missing or malformed data never yields an unusable button
# ---------------------------------------------------------------------------


class TestABadUrlProducesNoButton:
    @pytest.mark.parametrize(
        "value", [None, "", "   ", "not-a-path", "spaces/x/pathways/y",
                  "javascript:alert(1)", "//evil.example/steal"],
    )
    def test_no_cta_at_all(self, production_like, value):
        """Rather than a button that goes nowhere. A dead CTA is worse
        than none: the reader presses it, nothing happens, and the
        fallback underneath offers the same unusable string."""
        html = pathway_email(pathway_url=value).body_html
        assert cta(html) is None, f"a CTA rendered for {value!r}"
        assert fallback(html) is None, f"a fallback rendered for {value!r}"

    def test_the_email_still_sends(self, production_like):
        """Losing the button must not lose the announcement."""
        rendered = pathway_email(pathway_url=None)
        assert rendered.subject
        assert "Daring Heart" in rendered.subject
        assert rendered.body_html and rendered.body_text

    def test_a_protocol_relative_url_is_never_reflected(self, production_like):
        """``//host`` is read as an origin by some parsers, so it must
        not reach an ``href`` and must not be joined onto ours either."""
        html = pathway_email(pathway_url="//evil.example/steal").body_html
        assert "evil.example" not in html

    def test_the_suppression_is_logged(self, production_like, monkeypatch):
        """A vanishing CTA has to be discoverable. This one was found by
        a member noticing, which is the signal this replaces.

        Asserted by replacing the logger rather than with ``caplog``:
        alembic's ``fileConfig`` disables every ``app.*`` logger under
        pytest, so a ``caplog`` assertion here passes alone and fails
        in the full suite — or worse, passes vacuously."""
        from app.comms.templates import base

        warnings: list[tuple] = []

        class Recorder:
            def warning(self, message, *args):
                warnings.append((message, args))

        monkeypatch.setattr(base, "logger", Recorder())
        pathway_email(pathway_url="not-a-path")

        assert warnings, "a CTA disappeared with no log line"
        message, args = warnings[0]
        assert "suppressing a CTA" in message
        assert "not-a-path" in args, args


# ---------------------------------------------------------------------------
# 9 — the working Gathering and Series emails are unchanged
# ---------------------------------------------------------------------------


class TestTheGatheringAndSeriesEmailsAreUnaffected:
    def _gathering(self, **overrides):
        ctx = {
            "collective_name": "Moonlit Circle",
            "gathering_title": "November Circle",
            "gathering_id": "e_1",
            "gathering_when": "Saturday 8 November, 10:00am",
            "location_type": "online",
            "gathering_url": f"/spaces/{COLLECTIVE_SLUG}/events/e_1",
            "space_id": "sp_1",
        }
        ctx.update(overrides)
        template = get_template_for(
            "gathering.published", CHANNEL_EMAIL_TRANSACTIONAL,
        )
        return template.render(None, None, _recipient(**ctx))

    def _series(self, **overrides):
        ctx = {
            "collective_name": "Moonlit Circle",
            "series_title": "Autumn Term",
            "series_id": "es_1",
            "session_count": 6,
            "series_url": f"/spaces/{COLLECTIVE_SLUG}/gathering-series/autumn",
            "space_id": "sp_1",
        }
        ctx.update(overrides)
        template = get_template_for(
            "series.published", CHANNEL_EMAIL_TRANSACTIONAL,
        )
        return template.render(None, None, _recipient(**ctx))

    def test_the_gathering_button_is_unchanged(self, production_like):
        href, label = cta(self._gathering().body_html)
        assert href == f"{PUBLIC}/spaces/{COLLECTIVE_SLUG}/events/e_1"
        assert label == "Book Your Place"

    def test_a_ticketed_gathering_still_says_view_gathering(
        self, production_like,
    ):
        _href, label = cta(self._gathering(is_paid=True).body_html)
        assert label == "View Gathering"

    def test_the_series_button_is_unchanged(self, production_like):
        href, label = cta(self._series().body_html)
        assert href == (
            f"{PUBLIC}/spaces/{COLLECTIVE_SLUG}/gathering-series/autumn"
        )
        assert label

    def test_both_fallbacks_still_match_their_buttons(self, production_like):
        for rendered in (self._gathering(), self._series()):
            html = rendered.body_html
            href, _label = cta(html)
            assert href == fallback(html)

    def test_an_already_absolute_url_is_not_double_joined(
        self, production_like,
    ):
        """The admin preview supplies built links. Passing one through
        ``public_app_url`` would raise, so it is passed through."""
        built = f"{PUBLIC}/spaces/{COLLECTIVE_SLUG}/events/e_1"
        href, _label = cta(self._gathering(gathering_url=built).body_html)
        assert href == built


# ---------------------------------------------------------------------------
# The renderer invariant — does this affect any other template?
# ---------------------------------------------------------------------------


class TestNoEmailTemplateCanEmitARelativeLink:
    """The question the brief asks about the shared renderer.

    The existing sweep in ``test_public_app_url.py`` feeds every
    URL-ish context key an *absolute* value, so a template that fails
    to absolutise a path could not fail it — which is how this defect
    reached an inbox. This sweep feeds paths instead.
    """

    PATHS = {
        "reset_url": "/reset-password?token=abc",
        "verify_url": "/verify?token=abc",
        "next_url": "/dashboard",
        "view_url": f"/spaces/{COLLECTIVE_SLUG}/community/p_1",
        "cta_url": "/dashboard",
        "collective_url": f"/spaces/{COLLECTIVE_SLUG}",
        "billing_url": "/creator/billing",
        "gathering_url": f"/spaces/{COLLECTIVE_SLUG}/events/e_1",
        "pathway_url": PATHWAY_PATH,
        "series_url": f"/spaces/{COLLECTIVE_SLUG}/gathering-series/autumn",
        "member_url": f"/spaces/{COLLECTIVE_SLUG}",
        "repair_url": "/settings/billing",
        "retry_url": "/settings/billing",
        "accept_url": "/invitations/abc",
        "url": "/dashboard",
        "link": "/dashboard",
    }
    FILLER = {
        "first_name": "Sam", "name": "Sam", "sender_name": "Sam",
        "inviter_name": "Sam", "commenter_name": "Sam",
        "post_title": "A post", "title": "A thing", "excerpt": "Some words",
        "space_name": "Moonlit Circle", "collective_name": "Moonlit Circle",
        "pathway_title": "Daring Heart", "pathway_name": "Daring Heart",
        "event_title": "November Circle", "gathering_title": "November Circle",
        "series_title": "Autumn Term", "session_count": 6,
        "amount_display": "$10.00", "payment_mode": "once",
    }

    def _render_each(self, production_like):
        context = {**self.PATHS, **self.FILLER}
        out = []
        for event_type, channel in registered_templates():
            if channel != CHANNEL_EMAIL_TRANSACTIONAL:
                continue
            template = get_template_for(event_type, channel)
            try:
                rendered = template.render(
                    None, None, _recipient(**context),
                )
            except Exception:  # needs a DB or a real event
                continue
            out.append((event_type, rendered))
        assert len(out) >= 5, f"only {len(out)} templates rendered standalone"
        return out

    def test_no_button_carries_a_root_relative_href(self, production_like):
        for event_type, rendered in self._render_each(production_like):
            found = cta(rendered.body_html)
            if found is None:
                continue
            href, _label = found
            assert href.startswith(("http://", "https://")), (
                f"{event_type} rendered a CTA a mail client cannot "
                f"resolve: {href!r}"
            )

    def test_no_fallback_line_shows_a_bare_path(self, production_like):
        for event_type, rendered in self._render_each(production_like):
            shown = fallback(rendered.body_html)
            if shown is None:
                continue
            assert shown.startswith(("http://", "https://")), (
                f"{event_type} printed a bare path under 'or copy this "
                f"link': {shown!r}"
            )

    def test_every_href_in_every_email_is_absolute(self, production_like):
        """Not only the CTA — the footer links too."""
        for event_type, rendered in self._render_each(production_like):
            for href in re.findall(r'<a href="([^"]*)"', rendered.body_html):
                assert href.startswith(("http://", "https://", "mailto:")), (
                    f"{event_type} has a non-absolute href: {href!r}"
                )


class TestTheHelperItself:
    def test_a_path_is_joined_to_the_public_origin(self, production_like):
        from app.comms.templates.base import absolute_email_url

        assert absolute_email_url("/a/b") == f"{PUBLIC}/a/b"

    def test_an_absolute_url_passes_through(self, production_like):
        from app.comms.templates.base import absolute_email_url

        for built in (f"{PUBLIC}/a", "http://localhost:3000/a"):
            assert absolute_email_url(built) == built

    def test_nothing_in_yields_nothing_out(self, production_like):
        from app.comms.templates.base import absolute_email_url

        for empty in (None, "", "   "):
            assert absolute_email_url(empty) == ""

    def test_a_protocol_relative_value_is_not_given_our_origin(
        self, production_like,
    ):
        from app.comms.templates.base import absolute_email_url

        assert absolute_email_url("//evil.example") == "//evil.example"
        assert PUBLIC not in absolute_email_url("//evil.example")


# ---------------------------------------------------------------------------
# 10 — routing, preferences and dedupe are untouched
# ---------------------------------------------------------------------------


class TestNothingElseAboutTheAnnouncementChanged:
    def test_the_event_definition_is_unchanged(self):
        from app.comms.registry import get_event_definition

        definition = get_event_definition("pathway.published")
        assert definition is not None
        assert definition.topic == "pathways"
        assert definition.default_priority == "immediate"

    def test_the_dedupe_key_is_unchanged(self):
        """One announcement per Pathway, still keyed the same way — a
        changed key would re-announce everything already published."""
        from app.services.pathway_announcement import announcement_dedupe_key

        assert announcement_dedupe_key("pw_1", "sp_1") == "pw_1:sp_1"

    def test_the_topic_is_still_live(self):
        from app.core.config import settings as live

        assert "pathways" in live.comms_live_topics

    def test_the_in_app_notification_still_gets_a_path(self):
        """In-app navigation is relative by design, so the in-app
        template must keep the path — the absolutising belongs to the
        email channel only."""
        from app.comms.categories import CHANNEL_IN_APP

        template = get_template_for("pathway.published", CHANNEL_IN_APP)
        rendered = template.render(
            None, None, _recipient(
                collective_name="Moonlit Circle",
                pathway_title="Daring Heart",
                pathway_url=PATHWAY_PATH,
            ),
        )
        assert rendered.metadata["url"] == PATHWAY_PATH
