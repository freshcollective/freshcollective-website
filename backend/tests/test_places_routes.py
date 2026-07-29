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

    def test_response_shape_is_minimal(self, db, discovery_enabled):
        db.add(_place(
            slug="byron-bay",
            name="Byron Bay",
            country_code="AU",
            region="Northern Rivers",
            blurb="Editorial note that must not leak.",
        ))
        db.flush()
        result = list_places(db)
        assert len(result) == 1
        assert isinstance(result[0], PlaceSummary)
        assert set(result[0].model_dump().keys()) == {
            "id", "slug", "name", "country_code", "region",
        }


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
