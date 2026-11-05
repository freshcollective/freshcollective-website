"""What a member needs to explore their Collective's island.

Phase 2 is a read-only page. Every field it shows already lives
somewhere, and the point of these tests is that it stays that way:

    name, tagline, story, artwork   ``locations``, curated in /admin/atlas
    atmosphere words                ``spaces.atmosphere_keys`` → names
    colours                         ``spaces.colour_story_key`` → palette

There is no new endpoint. The page reads ``GET /api/spaces/{slug}``,
which is how every other Collective page is already guarded — so a
public Collective opens for anybody, a private one refuses an
anonymous caller, and there is no new way to enumerate anything.

The only backend change Phase 2 needed was carrying the Location's
long-form ``atlas_entry`` in that payload. It was already carried in
Creator Studio for Place and Feel; the member side had the short
description only, so there was no story to tell.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_collective_island_data.py
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_optional_user
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    AtmosphereOption,
    ColourStory,
    Location,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

TAGLINE = "Sheltered waters where people arrive, rest and begin again."
STORY = (
    "The water here is unusually still.\n"
    "\n"
    "People often arrive here searching for answers. More often, they "
    "discover the right questions instead."
)
HERO = "/api/uploads/atlas/moon-lagoon-hero.png"
THUMB = "/api/uploads/atlas/moon-lagoon-thumb.png"
FEELINGS = ["Calm", "Reflective", "Peaceful", "Curious", "Creative"]


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def island(db):
    row = Location(
        id=_uid("loc"), key=f"moon-lagoon-{uuid.uuid4().hex[:6]}",
        name="Moon Lagoon", description=TAGLINE, atlas_entry=STORY,
        hero_artwork_url=HERO, thumbnail_artwork_url=THUMB,
        preferred_atmospheres=["still"],
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def palette(db):
    row = ColourStory(
        id=_uid("cs"), key=f"moonlit-{uuid.uuid4().hex[:6]}", name="Moonlit",
        palette={
            "primary": "#0F5E5C", "secondary": "#123B4A",
            "accent": "#E7C65A", "background": "#F7F5F1",
        },
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def feelings(db):
    out = []
    for i, name in enumerate(FEELINGS):
        row = AtmosphereOption(
            id=_uid("ao"), key=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
            name=name, position=i,
        )
        db.add(row)
        out.append(row)
    db.flush()
    return out


@pytest.fixture
def collective(db, make_space, island, palette, feelings):
    space = make_space(name="Moonlit Circle", is_public=True)
    space.location_id = island.id
    space.colour_story_key = palette.key
    space.atmosphere_keys = [f.key for f in feelings]
    db.flush()
    db.commit()
    return space


def anonymous(db) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_optional_user] = lambda: None
    return TestClient(app)


def as_member(db, user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def payload(client, space) -> dict:
    r = client.get(f"/api/spaces/{space.slug}")
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# The data the page needs
# ---------------------------------------------------------------------------


class TestEverythingThePageNeedsIsInOnePayload:
    def test_the_island_name(self, db, collective):
        try:
            assert payload(anonymous(db), collective)["location"]["name"] == "Moon Lagoon"
        finally:
            app.dependency_overrides.clear()

    def test_the_tagline(self, db, collective):
        try:
            body = payload(anonymous(db), collective)
            assert body["location"]["description"] == TAGLINE
        finally:
            app.dependency_overrides.clear()

    def test_the_full_story(self, db, collective):
        """The one field Phase 2 had to add. The member payload carried
        the short description only, so there was no story to tell."""
        try:
            body = payload(anonymous(db), collective)
            assert body["location"]["atlas_entry"] == STORY
            # Its paragraph breaks survive — the page splits on them.
            assert "\n\n" in body["location"]["atlas_entry"]
        finally:
            app.dependency_overrides.clear()

    def test_the_hero_artwork(self, db, collective):
        try:
            body = payload(anonymous(db), collective)
            assert body["location"]["hero_artwork_url"] == HERO
            assert body["location"]["thumbnail_artwork_url"] == THUMB
        finally:
            app.dependency_overrides.clear()

    def test_the_atmosphere_words_in_the_creators_order(self, db, collective):
        try:
            body = payload(anonymous(db), collective)
            assert body["atmosphere_labels"] == FEELINGS
        finally:
            app.dependency_overrides.clear()

    def test_the_collective_palette(self, db, collective, palette):
        try:
            body = payload(anonymous(db), collective)
            assert body["colour_palette"]["palette"]["primary"] == "#0F5E5C"
        finally:
            app.dependency_overrides.clear()

    def test_the_collective_to_location_relationship(self, db, collective, island):
        try:
            body = payload(anonymous(db), collective)
            assert body["location"]["id"] == island.id
            assert body["location"]["key"] == island.key
        finally:
            app.dependency_overrides.clear()

    def test_no_second_request_is_needed(self, db, collective):
        """One payload. The page is a Server Component reading the
        Collective it is already inside."""
        try:
            body = payload(anonymous(db), collective)
            for key in ("location", "atmosphere_labels", "colour_palette", "name"):
                assert key in body, key
        finally:
            app.dependency_overrides.clear()


class TestIncompleteLocationData:
    def test_an_island_with_no_story_still_has_its_tagline(
        self, db, collective, island,
    ):
        island.atlas_entry = None
        db.commit()
        try:
            body = payload(anonymous(db), collective)
            assert body["location"]["atlas_entry"] is None
            assert body["location"]["description"] == TAGLINE
        finally:
            app.dependency_overrides.clear()

    def test_an_island_with_no_artwork_reports_none(
        self, db, collective, island,
    ):
        island.hero_artwork_url = None
        island.thumbnail_artwork_url = None
        db.commit()
        try:
            body = payload(anonymous(db), collective)
            assert body["location"]["hero_artwork_url"] is None
            assert body["location"]["thumbnail_artwork_url"] is None
        finally:
            app.dependency_overrides.clear()

    def test_a_collective_with_no_atmosphere_reports_an_empty_list(
        self, db, collective,
    ):
        collective.atmosphere_keys = []
        db.commit()
        try:
            assert payload(anonymous(db), collective)["atmosphere_labels"] == []
        finally:
            app.dependency_overrides.clear()

    def test_a_collective_with_no_palette_reports_none(self, db, collective):
        collective.colour_story_key = None
        db.commit()
        try:
            assert payload(anonymous(db), collective)["colour_palette"] is None
        finally:
            app.dependency_overrides.clear()

    def test_a_collective_with_no_location_reports_none(self, db, collective):
        """The page 404s on this — the route is about a place and there
        isn't one."""
        collective.location_id = None
        db.commit()
        try:
            assert payload(anonymous(db), collective)["location"] is None
        finally:
            app.dependency_overrides.clear()

    def test_an_archived_atmosphere_option_is_dropped_not_broken(
        self, db, collective, feelings,
    ):
        """A key that no longer resolves disappears from the labels
        rather than rendering as a raw key."""
        collective.atmosphere_keys = [feelings[0].key, "no-such-atmosphere"]
        db.commit()
        try:
            assert payload(anonymous(db), collective)["atmosphere_labels"] == [
                FEELINGS[0],
            ]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


