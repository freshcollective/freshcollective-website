"""
Tests for /api/places — the Discovery pillar's public read + resolve
surface.

Locks:

  * Flag off → 503 on every endpoint (no partial rollout).
  * Flag on  → GET list returns active Places only.
  * Response shape is the intentionally-small ``PlaceSummary``.
  * Lookup proxies the location provider; resolve dedupes by
    provider_place_id and creates a Place row from the provider's
    canonical payload.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401
from app.core.config import settings
from app.models.place import Place
from app.models.user import User
from app.places.routes import (
    LookupRequest,
    PlaceSummary,
    ResolveRequest,
    get_place,
    list_places,
    lookup_places,
    resolve_place,
)
from app.services.location_providers.base import LocationSuggestion


@pytest.fixture
def discovery_enabled(monkeypatch):
    monkeypatch.setattr(settings, "discovery_pillar_enabled", True)
    yield


@pytest.fixture
def discovery_disabled(monkeypatch):
    monkeypatch.setattr(settings, "discovery_pillar_enabled", False)
    yield


def _place(**overrides) -> Place:
    defaults = dict(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=f"test-{uuid.uuid4().hex[:8]}",
        name="Test City",
        country_code="AU",
    )
    defaults.update(overrides)
    return Place(**defaults)


# ---------------------------------------------------------------------------
# Fake provider — a canonical suggestion the tests control.
# ---------------------------------------------------------------------------

MELBOURNE_SUGGESTION = LocationSuggestion(
    provider_place_id="osm:node:12345",
    name="Melbourne",
    region="Victoria",
    country="Australia",
    country_code="AU",
    latitude=-37.8136,
    longitude=144.9631,
    timezone="Australia/Melbourne",
)


class _FakeProvider:
    """Deterministic stand-in for NominatimProvider so tests don't hit
    the network. Behaves like the Protocol."""

    def __init__(self, *, search_results=None, fetch_result=None):
        self._search = search_results or []
        self._fetch = fetch_result

    async def search(self, query, limit=6):
        return list(self._search)

    async def fetch(self, provider_place_id):
        return self._fetch


@pytest.fixture
def install_fake_provider(monkeypatch):
    """Install a fake location provider. Returns a factory that
    tests call with their desired responses."""
    def _factory(*, search_results=None, fetch_result=None):
        fake = _FakeProvider(search_results=search_results, fetch_result=fetch_result)
        monkeypatch.setattr(
            "app.places.routes.get_location_provider",
            lambda: fake,
        )
        return fake
    return _factory


def _run(coro):
    """Small helper — the routes are async now."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Flag defaults — regression guard
# ---------------------------------------------------------------------------

class TestFlagDefaults:
    """A previous incident: the operator had NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED
    set to true on the frontend, but DISCOVERY_PILLAR_ENABLED was unset on
    the backend, defaulting to False. The picker UI rendered but every
    lookup hit 503, surfacing as 'Location search is unavailable right
    now.'

    This test locks in the intended default so we cannot accidentally
    flip it to True and leak the pillar on by mistake. Flipping the
    default should be a deliberate, reviewed change to config.py."""

    def test_discovery_pillar_default_is_false(self, monkeypatch):
        # Ignore .env and any DISCOVERY_PILLAR_ENABLED currently in the
        # environment so we see the class default, not the operator's
        # local override.
        monkeypatch.delenv("DISCOVERY_PILLAR_ENABLED", raising=False)
        from app.core.config import Settings
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            database_url="postgresql://x/y",
            jwt_secret="test",
        )
        assert s.discovery_pillar_enabled is False, (
            "The Discovery pillar must default to disabled. A code change "
            "that flips this default would silently expose /api/places/* "
            "and the Discover Places / Ways to Connect routes on every "
            "deployment that had not explicitly opted out."
        )


# ---------------------------------------------------------------------------
# Flag gating
# ---------------------------------------------------------------------------

