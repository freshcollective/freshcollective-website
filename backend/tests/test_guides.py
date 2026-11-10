"""Guides — the public article section and its admin.

What these lock, and why each one is here rather than taken on trust:

**Admin-only, proved through the dependency.** Every admin route is
exercised over HTTP with ``get_current_user`` overridden to an
ordinary member, so ``get_admin_user`` actually runs. Calling the
route functions directly would bypass ``Depends`` entirely and the
authorisation tests would pass against a router with no guard at all.

**A draft is invisible.** Not merely absent from the list — the
public detail route answers 404, identically to a slug that was never
used, so an anonymous caller cannot learn that an unpublished Guide
exists.

**Saving never publishes.** Asserted at the schema level, because the
guarantee is structural: ``GuideUpdate`` has no ``status`` field, so
there is no payload that could flip a draft live.

**One featured Guide.** Enforced by a partial unique index, and the
test drives the API rather than the index so it proves the admin
never has to unfeature anything by hand.

**The sanitiser is the boundary.** Script tags, event handlers,
``javascript:`` hrefs and images the CSP would refuse are all stripped
on the way in, and the allowed vocabulary survives untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_admin_user, get_current_user, get_optional_user
from app.core.database import get_db
from app.core.storage import UPLOAD_DIR
from app.main import app
from app.models.guide import Guide, GuideSettings

BASE = "/api/admin/guides"
PUBLIC = "/api/public/guides"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin(make_user):
    return make_user(role="admin", email_verified_at=datetime.utcnow())


@pytest.fixture
def member(make_user):
    return make_user(role="user", email_verified_at=datetime.utcnow())


@pytest.fixture
def client(db, admin):
    """An administrator."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def member_client(db, member):
    """An ordinary signed-in member.

    ``get_admin_user`` is deliberately NOT overridden — it runs for
    real against this user, which is the only way the 403 means
    anything.
    """
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: member
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def public_client(db):
    """Nobody. No auth override of any kind."""
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _slug() -> str:
    return f"guide-{uuid.uuid4().hex[:8]}"