class TestAccess:
    def test_a_public_collective_opens_for_a_prospective_member(
        self, db, collective,
    ):
        try:
            body = payload(anonymous(db), collective)
            assert body["location"]["name"] == "Moon Lagoon"
        finally:
            app.dependency_overrides.clear()

    def test_a_private_collective_refuses_an_anonymous_visitor(
        self, db, collective,
    ):
        """Which is what sends them to log in and back, through the
        existing Collective layout."""
        collective.is_public = False
        db.commit()
        try:
            r = anonymous(db).get(f"/api/spaces/{collective.slug}")
            assert r.status_code in (401, 404), r.status_code
            assert "Moon Lagoon" not in r.text
        finally:
            app.dependency_overrides.clear()

    def test_a_member_of_a_private_collective_may_explore_it(
        self, db, collective, make_user,
    ):
        collective.is_public = False
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=collective.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        try:
            body = payload(as_member(db, member), collective)
            assert body["location"]["name"] == "Moon Lagoon"
            assert body["location"]["atlas_entry"] == STORY
        finally:
            app.dependency_overrides.clear()

    def test_a_missing_collective_and_a_private_one_answer_alike(
        self, db, collective,
    ):
        """No new way to enumerate anything."""
        collective.is_public = False
        db.commit()
        try:
            client = anonymous(db)
            private = client.get(f"/api/spaces/{collective.slug}")
            missing = client.get("/api/spaces/no-such-collective-xyz")
            assert private.status_code in (401, 404)
            assert missing.status_code in (401, 404)
            assert collective.name not in private.text
        finally:
            app.dependency_overrides.clear()

    def test_one_collective_cannot_see_anothers_island(
        self, db, collective, make_space, make_user,
    ):
        """Cross-Collective isolation: the payload is per-slug and
        carries only that Collective's Location."""
        other_island = Location(
            id=_uid("loc"), key=f"other-{uuid.uuid4().hex[:6]}",
            name="Ember Ridge", description="Warm stone.",
            atlas_entry="A ridge of warm stone.",
        )
        db.add(other_island)
        db.flush()
        other = make_space(is_public=True)
        other.location_id = other_island.id
        db.commit()
        try:
            client = anonymous(db)
            mine = payload(client, collective)
            theirs = payload(client, other)
            assert mine["location"]["name"] == "Moon Lagoon"
            assert theirs["location"]["name"] == "Ember Ridge"
            assert "Ember Ridge" not in str(mine)
            assert "Moon Lagoon" not in str(theirs)
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Changing islands
# ---------------------------------------------------------------------------