class TestFlagGating:
    def test_list_flag_off_returns_503(self, db, discovery_disabled):
        with pytest.raises(HTTPException) as exc:
            list_places(db)
        assert exc.value.status_code == 503

    def test_list_flag_off_hides_data(self, db, discovery_disabled):
        db.add(_place(slug="melbourne", name="Melbourne"))
        db.flush()
        with pytest.raises(HTTPException) as exc:
            list_places(db)
        assert exc.value.status_code == 503

    def test_lookup_flag_off_returns_503(self, db, discovery_disabled, make_user, install_fake_provider):
        install_fake_provider(search_results=[MELBOURNE_SUGGESTION])
        with pytest.raises(HTTPException) as exc:
            _run(lookup_places(LookupRequest(query="Melbourne"), _user=make_user(role="creator")))
        assert exc.value.status_code == 503

    def test_resolve_flag_off_returns_503(self, db, discovery_disabled, make_user, install_fake_provider):
        install_fake_provider(fetch_result=MELBOURNE_SUGGESTION)
        with pytest.raises(HTTPException) as exc:
            _run(resolve_place(
                ResolveRequest(provider_place_id="osm:node:12345"),
                db=db,
                _user=make_user(role="creator"),
            ))
        assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/places
# ---------------------------------------------------------------------------

class TestList:
    def test_flag_on_empty_list(self, db, discovery_enabled):
        assert list_places(db) == []

    def test_returns_active_places_only(self, db, discovery_enabled):
        db.add(_place(slug="melbourne", name="Melbourne", status="active"))
        db.add(_place(slug="perth",     name="Perth",     status="hidden"))
        db.add(_place(slug="brisbane",  name="Brisbane",  status="active"))
        db.flush()

        result = list_places(db)
        assert [p.name for p in result] == ["Brisbane", "Melbourne"]

    def test_response_shape_carries_artwork_blurb_and_summary(
        self, db, discovery_enabled,
    ):
        db.add(_place(
            slug="byron-bay",
            name="Byron Bay",
            country_code="AU",
            region="Northern Rivers",
            blurb="Byron is a coastal community.",
            admin_note="Internal note — must not leak publicly.",
        ))
        db.flush()
        result = list_places(db)
        assert len(result) == 1
        assert isinstance(result[0], PlaceSummary)
        # Public fields include the curated artwork payload + the
        # admin-authored editorial blurb + a small activity summary
        # so Discover Places renders without a second round-trip.
        # admin_note, coordinates, timezone, provider_place_id and
        # status stay off this shape.
        assert set(result[0].model_dump().keys()) == {
            "id", "slug", "name", "country_code", "region",
            "hero_artwork_url", "artwork_alt_text",
            "artwork_focal_x", "artwork_focal_y",
            "blurb", "themes", "collective_count",
            "upcoming_gathering_count",
        }
        assert result[0].blurb == "Byron is a coastal community."

    def test_admin_note_does_not_leak(self, db, discovery_enabled):
        db.add(_place(
            slug="secret",
            name="Secret",
            admin_note="Never expose this.",
        ))
        db.flush()
        [row] = list_places(db)
        assert "admin_note" not in row.model_dump()

    def test_summary_aggregates_from_linked_active_collectives(
        self, db, discovery_enabled, make_space,
    ):
        from app.models.place import SpacePlace
        p = _place(slug="wollongong", name="Wollongong")
        db.add(p)
        db.flush()

        s1 = make_space(themes=["Wellbeing", "Movement"])
        s2 = make_space(themes=["Movement", "Leadership"])
        db.add(SpacePlace(space_id=s1.id, place_id=p.id))
        db.add(SpacePlace(space_id=s2.id, place_id=p.id))
        db.flush()

        [row] = list_places(db)
        assert row.collective_count == 2
        # Deduped + first-appearance order preserved.
        assert row.themes == ["Wellbeing", "Movement", "Leadership"]

    def test_summary_excludes_draft_and_archived_collectives(
        self, db, discovery_enabled, make_space,
    ):
        from app.models.place import SpacePlace
        p = _place(slug="counted-carefully", name="Counted Carefully")
        db.add(p)
        db.flush()

        active   = make_space(themes=["Wellbeing"])
        drafted  = make_space(status="draft",    themes=["Should not count"])
        archived = make_space(status="archived", themes=["Also not counted"])
        db.add(SpacePlace(space_id=active.id,   place_id=p.id))
        db.add(SpacePlace(space_id=drafted.id,  place_id=p.id))
        db.add(SpacePlace(space_id=archived.id, place_id=p.id))
        db.flush()

        [row] = list_places(db)
        assert row.collective_count == 1
        assert row.themes == ["Wellbeing"]

    def test_upcoming_gathering_count(
        self, db, discovery_enabled, make_space, make_event,
    ):
        from datetime import datetime, timedelta
        from app.models.place import SpacePlace
        p = _place(slug="with-events", name="With Events")
        db.add(p)
        db.flush()

        space = make_space()
        db.add(SpacePlace(space_id=space.id, place_id=p.id))
        db.flush()

        # One future published event → counts; one past event → skipped.
        make_event(space=space, starts_at=datetime.utcnow() + timedelta(days=3),
                   ends_at=datetime.utcnow() + timedelta(days=3, hours=1))
        make_event(space=space, starts_at=datetime.utcnow() - timedelta(days=3),
                   ends_at=datetime.utcnow() - timedelta(days=3, hours=-1))
        db.flush()

        [row] = list_places(db)
        assert row.upcoming_gathering_count == 1