def _create(client, **overrides) -> dict:
    payload = {
        "title": overrides.pop("title", "Moving your community"),
        "slug": overrides.pop("slug", _slug()),
        "category": overrides.pop("category", "starting"),
    }
    res = client.post(BASE, json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _fill(client, guide_id: str, **fields) -> dict:
    body = {
        "standfirst": "One calm place you control.",
        "body": "<p>Something worth reading.</p>",
    }
    body.update(fields)
    res = client.patch(f"{BASE}/{guide_id}", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _publish(client, guide_id: str) -> dict:
    res = client.post(f"{BASE}/{guide_id}/publish")
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# 1 · Admin-only
# ---------------------------------------------------------------------------


class TestAdminOnly:
    """Every admin route refuses an ordinary member."""

    def test_every_admin_route_refuses_a_member(self, member_client, db, admin):
        # One real Guide to aim the per-id routes at, so a 403 is a
        # refusal rather than a 404 that would pass for the wrong reason.
        guide = Guide(
            id=str(uuid.uuid4()), slug=_slug(), title="T",
            standfirst="S", body="<p>B</p>", category="starting",
            status="draft", reading_time_minutes=1,
        )
        db.add(guide)
        db.flush()

        calls = [
            ("get", BASE, None),
            ("post", BASE, {"title": "T", "slug": _slug(), "category": "tools"}),
            ("get", f"{BASE}/settings", None),
            ("put", f"{BASE}/settings", {"starter_kit_url": None}),
            ("get", f"{BASE}/{guide.id}", None),
            ("patch", f"{BASE}/{guide.id}", {"title": "Changed"}),
            ("post", f"{BASE}/{guide.id}/publish", None),
            ("post", f"{BASE}/{guide.id}/unpublish", None),
            ("post", f"{BASE}/{guide.id}/feature", {"featured": True}),
            ("delete", f"{BASE}/{guide.id}", None),
        ]
        for method, path, payload in calls:
            res = getattr(member_client, method)(
                path, **({"json": payload} if payload is not None else {}),
            )
            assert res.status_code == 403, f"{method.upper()} {path} → {res.status_code}"

        # And nothing was changed by any of them.
        db.refresh(guide)
        assert guide.title == "T"
        assert guide.status == "draft"

    def test_an_administrator_is_allowed_through(self, client):
        """The control. Without it, a router that 403'd everyone would
        pass every assertion above."""
        assert client.get(BASE).status_code == 200


# ---------------------------------------------------------------------------
# 2 · Drafts are invisible to the public
# ---------------------------------------------------------------------------


class TestDraftsArePrivate:
    def test_a_draft_is_absent_from_the_public_list(self, client, public_client):
        draft = _create(client)
        _fill(client, draft["id"])
        slugs = [g["slug"] for g in public_client.get(PUBLIC).json()["guides"]]
        assert draft["slug"] not in slugs

    def test_a_draft_answers_404_like_a_slug_that_never_existed(
        self, client, public_client,
    ):
        draft = _create(client)
        _fill(client, draft["id"])
        drafted = public_client.get(f"{PUBLIC}/{draft['slug']}")
        never = public_client.get(f"{PUBLIC}/no-such-guide-at-all")
        assert drafted.status_code == 404
        assert never.status_code == 404
        # Identical, so the response cannot be read as "this exists".
        assert drafted.json() == never.json()

    def test_publishing_makes_it_visible_and_unpublishing_hides_it_again(
        self, client, public_client,
    ):
        guide = _create(client)
        _fill(client, guide["id"])
        _publish(client, guide["id"])
        assert public_client.get(f"{PUBLIC}/{guide['slug']}").status_code == 200

        assert client.post(f"{BASE}/{guide['id']}/unpublish").status_code == 200
        assert public_client.get(f"{PUBLIC}/{guide['slug']}").status_code == 404

    def test_unpublishing_takes_effect_on_the_very_next_request(
        self, client, public_client,
    ):
        """The guarantee behind the pages being uncached.

        A Guide is published, read by the public route, then
        unpublished. The *next* request must 404 — not the one after
        a cache window, and not conditionally on a cache
        invalidation having succeeded. The frontend holds up its end
        by fetching ``no-store`` (pinned in ``guides.test.ts``); this
        is the API's end of it, with no sleep and no second chance.
        """
        guide = _create(client)
        _fill(client, guide["id"])
        _publish(client, guide["id"])
        assert public_client.get(f"{PUBLIC}/{guide['slug']}").status_code == 200

        client.post(f"{BASE}/{guide['id']}/unpublish")

        gone = public_client.get(f"{PUBLIC}/{guide['slug']}")
        assert gone.status_code == 404
        # And indistinguishable from a slug that never existed, so the
        # 404 does not confirm the Guide is merely hidden.
        assert gone.json() == public_client.get(
            f"{PUBLIC}/never-existed-at-all",
        ).json()
        # Gone from the list and the sitemap in the same instant.
        slugs = [g["slug"] for g in public_client.get(PUBLIC).json()["guides"]]
        assert guide["slug"] not in slugs
        sitemap = [r["slug"] for r in public_client.get(f"{PUBLIC}/sitemap").json()]
        assert guide["slug"] not in sitemap

    def test_deleting_takes_effect_on_the_very_next_request(
        self, client, public_client,
    ):
        guide = _create(client)
        _fill(client, guide["id"])
        _publish(client, guide["id"])
        assert public_client.get(f"{PUBLIC}/{guide['slug']}").status_code == 200

        client.delete(f"{BASE}/{guide['id']}")
        assert public_client.get(f"{PUBLIC}/{guide['slug']}").status_code == 404

    def test_a_draft_is_absent_from_the_sitemap(self, client, public_client):
        draft = _create(client)
        _fill(client, draft["id"])
        published = _create(client)
        _fill(client, published["id"])
        _publish(client, published["id"])

        rows = public_client.get(f"{PUBLIC}/sitemap").json()
        slugs = [r["slug"] for r in rows]
        assert published["slug"] in slugs
        assert draft["slug"] not in slugs

    def test_the_sitemap_reports_updated_at_not_published_at(
        self, client, public_client,
    ):
        guide = _create(client)
        _fill(client, guide["id"])
        detail = _publish(client, guide["id"])
        edited = _fill(client, guide["id"], body="<p>Revised after publishing.</p>")

        row = next(
            r for r in public_client.get(f"{PUBLIC}/sitemap").json()
            if r["slug"] == guide["slug"]
        )
        assert row["updated_at"][:19] == edited["updated_at"][:19]
        assert detail["published_at"] is not None


# ---------------------------------------------------------------------------
# 3 · Slugs
# ---------------------------------------------------------------------------


class TestSlugs:
    def test_a_duplicate_slug_is_refused_with_409(self, client):
        first = _create(client)
        res = client.post(
            BASE,
            json={"title": "Another", "slug": first["slug"], "category": "tools"},
        )
        assert res.status_code == 409

    def test_renaming_onto_another_slug_is_refused(self, client):
        first = _create(client)
        second = _create(client)
        res = client.patch(f"{BASE}/{second['id']}", json={"slug": first["slug"]})
        assert res.status_code == 409

    def test_keeping_your_own_slug_is_not_a_conflict(self, client):
        guide = _create(client)
        res = client.patch(f"{BASE}/{guide['id']}", json={"slug": guide["slug"]})
        assert res.status_code == 200

    def test_a_slug_is_normalised_before_it_is_stored(self, client):
        res = client.post(
            BASE,
            json={"title": "T", "slug": "  Moving-Your-Community  ",
                  "category": "starting"},
        )
        assert res.status_code == 201
        assert res.json()["slug"] == "moving-your-community"

    @pytest.mark.parametrize("bad", [
        "Moving Your Community",   # spaces
        "moving--community",       # doubled hyphen
        "-moving",                 # leading hyphen
        "moving-",                 # trailing hyphen
        "moving/community",        # a path, not a slug
        "móving",                  # not ascii
    ])
    def test_a_malformed_slug_is_refused(self, client, bad):
        res = client.post(
            BASE, json={"title": "T", "slug": bad, "category": "starting"},
        )
        assert res.status_code == 422

    def test_lookup_is_case_insensitive_on_the_public_route(
        self, client, public_client,
    ):
        guide = _create(client, slug="finding-your-people")
        _fill(client, guide["id"])
        _publish(client, guide["id"])
        assert public_client.get(f"{PUBLIC}/Finding-Your-People").status_code == 200


# ---------------------------------------------------------------------------
# 4 · Saving never publishes
# ---------------------------------------------------------------------------


class TestSavingNeverPublishes:
    def test_the_update_schema_has_no_status_field(self):
        """Structural, not behavioural. There is no payload that could
        publish a Guide through a save, because the field does not
        exist to send."""
        from app.admin.guides.schemas import GuideUpdate

        assert "status" not in GuideUpdate.model_fields
        assert "published_at" not in GuideUpdate.model_fields

    def test_sending_status_anyway_does_not_publish(self, client):
        guide = _create(client)
        res = client.patch(
            f"{BASE}/{guide['id']}",
            json={"title": "Edited", "status": "published"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "draft"

    def test_publish_refuses_an_empty_guide(self, client):
        """A Guide with no standfirst or body would publish a blank
        page. The create endpoint deliberately makes those empty, so
        this is reachable rather than theoretical."""
        guide = _create(client)
        res = client.post(f"{BASE}/{guide['id']}/publish")
        assert res.status_code == 400

    def test_published_at_is_set_once_and_kept(self, client):
        guide = _create(client)
        _fill(client, guide["id"])
        first = _publish(client, guide["id"])["published_at"]
        client.post(f"{BASE}/{guide['id']}/unpublish")
        second = _publish(client, guide["id"])["published_at"]
        assert first == second


# ---------------------------------------------------------------------------
# 5 · At most one featured Guide
# ---------------------------------------------------------------------------


class TestFeatured:
    def test_featuring_one_clears_the_other(self, client):
        first = _create(client)
        second = _create(client)
        assert client.post(
            f"{BASE}/{first['id']}/feature", json={"featured": True},
        ).status_code == 200
        res = client.post(
            f"{BASE}/{second['id']}/feature", json={"featured": True},
        )
        assert res.status_code == 200
        assert res.json()["featured"] is True

        rows = {g["id"]: g["featured"] for g in client.get(BASE).json()}
        assert rows[first["id"]] is False
        assert rows[second["id"]] is True

    def test_only_one_row_is_ever_featured(self, client, db):
        for _ in range(3):
            guide = _create(client)
            client.post(f"{BASE}/{guide['id']}/feature", json={"featured": True})
        featured = db.query(Guide).filter(Guide.featured.is_(True)).count()
        assert featured == 1

    def test_unfeaturing_leaves_none_featured(self, client, db):
        guide = _create(client)
        client.post(f"{BASE}/{guide['id']}/feature", json={"featured": True})
        res = client.post(f"{BASE}/{guide['id']}/feature", json={"featured": False})
        assert res.json()["featured"] is False
        assert db.query(Guide).filter(Guide.featured.is_(True)).count() == 0

    def test_a_featured_draft_is_still_not_public(self, client, public_client):
        """Featuring is an editorial flag, not a publishing one."""
        guide = _create(client)
        _fill(client, guide["id"])
        client.post(f"{BASE}/{guide['id']}/feature", json={"featured": True})
        slugs = [g["slug"] for g in public_client.get(PUBLIC).json()["guides"]]
        assert guide["slug"] not in slugs


# ---------------------------------------------------------------------------
# 6 · The sanitiser
# ---------------------------------------------------------------------------


class TestSanitiser:
    """The body is a public page's HTML. This is the boundary."""

    def test_a_script_tag_does_not_survive(self, client):
        guide = _create(client)
        saved = _fill(
            client, guide["id"],
            body="<p>Hello</p><script>alert('x')</script>",
        )
        assert "<script" not in saved["body"]
        assert "alert" not in saved["body"]

    def test_an_event_handler_does_not_survive(self, client):
        guide = _create(client)
        saved = _fill(
            client, guide["id"],
            body='<p onclick="steal()">Hello</p>',
        )
        assert "onclick" not in saved["body"]
        assert "Hello" in saved["body"]

    def test_a_javascript_href_does_not_survive(self, client):
        guide = _create(client)
        saved = _fill(
            client, guide["id"],
            body='<p><a href="javascript:alert(1)">Tap</a></p>',
        )
        assert "javascript:" not in saved["body"]

    def test_an_iframe_does_not_survive(self, client):
        guide = _create(client)
        saved = _fill(
            client, guide["id"],
            body='<p>A</p><iframe src="https://evil.test"></iframe>',
        )
        assert "<iframe" not in saved["body"]

    def test_the_allowed_vocabulary_survives(self, client):
        """The control. A sanitiser that stripped everything would
        pass every assertion above."""
        guide = _create(client)
        body = (
            "<h2>Heading</h2><h3>Sub</h3>"
            "<p><strong>Bold</strong> and <em>italic</em> and "
            '<a href="https://example.com">a link</a>.</p>'
            "<ul><li>One</li></ul><ol><li>First</li></ol>"
            "<blockquote><p>A quote.</p></blockquote>"
        )
        saved = _fill(client, guide["id"], body=body)
        for fragment in ["<h2>", "<h3>", "<strong>", "<em>", "<a ",
                         "<ul>", "<ol>", "<li>", "<blockquote>"]:
            assert fragment in saved["body"], fragment

    def test_links_carry_rel_noopener(self, client):
        guide = _create(client)
        saved = _fill(
            client, guide["id"],
            body='<p><a href="https://example.com">x</a></p>',
        )
        assert 'rel="noopener noreferrer"' in saved["body"]

    def test_an_off_origin_image_is_refused_with_an_explanation(self, client):
        """Not silently dropped. The CSP would block it at render time
        and the author would see a broken box with no explanation, so
        the save is refused and says why."""
        guide = _create(client)
        res = client.patch(
            f"{BASE}/{guide['id']}",
            json={"body": '<p><img src="https://evil.test/x.png" alt="x"></p>'},
        )
        assert res.status_code == 400
        assert "upload" in res.json()["detail"].lower()

    def test_an_uploaded_image_is_kept(self, client):
        guide = _create(client)
        saved = _fill(
            client, guide["id"],
            body='<p><img src="/api/uploads/guide-images/abc.png" alt="A chart"></p>',
        )
        assert "/api/uploads/guide-images/abc.png" in saved["body"]
        assert 'alt="A chart"' in saved["body"]

    def test_sanitising_is_idempotent(self):
        from app.services.guide_body import sanitize_guide_body

        once = sanitize_guide_body(
            '<h2>T</h2><p><a href="https://e.test">x</a></p><script>y</script>',
        )
        assert sanitize_guide_body(once) == once

    def test_plain_text_is_returned_byte_for_byte(self):
        """nh3 escapes text as well as stripping tags, so running it
        over a body with no markup would rewrite "tea & biscuits" on an
        untouched save."""
        from app.services.guide_body import sanitize_guide_body

        assert sanitize_guide_body("tea & biscuits, 3 < 5") == "tea & biscuits, 3 < 5"

    def test_a_protocol_relative_image_is_not_mistaken_for_same_origin(self):
        from app.services.guide_body import is_permitted_image_src

        assert is_permitted_image_src("/api/uploads/guide-images/a.png") is True
        assert is_permitted_image_src("//evil.test/a.png") is False
        assert is_permitted_image_src("/not-uploads/a.png") is False
        assert is_permitted_image_src("") is False
        # Another upload namespace is not servable to a logged-out
        # reader, so a body may not reference one — including the
        # ``media/guides/`` shape these images used to have.
        assert is_permitted_image_src("/api/uploads/media/guides/a.png") is False
        assert is_permitted_image_src("/api/uploads/media/some-space/a.png") is False

    def test_the_renderer_and_the_sanitiser_allow_the_same_tags(self):
        """The invariant ``rich_text.py`` documents: a tag the
        sanitiser keeps and the renderer drops reads as lost work; the
        reverse reads as work lost on save. Asserted from the
        frontend's own source so the two cannot drift."""
        import re
        from pathlib import Path

        from app.services.guide_body import ALLOWED_TAGS

        renderer = (
            Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "components" / "guides" / "GuideBody.tsx"
        )
        source = renderer.read_text()
        match = re.search(
            r"export const RENDERED_TAGS[^=]*=\s*\[(.*?)\]", source, re.S,
        )
        assert match, "GuideBody.tsx should export RENDERED_TAGS"
        rendered = set(re.findall(r"'([a-z0-9]+)'", match.group(1)))
        assert rendered == set(ALLOWED_TAGS), (
            f"renderer-only: {rendered - set(ALLOWED_TAGS)}, "
            f"sanitiser-only: {set(ALLOWED_TAGS) - rendered}"
        )


# ---------------------------------------------------------------------------
# 7 · Reading time
# ---------------------------------------------------------------------------


class TestReadingTime:
    def test_it_counts_the_words_a_reader_sees_not_the_markup(self, client):
        guide = _create(client)
        # 440 words at ~220 wpm = 2 minutes.
        words = " ".join(["word"] * 440)
        saved = _fill(client, guide["id"], body=f"<p>{words}</p>")
        assert saved["reading_time_minutes"] == 2

    def test_markup_does_not_inflate_the_estimate(self, client):
        """Ten words wrapped in a hundred tags is still ten words."""
        guide = _create(client)
        body = "".join(f"<p><strong>word</strong></p>" for _ in range(10))
        saved = _fill(client, guide["id"], body=body)
        assert saved["reading_time_minutes"] == 1


# ---------------------------------------------------------------------------
# 8 · Hero alt text and the call to action
# ---------------------------------------------------------------------------


class TestRequiredPairs:
    def test_a_hero_without_alt_text_is_refused(self, client):
        guide = _create(client)
        res = client.patch(
            f"{BASE}/{guide['id']}",
            json={"hero_image_url": "/api/uploads/media/guides/h.png"},
        )
        assert res.status_code == 400
        assert "alt" in res.json()["detail"].lower()

    def test_a_hero_with_alt_text_is_accepted(self, client):
        guide = _create(client)
        res = client.patch(
            f"{BASE}/{guide['id']}",
            json={
                "hero_image_url": "/api/uploads/media/guides/h.png",
                "hero_image_alt": "An island at dusk",
            },
        )
        assert res.status_code == 200

    def test_a_half_filled_call_to_action_is_refused(self, client):
        guide = _create(client)
        res = client.patch(
            f"{BASE}/{guide['id']}",
            json={"cta_heading": "Get the kit", "cta_text": "A printable plan."},
        )
        assert res.status_code == 400

    def test_a_complete_call_to_action_is_accepted(self, client):
        guide = _create(client)
        res = client.patch(
            f"{BASE}/{guide['id']}",
            json={
                "cta_heading": "Get the kit",
                "cta_text": "A printable plan.",
                "cta_label": "Download",
                "cta_href": "/for-creators",
            },
        )
        assert res.status_code == 200

    def test_a_javascript_cta_link_is_refused(self, client):
        guide = _create(client)
        res = client.patch(
            f"{BASE}/{guide['id']}",
            json={
                "cta_heading": "H", "cta_text": "T", "cta_label": "L",
                "cta_href": "javascript:alert(1)",
            },
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# 9 · The Creator Starter Kit setting
# ---------------------------------------------------------------------------


class TestStarterKitSetting:
    def test_it_starts_empty_and_nothing_is_offered(self, client, public_client):
        assert client.get(f"{BASE}/settings").json()["starter_kit_url"] is None
        assert public_client.get(PUBLIC).json()["starter_kit_url"] is None

    def test_setting_it_switches_both_placements_on(
        self, client, public_client,
    ):
        guide = _create(client)
        _fill(client, guide["id"])
        _publish(client, guide["id"])

        res = client.put(
            f"{BASE}/settings",
            json={"starter_kit_url": "https://example.com/kit"},
        )
        assert res.status_code == 200

        index = public_client.get(PUBLIC).json()
        article = public_client.get(f"{PUBLIC}/{guide['slug']}").json()
        assert index["starter_kit_url"] == "https://example.com/kit"
        assert article["starter_kit_url"] == "https://example.com/kit"

    def test_clearing_it_switches_both_off_again(self, client, public_client):
        guide = _create(client)
        _fill(client, guide["id"])
        _publish(client, guide["id"])
        client.put(
            f"{BASE}/settings", json={"starter_kit_url": "https://example.com/kit"},
        )
        client.put(f"{BASE}/settings", json={"starter_kit_url": ""})

        assert public_client.get(PUBLIC).json()["starter_kit_url"] is None
        assert public_client.get(
            f"{PUBLIC}/{guide['slug']}",
        ).json()["starter_kit_url"] is None

    @pytest.mark.parametrize("bad", [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "//evil.test/kit",
        "not a url",
    ])
    def test_an_unusable_link_is_refused(self, client, bad):
        """This value becomes the href of a button on every Guide."""
        res = client.put(f"{BASE}/settings", json={"starter_kit_url": bad})
        assert res.status_code == 400

    def test_a_site_relative_path_is_accepted(self, client):
        res = client.put(f"{BASE}/settings", json={"starter_kit_url": "/for-creators"})
        assert res.status_code == 200
        assert res.json()["starter_kit_url"] == "/for-creators"

    def test_there_is_only_ever_one_settings_row(self, client, db):
        client.put(f"{BASE}/settings", json={"starter_kit_url": "https://a.test/k"})
        client.put(f"{BASE}/settings", json={"starter_kit_url": "https://b.test/k"})
        assert db.query(GuideSettings).count() == 1


# ---------------------------------------------------------------------------
# 10 · The public payload
# ---------------------------------------------------------------------------


class TestPublicPayload:
    def test_the_public_article_carries_no_status_field(
        self, client, public_client,
    ):
        """A published row has nothing to hide, but a payload that
        prints the whole object is how a future field leaks."""
        guide = _create(client)
        _fill(client, guide["id"])
        _publish(client, guide["id"])
        article = public_client.get(f"{PUBLIC}/{guide['slug']}").json()["guide"]
        assert "status" not in article
        assert "id" not in article

    def test_keep_reading_prefers_the_same_category(
        self, client, public_client,
    ):
        target = _create(client, category="starting")
        same = _create(client, category="starting")
        other = _create(client, category="tools")
        for g in (target, same, other):
            _fill(client, g["id"])
            _publish(client, g["id"])

        related = public_client.get(
            f"{PUBLIC}/{target['slug']}",
        ).json()["related"]
        slugs = [r["slug"] for r in related]
        assert target["slug"] not in slugs
        assert slugs[0] == same["slug"]
        assert other["slug"] in slugs

    def test_keep_reading_is_capped_at_three(self, client, public_client):
        target = _create(client)
        for _ in range(5):
            g = _create(client)
            _fill(client, g["id"])
            _publish(client, g["id"])
        _fill(client, target["id"])
        _publish(client, target["id"])

        related = public_client.get(
            f"{PUBLIC}/{target['slug']}",
        ).json()["related"]
        assert len(related) == 3

    def test_an_off_origin_hero_is_reported_as_absent(
        self, client, public_client, db,
    ):
        """The hero is a plain column and never passes the body
        sanitiser, so the same rule is applied on the way out. A hero
        the CSP would block is better absent than broken."""
        guide = _create(client)
        _fill(client, guide["id"])
        _publish(client, guide["id"])
        row = db.query(Guide).filter(Guide.id == guide["id"]).one()
        row.hero_image_url = "https://evil.test/hero.png"
        row.hero_image_alt = "x"
        db.flush()

        article = public_client.get(f"{PUBLIC}/{guide['slug']}").json()["guide"]
        assert article["hero_image_url"] is None

    def test_the_list_is_newest_first(self, client, public_client):
        older = _create(client)
        _fill(client, older["id"])
        _publish(client, older["id"])
        newer = _create(client)
        _fill(client, newer["id"])
        _publish(client, newer["id"])

        slugs = [g["slug"] for g in public_client.get(PUBLIC).json()["guides"]]
        assert slugs.index(newer["slug"]) < slugs.index(older["slug"])

    def test_the_sitemap_path_is_not_read_as_a_slug(self, client, public_client):
        """``/sitemap`` is declared before ``/{slug}``. Without that
        ordering this answers as a lookup for a Guide slugged
        "sitemap" and the sitemap silently 404s."""
        res = public_client.get(f"{PUBLIC}/sitemap")
        assert res.status_code == 200
        assert isinstance(res.json(), list)


# ---------------------------------------------------------------------------
# 10b · Guide images — their own namespace, servable to a stranger
# ---------------------------------------------------------------------------


GUIDE_IMAGE = "/api/uploads/guide-images/abc123_hero.png"


@pytest.fixture
def read_as(db):
    """Fetch a URL as a given identity — ``None`` means anonymous.

    One fixture rather than an anonymous client *and* an admin client,
    because ``get_optional_user`` is a single global override: two
    fixtures requested by the same test clobber each other, and the
    "anonymous" one silently becomes whichever was set last. That is
    not a hypothetical — it is how the first draft of these tests
    passed an admin off as a stranger.
    """
    app.dependency_overrides[get_db] = lambda: db

    def _get(url: str, user=None):
        if user is None:
            app.dependency_overrides.pop(get_optional_user, None)
        else:
            app.dependency_overrides[get_optional_user] = lambda: user
        return TestClient(app, follow_redirects=False).get(url)

    yield _get
    app.dependency_overrides.clear()


@pytest.fixture
def uploaded_image(client):
    """A real image, through the real admin upload endpoint.

    Returns the URL the endpoint hands back, so a test that uses it
    is exercising whatever shape the upload currently produces rather
    than a shape the test author believed in.
    """
    import io

    res = client.post(
        f"{BASE}/images",
        files={"file": ("hero.png",
                        io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64),
                        "image/png")},
    )
    assert res.status_code == 201, res.text
    url = res.json()["url"]
    yield url
    (UPLOAD_DIR / url[len("/api/uploads/"):]).unlink(missing_ok=True)


@pytest.fixture
def guide_image_on_disk():
    """Real bytes, so a permitted read is a 200 rather than a 404
    about a missing file."""
    target = UPLOAD_DIR / "guide-images" / "abc123_hero.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    yield target
    target.unlink(missing_ok=True)


class TestGuideImages:
    """The bug: every Guide image 404'd, for everyone.

    ``save_media_file(space_slug="guides")`` produced
    ``media/guides/…``, which the uploads authoriser reads as the
    Asset Library of a Collective slugged "guides". No such
    Collective exists, so it 404'd — including for an administrator
    in the preview — and even resolved it would have been member-only,
    so a logged-out reader could never have been served.
    """

    def test_the_upload_endpoint_writes_to_the_guide_namespace(
        self, client, monkeypatch,
    ):
        import io

        res = client.post(
            f"{BASE}/images",
            files={"file": ("hero.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64),
                            "image/png")},
        )
        assert res.status_code == 201, res.text
        url = res.json()["url"]
        assert url.startswith("/api/uploads/guide-images/"), url
        # The shape that caused the bug must not come back.
        assert "/media/guides/" not in url

    def test_uploading_still_requires_an_administrator(self, member_client):
        import io

        res = member_client.post(
            f"{BASE}/images",
            files={"file": ("hero.png", io.BytesIO(b"x"), "image/png")},
        )
        assert res.status_code == 403

    # -- the reported symptom ----------------------------------------

    def test_an_anonymous_visitor_can_read_a_published_guides_hero(
        self, client, read_as, guide_image_on_disk,
    ):
        guide = _create(client)
        _fill(
            client, guide["id"],
            hero_image_url=GUIDE_IMAGE,
            hero_image_alt="An island at dusk",
        )
        _publish(client, guide["id"])

        res = read_as(GUIDE_IMAGE)
        assert res.status_code == 200, res.text

    def test_an_inline_body_image_is_readable_too(
        self, client, read_as, guide_image_on_disk,
    ):
        """Not only the hero column — an image embedded in the body
        has to be servable or the article renders with a hole in it."""
        guide = _create(client)
        _fill(
            client, guide["id"],
            body=f'<p>Text</p><p><img src="{GUIDE_IMAGE}" alt="A chart"></p>',
        )
        _publish(client, guide["id"])

        assert read_as(GUIDE_IMAGE).status_code == 200

    # -- still narrow -------------------------------------------------

    def test_a_drafts_image_is_not_public_but_an_admin_can_preview_it(
        self, client, read_as, admin, guide_image_on_disk,
    ):
        guide = _create(client)
        _fill(
            client, guide["id"],
            hero_image_url=GUIDE_IMAGE, hero_image_alt="x",
        )
        # Left as a draft.
        assert read_as(GUIDE_IMAGE).status_code == 404
        assert read_as(GUIDE_IMAGE, admin).status_code == 200

    def test_unpublishing_takes_the_image_down_too(
        self, client, read_as, guide_image_on_disk,
    ):
        guide = _create(client)
        _fill(
            client, guide["id"],
            hero_image_url=GUIDE_IMAGE, hero_image_alt="x",
        )
        _publish(client, guide["id"])
        assert read_as(GUIDE_IMAGE).status_code == 200

        client.post(f"{BASE}/{guide['id']}/unpublish")
        assert read_as(GUIDE_IMAGE).status_code == 404

    def test_an_uploaded_but_unused_image_is_not_public(
        self, read_as, guide_image_on_disk,
    ):
        """Uploading publishes nothing. Only a key a published Guide
        points at is readable."""
        assert read_as(GUIDE_IMAGE).status_code == 404

    def test_a_refusal_looks_like_a_key_that_never_existed(self, read_as):
        """No oracle: a draft's image and a key nobody uploaded give
        the same answer, so the route cannot be used to learn that a
        draft exists."""
        a = read_as(GUIDE_IMAGE)
        b = read_as("/api/uploads/guide-images/nope_nothing.png")
        assert a.status_code == b.status_code == 404
        assert a.json() == b.json()

    # -- the collision the namespace removes --------------------------

    def test_a_collective_slugged_guides_cannot_capture_guide_images(
        self, db, read_as, admin, guide_image_on_disk, make_user,
    ):
        """The latent trap, made unreachable.

        While Guide images lived at ``media/guides/…`` they were
        resolved by slug, so registering a Collective called "guides"
        would have put every Guide image under that Collective's
        membership rules. The namespace is no longer slug-derived, so
        the Collective can exist and change nothing.
        """
        from app.models.platform import Space, SpaceStatus

        owner = make_user(role="creator")
        db.add(Space(
            id=f"s_{uuid.uuid4().hex[:10]}",
            slug="guides", name="Guides", status=SpaceStatus.active,
            visibility="link", is_public=False, kind="standard",
            connection_style="online", creator_id=owner.id, themes=[],
            pricing_type="free", pricing_currency="AUD",
            has_paid_internal_content=False,
            timezone="Australia/Melbourne", island_artwork_status="not_started",
        ))
        db.flush()

        # The Guide image route is unaffected by that Collective.
        assert read_as(GUIDE_IMAGE, admin).status_code == 200
        # And the Collective's own Asset Library is still its own,
        # refused to a stranger — the two namespaces never meet.
        assert read_as(
            "/api/uploads/media/guides/anything.png",
        ).status_code == 401

    # -- the test that would have caught the bug ----------------------

    def test_the_hero_url_a_guide_returns_is_servable_to_a_stranger(
        self, client, read_as, uploaded_image,
    ):
        """The end-to-end invariant, and the one that was missing.

        Every earlier test asserted one side or the other: that the
        API returns a hero URL, or that some key is readable. The bug
        lived exactly between them — the public payload advertised a
        URL the uploads route refused to serve to the audience the
        page is written for, and no test crossed that seam.

        So nothing here is written down. The image goes through the
        real admin upload, the URL *it* returns becomes the hero, the
        Guide is published, and the URL the *public endpoint* hands
        back is fetched with no session. Every link in the chain is
        the real one, which is what makes this fail against the old
        ``media/guides/`` shape rather than passing on a hard-coded
        path that happens to be right.
        """
        guide = _create(client)
        _fill(
            client, guide["id"],
            hero_image_url=uploaded_image, hero_image_alt="An island at dusk",
        )
        _publish(client, guide["id"])

        payload = read_as(f"{PUBLIC}/{guide['slug']}").json()
        hero = payload["guide"]["hero_image_url"]
        assert hero, (
            "the public payload dropped the hero entirely — the URL the "
            "upload returned is not one the API will even advertise"
        )

        res = read_as(hero)
        assert res.status_code == 200, (
            f"the API advertises {hero} but serving it to an anonymous "
            f"reader answered {res.status_code}"
        )

    def test_the_same_invariant_for_every_image_in_the_body(
        self, client, read_as, uploaded_image,
    ):
        """The body half of the same contract, read out of the stored
        HTML rather than assumed."""
        import re

        guide = _create(client)
        _fill(
            client, guide["id"],
            body=f'<p><img src="{uploaded_image}" alt="A chart"></p>',
        )
        _publish(client, guide["id"])

        body = read_as(
            f"{PUBLIC}/{guide['slug']}",
        ).json()["guide"]["body"]
        srcs = re.findall(r'<img[^>]+src="([^"]+)"', body)
        assert srcs, "the body lost its image"
        for src in srcs:
            assert read_as(src).status_code == 200, src


# ---------------------------------------------------------------------------
# 11 · Delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_removes_the_row(self, client, db):
        guide = _create(client)
        assert client.delete(f"{BASE}/{guide['id']}").status_code == 204
        assert db.query(Guide).filter(Guide.id == guide["id"]).first() is None

    def test_deleting_an_unknown_guide_is_a_404(self, client):
        assert client.delete(f"{BASE}/{uuid.uuid4()}").status_code == 404
