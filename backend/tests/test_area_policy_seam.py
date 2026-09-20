"""Area policy, end to end.

The rule the earlier phases kept breaking: a hidden doorway must be
hidden *everywhere* — nav, tiles, route and API — and all four must be
reading one answer rather than each deriving it. So these walk the
seams rather than the units.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_user, get_optional_user, get_verified_current_user,
)
from app.core.database import get_db
from app.main import app
from app.models.access_pass import (
    AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
)
from app.models.platform import Event, SpaceMembership


@pytest.fixture
def discovery_enabled(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "discovery_pillar_enabled", True)
    yield


@pytest.fixture
def make_place_with_space(db, make_space):
    """A Place with one active Collective linked to it — the shape
    Discover Places renders."""
    from app.models.place import Place, SpacePlace

    def _factory(**space_kwargs):
        space = make_space(is_public=True, **space_kwargs)
        place = Place(
            id=f"place_{uuid.uuid4().hex[:12]}",
            slug=f"place-{uuid.uuid4().hex[:8]}",
            name="South Croydon",
            country_code="AU",
            status="active",
        )
        db.add(place)
        db.add(SpacePlace(space_id=space.id, place_id=place.id))
        db.flush()
        return space, place

    return _factory


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    for dep in (get_current_user, get_optional_user, get_verified_current_user):
        app.dependency_overrides[dep] = lambda u=user: u


def as_anonymous():
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides.pop(get_current_user, None)


def join(db, user, space, role="learner"):
    db.add(SpaceMembership(
        id=str(uuid.uuid4()), user_id=user.id, space_id=space.id,
        role=role, status="active",
    ))
    db.flush()


def give_pass(db, user, space):
    db.add(AccessPass(
        id=f"ap_{uuid.uuid4().hex[:16]}", user_id=user.id, space_id=space.id,
        pass_type=AccessPassType.term_pass, status=AccessPassStatus.active,
        source=AccessPassSource.one_time_purchase,
        valid_from=datetime.utcnow() - timedelta(days=1), valid_until=None,
    ))
    db.flush()


def add_event(db, space, *, is_public=True):
    ev = Event(
        id=str(uuid.uuid4()), space_id=space.id, title="Monday circle",
        starts_at=datetime.utcnow() + timedelta(days=3),
        ends_at=datetime.utcnow() + timedelta(days=3, hours=1),
        is_published=True, is_public=is_public, status="active",
    )
    db.add(ev); db.flush()
    return ev


class TestTheDoorwayIsShutEverywhere:
    """A hidden area must be hidden in the payload the nav and tiles
    read, AND refuse when the URL is typed directly, AND refuse at its
    API. Hiding one without the others is a decoration."""

    def test_members_only_gatherings_refuse_a_visitor_at_every_layer(
        self, client, db, make_space,
    ):
        space = make_space(is_public=True)   # gatherings default: members
        add_event(db, space)
        as_anonymous()

        payload = client.get(f"/api/spaces/{space.slug}").json()
        assert "gatherings" not in payload["area_access"]
        assert "gatherings" not in [t["key"] for t in payload["home_tiles"]]

        # The list API, which the page and any direct caller share.
        assert client.get(f"/api/spaces/{space.slug}/events").status_code == 404

    def test_a_public_gatherings_area_answers_the_same_visitor(
        self, client, db, make_space,
    ):
        space = make_space(
            is_public=True, area_policies={"areas": {"gatherings": "public"}},
        )
        add_event(db, space)
        as_anonymous()
        payload = client.get(f"/api/spaces/{space.slug}").json()
        assert "gatherings" in payload["area_access"]
        res = client.get(f"/api/spaces/{space.slug}/events")
        assert res.status_code == 200, res.text
        assert len(res.json()) == 1

    def test_the_refusal_is_indistinguishable_from_a_missing_collective(
        self, client, db, make_space,
    ):
        space = make_space(is_public=True)
        as_anonymous()
        hidden = client.get(f"/api/spaces/{space.slug}/events")
        absent = client.get("/api/spaces/no-such-collective/events")
        assert hidden.status_code == absent.status_code == 404

    def test_a_gathering_detail_is_never_more_open_than_its_list(
        self, client, db, make_space,
    ):
        space = make_space(is_public=True)
        event = add_event(db, space)
        as_anonymous()
        assert client.get(f"/api/spaces/{space.slug}/events").status_code == 404
        assert client.get(
            f"/api/spaces/{space.slug}/events/{event.id}").status_code == 404

    def test_series_endpoints_inherit_the_gatherings_policy(
        self, client, db, make_space,
    ):
        space = make_space(is_public=True)
        as_anonymous()
        assert client.get(
            f"/api/spaces/{space.slug}/gathering-series").status_code == 404

    def test_conversations_refuse_a_non_member(
        self, client, db, make_space, make_user,
    ):
        space = make_space(is_public=True)
        as_user(make_user(role="user"))
        assert client.get(f"/api/spaces/{space.slug}/community").status_code == 404


class TestActiveAccessAtTheApi:
    def test_a_lapsed_member_is_refused_and_an_entitled_one_is_not(
        self, client, db, make_space, make_user,
    ):
        space = make_space(
            is_public=True,
            area_policies={"areas": {"gatherings": "active_access"}},
        )
        add_event(db, space)

        lapsed = make_user(role="user")
        join(db, lapsed, space)
        as_user(lapsed)
        assert client.get(f"/api/spaces/{space.slug}/events").status_code == 404
        assert "gatherings" not in client.get(
            f"/api/spaces/{space.slug}").json()["area_access"]

        entitled = make_user(role="user")
        join(db, entitled, space)
        give_pass(db, entitled, space)
        as_user(entitled)
        assert client.get(f"/api/spaces/{space.slug}/events").status_code == 200
        assert "gatherings" in client.get(
            f"/api/spaces/{space.slug}").json()["area_access"]

    def test_a_lapsed_member_keeps_the_home_and_messages(
        self, client, db, make_space, make_user,
    ):
        """The two doors that must never be entitlement-gated: somewhere
        to land, and a way to ask for help about the very access
        problem that locked them out."""
        space = make_space(is_public=True, area_policies={"areas": {
            "gatherings": "active_access", "pathways": "active_access",
            "conversations": "active_access", "members": "active_access",
        }})
        lapsed = make_user(role="user")
        join(db, lapsed, space)
        as_user(lapsed)
        areas = client.get(f"/api/spaces/{space.slug}").json()["area_access"]
        assert "home" in areas
        assert "messages" in areas
        assert "about" in areas


class TestPathwaysKeepTheirPurchaseDoor:
    def test_the_list_obeys_the_policy(self, client, db, make_space, make_user):
        space = make_space(
            is_public=True, area_policies={"areas": {"pathways": "active_access"}},
        )
        lapsed = make_user(role="user")
        join(db, lapsed, space)
        as_user(lapsed)
        assert client.get(f"/api/spaces/{space.slug}/pathways").status_code == 404

    def test_but_about_is_always_reachable(self, client, db, make_space, make_user):
        """The joining and purchasing surface. Gating it would mean
        needing access to reach the page where access is bought."""
        space = make_space(is_public=True, area_policies={"areas": {
            "pathways": "active_access", "gatherings": "active_access",
        }})
        as_anonymous()
        areas = client.get(f"/api/spaces/{space.slug}").json()["area_access"]
        assert "about" in areas


class TestTilesAndAreasAgree:
    def test_every_home_tile_names_a_reachable_area(
        self, client, db, make_space, make_user,
    ):
        """The Members tile / Members tab disagreement, generalised:
        the Home must never offer a doorway the route will refuse."""
        space = make_space(is_public=True, show_member_directory=True,
                           area_policies={"areas": {
                               "gatherings": "active_access",
                               "conversations": "active_access",
                           }})
        member = make_user(role="user")
        join(db, member, space)
        as_user(member)
        payload = client.get(f"/api/spaces/{space.slug}").json()
        for tile in payload["home_tiles"]:
            assert tile["key"] in payload["area_access"], tile["key"]


class TestCacheSafety:
    def test_the_personalised_payload_is_never_shared_cached(
        self, client, db, make_space,
    ):
        space = make_space(is_public=True)
        as_anonymous()
        res = client.get(f"/api/spaces/{space.slug}")
        assert "no-store" in res.headers.get("Cache-Control", "")
        assert "private" in res.headers.get("Cache-Control", "")
        assert "Cookie" in res.headers.get("Vary", "")

    def test_one_viewers_area_set_is_not_served_to_another(
        self, client, db, make_space, make_user,
    ):
        """Same URL, same process, different answers — the property a
        shared cache would destroy."""
        space = make_space(is_public=True, show_member_directory=True,
                           area_policies={"areas": {"gatherings": "active_access"}})
        entitled = make_user(role="user")
        join(db, entitled, space)
        give_pass(db, entitled, space)
        lapsed = make_user(role="user")
        join(db, lapsed, space)

        as_user(entitled)
        rich = client.get(f"/api/spaces/{space.slug}").json()["area_access"]
        as_user(lapsed)
        poor = client.get(f"/api/spaces/{space.slug}").json()["area_access"]
        as_anonymous()
        none = client.get(f"/api/spaces/{space.slug}").json()["area_access"]

        assert "gatherings" in rich
        assert "gatherings" not in poor
        assert "conversations" in poor and "conversations" not in none
        assert rich != poor != none


class TestDiscoverPlacesIsNotABackDoor:
    def test_members_only_gatherings_do_not_appear_on_a_place_page(
        self, client, db, make_space, make_place_with_space, discovery_enabled,
    ):
        space, place = make_place_with_space(area_policies=None)
        add_event(db, space)
        as_anonymous()
        res = client.get(f"/api/places/{place.slug}")
        assert res.status_code == 200, res.text
        assert res.json()["upcoming_gatherings"] == []

    def test_public_gatherings_do_appear(
        self, client, db, make_space, make_place_with_space, discovery_enabled,
    ):
        space, place = make_place_with_space(
            area_policies={"areas": {"gatherings": "public"}},
        )
        add_event(db, space)
        as_anonymous()
        body = client.get(f"/api/places/{place.slug}").json()
        assert len(body["upcoming_gatherings"]) == 1


class TestCompatibility:
    def test_a_collective_that_has_never_configured_anything(
        self, client, db, make_space, make_user,
    ):
        """Every Collective in production on the day this ships."""
        space = make_space(is_public=True, show_member_directory=True)
        assert space.area_policies is None
        member = make_user(role="user")
        join(db, member, space)
        as_user(member)
        areas = client.get(f"/api/spaces/{space.slug}").json()["area_access"]
        assert set(areas) == {
            "about", "home", "gatherings", "pathways",
            "conversations", "members", "messages",
        }

    def test_an_invalid_write_is_refused_with_400(
        self, client, db, make_space, make_user,
    ):
        from app.auth.dependencies import get_creator_user, get_verified_creator_user
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        for dep in (get_creator_user, get_verified_creator_user):
            app.dependency_overrides[dep] = lambda u=owner: u
        as_user(owner)
        res = client.patch(
            f"/api/creator/spaces/{space.slug}",
            json={"area_policies": {"areas": {"conversations": "public"}}},
        )
        assert res.status_code == 400, res.text
        db.refresh(space)
        assert space.area_policies is None

    def test_a_valid_write_round_trips_and_shows_resolved_defaults(
        self, client, db, make_space, make_user,
    ):
        from app.auth.dependencies import get_creator_user, get_verified_creator_user
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        for dep in (get_creator_user, get_verified_creator_user):
            app.dependency_overrides[dep] = lambda u=owner: u
        as_user(owner)
        res = client.patch(
            f"/api/creator/spaces/{space.slug}",
            json={"area_policies": {"areas": {"gatherings": "public"}}},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["area_policies"]["gatherings"] == "public"
        # Unset areas show the default actually in force, not a blank.
        assert body["area_policies"]["conversations"] == "members"
        assert "gatherings" in body["area_policy_options"]
        assert "about" not in body["area_policy_options"]