# ---------------------------------------------------------------------------
# GET /api/places/{slug} — the detail surface behind /discover-places/[slug]
# ---------------------------------------------------------------------------

class TestGetPlace:
    def test_returns_active_place(self, db, discovery_enabled):
        db.add(_place(
            slug="melbourne",
            name="Melbourne",
            region="Victoria",
            country_code="AU",
            blurb="A creative, connected city.",
            hero_artwork_url="/api/uploads/place-artwork/melbourne/hero.png",
            artwork_alt_text="Melbourne skyline",
        ))
        db.flush()

        detail = get_place("melbourne", db=db)
        assert detail.slug == "melbourne"
        assert detail.name == "Melbourne"
        assert detail.region == "Victoria"
        assert detail.blurb == "A creative, connected city."
        assert detail.hero_artwork_url == "/api/uploads/place-artwork/melbourne/hero.png"
        assert detail.artwork_alt_text == "Melbourne skyline"
        assert detail.collectives == []
        assert detail.upcoming_gatherings == []
        assert detail.collective_count == 0

    def test_flag_off_returns_503(self, db, discovery_disabled):
        db.add(_place(slug="whatever", name="Whatever"))
        db.flush()
        with pytest.raises(HTTPException) as ex:
            get_place("whatever", db=db)
        assert ex.value.status_code == 503

    def test_draft_place_404s(self, db, discovery_enabled):
        db.add(_place(slug="draft-town", name="Draft Town", status="draft"))
        db.flush()
        with pytest.raises(HTTPException) as ex:
            get_place("draft-town", db=db)
        assert ex.value.status_code == 404

    def test_hidden_and_archived_places_404(self, db, discovery_enabled):
        db.add_all([
            _place(slug="hidden-town",   status="hidden"),
            _place(slug="archived-town", status="archived"),
        ])
        db.flush()
        for slug in ("hidden-town", "archived-town"):
            with pytest.raises(HTTPException) as ex:
                get_place(slug, db=db)
            assert ex.value.status_code == 404

    def test_missing_slug_404s(self, db, discovery_enabled):
        with pytest.raises(HTTPException) as ex:
            get_place("nowhere", db=db)
        assert ex.value.status_code == 404

    def test_lists_linked_public_active_collectives_only(
        self, db, discovery_enabled, make_space,
    ):
        from app.models.place import SpacePlace
        p = _place(slug="curated", name="Curated")
        db.add(p)
        db.flush()

        # Public + active + no auto_grant_role — should appear.
        included = make_space(
            slug="included-coll", name="Included",
            is_public=True, themes=["Wellbeing"],
        )
        # Private space — must not appear on the public detail.
        private = make_space(
            slug="private-coll", name="Private",
            is_public=False, themes=["Should not appear"],
        )
        # Draft — must not appear.
        drafted = make_space(
            slug="drafted-coll", name="Drafted",
            status="draft", is_public=True, themes=["Also skipped"],
        )
        db.add_all([
            SpacePlace(space_id=included.id, place_id=p.id),
            SpacePlace(space_id=private.id,  place_id=p.id),
            SpacePlace(space_id=drafted.id,  place_id=p.id),
        ])
        db.flush()

        detail = get_place("curated", db=db)
        assert [c.slug for c in detail.collectives] == ["included-coll"]
        assert detail.collective_count == 1
        # Themes list comes from the surviving Collective(s) only.
        assert detail.themes == ["Wellbeing"]

    def test_upcoming_gatherings_are_public_and_future(
        self, db, discovery_enabled, make_space, make_event,
    ):
        from datetime import datetime, timedelta
        from app.models.place import SpacePlace
        p = _place(slug="with-events", name="With Events")
        db.add(p)
        db.flush()

        space = make_space(is_public=True)
        db.add(SpacePlace(space_id=space.id, place_id=p.id))
        db.flush()

        future = datetime.utcnow() + timedelta(days=4)
        past   = datetime.utcnow() - timedelta(days=4)
        # Public future — shows up.
        make_event(
            space=space, title="Open Circle",
            starts_at=future, ends_at=future + timedelta(hours=1),
            is_public=True,
        )
        # Private future (not paid_separately) — hidden. The
        # make_event fixture defaults ``booking_access_type`` to
        # 'paid_separately' for the ticket flow's happy path, so an
        # override is required here to make this event truly private.
        make_event(
            space=space, title="Members Only",
            starts_at=future + timedelta(days=1),
            ends_at=future + timedelta(days=1, hours=1),
            is_public=False,
            booking_access_type="included_with_collective",
        )
        # Public past — hidden.
        make_event(
            space=space, title="Was Yesterday",
            starts_at=past, ends_at=past + timedelta(hours=1),
            is_public=True,
        )
        db.flush()

        detail = get_place("with-events", db=db)
        titles = [g.title for g in detail.upcoming_gatherings]
        assert "Open Circle" in titles
        assert "Members Only" not in titles
        assert "Was Yesterday" not in titles

    def test_gathering_projection_omits_venue_address(
        self, db, discovery_enabled, make_space, make_event,
    ):
        from datetime import datetime, timedelta
        from app.models.place import SpacePlace
        p = _place(slug="private-venue", name="Private Venue")
        db.add(p)
        db.flush()
        space = make_space(is_public=True)
        db.add(SpacePlace(space_id=space.id, place_id=p.id))
        db.flush()

        starts = datetime.utcnow() + timedelta(days=2)
        make_event(
            space=space, title="Somatic Circle",
            starts_at=starts, ends_at=starts + timedelta(hours=1),
            is_public=True,
            venue_name="Private residence · South Croydon",
            venue_address="12 Actual Street, South Croydon VIC 3136",
        )
        db.flush()

        detail = get_place("private-venue", db=db)
        [g] = detail.upcoming_gatherings
        assert g.venue_name == "Private residence · South Croydon"
        # Only coarse locality reaches the public shape.
        assert "venue_address" not in g.model_dump()

    def test_artwork_payload_surfaces_when_set(self, db, discovery_enabled):
        db.add(_place(
            slug="apollo-bay",
            name="Apollo Bay",
            country_code="AU",
            hero_artwork_url="/api/uploads/place-artwork/apollo-bay/hero.jpg",
            artwork_alt_text="Coastal cliffs at sunrise",
            artwork_focal_x=0.35,
            artwork_focal_y=0.6,
        ))
        db.flush()
        [row] = list_places(db)
        assert row.hero_artwork_url == "/api/uploads/place-artwork/apollo-bay/hero.jpg"
        assert row.artwork_alt_text == "Coastal cliffs at sunrise"
        assert row.artwork_focal_x == pytest.approx(0.35)
        assert row.artwork_focal_y == pytest.approx(0.6)

    def test_artwork_defaults_are_null_and_center(self, db, discovery_enabled):
        db.add(_place(slug="hobart", name="Hobart"))
        db.flush()
        [row] = list_places(db)
        assert row.hero_artwork_url is None
        assert row.artwork_alt_text is None
        assert row.artwork_focal_x == 0.5
        assert row.artwork_focal_y == 0.5


