"""What the sitemap is allowed to tell a search engine about.

What this guards
----------------
A sitemap is an invitation to crawl, so every mistake here is a
privacy or correctness mistake that is hard to take back once an
index has it.

The list is built on ``_public_space_query`` — the same predicate
Explore uses — so visibility is decided in one place and the two
surfaces cannot drift. These tests pin that and the two filters
layered on top, both subtractive:

* a Collective classified ``test`` or ``demonstration`` is a fixture
  and not content to lead a crawler to;
* a Collective whose About page renders ``noindex`` is not advertised,
  which is narrower than discoverability — see ``TestTheNamedException``.

The inverse is deliberately **not** true and is tested as such. A
``production`` classification is an analytics fact about a Collective,
never evidence that its page should be indexed; an unclassified
public Collective is included and a private production one is not.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.core.database import get_db
from app.main import app
from app.reporting.classification import (
    DEMONSTRATION,
    INTERNAL_OPERATIONS,
    PRODUCTION,
    TEST,
)

ENDPOINT = "/api/public/sitemap/collectives"


@pytest.fixture
def client(db):
    """Anonymous. A crawler has no session and neither does this."""
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def slugs(client) -> set[str]:
    r = client.get(ENDPOINT)
    assert r.status_code == 200, r.text
    return {row["slug"] for row in r.json()}


class TestWhatIsIncluded:
    def test_a_public_active_collective_is_listed(self, client, make_space):
        s = make_space(status="active", is_public=True, reporting_class=PRODUCTION)
        assert s.slug in slugs(client)

    def test_an_unclassified_public_collective_is_listed(self, client, make_space):
        """Most Collectives have no reporting class. Absence of a
        classification is not a reason to hide a public page."""
        s = make_space(status="active", is_public=True, reporting_class=None)
        assert s.slug in slugs(client)

    def test_no_authentication_is_required(self, client, make_space):
        make_space(status="active", is_public=True)
        assert client.get(ENDPOINT).status_code == 200

    def test_every_entry_carries_a_real_timestamp(self, client, make_space):
        """``lastModified`` must come from a recorded change, never
        from the moment of the request."""
        make_space(status="active", is_public=True)
        rows = client.get(ENDPOINT).json()
        assert rows
        for row in rows:
            assert row["updated_at"]

    def test_the_payload_carries_nothing_but_slug_and_date(self, client, make_space):
        make_space(status="active", is_public=True, reporting_class=PRODUCTION)
        for row in client.get(ENDPOINT).json():
            assert set(row) == {"slug", "updated_at"}, (
                "the sitemap source must not become a second public "
                "payload — and must never publish the reporting class "
                "it filters on"
            )


class TestWhatIsExcluded:
    def test_a_private_collective_is_not_listed(self, client, make_space):
        s = make_space(status="active", is_public=False)
        assert s.slug not in slugs(client)

    def test_a_private_collective_is_excluded_even_when_production(
        self, client, make_space,
    ):
        """The distinction the brief asks for, stated as a test.

        Production is an analytics classification. It says the
        activity is genuine trade; it says nothing about whether the
        page may be indexed, and must never be read as permission.
        """
        s = make_space(status="active", is_public=False, reporting_class=PRODUCTION)
        assert s.slug not in slugs(client)

    def test_a_draft_collective_is_not_listed(self, client, make_space):
        s = make_space(status="draft", is_public=True)
        assert s.slug not in slugs(client)

    def test_an_archived_collective_is_not_listed(self, client, make_space):
        s = make_space(status="archived", is_public=True)
        assert s.slug not in slugs(client)

    def test_a_test_classified_collective_is_not_listed(self, client, make_space):
        s = make_space(status="active", is_public=True, reporting_class=TEST)
        assert s.slug not in slugs(client)

    def test_a_demonstration_collective_is_not_listed(self, client, make_space):
        s = make_space(status="active", is_public=True, reporting_class=DEMONSTRATION)
        assert s.slug not in slugs(client)

    def test_an_auto_managed_collective_is_not_listed_by_default(
        self, client, make_space,
    ):
        """Operational Collectives are invisible to public surfaces
        unless named in the discoverability exception."""
        s = make_space(
            status="active", is_public=True, auto_grant_role="creator",
        )
        assert s.slug not in slugs(client)

    def test_the_classification_filter_is_subtractive_only(
        self, client, make_space,
    ):
        """Classifying something internal_operations does not hide it
        if it is genuinely public, and does not reveal it if not.

        Only ``test`` and ``demonstration`` subtract. Everything else
        leaves the visibility rule to decide, which is the point.
        """
        public_internal = make_space(
            status="active", is_public=True,
            reporting_class=INTERNAL_OPERATIONS,
        )
        assert public_internal.slug in slugs(client)


class TestTheNamedException:
    """Discoverable is not the same as indexable.

    World Builders is reachable anonymously and has a real public
    About page, through ``PUBLICLY_DISCOVERABLE_MANAGED_SLUGS``. It
    is nonetheless absent from the sitemap, because that page keys
    its own indexability on ``is_public`` — which the exception
    leaves false — and therefore renders ``noindex, nofollow``.
    Advertising a page that tells crawlers to go away is the one
    self-contradiction a sitemap can make.
    """

    def test_a_discoverable_but_noindex_collective_is_not_listed(self, client):
        from app.spaces.routes import PUBLICLY_DISCOVERABLE_MANAGED_SLUGS

        explore = {s["slug"] for s in client.get("/api/public/spaces").json()}
        listed = slugs(client)
        for slug in PUBLICLY_DISCOVERABLE_MANAGED_SLUGS:
            assert slug in explore, f"{slug} should still be discoverable"
            assert slug not in listed, (
                f"{slug} renders noindex, so the sitemap must not "
                "invite a crawler to it"
            )

    def test_it_would_appear_if_it_became_genuinely_public(self, client, db):
        """The filter tracks the page's own rule rather than the slug.

        If the exception were ever widened to set ``is_public`` — the
        page would stop rendering ``noindex`` — the sitemap follows
        without a second edit here.
        """
        from app.models.platform import Space
        from app.spaces.routes import PUBLICLY_DISCOVERABLE_MANAGED_SLUGS

        slug = next(iter(PUBLICLY_DISCOVERABLE_MANAGED_SLUGS))
        wb = db.query(Space).filter(Space.slug == slug).one()
        wb.is_public = True
        db.flush()
        assert slug in slugs(client)

    def test_it_still_drops_out_if_classified_a_fixture(self, client, db):
        """Both filters apply, and the stricter one wins."""
        from app.models.platform import Space
        from app.spaces.routes import PUBLICLY_DISCOVERABLE_MANAGED_SLUGS

        slug = next(iter(PUBLICLY_DISCOVERABLE_MANAGED_SLUGS))
        wb = db.query(Space).filter(Space.slug == slug).one()
        wb.is_public = True
        wb.reporting_class = DEMONSTRATION
        db.flush()
        assert slug not in slugs(client)


class TestItAgreesWithTheSurfaceItMirrors:
    def test_it_never_lists_what_explore_will_not_show(
        self, client, make_space,
    ):
        """One predicate, two surfaces. If these ever diverge, a page
        is being advertised that the site itself will not link to.
        """
        make_space(status="active", is_public=True)
        make_space(status="draft", is_public=True)
        make_space(status="active", is_public=False)
        make_space(status="active", is_public=True, reporting_class=TEST)

        explore = {s["slug"] for s in client.get("/api/public/spaces").json()}
        sitemap = slugs(client)
        assert sitemap <= explore, sitemap - explore

    def test_there_are_no_duplicates(self, client, make_space):
        for _ in range(3):
            make_space(status="active", is_public=True)
        rows = client.get(ENDPOINT).json()
        found = [r["slug"] for r in rows]
        assert len(found) == len(set(found))
