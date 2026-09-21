"""The number on a Place card is a promise about the next click.

Melbourne advertised "33 upcoming gatherings" above a page showing 30.
The count query and the detail query had drifted: the count kept
tallying Gatherings that were cancelled, archived, not public, or
owned by a Collective the page would never list.

Both now share ``public_gathering_filters``, so the card cannot
promise what the page will not show.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_optional_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.place import Place, SpacePlace
from app.models.platform import Event

PUBLIC_GATHERINGS = {"areas": {"gatherings": "public"}}


@pytest.fixture
def discovery_enabled(monkeypatch):
    monkeypatch.setattr(settings, "discovery_pillar_enabled", True)
    yield


@pytest.fixture
def client(db, discovery_enabled):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_optional_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def place(db):
    def _make():
        p = Place(
            id=f"place_{uuid.uuid4().hex[:12]}",
            slug=f"melbourne-{uuid.uuid4().hex[:6]}", name="Melbourne",
            country_code="AU", status="active",
        )
        db.add(p)
        db.flush()
        return p
    return _make


@pytest.fixture
def link(db):
    def _link(space, pl):
        db.add(SpacePlace(space_id=space.id, place_id=pl.id))
        db.flush()
    return _link


def gathering(db, space, **over):
    """A Gathering that qualifies, unless a test says otherwise."""
    defaults = dict(
        is_published=True, is_public=True, status="active",
        booking_access_type="included_with_collective",
        starts_at=datetime.utcnow() + timedelta(days=5),
        ends_at=datetime.utcnow() + timedelta(days=5, hours=1),
    )
    defaults.update(over)
    ev = Event(id=str(uuid.uuid4()), space_id=space.id,
               title=over.pop("title", "Circle"), **defaults)
    db.add(ev)
    db.flush()
    return ev


def count_for(client, pl) -> int:
    rows = client.get("/api/places").json()
    row = next((r for r in rows if r["slug"] == pl.slug), None)
    assert row is not None, "the Place vanished from the list"
    return row["upcoming_gathering_count"]


@pytest.fixture
def eligible(db, make_space, place, link):
    """A public Place, a public Collective with public Gatherings."""
    space = make_space(is_public=True, area_policies=PUBLIC_GATHERINGS)
    pl = place()
    link(space, pl)
    return space, pl


class TestWhatCounts:
    def test_an_active_published_public_future_gathering(self, client, db, eligible):
        space, pl = eligible
        gathering(db, space)
        assert count_for(client, pl) == 1

    def test_a_paid_separately_gathering_counts_even_when_not_flagged_public(
        self, client, db, eligible,
    ):
        """Its ticket page is sold to the public, so it is visible."""
        space, pl = eligible
        # A published paid_separately Gathering must carry a price —
        # the DB enforces it.
        gathering(db, space, is_public=False,
                  booking_access_type="paid_separately",
                  ticket_price_cents=2500, ticket_currency="AUD")
        assert count_for(client, pl) == 1

    def test_several_count_as_several(self, client, db, eligible):
        space, pl = eligible
        for _ in range(30):
            gathering(db, space)
        assert count_for(client, pl) == 30


class TestWhatDoesNotCount:
    def test_a_cancelled_gathering(self, client, db, eligible):
        space, pl = eligible
        gathering(db, space, status="cancelled")
        assert count_for(client, pl) == 0

    def test_an_archived_gathering(self, client, db, eligible):
        """Invisible on every public surface — and previously counted,
        because the count had no status filter at all."""
        space, pl = eligible
        gathering(db, space, status="archived")
        assert count_for(client, pl) == 0

    def test_an_unpublished_gathering(self, client, db, eligible):
        space, pl = eligible
        gathering(db, space, is_published=False)
        assert count_for(client, pl) == 0

    def test_a_non_public_gathering_that_is_not_paid_separately(
        self, client, db, eligible,
    ):
        space, pl = eligible
        gathering(db, space, is_public=False,
                  booking_access_type="included_with_collective")
        assert count_for(client, pl) == 0

    def test_a_past_gathering(self, client, db, eligible):
        space, pl = eligible
        gathering(db, space,
                  starts_at=datetime.utcnow() - timedelta(days=2),
                  ends_at=datetime.utcnow() - timedelta(days=2) + timedelta(hours=1))
        assert count_for(client, pl) == 0

    def test_a_gathering_in_a_private_collective(
        self, client, db, make_space, place, link,
    ):
        space = make_space(is_public=False, area_policies=PUBLIC_GATHERINGS)
        pl = place()
        link(space, pl)
        gathering(db, space)
        assert count_for(client, pl) == 0

    def test_a_gathering_in_an_auto_managed_collective(
        self, client, db, make_space, place, link,
    ):
        """World Builders and friends never appear on a public Place."""
        space = make_space(is_public=True, auto_grant_role="creator",
                           area_policies=PUBLIC_GATHERINGS)
        pl = place()
        link(space, pl)
        gathering(db, space)
        assert count_for(client, pl) == 0

    def test_a_gathering_in_a_draft_collective(
        self, client, db, make_space, place, link,
    ):
        space = make_space(is_public=True, status="draft",
                           area_policies=PUBLIC_GATHERINGS)
        pl = place()
        link(space, pl)
        gathering(db, space)
        assert count_for(client, pl) == 0

    def test_a_collective_whose_gatherings_are_members_only(
        self, client, db, make_space, place, link,
    ):
        space = make_space(is_public=True,
                           area_policies={"areas": {"gatherings": "members"}})
        pl = place()
        link(space, pl)
        gathering(db, space)
        assert count_for(client, pl) == 0

    def test_a_collective_that_never_configured_its_areas(
        self, client, db, make_space, place, link,
    ):
        """Gatherings default to members, so nothing is advertised."""
        space = make_space(is_public=True)
        pl = place()
        link(space, pl)
        gathering(db, space)
        assert count_for(client, pl) == 0

    def test_the_place_still_appears_with_a_zero(self, client, db, eligible):
        """Excluding Gatherings must never exclude the Place."""
        space, pl = eligible
        gathering(db, space, status="cancelled")
        rows = client.get("/api/places").json()
        assert any(r["slug"] == pl.slug for r in rows)


class TestTheCardAndThePageAgree:
    """The seam. Whatever the filters become, these two must move
    together — that is the property whose absence produced 33 over 30."""

    def _detail(self, client, pl):
        res = client.get(f"/api/places/{pl.slug}")
        assert res.status_code == 200, res.text
        return res.json()

    def test_the_count_equals_the_eligible_occurrences_on_the_detail_page(
        self, client, db, eligible,
    ):
        space, pl = eligible
        for _ in range(7):
            gathering(db, space)
        # Noise the card must not count and the page must not show.
        gathering(db, space, status="cancelled")
        gathering(db, space, is_published=False)
        gathering(db, space, is_public=False,
                  booking_access_type="included_with_collective")

        detail = self._detail(client, pl)
        occurrences = len(detail["upcoming_gatherings"]) + sum(
            s.get("occurrence_count") or 0 for s in detail["upcoming_series"]
        )
        assert count_for(client, pl) == occurrences == 7

    def test_series_grouping_does_not_change_the_count(
        self, client, db, eligible, make_space,
    ):
        """Thirty Term 4 occurrences render as one card. The card still
        says thirty, because it counts Gatherings, not cards."""
        from app.models.platform import EventSeries
        space, pl = eligible
        series = EventSeries(
            id=f"es_{uuid.uuid4().hex[:12]}", space_id=space.id,
            slug="term-4", title="Term 4 2026", status="published",
            starts_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=60),
            published_at=datetime.utcnow(),
        )
        db.add(series)
        db.flush()
        for _ in range(30):
            gathering(db, space, series_id=series.id)

        detail = self._detail(client, pl)
        assert len(detail["upcoming_series"]) == 1, "grouped into one card"
        assert len(detail["upcoming_gatherings"]) == 0, "no individual cards"
        assert detail["upcoming_series"][0]["occurrence_count"] == 30
        assert count_for(client, pl) == 30, "the card counts gatherings, not cards"

    def test_they_agree_when_there_is_nothing(self, client, db, eligible):
        space, pl = eligible
        detail = self._detail(client, pl)
        assert detail["upcoming_gatherings"] == []
        assert detail["upcoming_series"] == []
        assert count_for(client, pl) == 0
