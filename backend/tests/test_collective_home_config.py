"""Creator configuration for the member Collective Home.

The rule everything here defends: **absence is a complete
configuration.** A Collective that never opens the editor renders the
platform defaults, a Collective configured before a tile type existed
gains that tile automatically, and a creator can never configure their
way past a privacy setting the platform owns.
"""

from __future__ import annotations

import pytest

from app.spaces.home_config import (
    TILE_KEYS,
    HomeConfigError,
    resolve,
    validate,
)


def keys(tiles) -> list[str]:
    return [t["key"] for t in tiles]


class TestDefaults:
    def test_no_config_renders_every_tile_in_canonical_order(self):
        assert keys(resolve(None, show_member_directory=True)) == list(TILE_KEYS)

    @pytest.mark.parametrize("stored", [None, {}, {"tiles": []}, {"tiles": None}, "nonsense"])
    def test_every_shape_of_absence_lands_on_the_defaults(self, stored):
        assert keys(resolve(stored, show_member_directory=True)) == list(TILE_KEYS)

    def test_a_tile_the_config_predates_still_appears(self):
        """The property that means adding a tile type never requires a
        creator to reopen the editor."""
        cfg = validate({"tiles": [{"key": "about"}, {"key": "gatherings"}]})
        got = keys(resolve(cfg, show_member_directory=True))
        assert got[:2] == ["about", "gatherings"]
        for key in TILE_KEYS:
            assert key in got, f"{key} was dropped by a partial config"


class TestCreatorControls:
    def test_order_is_respected(self):
        cfg = validate({"tiles": [{"key": "about"}, {"key": "members"}, {"key": "gatherings"}]})
        assert keys(resolve(cfg, show_member_directory=True))[:3] == [
            "about", "members", "gatherings",
        ]

    def test_hiding_a_tile_removes_it(self):
        cfg = validate({"tiles": [{"key": "pathways", "visible": False}]})
        assert "pathways" not in keys(resolve(cfg, show_member_directory=True))

    def test_a_custom_description_overrides_only_its_own_tile(self):
        cfg = validate({"tiles": [{"key": "gatherings", "description": "Our Tuesday circles."}]})
        tiles = {t["key"]: t for t in resolve(cfg, show_member_directory=True)}
        assert tiles["gatherings"]["description"] == "Our Tuesday circles."
        assert tiles["pathways"]["description"] is None

    def test_a_blank_description_means_use_the_platform_copy(self):
        cfg = validate({"tiles": [{"key": "gatherings", "description": "   "}]})
        assert cfg["tiles"][0]["description"] is None

    def test_a_custom_image_is_kept(self):
        cfg = validate({"tiles": [{"key": "members", "image_url": "/api/uploads/media/x/y.webp"}]})
        tiles = {t["key"]: t for t in resolve(cfg, show_member_directory=True)}
        assert tiles["members"]["image_url"] == "/api/uploads/media/x/y.webp"


class TestPrivacyWins:
    def test_members_cannot_be_configured_back_on(self):
        """A creator must not be able to expose a directory the
        Collective has switched off."""
        cfg = validate({"tiles": [{"key": "members", "visible": True}]})
        assert "members" not in keys(resolve(cfg, show_member_directory=False))

    def test_members_appears_when_the_directory_is_on(self):
        assert "members" in keys(resolve(None, show_member_directory=True))


