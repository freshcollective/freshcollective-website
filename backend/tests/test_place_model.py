"""
Model-level tests for Places, SpacePlace, Space.kind, and User.home_place_id.

These are the Phase 0 building blocks of the Discovery, Connection &
Belonging pillar. No user-visible surface yet — these tests exist to
lock down the shape of the data so later phases can build on it with
confidence.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

# User has FKs to community_care_actions; import the community_care
# model so SQLAlchemy can resolve them when this file runs in isolation.
import app.models.community_care  # noqa: F401
from app.models.place import Place, SpacePlace
from app.models.platform import Space
from app.models.user import User


def _place(**overrides) -> Place:
    """Small constructor — Places don't need a factory fixture yet."""
    defaults = dict(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=f"test-{uuid.uuid4().hex[:8]}",
        name="Test City",
        country_code="AU",
    )
    defaults.update(overrides)
    return Place(**defaults)


# ---------------------------------------------------------------------------
# Place
# ---------------------------------------------------------------------------

class TestPlace:
    def test_create_minimal_place(self, db):
        p = _place(name="Byron Bay", slug="byron-bay")
        db.add(p)
        db.flush()

        assert p.id.startswith("place_")
        # Defaults land.
        assert p.status == "active"
        assert p.region is None
        assert p.blurb is None
        assert p.created_at is not None
        assert p.updated_at is not None

    def test_slug_is_unique(self, db):
        db.add(_place(slug="melbourne"))
        db.flush()
        db.add(_place(slug="melbourne"))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_status_check_rejects_unknown_values(self, db):
        # Only 'active' and 'hidden' are permitted — deliberately no
        # 'deleted' vocabulary. Curated places are hidden, not deleted.
        db.add(_place(status="deleted"))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_status_hidden_is_allowed(self, db):
        p = _place(status="hidden")
        db.add(p)
        db.flush()
        assert p.status == "hidden"


# ---------------------------------------------------------------------------
# SpacePlace (join)
# ---------------------------------------------------------------------------

class TestSpacePlace:
    def test_attach_place_to_space(self, db, make_space):
        space = make_space()
        place = _place()
        db.add(place)
        db.flush()

        link = SpacePlace(space_id=space.id, place_id=place.id)
        db.add(link)
        db.flush()

        row = db.execute(
            select(SpacePlace).where(SpacePlace.space_id == space.id)
        ).scalar_one()
        assert row.place_id == place.id

    def test_composite_pk_prevents_duplicate_link(self, db, make_space):
        space = make_space()
        place = _place()
        db.add(place)
        db.flush()

        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_one_space_can_link_to_multiple_places(self, db, make_space):
        space = make_space()
        p1, p2 = _place(slug="a"), _place(slug="b")
        db.add_all([p1, p2])
        db.flush()

        db.add(SpacePlace(space_id=space.id, place_id=p1.id))
        db.add(SpacePlace(space_id=space.id, place_id=p2.id))
        db.flush()

        rows = db.execute(
            select(SpacePlace).where(SpacePlace.space_id == space.id)
        ).scalars().all()
        assert {r.place_id for r in rows} == {p1.id, p2.id}

    def test_space_delete_cascades_to_join(self, db, make_space):
        space = make_space()
        place = _place()
        db.add(place)
        db.flush()
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()

        db.delete(space)
        db.flush()

        remaining = db.execute(select(SpacePlace)).scalars().all()
        assert remaining == []
        # But the Place itself is untouched.
        assert db.get(Place, place.id) is not None

    def test_place_delete_cascades_to_join(self, db, make_space):
        space = make_space()
        place = _place()
        db.add(place)
        db.flush()
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()

        db.delete(place)
        db.flush()

        remaining = db.execute(select(SpacePlace)).scalars().all()
        assert remaining == []
        # But the Space itself is untouched.
        assert db.get(Space, space.id) is not None


# ---------------------------------------------------------------------------
# Space.kind
# ---------------------------------------------------------------------------