class TestChangingTheIsland:
    def test_the_page_follows_the_creators_selection(
        self, db, collective, make_user,
    ):
        """No duplication to update: changing ``location_id`` changes
        what a member reads, with nothing re-authored."""
        second = Location(
            id=_uid("loc"), key=f"ember-{uuid.uuid4().hex[:6]}",
            name="Ember Ridge", description="Warm stone at dusk.",
            atlas_entry="The rock holds the day's heat.",
            hero_artwork_url="/api/uploads/atlas/ember-hero.png",
        )
        db.add(second)
        db.flush()
        db.commit()

        try:
            before = payload(anonymous(db), collective)["location"]
            assert before["name"] == "Moon Lagoon"
        finally:
            app.dependency_overrides.clear()

        collective.location_id = second.id
        db.commit()

        try:
            after = payload(anonymous(db), collective)["location"]
            assert after["name"] == "Ember Ridge"
            assert after["description"] == "Warm stone at dusk."
            assert after["atlas_entry"] == "The rock holds the day's heat."
            assert after["hero_artwork_url"] == "/api/uploads/atlas/ember-hero.png"
        finally:
            app.dependency_overrides.clear()

    def test_the_url_does_not_change_with_the_island(self, db, collective):
        """Collective-scoped, so an existing link survives a creator
        changing islands."""
        from app.models.platform import Location as _Loc

        slug_before = collective.slug
        other = _Loc(
            id=_uid("loc"), key=f"x-{uuid.uuid4().hex[:6]}", name="Elsewhere",
        )
        db.add(other)
        db.flush()
        collective.location_id = other.id
        db.commit()
        db.expire_all()
        assert db.get(Space, collective.id).slug == slug_before


# ---------------------------------------------------------------------------
# Nothing is written
# ---------------------------------------------------------------------------


class TestItOnlyReads:
    def test_reading_the_payload_changes_no_location_record(
        self, db, collective, island,
    ):
        before = (
            island.name, island.description, island.atlas_entry,
            island.hero_artwork_url, island.thumbnail_artwork_url,
            list(island.preferred_atmospheres or []),
        )
        db.commit()
        try:
            payload(anonymous(db), collective)
            payload(anonymous(db), collective)
        finally:
            app.dependency_overrides.clear()
        db.expire_all()
        after = db.get(Location, island.id)
        assert (
            after.name, after.description, after.atlas_entry,
            after.hero_artwork_url, after.thumbnail_artwork_url,
            list(after.preferred_atmospheres or []),
        ) == before

    def test_reading_changes_no_branding_preference(
        self, db, collective,
    ):
        """Phase 1's header-image choice and the uploaded banner are
        not touched by Phase 2."""
        collective.cover_image_url = "/api/uploads/covers/x/banner.png"
        collective.header_image_preference = "banner"
        collective.logo_url = "/api/uploads/logos/x/logo.png"
        db.commit()
        try:
            body = payload(anonymous(db), collective)
            # Still reported, still unchanged.
            assert body["header_image_preference"] == "banner"
        finally:
            app.dependency_overrides.clear()
        db.expire_all()
        after = db.get(Space, collective.id)
        assert after.cover_image_url == "/api/uploads/covers/x/banner.png"
        assert after.header_image_preference == "banner"
        assert after.logo_url == "/api/uploads/logos/x/logo.png"

    def test_reading_changes_no_world_artwork(self, db, collective):
        collective.island_artwork_url = "https://cdn.test/island.png"
        collective.island_artwork_version = 7
        db.commit()
        try:
            payload(anonymous(db), collective)
        finally:
            app.dependency_overrides.clear()
        db.expire_all()
        after = db.get(Space, collective.id)
        assert after.island_artwork_url == "https://cdn.test/island.png"
        assert after.island_artwork_version == 7

    def test_the_atmosphere_and_palette_tables_are_untouched(
        self, db, collective, palette, feelings,
    ):
        before_palette = dict(palette.palette)
        before_names = [f.name for f in feelings]
        db.commit()
        try:
            payload(anonymous(db), collective)
        finally:
            app.dependency_overrides.clear()
        db.expire_all()
        assert dict(db.get(ColourStory, palette.id).palette) == before_palette
        assert [
            db.get(AtmosphereOption, f.id).name for f in feelings
        ] == before_names
