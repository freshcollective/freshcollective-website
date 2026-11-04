"""Which image welcomes people into a Collective.

A Collective has two visual identities: the creator's own brand, and
its home in the Fresh Collective world. Until now the second always
won — every header, card and signup page read Location artwork first
and the creator's uploaded banner last, each with its own slightly
different fallback chain. A creator who uploaded a banner saw it
nowhere.

Phase 1 gives the creator the choice, through one rule asked by every
primary Collective surface.

The two properties that matter most
-----------------------------------
**No existing Collective changes appearance.** The column defaults to
``'location'`` with no backfill, so a Collective holding a banner from
before this existed looks exactly as it did — and its banner is still
there, selectable without a re-upload.

**The fallback is safe in one direction only.** A creator who chose
their banner and whose banner has gone sees their Location artwork
rather than a broken image, and *their stored choice is not changed by
that*. The display falls back; the preference does not.

World Artwork is untouched. Location artwork is read for display and
never written, and ``island_artwork_*`` is not read at all — there are
tests for both.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_collective_header_image.py
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import (
    get_creator_user,
    get_current_user,
    get_optional_user,
    get_verified_creator_user,
)
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    Location,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services.collective_header_image import (
    DEFAULT_PREFERENCE,
    PREFER_BANNER,
    PREFER_LOCATION,
    collective_header_image,
    normalise_preference,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
BANNER = "/api/uploads/covers/x/banner.png"
HERO = "/atlas/moon-lagoon-hero.png"
THUMB = "/atlas/moon-lagoon-thumb.png"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(make_space):
    return make_space()


@pytest.fixture
def owner(db, space):
    return db.query(User).filter(User.id == space.creator_id).one()


@pytest.fixture
def client(db, owner):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_creator_user] = lambda: owner
    app.dependency_overrides[get_verified_creator_user] = lambda: owner
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(db, user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_creator_user] = lambda: user
    app.dependency_overrides[get_verified_creator_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def with_location(db, space):
    """A Collective in an Atlas Location, as most are."""
    loc = Location(
        id=_uid("loc"), key=f"moon-lagoon-{uuid.uuid4().hex[:6]}",
        name="Moon Lagoon", description="Still water.",
        hero_artwork_url=HERO, thumbnail_artwork_url=THUMB,
    )
    db.add(loc)
    db.flush()
    space.location_id = loc.id
    db.flush()
    return loc


def base(space) -> str:
    return f"/api/creator/spaces/{space.slug}"


def settings(client, space) -> dict:
    r = client.get(base(space))
    assert r.status_code == 200, r.text
    return r.json()


def upload_banner(client, space):
    return client.post(
        f"{base(space)}/cover",
        files={"file": ("banner.png", io.BytesIO(PNG), "image/png")},
    )


def set_preference(client, space, value: str):
    return client.patch(base(space), json={"header_image_preference": value})


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


class TestTheRule:
    @pytest.mark.parametrize("preference,banner,hero,thumb,expected", [
        # The creator chose their banner.
        (PREFER_BANNER, BANNER, HERO, THUMB, BANNER),
        (PREFER_BANNER, BANNER, None, None, BANNER),
        # The creator chose Location artwork.
        (PREFER_LOCATION, BANNER, HERO, THUMB, HERO),
        (PREFER_LOCATION, None, None, THUMB, THUMB),
        # The pre-existing legacy fallback, unchanged.
        (PREFER_LOCATION, BANNER, None, None, BANNER),
        # The safe fallback: chose the banner, banner gone.
        (PREFER_BANNER, None, HERO, None, HERO),
        (PREFER_BANNER, "   ", HERO, None, HERO),
        # Nothing at all.
        (PREFER_LOCATION, None, None, None, None),
        (PREFER_BANNER, None, None, None, None),
    ])
    def test_each_case(self, preference, banner, hero, thumb, expected):
        assert collective_header_image(
            preference=preference, banner_url=banner,
            location_hero_url=hero, location_thumbnail_url=thumb,
        ) == expected

    @pytest.mark.parametrize("stored", [None, "", "   ", "nonsense", "BANNER"])
    def test_an_unrecognised_preference_reads_as_the_default(self, stored):
        """Never as the banner — a bad value must not be able to change
        how a Collective looks."""
        assert normalise_preference(stored) == DEFAULT_PREFERENCE
        assert collective_header_image(
            preference=stored, banner_url=BANNER, location_hero_url=HERO,
        ) == HERO

    def test_the_default_is_location(self):
        assert DEFAULT_PREFERENCE == PREFER_LOCATION

    def test_the_frontend_mirror_agrees(self):
        """Two implementations of one small rule. If one changes, the
        shape of the other should look wrong here."""
        import pathlib

        ts = (
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "frontend" / "src" / "lib" / "collectiveHeaderImage.ts"
        ).read_text()
        assert "export const PREFER_LOCATION = 'location'" in ts
        assert "export const PREFER_BANNER = 'banner'" in ts
        assert "return hero ?? thumbnail ?? banner" in ts


# ---------------------------------------------------------------------------
# Existing Collectives
# ---------------------------------------------------------------------------


class TestNothingChangesForAnExistingCollective:
    def test_a_fresh_collective_defaults_to_location(
        self, client, db, space, with_location,
    ):
        db.commit()
        body = settings(client, space)
        assert body["header_image_preference"] == PREFER_LOCATION
        assert body["header_image_url"] == HERO

    def test_a_collective_holding_a_banner_still_shows_its_location(
        self, client, db, space, with_location,
    ):
        """The one thing this must not do: change how an existing
        Collective looks because a column was added. A banner uploaded
        before the preference existed reads as ``'location'``."""
        space.cover_image_url = BANNER
        db.commit()
        body = settings(client, space)
        assert body["header_image_preference"] == PREFER_LOCATION
        assert body["header_image_url"] == HERO
        # And the banner is still stored, ready to be chosen.
        assert body["cover_image_url"] == BANNER

    def test_a_collective_with_no_location_still_shows_its_banner(
        self, client, db, space,
    ):
        """The legacy fallback. Unchanged."""
        space.cover_image_url = BANNER
        db.commit()
        body = settings(client, space)
        assert body["header_image_url"] == BANNER

    def test_the_column_default_is_location(self, db, space):
        db.commit()
        db.expire_all()
        assert db.get(Space, space.id).header_image_preference == PREFER_LOCATION


# ---------------------------------------------------------------------------
# Choosing
# ---------------------------------------------------------------------------


class TestChoosing:
    def test_uploading_a_banner_selects_it(
        self, client, db, space, with_location,
    ):
        """A creator who has just chosen an image wants to see it."""
        db.commit()
        body = upload_banner(client, space).json()
        assert body["header_image_preference"] == PREFER_BANNER
        assert body["header_image_url"] == body["cover_image_url"]
        assert body["header_image_url"] != HERO

    def test_switching_to_location_keeps_the_banner(
        self, client, db, space, with_location,
    ):
        db.commit()
        banner = upload_banner(client, space).json()["cover_image_url"]
        r = set_preference(client, space, PREFER_LOCATION)
        assert r.status_code == 200, r.text
        body = settings(client, space)
        assert body["header_image_preference"] == PREFER_LOCATION
        assert body["header_image_url"] == HERO
        assert body["cover_image_url"] == banner, "the banner was discarded"

    def test_switching_back_needs_no_re_upload(
        self, client, db, space, with_location,
    ):
        db.commit()
        banner = upload_banner(client, space).json()["cover_image_url"]
        set_preference(client, space, PREFER_LOCATION)
        r = set_preference(client, space, PREFER_BANNER)
        assert r.status_code == 200, r.text
        body = settings(client, space)
        assert body["header_image_preference"] == PREFER_BANNER
        assert body["header_image_url"] == banner

    def test_choosing_a_banner_that_does_not_exist_is_refused(
        self, client, db, space, with_location,
    ):
        """Rather than stored as a preference pointing at nothing."""
        db.commit()
        r = set_preference(client, space, PREFER_BANNER)
        assert r.status_code == 400, r.text
        assert "upload a banner" in r.json()["detail"].lower()
        assert settings(client, space)["header_image_preference"] == PREFER_LOCATION

    def test_an_invalid_preference_is_refused(self, client, db, space):
        db.commit()
        r = set_preference(client, space, "island")
        assert r.status_code == 422, r.status_code
        assert settings(client, space)["header_image_preference"] == PREFER_LOCATION

    def test_replacing_a_banner_keeps_the_banner_selected(
        self, client, db, space, with_location,
    ):
        db.commit()
        first = upload_banner(client, space).json()["cover_image_url"]
        second = upload_banner(client, space).json()
        assert second["cover_image_url"] != first
        assert second["header_image_preference"] == PREFER_BANNER
        assert second["header_image_url"] == second["cover_image_url"]

    def test_a_failed_upload_changes_neither_the_banner_nor_the_choice(
        self, client, db, space, with_location,
    ):
        db.commit()
        banner = upload_banner(client, space).json()["cover_image_url"]
        set_preference(client, space, PREFER_LOCATION)
        bad = client.post(
            f"{base(space)}/cover",
            files={"file": ("x.gif", io.BytesIO(b"GIF89a"), "image/gif")},
        )
        assert bad.status_code == 400
        body = settings(client, space)
        assert body["cover_image_url"] == banner
        assert body["header_image_preference"] == PREFER_LOCATION


class TestRemoving:
    def test_removing_returns_to_location(
        self, client, db, space, with_location,
    ):
        db.commit()
        upload_banner(client, space)
        r = client.delete(f"{base(space)}/cover")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cover_image_url"] is None
        assert body["header_image_preference"] == PREFER_LOCATION
        assert body["header_image_url"] == HERO

    def test_removing_preserves_the_location_assignment(
        self, client, db, space, with_location,
    ):
        """The island artwork and the Location choice are untouched."""
        db.commit()
        upload_banner(client, space)
        client.delete(f"{base(space)}/cover")
        db.expire_all()
        reloaded = db.get(Space, space.id)
        assert reloaded.location_id == with_location.id
        loc = db.get(Location, with_location.id)
        assert loc.hero_artwork_url == HERO
        assert loc.thumbnail_artwork_url == THUMB

    def test_removing_preserves_the_logo(
        self, client, db, space, with_location,
    ):
        db.commit()
        logo = client.post(
            f"{base(space)}/logo",
            files={"file": ("logo.png", io.BytesIO(PNG), "image/png")},
        ).json()["logo_url"]
        upload_banner(client, space)
        client.delete(f"{base(space)}/cover")
        assert settings(client, space)["logo_url"] == logo

    def test_removing_when_there_is_nothing_to_remove_is_harmless(
        self, client, db, space, with_location,
    ):
        db.commit()
        r = client.delete(f"{base(space)}/cover")
        assert r.status_code == 200, r.text
        assert r.json()["header_image_preference"] == PREFER_LOCATION


# ---------------------------------------------------------------------------
# Serialisation across the surfaces
# ---------------------------------------------------------------------------


class TestEverySurfaceGetsTheSameAnswer:
    def test_the_member_space_payload_carries_it(
        self, client, db, space, with_location, make_user,
    ):
        space.is_public = True
        db.commit()
        upload_banner(client, space)
        banner = settings(client, space)["cover_image_url"]
        app.dependency_overrides.clear()

        viewer = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=viewer.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: viewer
        app.dependency_overrides[get_current_user] = lambda: viewer
        try:
            body = TestClient(app).get(f"/api/spaces/{space.slug}").json()
            assert body["header_image_preference"] == PREFER_BANNER
            assert body["header_image_url"] == banner
            # The Location fields are untouched — the island card on
            # the About page reads these whatever the header shows.
            assert body["location"]["hero_artwork_url"] == HERO
            assert body["location"]["thumbnail_artwork_url"] == THUMB
        finally:
            app.dependency_overrides.clear()

    def test_the_public_about_payload_carries_it(
        self, client, db, space, with_location,
    ):
        space.is_public = True
        db.commit()
        upload_banner(client, space)
        banner = settings(client, space)["cover_image_url"]
        app.dependency_overrides.clear()
        try:
            r = TestClient(app).get(f"/api/public/spaces/{space.slug}/about")
            if r.status_code != 200:
                pytest.skip(f"About is not public for this Collective ({r.status_code})")
            body = r.json()
            assert body["header_image_preference"] == PREFER_BANNER
            assert body["header_image_url"] == banner
            assert body["location_hero_artwork_url"] == HERO
        finally:
            app.dependency_overrides.clear()

    def test_the_explore_card_carries_it_and_the_location_name(
        self, client, db, space, with_location,
    ):
        from app.spaces.routes import hydrate_public_space_cards

        space.is_public = True
        db.commit()
        upload_banner(client, space)
        db.expire_all()
        cards = hydrate_public_space_cards([db.get(Space, space.id)], db)
        assert len(cards) == 1
        card = cards[0]
        assert card.header_image_preference == PREFER_BANNER
        assert card.header_image_url == db.get(Space, space.id).cover_image_url
        # The Location is still named, so a Collective is discoverable
        # by its atmosphere as well as its creator's branding.
        assert card.location_name == "Moon Lagoon"
        assert card.location_hero_artwork_url == HERO

    def test_an_explore_card_on_location_shows_the_location(
        self, client, db, space, with_location,
    ):
        from app.spaces.routes import hydrate_public_space_cards

        space.is_public = True
        space.cover_image_url = BANNER
        db.commit()
        cards = hydrate_public_space_cards([db.get(Space, space.id)], db)
        assert cards[0].header_image_preference == PREFER_LOCATION
        assert cards[0].header_image_url == HERO


# ---------------------------------------------------------------------------
# World Artwork
# ---------------------------------------------------------------------------


class TestWorldArtworkIsUntouched:
    def test_choosing_and_removing_never_writes_island_artwork(
        self, client, db, space, with_location,
    ):
        row = db.get(Space, space.id)
        row.island_artwork_url = "https://cdn.test/island.png"
        row.island_artwork_version = 4
        row.island_artwork_status = "ready"
        db.commit()

        upload_banner(client, space)
        set_preference(client, space, PREFER_LOCATION)
        set_preference(client, space, PREFER_BANNER)
        client.delete(f"{base(space)}/cover")
        db.expire_all()

        after = db.get(Space, space.id)
        assert after.island_artwork_url == "https://cdn.test/island.png"
        assert after.island_artwork_version == 4
        assert after.island_artwork_status == "ready"

    def test_the_location_row_is_never_written(
        self, client, db, space, with_location,
    ):
        before = (
            with_location.hero_artwork_url,
            with_location.thumbnail_artwork_url,
            with_location.name,
            with_location.description,
        )
        db.commit()
        upload_banner(client, space)
        set_preference(client, space, PREFER_LOCATION)
        client.delete(f"{base(space)}/cover")
        db.expire_all()
        loc = db.get(Location, with_location.id)
        assert (
            loc.hero_artwork_url, loc.thumbnail_artwork_url,
            loc.name, loc.description,
        ) == before

    def test_the_rule_never_reads_island_artwork(self):
        """Location artwork is read for display; the island artwork is
        a different thing and is not part of this at all."""
        import inspect

        from app.services import collective_header_image as mod

        source = inspect.getsource(mod)
        body = source.split('"""', 2)[2] if source.count('"""') >= 2 else source
        assert "island_artwork" not in body

    def test_the_migration_does_not_backfill(self):
        """A backfill to ``'banner'`` for Collectives holding a cover
        is the one thing it must not do."""
        import pathlib

        migration = (
            pathlib.Path(__file__).resolve().parent.parent
            / "alembic" / "versions"
            / "181_collective_header_image_preference.py"
        ).read_text()
        upgrade = migration.split("def upgrade()")[1].split("def downgrade()")[0]
        assert "UPDATE" not in upgrade.upper().replace("UPGRADE", "")
        assert 'server_default="location"' in upgrade


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_a_stranger_cannot_choose(self, db, space, make_user):
        space.cover_image_url = BANNER
        db.commit()
        outsider = make_user(role="creator")
        try:
            r = set_preference(as_user(db, outsider), space, PREFER_BANNER)
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()
        db.expire_all()
        assert db.get(Space, space.id).header_image_preference == PREFER_LOCATION

    def test_an_ordinary_member_cannot_choose(self, db, space, make_user):
        space.cover_image_url = BANNER
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        try:
            client = as_user(db, member)
            assert set_preference(
                client, space, PREFER_BANNER,
            ).status_code in (403, 404)
            assert client.delete(
                f"{base(space)}/cover",
            ).status_code in (403, 404)
        finally:
            app.dependency_overrides.clear()

    def test_a_moderator_may(self, db, space, make_user):
        space.cover_image_url = BANNER
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=moderator.id, space_id=space.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        try:
            r = set_preference(as_user(db, moderator), space, PREFER_BANNER)
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

    def test_another_collective_cannot_be_changed(
        self, client, db, space, make_space,
    ):
        other = make_space()
        other.cover_image_url = BANNER
        db.commit()
        assert set_preference(
            client, other, PREFER_BANNER,
        ).status_code in (403, 404)
        assert client.delete(
            f"/api/creator/spaces/{other.slug}/cover",
        ).status_code in (403, 404)
        db.expire_all()
        assert db.get(Space, other.id).header_image_preference == PREFER_LOCATION
        assert db.get(Space, other.id).cover_image_url == BANNER