# ---------------------------------------------------------------------------
# POST /api/places/lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def test_returns_provider_suggestions(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        install_fake_provider(search_results=[MELBOURNE_SUGGESTION])
        creator = make_user(role="creator")

        resp = _run(lookup_places(LookupRequest(query="melb"), _user=creator))
        assert len(resp.results) == 1
        row = resp.results[0]
        assert row.provider_place_id == "osm:node:12345"
        assert row.display == "Melbourne, Victoria, Australia"
        assert row.name == "Melbourne"
        assert row.country_code == "AU"

    def test_empty_provider_response_returns_empty_list(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        install_fake_provider(search_results=[])
        creator = make_user(role="creator")

        resp = _run(lookup_places(LookupRequest(query="nowhere"), _user=creator))
        assert resp.results == []


# ---------------------------------------------------------------------------
# POST /api/places/resolve
# ---------------------------------------------------------------------------

class TestResolve:
    def test_creates_place_from_provider_payload(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        install_fake_provider(fetch_result=MELBOURNE_SUGGESTION)
        creator = make_user(role="creator")

        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:node:12345"),
            db=db,
            _user=creator,
        ))

        assert resp.created is True
        assert resp.name == "Melbourne"
        assert resp.region == "Victoria"
        assert resp.country_code == "AU"
        assert resp.latitude == pytest.approx(-37.8136)
        assert resp.timezone == "Australia/Melbourne"
        assert resp.slug == "melbourne"
        # And it persisted.
        stored = db.query(Place).filter(Place.provider_place_id == "osm:node:12345").one()
        assert stored.name == "Melbourne"

    def test_picker_created_place_lands_as_draft(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # Physical Locations are curated by admins. A picker-driven
        # resolve therefore lands as ``draft`` so nothing suburb-level
        # ever slips onto Discover Places automatically — only after
        # an admin promotes the row does it become member-visible.
        install_fake_provider(fetch_result=MELBOURNE_SUGGESTION)
        creator = make_user(role="creator")

        _run(resolve_place(
            ResolveRequest(provider_place_id="osm:node:12345"),
            db=db,
            _user=creator,
        ))
        stored = db.query(Place).filter(Place.provider_place_id == "osm:node:12345").one()
        assert stored.status == "draft"

    def test_existing_active_place_stays_active_on_resolve(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # If the admin has already curated the area to ``active``,
        # resolving the same provider id from a Creator must not
        # regress its status.
        db.add(_place(
            slug="melbourne",
            name="Melbourne",
            status="active",
            provider_place_id="osm:node:12345",
        ))
        db.commit()

        install_fake_provider(fetch_result=MELBOURNE_SUGGESTION)
        creator = make_user(role="creator")
        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:node:12345"),
            db=db,
            _user=creator,
        ))
        assert resp.created is False
        stored = db.query(Place).filter(Place.provider_place_id == "osm:node:12345").one()
        assert stored.status == "active"

    def test_dedupes_by_provider_place_id(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # Existing row for the same provider id — resolve should
        # return it, not create another.
        db.add(_place(
            slug="melbourne",
            name="Melbourne",
            provider_place_id="osm:node:12345",
            latitude=-37.8136,
            longitude=144.9631,
        ))
        db.commit()

        install_fake_provider(fetch_result=MELBOURNE_SUGGESTION)
        creator = make_user(role="creator")

        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:node:12345"),
            db=db,
            _user=creator,
        ))

        assert resp.created is False
        assert resp.name == "Melbourne"
        # Only one row across the whole table.
        rows = db.query(Place).filter(Place.provider_place_id == "osm:node:12345").all()
        assert len(rows) == 1

    def test_provider_miss_returns_404(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        install_fake_provider(fetch_result=None)
        creator = make_user(role="creator")

        with pytest.raises(HTTPException) as exc:
            _run(resolve_place(
                ResolveRequest(provider_place_id="osm:node:404"),
                db=db,
                _user=creator,
            ))
        assert exc.value.status_code == 404

    def test_collision_appends_numeric_suffix(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # A different Place already claims the "melbourne" slug (e.g.
        # seeded manually with no provider payload). Resolving a real
        # provider payload should not error — it appends "-2".
        db.add(_place(slug="melbourne", name="Melbourne", provider_place_id=None))
        db.commit()

        install_fake_provider(fetch_result=MELBOURNE_SUGGESTION)
        creator = make_user(role="creator")

        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:node:12345"),
            db=db,
            _user=creator,
        ))

        assert resp.created is True
        assert resp.slug == "melbourne-2"
