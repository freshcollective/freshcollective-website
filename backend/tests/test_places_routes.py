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

    def test_gathering_inherits_parent_collective_primary_colour(
        self, db, discovery_enabled, make_space, make_event,
    ):
        """Gathering cards must inherit the parent Collective's Colour
        Palette primary hex — the projection carries that colour so the
        client can visually mark Gatherings as belonging to a Collective
        without a second round-trip."""
        from datetime import datetime, timedelta
        from app.models.place import SpacePlace
        from app.models.platform import ColourStory

        db.add(ColourStory(
            id="cs_test", key="earth-and-moss", name="Earth & Moss",
            palette={
                "primary":    "#4B6B3A",
                "secondary":  "#7C9A6B",
                "accent":     "#B8D0A5",
                "background": "#F4F6EF",
            },
            position=0, is_active=True,
        ))
        p = _place(slug="palette-city", name="Palette City")
        db.add(p)
        db.flush()

        # Two collectives, only one with a palette assigned; the second
        # exercises the null-fallback path.
        with_palette = make_space(is_public=True, colour_story_key="earth-and-moss")
        without_palette = make_space(is_public=True)
        db.add_all([
            SpacePlace(space_id=with_palette.id,    place_id=p.id),
            SpacePlace(space_id=without_palette.id, place_id=p.id),
        ])
        db.flush()

        future = datetime.utcnow() + timedelta(days=3)
        make_event(
            space=with_palette, title="Grove Circle",
            starts_at=future, ends_at=future + timedelta(hours=1),
            is_public=True,
        )
        make_event(
            space=without_palette, title="Unstyled Circle",
            starts_at=future + timedelta(days=1),
            ends_at=future + timedelta(days=1, hours=1),
            is_public=True,
        )
        db.flush()

        detail = get_place("palette-city", db=db)
        by_title = {g.title: g for g in detail.upcoming_gatherings}
        # Primary drives the border + title; accent drives the wash.
        assert by_title["Grove Circle"].collective_primary_colour == "#4B6B3A"
        assert by_title["Grove Circle"].collective_accent_colour  == "#B8D0A5"
        assert by_title["Unstyled Circle"].collective_primary_colour is None
        assert by_title["Unstyled Circle"].collective_accent_colour  is None

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

    # -- Absorption into curated active Places --------------------------
    #
    # Nominatim exposes several OSM features for the same city
    # (Melbourne / City of Melbourne / Greater Melbourne). Dedup by
    # provider_place_id alone means a Creator picking a different
    # variant creates a fresh draft that needs admin curation. The
    # absorbing dedup closes that gap: a picker suggestion inside an
    # existing active Place's radius should link straight to the
    # curated Place, no draft, no admin step.

    def test_absorbs_nearby_pick_into_existing_active_place(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # A curated active Melbourne already exists (with its own OSM
        # relation id). The Creator picks a different OSM feature at
        # a nearby coordinate — resolve must absorb it into Melbourne
        # rather than create a draft.
        db.add(_place(
            slug="melbourne", name="Melbourne", country_code="AU",
            status="active",
            provider_place_id="osm:relation:4246124",
            latitude=-37.8142, longitude=144.9631,
        ))
        db.commit()

        # Same metro area, different OSM feature — the "City of
        # Melbourne" relation, ~2 km north.
        variant = LocationSuggestion(
            provider_place_id="osm:relation:2404870",
            name="City of Melbourne",
            region="Victoria",
            country="Australia",
            country_code="AU",
            latitude=-37.7963,
            longitude=144.9614,
            timezone="Australia/Melbourne",
        )
        install_fake_provider(fetch_result=variant)
        creator = make_user(role="creator")

        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:relation:2404870"),
            db=db,
            _user=creator,
        ))

        # Returned the curated Melbourne, not a fresh draft.
        assert resp.created is False
        assert resp.slug == "melbourne"
        # No new row was inserted.
        assert db.query(Place).count() == 1

    def test_distant_pick_still_creates_draft(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # An active Melbourne exists. A picker pick in Hobart (~600 km
        # away) is a genuinely new discovery area — it must land as a
        # draft for admin curation, not silently absorb into Melbourne.
        db.add(_place(
            slug="melbourne", name="Melbourne", country_code="AU",
            status="active",
            provider_place_id="osm:relation:4246124",
            latitude=-37.8142, longitude=144.9631,
        ))
        db.commit()

        hobart = LocationSuggestion(
            provider_place_id="osm:relation:9999999",
            name="Hobart",
            region="Tasmania",
            country="Australia",
            country_code="AU",
            latitude=-42.8821,
            longitude=147.3272,
            timezone="Australia/Hobart",
        )
        install_fake_provider(fetch_result=hobart)
        creator = make_user(role="creator")

        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:relation:9999999"),
            db=db,
            _user=creator,
        ))

        assert resp.created is True
        assert resp.slug == "hobart"
        # Newly-created row lands as a draft — admin curation still
        # governs new discovery areas.
        stored = db.query(Place).filter(
            Place.provider_place_id == "osm:relation:9999999"
        ).one()
        assert stored.status == "draft"

    def test_absorption_respects_country_code(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # Melbourne, Australia already exists as an active curated
        # Place. A Creator picking "Melbourne, Florida" from Nominatim
        # is in a different country — even if it were geographically
        # close by fluke, absorption must not cross national borders.
        db.add(_place(
            slug="melbourne", name="Melbourne", country_code="AU",
            status="active",
            provider_place_id="osm:relation:4246124",
            latitude=-37.8142, longitude=144.9631,
        ))
        db.commit()

        florida = LocationSuggestion(
            provider_place_id="osm:relation:117646",
            name="Melbourne",
            region="Florida",
            country="United States",
            country_code="US",
            latitude=28.0836,
            longitude=-80.6081,
            timezone="America/New_York",
        )
        install_fake_provider(fetch_result=florida)
        creator = make_user(role="creator")

        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:relation:117646"),
            db=db,
            _user=creator,
        ))

        # A new US draft — not absorbed into Australian Melbourne.
        assert resp.created is True
        assert resp.slug == "melbourne-2"  # slug collision handled

    def test_absorption_ignores_active_places_without_coordinates(
        self, db, discovery_enabled, make_user, install_fake_provider,
    ):
        # A seed-only Place with no lat/lng cannot participate in
        # proximity absorption. A Creator's pick creates a draft
        # instead of silently swallowing into a coordinate-less row.
        db.add(_place(
            slug="melbourne", name="Melbourne", country_code="AU",
            status="active",
            provider_place_id=None,
            latitude=None, longitude=None,
        ))
        db.commit()

        install_fake_provider(fetch_result=MELBOURNE_SUGGESTION)
        creator = make_user(role="creator")

        resp = _run(resolve_place(
            ResolveRequest(provider_place_id="osm:node:12345"),
            db=db,
            _user=creator,
        ))
        # Slug clash → -2 suffix.
        assert resp.created is True
        assert resp.slug == "melbourne-2"


