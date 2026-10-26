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
    merge_unavailable,
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


# ---------------------------------------------------------------------------
# Offerings — the seventh tile
# ---------------------------------------------------------------------------


class TestTheOfferingsTile:
    """Offerings joined the vocabulary with no migration, which is the
    whole point of ``TILE_KEYS``: *"Adding a tile here is all it takes
    for every existing Collective to gain it."*

    These tests pin both halves of that claim — the new tile arrives in
    the right place, and nothing a creator has already saved moves.
    """

    def test_it_sits_immediately_after_pathways_by_default(self):
        got = keys(resolve(None, show_member_directory=True))
        assert got.index("offerings") == got.index("pathways") + 1

    def test_the_default_order_is_the_approved_one(self):
        assert list(TILE_KEYS) == [
            "gatherings", "pathways", "offerings", "conversations",
            "messages", "members", "about",
        ]

    def test_a_collective_that_configured_before_it_existed_still_gains_it(self):
        """The migration-free path, stated as the behaviour rather than
        the mechanism. This is a configuration saved when the
        vocabulary had six keys."""
        stored = {"tiles": [
            {"key": "about", "visible": True},
            {"key": "gatherings", "visible": True},
            {"key": "pathways", "visible": False},
            {"key": "conversations", "visible": True},
            {"key": "messages", "visible": True},
            {"key": "members", "visible": True},
        ]}
        got = keys(resolve(stored, show_member_directory=True))
        assert "offerings" in got

    def test_an_existing_configuration_keeps_its_exact_order(self):
        """The guarantee that matters most: a creator's saved layout is
        not rearranged to make room. Their tiles stay in their order and
        Offerings is appended — never spliced into position 3, which
        would silently redesign their Home."""
        stored = {"tiles": [
            {"key": "about"},
            {"key": "gatherings"},
            {"key": "conversations"},
        ]}
        got = keys(resolve(stored, show_member_directory=True))
        assert got[:3] == ["about", "gatherings", "conversations"]
        assert got.index("offerings") > 2

    def test_an_existing_configuration_keeps_its_copy_and_images(self):
        stored = {"tiles": [
            {
                "key": "gatherings",
                "description": "Our Tuesday circle.",
                "image_url": "https://example.test/g.jpg",
                "visible": True,
            },
            {"key": "pathways", "visible": False},
        ]}
        got = resolve(stored, show_member_directory=True)
        by_key = {t["key"]: t for t in got}
        assert by_key["gatherings"]["description"] == "Our Tuesday circle."
        assert by_key["gatherings"]["image_url"] == "https://example.test/g.jpg"
        # Hidden stays hidden; the new tile has not disturbed it.
        assert "pathways" not in by_key

    def test_a_creator_can_hide_it(self):
        stored = {"tiles": [{"key": "offerings", "visible": False}]}
        assert "offerings" not in keys(
            resolve(stored, show_member_directory=True),
        )

    def test_a_creator_can_reorder_it(self):
        stored = {"tiles": [
            {"key": "offerings"}, {"key": "gatherings"},
        ]}
        got = keys(resolve(stored, show_member_directory=True))
        assert got[:2] == ["offerings", "gatherings"]

    def test_a_creator_can_describe_and_illustrate_it(self):
        cfg = validate({"tiles": [{
            "key": "offerings",
            "description": "Workbooks and audio for your own time.",
            "image_url": "/api/uploads/media/abc.jpg",
        }]})
        got = resolve(cfg, show_member_directory=True)
        tile = next(t for t in got if t["key"] == "offerings")
        assert tile["description"] == "Workbooks and audio for your own time."
        assert tile["image_url"] == "/api/uploads/media/abc.jpg"

    def test_an_unreachable_area_removes_it(self):
        """How a Collective outside the Offerings pilot gets no tile.

        ``resolve`` knows nothing about pilots or feature flags — it is
        handed the areas this viewer can reach, and ``area_access``
        drops Offerings when ``offerings_available_for`` says no. One
        switch, and the tab, the catalogue route and the tile disappear
        together.
        """
        reachable = frozenset(k for k in TILE_KEYS if k != "offerings")
        got = keys(resolve(
            None, show_member_directory=True, reachable_areas=reachable,
        ))
        assert "offerings" not in got
        # And nothing else was collateral.
        assert got == [k for k in TILE_KEYS if k != "offerings"]

    def test_a_creator_cannot_configure_it_back_on(self):
        """Same rule the Members tile has: a stored ``visible: True``
        does not beat the platform's own answer about availability."""
        stored = {"tiles": [{"key": "offerings", "visible": True}]}
        got = keys(resolve(
            stored, show_member_directory=True,
            reachable_areas=frozenset(k for k in TILE_KEYS if k != "offerings"),
        ))
        assert "offerings" not in got


