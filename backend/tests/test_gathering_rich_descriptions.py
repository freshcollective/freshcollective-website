"""Formatted Gathering descriptions: safe stored, plain where needed.

A description now carries the creator's own formatting, written in the
same TipTap editor the Collective About page uses and stored as HTML in
the column it has always used. Two things have to hold.

**Nothing unsafe is stored.** The editor constrains what a creator can
produce, but that is a UX constraint — any direct HTTP call bypasses
it. The authoritative boundary is a field validator on the request
schemas, so create, update and bulk-create are covered by one rule and
a new write path cannot forget it.

**No surface shows markup it cannot render.** A card, a calendar entry
and an email body are all text. The email is the sharpest case:
``render_email_shell`` escapes everything it is handed, so a raw
description would put literal angle brackets in front of a member.

And the quiet requirement underneath both: the descriptions that
already exist are plain text, and they have to keep reading exactly as
they did.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_gathering_rich_descriptions.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import (
    get_creator_user,
    get_current_user,
    get_optional_user,
    get_verified_creator_user,
)
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    Event,
    EventSeries,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.rich_text import (
    ALLOWED_TAGS,
    rich_text_first_line,
    rich_text_to_plain,
    sanitize_rich_text,
)

FORMATTED = (
    "<h2>What to expect</h2>"
    "<p>Join us for an <strong>evening</strong> of <em>quiet</em> company.</p>"
    "<ul><li>Bring a journal</li><li>Tea provided</li></ul>"
    "<ol><li>Arrive</li><li>Settle</li></ol>"
    '<p>Details on <a href="https://freshcollective.au/x">our page</a>.</p>'
)

#: What Kelly's Gatherings actually hold — written before formatting
#: existed. Two paragraphs separated by a blank line, and a soft break.
LEGACY = (
    "Our monthly Women's Circle.\n"
    "Doors open at 6.30pm.\n"
    "\n"
    "Bring something to share — tea & biscuits provided."
)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def creator(make_user):
    return make_user(role="creator")


@pytest.fixture
def space(make_space, creator):
    return make_space(creator=creator)


@pytest.fixture
def client(db, creator):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: creator
    app.dependency_overrides[get_creator_user] = lambda: creator
    app.dependency_overrides[get_verified_creator_user] = lambda: creator
    yield TestClient(app)
    app.dependency_overrides.clear()


def events_url(space) -> str:
    return f"/api/creator/spaces/{space.slug}/events"


def event_url(space, event_id: str) -> str:
    return f"{events_url(space)}/{event_id}"


def _create(client, space, **overrides) -> dict:
    body = {
        "title": "November Women's Circle",
        "starts_at": (datetime.utcnow() + timedelta(days=20)).isoformat(),
        "location_type": "in_person",
        "attendance_format": "in_person",
        "is_published": False,
    }
    body.update(overrides)
    r = client.post(events_url(space), json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ---------------------------------------------------------------------------
# Sanitising
# ---------------------------------------------------------------------------


class TestTheSanitiser:
    def test_the_formatting_creators_are_offered_survives(self):
        out = sanitize_rich_text(FORMATTED)
        for fragment in (
            "<h2>", "<strong>", "<em>", "<ul>", "<ol>", "<li>", "<p>",
            "What to expect", "Bring a journal", "our page",
        ):
            assert fragment in out, fragment

    def test_a_script_tag_and_its_contents_are_removed(self):
        out = sanitize_rich_text(
            "<p>Hello</p><script>fetch('https://evil.test')</script>",
        )
        assert "script" not in out.lower()
        assert "evil.test" not in out
        assert "<p>Hello</p>" in out

    def test_an_event_handler_attribute_is_removed(self):
        out = sanitize_rich_text('<p onclick="steal()">Hello</p>')
        assert "onclick" not in out.lower()
        assert "steal" not in out
        assert "Hello" in out

    @pytest.mark.parametrize("scheme", [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
    ])
    def test_a_dangerous_url_scheme_is_dropped(self, scheme):
        out = sanitize_rich_text(f'<p><a href="{scheme}">click</a></p>')
        assert "javascript" not in out.lower()
        assert "vbscript" not in out.lower()
        assert "base64" not in out.lower()
        assert "etc/passwd" not in out
        # The text stays — the link stops being a link.
        assert "click" in out

    def test_an_https_link_keeps_its_href_and_gains_rel(self):
        out = sanitize_rich_text('<p><a href="https://x.test">x</a></p>')
        assert 'href="https://x.test"' in out
        assert "noopener" in out
        assert "noreferrer" in out

    @pytest.mark.parametrize("pasted", [
        '<iframe src="https://evil.test"></iframe>',
        '<img src=x onerror="alert(1)">',
        "<style>body{display:none}</style>",
        '<object data="x.swf"></object>',
        '<form action="/steal"><input name="pw"></form>',
        "<svg><script>alert(1)</script></svg>",
        '<p style="position:fixed;top:0">covering</p>',
    ])
    def test_pasted_content_is_neutralised(self, pasted):
        out = sanitize_rich_text(f"<p>Before</p>{pasted}<p>After</p>")
        for banned in (
            "iframe", "onerror", "<style", "<object", "<form",
            "<input", "<svg", "<script", "style=",
        ):
            assert banned not in out.lower(), banned
        assert "Before" in out and "After" in out

    def test_it_is_idempotent(self):
        """A description is sanitised on every save, so an edit that
        changes nothing must not erode the content."""
        once = sanitize_rich_text(FORMATTED)
        assert sanitize_rich_text(once) == once

    def test_the_allowlist_has_no_unrenderable_tag(self):
        """Matched against the renderer deliberately: a tag that
        survives sanitising with no renderer vanishes at display time,
        which reads to a creator as lost work."""
        import pathlib

        renderer = (
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "frontend" / "src" / "components" / "ui" / "MarkdownBody.tsx"
        ).read_text()
        for tag in ALLOWED_TAGS:
            assert f"'{tag}'" in renderer or f"<{tag}" in renderer, (
                f"{tag} is allowed through but the renderer never shows it"
            )

    def test_nothing_in_means_nothing_out(self):
        assert sanitize_rich_text(None) is None
        assert sanitize_rich_text("") == ""


class TestLegacyDescriptionsAreUntouched:
    def test_plain_text_passes_through_unchanged(self):
        assert sanitize_rich_text(LEGACY) == LEGACY

    def test_its_line_structure_survives_the_plain_conversion(self):
        out = rich_text_to_plain(LEGACY)
        assert "Our monthly Women's Circle." in out
        assert "Doors open at 6.30pm." in out
        assert out.count("\n") >= 2, out

    def test_an_ampersand_is_not_mangled(self):
        """``&`` is common in a description and is the entity most
        likely to be double-escaped by a round trip."""
        assert "tea & biscuits" in sanitize_rich_text(LEGACY)
        assert "tea & biscuits" in rich_text_to_plain(LEGACY)

    @pytest.mark.parametrize("text", [
        "Curly ’quotes’ and “doubles”",
        "Em — dash, ellipsis…",
        "Accents: café, naïve, Zoë",
        "Emoji: 🌱 🫖",
        "Maths: 3 < 5 > 2",
        "100% & more",
    ])
    def test_special_characters_survive_a_round_trip(self, text):
        stored = sanitize_rich_text(text)
        assert rich_text_to_plain(stored) == text


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


class TestThePlainConversion:
    def test_markup_becomes_text(self):
        out = rich_text_to_plain(FORMATTED)
        assert "<" not in out and ">" not in out
        assert "What to expect" in out
        assert "Join us for an evening of quiet company." in out
        assert "Bring a journal" in out
        assert "our page" in out

    def test_paragraphs_stay_separated(self):
        out = rich_text_to_plain("<p>One</p><p>Two</p>")
        assert out == "One\n\nTwo", repr(out)

    def test_a_soft_break_becomes_a_line_break(self):
        out = rich_text_to_plain("<p>One<br>Two</p>")
        assert "One" in out and "Two" in out
        assert "OneTwo" not in out

    def test_entities_are_resolved(self):
        assert rich_text_to_plain("<p>A &amp; B &lt;ok&gt;</p>") == "A & B <ok>"

    def test_the_limit_cuts_on_a_word_boundary(self):
        out = rich_text_to_plain("<p>" + "alpha " * 40 + "</p>", limit=40)
        assert len(out) <= 41
        assert out.endswith("…")
        assert not out.rstrip("…").endswith("alph")

    def test_a_short_description_is_not_given_an_ellipsis(self):
        assert rich_text_to_plain("<p>Short.</p>", limit=200) == "Short."

    def test_the_first_line_is_the_first_line(self):
        assert rich_text_first_line(FORMATTED) == "What to expect"
        assert rich_text_first_line(LEGACY) == "Our monthly Women's Circle."

    def test_a_markup_only_description_yields_nothing(self):
        assert rich_text_to_plain("<p></p><p>  </p>") == ""

    def test_nothing_in_means_empty_out(self):
        assert rich_text_to_plain(None) == ""
        assert rich_text_to_plain("") == ""


# ---------------------------------------------------------------------------
# The write paths
# ---------------------------------------------------------------------------


class TestEveryWritePathSanitises:
    def test_creating_a_gathering(self, client, db, space):
        body = _create(
            client, space,
            description=f"<p>Hi</p><script>alert(1)</script>",
        )
        assert "script" not in (body["description"] or "").lower()
        assert "<p>Hi</p>" in body["description"]

    def test_updating_a_gathering(self, client, db, space, make_event):
        event = make_event(space=space, is_published=True)
        db.commit()
        r = client.patch(event_url(space, event.id), json={
            "description": '<p>Hi</p><a href="javascript:alert(1)">x</a>',
        })
        assert r.status_code == 200, r.text
        db.expire_all()
        stored = db.get(Event, event.id).description
        assert "javascript" not in stored.lower()
        assert "Hi" in stored

    def test_bulk_creating_gatherings(self, client, db, space):
        r = client.post(f"{events_url(space)}/bulk", json={
            "title": "Weekly Circle",
            "starts_at": (datetime.utcnow() + timedelta(days=3)).isoformat(),
            "location_type": "in_person",
            "description": "<p>Hi</p><iframe src='https://evil.test'></iframe>",
            "recurrence": {
                "pattern": "weekly", "days_of_week": [0], "end_after_n": 2,
            },
        })
        assert r.status_code == 201, r.text
        rows = db.query(Event).filter(
            Event.space_id == space.id, Event.title == "Weekly Circle",
        ).all()
        assert rows
        for row in rows:
            assert "iframe" not in (row.description or "").lower()
            assert "evil.test" not in (row.description or "")

    def test_creating_a_series(self, client, db, space):
        r = client.post(
            f"/api/creator/spaces/{space.slug}/gathering-series",
            json={
                "title": "Autumn Term",
                "starts_at": (datetime.utcnow() + timedelta(days=7)).isoformat(),
                "description": "<p>Six weeks</p><script>x()</script>",
            },
        )
        assert r.status_code in (200, 201), r.text
        row = db.query(EventSeries).filter(
            EventSeries.space_id == space.id).order_by(
            EventSeries.created_at.desc()).first()
        assert "script" not in (row.description or "").lower()
        assert "Six weeks" in row.description

    def test_updating_a_series(self, client, db, space):
        r = client.post(
            f"/api/creator/spaces/{space.slug}/gathering-series",
            json={
                "title": "Autumn Term",
                "starts_at": (datetime.utcnow() + timedelta(days=7)).isoformat(),
                "description": "<p>Plain</p>",
            },
        )
        assert r.status_code in (200, 201), r.text
        slug = r.json()["slug"]
        r2 = client.patch(
            f"/api/creator/spaces/{space.slug}/gathering-series/{slug}",
            json={"description": '<p>New</p><img src=x onerror="alert(1)">'},
        )
        assert r2.status_code == 200, r2.text
        db.expire_all()
        row = db.query(EventSeries).filter(EventSeries.slug == slug).one()
        assert "onerror" not in (row.description or "").lower()
        assert "New" in row.description

    def test_the_validator_is_on_every_description_request_schema(self):
        """Declared at the schema rather than in each handler, so a
        write path added later is covered without being remembered."""
        from app.creator.schemas import (
            EventCreateRequest,
            EventUpdateRequest,
            GatheringSeriesCreateRequest,
            GatheringSeriesUpdateRequest,
        )

        payloads = {
            EventCreateRequest: {
                "title": "x", "starts_at": datetime.utcnow(),
            },
            EventUpdateRequest: {},
            GatheringSeriesCreateRequest: {
                "title": "x", "starts_at": datetime.utcnow(),
            },
            GatheringSeriesUpdateRequest: {},
        }
        for schema, required in payloads.items():
            built = schema.model_validate({
                **required,
                "description": "<script>x()</script><p>ok</p>",
            })
            assert "script" not in (built.description or "").lower(), schema
            assert "ok" in (built.description or ""), schema


class TestTheRoundTrip:
    def test_save_reload_edit_reload(self, client, db, space):
        """The creator sequence: write formatted content, come back,
        change it, come back again."""
        created = _create(client, space, description=FORMATTED)
        url = event_url(space, created["id"])

        first = client.get(url).json()["description"]
        assert "<h2>What to expect</h2>" in first
        assert "<ol>" in first

        edited = first.replace("What to expect", "What to bring")
        r = client.patch(url, json={"description": edited})
        assert r.status_code == 200, r.text
        again = client.get(url).json()["description"]
        assert "<h2>What to bring</h2>" in again
        assert "<ol>" in again

    def test_publishing_does_not_alter_it(self, client, db, space):
        created = _create(client, space, description=FORMATTED)
        url = event_url(space, created["id"])
        r = client.patch(url, json={"is_published": True})
        assert r.status_code == 200, r.text
        assert "<strong>evening</strong>" in client.get(url).json()["description"]

    def test_an_empty_description_stays_empty(self, client, db, space):
        created = _create(client, space, description=None)
        assert created["description"] is None
        url = event_url(space, created["id"])
        client.patch(url, json={"description": ""})
        assert (client.get(url).json()["description"] or "") == ""

    def test_a_long_description_survives(self, client, db, space):
        long_html = "".join(f"<p>Paragraph {i} with words.</p>" for i in range(200))
        created = _create(client, space, description=long_html)
        stored = client.get(event_url(space, created["id"])).json()["description"]
        assert stored.count("<p>") == 200

    def test_a_legacy_description_opens_unchanged(
        self, client, db, space, make_event,
    ):
        """What a creator sees when they open one of the Gatherings
        that already exist. The editor converts on load; the stored
        value is not rewritten by being looked at."""
        event = make_event(space=space, is_published=True, description=LEGACY)
        db.commit()
        assert client.get(event_url(space, event.id)).json()["description"] == LEGACY
        db.expire_all()
        assert db.get(Event, event.id).description == LEGACY


# ---------------------------------------------------------------------------
# The surfaces that cannot show markup
# ---------------------------------------------------------------------------


class TestTheAnnouncementEmail:
    def test_the_payload_carries_text_not_markup(
        self, db, space, creator, make_event,
    ):
        from app.services import publication_announcement as pub

        event = make_event(
            space=space, is_published=True, description=FORMATTED,
            notify_members=True,
        )
        db.flush()
        emitted = pub.announce_gathering_if_newly_published(
            db, event, actor_user_id=creator.id,
        )
        assert emitted is not None
        description = emitted.payload["description"]
        assert "<" not in description and ">" not in description
        assert "Join us for an evening of quiet company." in description

    def test_the_rendered_email_shows_no_tags(self, db, space):
        """The sharpest case. ``render_email_shell`` escapes everything
        it is handed, so a raw description would reach a member as
        literal angle brackets rather than as bold text."""
        import app.comms.templates  # noqa: F401
        from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
        from app.comms.routing.resolver import ResolvedRecipient
        from app.comms.templates.registry import get_template_for
        from app.services.rich_text import rich_text_to_plain

        template = get_template_for(
            "gathering.published", CHANNEL_EMAIL_TRANSACTIONAL,
        )
        rendered = template.render(None, None, ResolvedRecipient(
            user_id="u_1", role_in_event="member_of_collective",
            human_reason="x",
            template_context={
                "collective_name": "Moonlit Circle",
                "gathering_title": "November Circle",
                "gathering_id": "e_1",
                "gathering_url": "/spaces/x/events/e_1",
                "description": rich_text_to_plain(FORMATTED, limit=280),
                "space_id": "sp_1",
            },
        ))
        whole = f"{rendered.body_html} {rendered.body_text}"
        for leak in ("&lt;strong&gt;", "&lt;h2&gt;", "<strong>evening", "&lt;p&gt;"):
            assert leak not in whole, leak
        assert "Join us for an evening" in whole

    def test_a_legacy_description_still_reads_normally(self, db, space, creator,
                                                      make_event):
        from app.services import publication_announcement as pub

        event = make_event(
            space=space, is_published=True, description=LEGACY,
            notify_members=True,
        )
        db.flush()
        emitted = pub.announce_gathering_if_newly_published(
            db, event, actor_user_id=creator.id,
        )
        assert "Our monthly Women's Circle." in emitted.payload["description"]


class TestTheCalendarFile:
    @staticmethod
    def _ics(db, space, event, viewer=None):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: viewer
        try:
            r = TestClient(app).get(
                f"/api/spaces/{space.slug}/events/{event.id}/calendar.ics")
            assert r.status_code == 200, r.text
            return r.text
        finally:
            app.dependency_overrides.clear()

    def test_the_description_field_is_plain_text(
        self, db, make_space, make_event, make_user,
    ):
        space = make_space(
            is_public=True, area_policies={"areas": {"gatherings": "public"}},
        )
        event = make_event(
            space=space, is_published=True, is_public=True,
            description=FORMATTED,
        )
        db.flush()
        body = self._ics(db, space, event)
        line = [ln for ln in body.split("\r\n") if ln.startswith("DESCRIPTION:")]
        assert line, body
        assert "<" not in line[0] and ">" not in line[0]
        assert "Join us for an evening" in line[0]

    def test_line_breaks_are_escaped_the_way_icalendar_wants(
        self, db, make_space, make_event,
    ):
        space = make_space(
            is_public=True, area_policies={"areas": {"gatherings": "public"}},
        )
        event = make_event(
            space=space, is_published=True, is_public=True,
            description="<p>One</p><p>Two</p>",
        )
        db.flush()
        line = [
            ln for ln in self._ics(db, space, event).split("\r\n")
            if ln.startswith("DESCRIPTION:")
        ][0]
        assert "\\n" in line
        assert line.startswith("DESCRIPTION:One")


class TestVisibilityIsUnchanged:
    def test_a_draft_gatherings_description_is_not_public(
        self, db, make_space, make_event, make_user,
    ):
        space = make_space(
            is_public=True, area_policies={"areas": {"gatherings": "public"}},
        )
        event = make_event(
            space=space, is_published=False, is_public=True,
            description=FORMATTED,
        )
        db.flush()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: None
        try:
            client = TestClient(app)
            rows = client.get(f"/api/spaces/{space.slug}/events").json()
            assert "Join us" not in str(rows)
            detail = client.get(f"/api/spaces/{space.slug}/events/{event.id}")
            assert detail.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_a_member_may_not_edit_a_description(
        self, db, space, make_event, make_user,
    ):
        event = make_event(space=space, is_published=True, description=LEGACY)
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: member
        app.dependency_overrides[get_verified_creator_user] = lambda: member
        try:
            r = TestClient(app).patch(
                event_url(space, event.id), json={"description": "<p>Mine</p>"},
            )
            assert r.status_code in (403, 404), r.status_code
            db.expire_all()
            assert db.get(Event, event.id).description == LEGACY
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Duplication
# ---------------------------------------------------------------------------


class TestDuplicationCarriesTheFormatting:
    def test_the_formatted_description_is_copied(
        self, client, db, space, make_event,
    ):
        original = make_event(
            space=space, is_published=True, description=FORMATTED,
        )
        db.commit()
        created = client.post(
            f"{event_url(space, original.id)}/duplicate").json()
        assert created["description"] == FORMATTED
        for fragment in ("<h2>", "<strong>", "<ul>", "<ol>", "<a href="):
            assert fragment in created["description"], fragment

    def test_the_duplicate_is_edited_independently(
        self, client, db, space, make_event,
    ):
        original = make_event(
            space=space, is_published=True, description=FORMATTED,
        )
        db.commit()
        created = client.post(
            f"{event_url(space, original.id)}/duplicate").json()
        client.patch(event_url(space, created["id"]),
                     json={"description": "<p>Rewritten.</p>"})
        db.expire_all()
        assert db.get(Event, created["id"]).description == "<p>Rewritten.</p>"
        assert db.get(Event, original.id).description == FORMATTED

    def test_a_legacy_description_is_copied_as_it_is(
        self, client, db, space, make_event,
    ):
        original = make_event(
            space=space, is_published=True, description=LEGACY,
        )
        db.commit()
        created = client.post(
            f"{event_url(space, original.id)}/duplicate").json()
        assert created["description"] == LEGACY