# ---------------------------------------------------------------------------
# End-to-end: Collective ↔ Physical Location visibility
# ---------------------------------------------------------------------------
# The six user-visible scenarios asked for by the Discover Place fix. Each
# drives the real ``update_space`` PATCH path through to the public
# ``get_place`` read path, so a regression in either surface fails a
# named scenario rather than a helper unit test.

class TestCollectivePlaceLifecycle:
    def _melbourne(self):
        return _place(
            slug="melbourne", name="Melbourne", country_code="AU",
            status="active",
            provider_place_id="osm:relation:4246124",
            latitude=-37.8142, longitude=144.9631,
        )

    def test_in_person_collective_appears_on_place_page(
        self, db, discovery_enabled, make_space, make_user,
    ):
        from app.creator.routes import update_space
        from app.creator.schemas import SpaceUpdateRequest
        db.add(self._melbourne())
        db.flush()
        melb = db.query(Place).filter(Place.slug == "melbourne").one()
        creator = make_user(role="creator")
        space = make_space(
            creator=creator, slug="in-person-coll", name="In Person Coll",
            is_public=True, connection_style="online",
        )
        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(
                connection_style="in_person",
                primary_place_id=melb.id,
            ),
            db=db,
            current_user=creator,
        )
        detail = get_place("melbourne", db=db)
        assert [c.slug for c in detail.collectives] == ["in-person-coll"]

    def test_hybrid_collective_appears_on_place_page(
        self, db, discovery_enabled, make_space, make_user,
    ):
        """Hybrid ('both') is a participation format — the Collective
        still has a geographic home and belongs on that Place page.
        This is the specific case that regressed for The Grove."""
        from app.creator.routes import update_space
        from app.creator.schemas import SpaceUpdateRequest
        db.add(self._melbourne())
        db.flush()
        melb = db.query(Place).filter(Place.slug == "melbourne").one()
        creator = make_user(role="creator")
        space = make_space(
            creator=creator, slug="hybrid-coll", name="Hybrid Coll",
            is_public=True, connection_style="online",
        )
        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(
                connection_style="both",
                primary_place_id=melb.id,
            ),
            db=db,
            current_user=creator,
        )
        # Both the persisted style and the visibility must reflect the
        # save. Online support does not exclude the Collective from
        # its selected Place.
        db.refresh(space)
        assert space.connection_style == "both"
        detail = get_place("melbourne", db=db)
        assert [c.slug for c in detail.collectives] == ["hybrid-coll"]

    def test_online_only_collective_never_appears_on_place_page(
        self, db, discovery_enabled, make_space, make_user,
    ):
        db.add(self._melbourne())
        db.flush()
        creator = make_user(role="creator")
        make_space(
            creator=creator, slug="online-coll", name="Online Coll",
            is_public=True, connection_style="online",
        )
        detail = get_place("melbourne", db=db)
        assert detail.collectives == []

    def test_removing_place_removes_collective_from_page(
        self, db, discovery_enabled, make_space, make_user,
    ):
        from app.creator.routes import update_space
        from app.creator.schemas import SpaceUpdateRequest
        from app.models.place import SpacePlace
        db.add(self._melbourne())
        db.flush()
        melb = db.query(Place).filter(Place.slug == "melbourne").one()
        creator = make_user(role="creator")
        space = make_space(
            creator=creator, slug="fickle-coll", name="Fickle Coll",
            is_public=True, connection_style="in_person",
        )
        db.add(SpacePlace(space_id=space.id, place_id=melb.id))
        db.flush()
        assert [c.slug for c in get_place("melbourne", db=db).collectives] == ["fickle-coll"]

        # Creator flips back to online; the link must clear.
        update_space(
            slug=space.slug,
            body=SpaceUpdateRequest(connection_style="online"),
            db=db,
            current_user=creator,
        )
        assert get_place("melbourne", db=db).collectives == []

    def test_saving_same_location_repeatedly_does_not_duplicate_link(
        self, db, discovery_enabled, make_space, make_user,
    ):
        from app.creator.routes import update_space
        from app.creator.schemas import SpaceUpdateRequest
        from app.models.place import SpacePlace
        db.add(self._melbourne())
        db.flush()
        melb = db.query(Place).filter(Place.slug == "melbourne").one()
        creator = make_user(role="creator")
        space = make_space(
            creator=creator, slug="stable-coll", name="Stable Coll",
            is_public=True, connection_style="online",
        )

        for _ in range(3):
            update_space(
                slug=space.slug,
                body=SpaceUpdateRequest(
                    connection_style="both",
                    primary_place_id=melb.id,
                ),
                db=db,
                current_user=creator,
            )

        links = db.query(SpacePlace).filter(SpacePlace.space_id == space.id).all()
        assert len(links) == 1
        assert links[0].place_id == melb.id
        # And the Place page still shows one Collective, not three.
        detail = get_place("melbourne", db=db)
        assert [c.slug for c in detail.collectives] == ["stable-coll"]

    def test_hidden_archived_and_private_collectives_stay_excluded(
        self, db, discovery_enabled, make_space, make_user,
    ):
        """Public-safety filtering must survive the linkage fix — a
        Collective that has a SpacePlace link should still be hidden
        if it is private, draft, hidden or archived."""
        from app.models.place import SpacePlace
        db.add(self._melbourne())
        db.flush()
        melb = db.query(Place).filter(Place.slug == "melbourne").one()

        # Visible baseline — a public active Collective linked to Melbourne.
        visible = make_space(
            slug="visible-coll", name="Visible",
            is_public=True, status="active",
        )
        # Private (public=False) — should not appear.
        private = make_space(
            slug="private-coll", name="Private",
            is_public=False, status="active",
        )
        # Draft — should not appear.
        drafted = make_space(
            slug="drafted-coll", name="Drafted",
            is_public=True, status="draft",
        )
        # Archived (implemented as status='archived' in the enum).
        # The public query filters on ``SpaceStatus.active``, so any
        # non-active status is excluded. We assert that here.
        archived = make_space(
            slug="archived-coll", name="Archived",
            is_public=True, status="archived",
        )
        db.add_all([
            SpacePlace(space_id=visible.id,  place_id=melb.id),
            SpacePlace(space_id=private.id,  place_id=melb.id),
            SpacePlace(space_id=drafted.id,  place_id=melb.id),
            SpacePlace(space_id=archived.id, place_id=melb.id),
        ])
        db.flush()

        detail = get_place("melbourne", db=db)
        assert [c.slug for c in detail.collectives] == ["visible-coll"]
