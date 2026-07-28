"""
Tests for /api/places — the Discovery pillar's minimal public read
surface.

Phase 0 locks:

  * Flag off → 503 on every request (no partial rollout, matches
    Community Care precedent).
  * Flag on  → returns active Places only.
  * Hidden Places are excluded from the list.
  * Response shape is the intentionally-small ``PlaceSummary`` — no
    member data, no Recognition data, no personalisation.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401
from app.core.config import settings
from app.models.place import Place
from app.places.routes import PlaceSummary, list_places


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
# Flag gating
# ---------------------------------------------------------------------------

class TestFlagGating:
    def test_flag_off_returns_503(self, db, discovery_disabled):
        with pytest.raises(HTTPException) as exc:
            list_places(db)
        assert exc.value.status_code == 503

    def test_flag_off_hides_data(self, db, discovery_disabled):
        # Even with an active Place present, the flag-off response is
        # 503 — the endpoint reveals nothing about what would be
        # returned when it's on.
        db.add(_place(slug="melbourne", name="Melbourne"))
        db.flush()
        with pytest.raises(HTTPException) as exc:
            list_places(db)
        assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

class TestList:
    def test_flag_on_empty_list(self, db, discovery_enabled):
        result = list_places(db)
        assert result == []

    def test_returns_active_places_only(self, db, discovery_enabled):
        db.add(_place(slug="melbourne", name="Melbourne", status="active"))
        db.add(_place(slug="perth",     name="Perth",     status="hidden"))
        db.add(_place(slug="brisbane",  name="Brisbane",  status="active"))
        db.flush()

        result = list_places(db)

        names = [p.name for p in result]
        # Alphabetical by name, hidden excluded.
        assert names == ["Brisbane", "Melbourne"]

    def test_response_shape_is_minimal(self, db, discovery_enabled):
        db.add(
            _place(
                slug="byron-bay",
                name="Byron Bay",
                country_code="AU",
                region="Northern Rivers",
                blurb="An internal editorial note that must not leak.",
            )
        )
        db.flush()

        result = list_places(db)

        assert len(result) == 1
        summary = result[0]
        assert isinstance(summary, PlaceSummary)
        assert summary.slug == "byron-bay"
        assert summary.name == "Byron Bay"
        assert summary.country_code == "AU"
        assert summary.region == "Northern Rivers"
        # PlaceSummary is deliberately narrow — no blurb, no status,
        # no timestamps. If any of these surface accidentally, this
        # assertion fails loudly.
        assert set(summary.model_dump().keys()) == {
            "id",
            "slug",
            "name",
            "country_code",
            "region",
        }