class TestValidation:
    def test_unknown_tile_keys_are_ignored_not_rejected(self):
        """A newer client naming a tile this server has not heard of
        must not fail the creator's whole save."""
        cfg = validate({"tiles": [{"key": "gatherings"}, {"key": "teleporter"}]})
        assert [t["key"] for t in cfg["tiles"]] == ["gatherings"]

    def test_duplicate_keys_collapse(self):
        cfg = validate({"tiles": [{"key": "about"}, {"key": "about", "visible": False}]})
        assert len(cfg["tiles"]) == 1

    @pytest.mark.parametrize("url", [
        "javascript:alert(1)",
        "http://evil.test/x.png",
        "../../etc/passwd",
        "/etc/passwd",
    ])
    def test_unsafe_image_urls_are_refused(self, url):
        with pytest.raises(HomeConfigError):
            validate({"tiles": [{"key": "about", "image_url": url}]})

    @pytest.mark.parametrize("url", [
        "/api/uploads/media/space/abc_pic.webp",
        "https://images.example.com/pic.jpg",
    ])
    def test_media_and_https_urls_are_accepted(self, url):
        cfg = validate({"tiles": [{"key": "about", "image_url": url}]})
        assert cfg["tiles"][0]["image_url"] == url

    def test_an_overlong_description_is_refused(self):
        with pytest.raises(HomeConfigError):
            validate({"tiles": [{"key": "about", "description": "x" * 400}]})

    def test_wrong_types_are_refused(self):
        with pytest.raises(HomeConfigError):
            validate({"tiles": "not a list"})
        with pytest.raises(HomeConfigError):
            validate({"tiles": [{"key": "about", "visible": "yes"}]})
        with pytest.raises(HomeConfigError):
            validate("nope")

    def test_an_empty_result_stores_nothing(self):
        """Nothing usable in, null out — the column stays clean rather
        than holding an empty document that means the same thing."""
        assert validate({"tiles": [{"key": "teleporter"}]}) is None
        assert validate({"tiles": []}) is None
        assert validate(None) is None


# ---------------------------------------------------------------------------
# Permissions on the creator endpoint
# ---------------------------------------------------------------------------


class TestPermissions:
    @staticmethod
    def _client(db, user=None):
        from fastapi.testclient import TestClient
        from app.auth.dependencies import get_current_user, get_verified_creator_user
        from app.core.database import get_db
        from app.main import app

        app.dependency_overrides[get_db] = lambda: db
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_verified_creator_user] = lambda: user
        return TestClient(app)

    def test_a_signed_out_caller_is_refused(self, db, make_space):
        space = make_space(is_public=True)
        db.flush()
        from fastapi.testclient import TestClient
        from app.core.database import get_db
        from app.main import app
        app.dependency_overrides[get_db] = lambda: db
        try:
            res = TestClient(app).put(
                f"/api/creator/spaces/{space.slug}/home-config", json={"tiles": []},
            )
            assert res.status_code in (401, 403), res.text
        finally:
            app.dependency_overrides.clear()

    def test_a_member_who_does_not_manage_the_collective_is_refused(
        self, db, make_space, make_user,
    ):
        """Creator Studio authorisation is per-Collective. Being a
        creator somewhere else is not permission here."""
        space = make_space(is_public=True)
        outsider = make_user(role="creator")
        db.flush()
        client = self._client(db, outsider)
        try:
            res = client.put(
                f"/api/creator/spaces/{space.slug}/home-config", json={"tiles": []},
            )
            assert res.status_code in (403, 404), res.text
        finally:
            from app.main import app
            app.dependency_overrides.clear()

    def test_the_owner_can_save_and_read_back(self, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        client = self._client(db, owner)
        try:
            res = client.put(
                f"/api/creator/spaces/{space.slug}/home-config",
                json={"tiles": [
                    {"key": "about", "visible": True},
                    {"key": "gatherings", "visible": False},
                ]},
            )
            assert res.status_code == 200, res.text
            body = res.json()
            assert [t["key"] for t in body["home_config"]["tiles"]] == ["about", "gatherings"]
            assert "gatherings" not in [t["key"] for t in body["home_tiles"]]
            assert "about" in body["available_keys"]

            again = client.get(f"/api/creator/spaces/{space.slug}/home-config")
            assert again.status_code == 200
            assert again.json()["home_config"] == body["home_config"]
        finally:
            from app.main import app
            app.dependency_overrides.clear()

    def test_an_invalid_payload_is_a_400_not_a_500(self, db, make_space, make_user):
        owner = make_user(role="creator")
        space = make_space(is_public=True, creator=owner)
        db.flush()
        client = self._client(db, owner)
        try:
            res = client.put(
                f"/api/creator/spaces/{space.slug}/home-config",
                json={"tiles": [{"key": "about", "image_url": "javascript:alert(1)"}]},
            )
            assert res.status_code == 400, res.text
        finally:
            from app.main import app
            app.dependency_overrides.clear()