class TestSpaceKind:
    def test_default_is_standard(self, db, make_space):
        space = make_space()
        assert space.kind == "standard"

    def test_local_circle_is_allowed(self, db, make_space):
        space = make_space(kind="local_circle")
        assert space.kind == "local_circle"

    def test_kind_check_rejects_unknown_values(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_space(kind="community")


# ---------------------------------------------------------------------------
# User.home_place_id
# ---------------------------------------------------------------------------

class TestUserHomePlace:
    def test_default_is_null(self, db, make_user):
        u = make_user()
        assert u.home_place_id is None

    def test_can_set_home_place(self, db, make_user):
        p = _place(slug="brisbane", name="Brisbane")
        db.add(p)
        db.flush()

        u = make_user()
        u.home_place_id = p.id
        db.flush()

        assert u.home_place_id == p.id

    def test_place_delete_sets_home_place_null(self, db, make_user):
        p = _place(slug="perth", name="Perth")
        db.add(p)
        db.flush()

        u = make_user(home_place_id=p.id)
        assert u.home_place_id == p.id

        db.delete(p)
        db.flush()
        db.refresh(u)

        # SET NULL, not CASCADE — the person survives the Place retiring.
        assert u.home_place_id is None
        assert db.get(User, u.id) is not None


# ---------------------------------------------------------------------------
# Schema shape — belt-and-braces reflection checks
# ---------------------------------------------------------------------------

class TestSchemaShape:
    def test_places_table_has_expected_columns(self, db):
        cols = {c.name for c in inspect(Place).columns}
        assert cols == {
            "id",
            "slug",
            "name",
            "country_code",
            "region",
            "blurb",
            "latitude",
            "longitude",
            "timezone",
            "provider_place_id",
            "status",
            "created_at",
            "updated_at",
        }

    def test_space_places_is_pure_join(self, db):
        # Only three columns: two FKs and a created_at. No is_primary.
        cols = {c.name for c in inspect(SpacePlace).columns}
        assert cols == {"space_id", "place_id", "created_at"}


# ---------------------------------------------------------------------------
# Place — coordinates, timezone and dedup key (migration 092)
# ---------------------------------------------------------------------------

class TestPlacePickerFields:
    def test_defaults_are_null(self, db):
        p = _place(slug="hobart", name="Hobart")
        db.add(p)
        db.flush()
        assert p.latitude is None
        assert p.longitude is None
        assert p.timezone is None
        assert p.provider_place_id is None

    def test_can_set_picker_payload(self, db):
        p = _place(
            slug="darwin",
            name="Darwin",
            latitude=-12.4634,
            longitude=130.8456,
            timezone="Australia/Darwin",
            provider_place_id="osm:node:12345",
        )
        db.add(p)
        db.flush()
        assert p.latitude == -12.4634
        assert p.longitude == 130.8456
        assert p.timezone == "Australia/Darwin"
        assert p.provider_place_id == "osm:node:12345"

    def test_provider_place_id_is_unique(self, db):
        db.add(_place(slug="a", provider_place_id="osm:node:99"))
        db.flush()
        db.add(_place(slug="b", provider_place_id="osm:node:99"))
        with pytest.raises(IntegrityError):
            db.flush()

    def test_provider_place_id_null_is_not_unique(self, db):
        # Two Places may exist with no provider payload — e.g. legacy
        # rows or Phase 0 seeded Places.
        db.add(_place(slug="a", provider_place_id=None))
        db.add(_place(slug="b", provider_place_id=None))
        db.flush()  # must not raise


# ---------------------------------------------------------------------------
# Space.connection_style (migration 092)
# ---------------------------------------------------------------------------

class TestSpaceConnectionStyle:
    def test_default_is_online(self, db, make_space):
        s = make_space()
        assert s.connection_style == "online"

    def test_in_person_is_allowed(self, db, make_space):
        s = make_space(connection_style="in_person")
        assert s.connection_style == "in_person"

    def test_both_is_allowed(self, db, make_space):
        s = make_space(connection_style="both")
        assert s.connection_style == "both"

    def test_check_rejects_unknown_values(self, db, make_space):
        with pytest.raises(IntegrityError):
            make_space(connection_style="hybrid")