# ---------------------------------------------------------------------------
# A tile the editor could not show keeps its configuration
# ---------------------------------------------------------------------------


class TestUnavailableTilesAreCarriedForward:
    """``available_keys`` narrows the vocabulary by two platform
    switches a creator does not own — ``show_member_directory`` and the
    Offerings flag plus pilot scope. The editor renders no row for
    anything outside it, and the save is a whole-document PUT.

    So without ``merge_unavailable``, a creator who had set up a tile,
    lost access to the feature behind it, and then changed something
    unrelated had that tile's description, image, visibility and
    position quietly deleted — and getting the feature back handed them
    a default tile at the end of the list instead of the one they built.

    Deliberately keyed on availability rather than on Offerings, so the
    Members tile gets the same protection without a second code path.
    """

    AVAILABLE = tuple(k for k in TILE_KEYS if k != "offerings")

    def _stored(self, **offerings):
        entry = {
            "key": "offerings",
            "visible": True,
            "image_url": None,
            "description": None,
        }
        entry.update(offerings)
        return {"tiles": [
            {
                "key": "gatherings", "visible": True,
                "image_url": None, "description": None,
            },
            entry,
            {
                "key": "conversations", "visible": True,
                "image_url": None, "description": None,
            },
        ]}

    def test_its_settings_survive_an_unrelated_save(self):
        stored = self._stored(
            description="Workbooks and audio.",
            image_url="https://example.test/offerings.jpg",
        )
        # What the editor would send: it has no row for offerings.
        cleaned = validate({"tiles": [
            {"key": "gatherings", "description": "Tuesday circle."},
            {"key": "conversations"},
        ]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=self.AVAILABLE,
        )

        by_key = {t["key"]: t for t in merged["tiles"]}
        assert by_key["offerings"]["description"] == "Workbooks and audio."
        assert by_key["offerings"]["image_url"] == (
            "https://example.test/offerings.jpg"
        )
        # And the creator's actual edit landed.
        assert by_key["gatherings"]["description"] == "Tuesday circle."

    def test_its_hidden_state_survives(self):
        """Visibility is a setting like any other. A creator who turned
        the tile off should not find it on again when the feature
        returns."""
        stored = self._stored(visible=False)
        cleaned = validate({"tiles": [{"key": "gatherings"}]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=self.AVAILABLE,
        )

        offerings = next(
            t for t in merged["tiles"] if t["key"] == "offerings"
        )
        assert offerings["visible"] is False

    def test_it_keeps_the_tile_it_sat_before(self):
        """Position is remembered against its neighbour, not an index,
        so it survives the creator reordering everything else."""
        stored = self._stored()
        # Creator reverses the two tiles they can see.
        cleaned = validate({"tiles": [
            {"key": "conversations"}, {"key": "gatherings"},
        ]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=self.AVAILABLE,
        )

        keys_out = keys(merged["tiles"])
        # It sat before conversations, and still does.
        assert keys_out.index("offerings") == keys_out.index("conversations")- 1

    def test_a_tile_stored_last_stays_last(self):
        stored = {"tiles": [
            {
                "key": "gatherings", "visible": True,
                "image_url": None, "description": None,
            },
            {
                "key": "offerings", "visible": True,
                "image_url": None, "description": "Last.",
            },
        ]}
        cleaned = validate({"tiles": [{"key": "gatherings"}]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=self.AVAILABLE,
        )

        assert keys(merged["tiles"]) == ["gatherings", "offerings"]

    def test_it_is_still_hidden_from_the_member_home(self):
        """Carrying the configuration forward must not make the tile
        appear. ``resolve`` drops an unreachable area whatever is
        stored, which is what keeps this safe rather than clever."""
        stored = self._stored(description="Workbooks and audio.")
        merged = merge_unavailable(
            stored, validate({"tiles": [{"key": "gatherings"}]}),
            available_keys=self.AVAILABLE,
        )

        got = keys(resolve(
            merged, show_member_directory=True,
            reachable_areas=frozenset(self.AVAILABLE),
        ))
        assert "offerings" not in got

    def test_it_comes_back_configured_when_the_feature_returns(self):
        """The point of the whole thing: regaining the feature restores
        the tile the creator built, not a default one."""
        stored = self._stored(
            description="Workbooks and audio.",
            image_url="/api/uploads/media/mine.jpg",
        )
        merged = merge_unavailable(
            stored, validate({"tiles": [
                {"key": "gatherings"}, {"key": "conversations"},
            ]}),
            available_keys=self.AVAILABLE,
        )

        # Pilot restored — every tile available again.
        got = resolve(merged, show_member_directory=True)
        offerings = next(t for t in got if t["key"] == "offerings")
        assert offerings["description"] == "Workbooks and audio."
        assert offerings["image_url"] == "/api/uploads/media/mine.jpg"

    def test_the_members_tile_gets_the_same_protection(self):
        """Applied to availability rather than to Offerings, so the
        privacy switch behaves the same way without a second code
        path."""
        stored = {"tiles": [
            {
                "key": "members", "visible": True,
                "image_url": None, "description": "Meet everyone.",
            },
            {
                "key": "about", "visible": True,
                "image_url": None, "description": None,
            },
        ]}
        available = tuple(k for k in TILE_KEYS if k != "members")
        cleaned = validate({"tiles": [{"key": "about"}]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=available,
        )

        by_key = {t["key"]: t for t in merged["tiles"]}
        assert by_key["members"]["description"] == "Meet everyone."
        # Still withheld while the directory is off.
        assert "members" not in keys(
            resolve(merged, show_member_directory=False),
        )

    def test_nothing_is_carried_forward_for_an_available_tile(self):
        """The request stays authoritative for everything the editor
        could show. A creator removing a tile from their layout must
        not have it reinstated."""
        stored = self._stored()
        cleaned = validate({"tiles": [{"key": "gatherings"}]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=TILE_KEYS,
        )

        assert keys(merged["tiles"]) == ["gatherings"]

    def test_a_creator_clearing_everything_still_keeps_it(self):
        """``validate`` returns ``None`` for an empty document. Writing
        that would delete exactly what this protects, so the carried
        tile becomes the whole configuration."""
        stored = self._stored(description="Workbooks and audio.")

        merged = merge_unavailable(
            stored, None, available_keys=self.AVAILABLE,
        )

        assert keys(merged["tiles"]) == ["offerings"]
        assert merged["tiles"][0]["description"] == "Workbooks and audio."

    def test_no_stored_configuration_changes_nothing(self):
        cleaned = validate({"tiles": [{"key": "gatherings"}]})
        assert merge_unavailable(
            None, cleaned, available_keys=self.AVAILABLE,
        ) == cleaned
        assert merge_unavailable(
            None, None, available_keys=self.AVAILABLE,
        ) is None

    def test_a_request_naming_the_tile_is_not_duplicated(self):
        """Defence in depth. The editor cannot send a row it did not
        render, but a hand-crafted request could — and two entries for
        one key would make ordering ambiguous. ``resolve`` still
        withholds it, so this is about the document staying coherent."""
        stored = self._stored(description="Stored copy.")
        cleaned = validate({"tiles": [
            {"key": "gatherings"},
            {"key": "offerings", "description": "Request copy."},
        ]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=self.AVAILABLE,
        )

        assert keys(merged["tiles"]).count("offerings") == 1

    def test_an_unreadable_stored_row_is_dropped_not_fatal(self):
        """A hand-edited column must not make a creator's save
        impossible — they cannot fix a tile the editor will not show
        them."""
        stored = {"tiles": [
            {"key": "gatherings", "visible": True},
            {"key": "offerings", "image_url": "javascript:alert(1)"},
        ]}
        cleaned = validate({"tiles": [{"key": "gatherings"}]})

        merged = merge_unavailable(
            stored, cleaned, available_keys=self.AVAILABLE,
        )

        assert keys(merged["tiles"]) == ["gatherings"]
