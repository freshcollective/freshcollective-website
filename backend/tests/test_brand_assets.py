"""Fresh Collective brand assets — roles, defaults, overrides, resolution.

The properties worth defending here are mostly about what does NOT
happen. A role with no approved artwork must report ``missing`` rather
than quietly rendering something that looks close enough; the generic
teal square that stands in for the brand today must not be reachable
from the resolver at all; and a URL bound for an email must never be
one that only answers to a signed-in session.

No network and no R2: ``save_file`` falls back to the local uploads
directory whenever R2 credentials are absent, which is the case in
tests, and every upload here is a few hundred bytes of Pillow output.
"""

from __future__ import annotations

import io
import pathlib
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.auth.dependencies import get_admin_user, get_current_user
from app.brand import (
    BRAND_ASSET_ROLES,
    ROLE_ORDER,
    SOURCE_CUSTOM,
    SOURCE_DEFAULT,
    SOURCE_MISSING,
    UnknownBrandRoleError,
    get_role,
    resolve,
    resolve_all,
    resolve_for_email,
    storage_key_for,
    storage_subdir_for,
)
from app.brand.resolver import PUBLIC_UPLOAD_PREFIX
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.platform import PlatformArtwork


ADMIN_BASE = "/api/admin/brand-assets"
PUBLIC_BASE = "/api/brand-assets"

WITH_DEFAULT = [r for r in ROLE_ORDER if BRAND_ASSET_ROLES[r].default_path]
WITHOUT_DEFAULT = [r for r in ROLE_ORDER if not BRAND_ASSET_ROLES[r].default_path]

# Roles with no approved artwork yet — the compact and system assets,
# and only those. Spelled out rather than derived so that supplying one
# becomes a deliberate edit here, visible in review, instead of a
# silent change in a list.
EXPECTED_MISSING = [
    "compact_light_mark",
    "compact_dark_mark",
    "favicon_app_icon",
    "social_share_image",
]


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _png(width: int = 512, height: int = 512, mode: str = "RGBA") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (width, height), (56, 160, 158, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(width: int = 1200, height: int = 630) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (12, 24, 38)).save(buf, format="JPEG")
    return buf.getvalue()


def _webp(width: int = 512, height: int = 512) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), (212, 176, 72, 255)).save(buf, format="WEBP")
    return buf.getvalue()


@pytest.fixture
def admin(make_user):
    return make_user(role="admin", email_verified_at=datetime.utcnow())


@pytest.fixture
def member(make_user):
    return make_user(role="user", email_verified_at=datetime.utcnow())


@pytest.fixture
def client(db, admin):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client(db):
    """No admin override — the real ``get_admin_user`` dependency runs."""
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload(client, role: str, data: bytes, filename: str, content_type: str):
    return client.post(
        f"{ADMIN_BASE}/{role}",
        files={"file": (filename, data, content_type)},
    )


def _flatten(payload) -> dict:
    return {a["role"]: a for g in payload for a in g["assets"]}


# ===========================================================================
# 1. The role vocabulary is closed and application-defined
# ===========================================================================


class TestRoles:
    def test_every_role_is_grouped_and_described(self):
        for role in ROLE_ORDER:
            d = BRAND_ASSET_ROLES[role]
            assert d.group in ("full_logos", "compact_system"), role
            assert d.title and d.intended_use and d.recommended, role
            assert d.content_types, role

    def test_a_role_without_a_default_explains_why(self):
        for role in WITHOUT_DEFAULT:
            assert BRAND_ASSET_ROLES[role].missing_note, (
                f"{role} has no approved artwork and no note saying why — "
                "an empty preview with no explanation reads as a bug"
            )

    def test_unknown_role_raises(self):
        with pytest.raises(UnknownBrandRoleError):
            get_role("teal_square")

    def test_storage_keys_are_namespaced_away_from_world_artwork(self):
        """Brand roles share the platform_artwork table. Neither list
        may render the other's rows."""
        from app.admin.platform_artwork import PLATFORM_ARTWORK_KEYS
        for role in ROLE_ORDER:
            key = storage_key_for(role)
            assert key.startswith("brand_")
            assert key not in PLATFORM_ARTWORK_KEYS

    def test_uploads_land_under_the_public_prefix(self):
        """``platform-artwork/`` is what routes an object to the public
        bucket and the unauthenticated serve route. An email image that
        needs a session is an email image that never loads."""
        for role in ROLE_ORDER:
            assert storage_subdir_for(role).startswith("platform-artwork/"), role


# ===========================================================================
# 2. Resolution: override → approved default → missing
# ===========================================================================


class TestResolution:
    @pytest.mark.parametrize("role", WITH_DEFAULT)
    def test_role_with_approved_artwork_resolves_to_its_default(self, db, role):
        res = resolve(db, role)
        assert res.source == SOURCE_DEFAULT
        assert res.url == BRAND_ASSET_ROLES[role].default_path
        assert res.url.startswith("/brand/")
        assert res.public_url and res.public_url.startswith("http")

    @pytest.mark.parametrize("role", WITHOUT_DEFAULT)
    def test_role_without_approved_artwork_reports_missing(self, db, role):
        res = resolve(db, role)
        assert res.source == SOURCE_MISSING
        assert res.url is None
        assert res.public_url is None
        assert res.is_missing

    def test_the_missing_roles_are_exactly_the_compact_ones(self, db):
        missing = [r.role for r in resolve_all(db) if r.is_missing]
        assert missing == EXPECTED_MISSING

    def test_an_upload_wins_over_the_default(self, db, client):
        role = "primary_light_logo"
        assert resolve(db, role).source == SOURCE_DEFAULT
        assert _upload(client, role, _png(), "logo.png", "image/png").status_code == 200
        res = resolve(db, role)
        assert res.source == SOURCE_CUSTOM
        assert res.url != BRAND_ASSET_ROLES[role].default_path
        assert res.url.startswith(PUBLIC_UPLOAD_PREFIX)

    def test_reset_restores_the_approved_default(self, db, client):
        role = "alternate_light_logo"
        _upload(client, role, _png(), "logo.png", "image/png")
        assert resolve(db, role).source == SOURCE_CUSTOM

        assert client.delete(f"{ADMIN_BASE}/{role}").status_code == 200
        res = resolve(db, role)
        assert res.source == SOURCE_DEFAULT
        assert res.url == BRAND_ASSET_ROLES[role].default_path

    def test_reset_on_a_role_with_no_default_returns_it_to_missing(
        self, db, client,
    ):
        role = "compact_light_mark"
        _upload(client, role, _png(256, 256), "mark.png", "image/png")
        assert resolve(db, role).source == SOURCE_CUSTOM

        assert client.delete(f"{ADMIN_BASE}/{role}").status_code == 200
        assert resolve(db, role).source == SOURCE_MISSING

    def test_unknown_role_is_rejected_by_the_resolver(self, db):
        with pytest.raises(UnknownBrandRoleError):
            resolve(db, "logo_on_chartreuse")

    def test_resolve_all_covers_every_role_in_order(self, db):
        assert [r.role for r in resolve_all(db)] == list(ROLE_ORDER)


# ===========================================================================
# 3. No placeholder fallback, ever
# ===========================================================================


class TestNoPlaceholderFallback:
    def test_no_role_resolves_to_the_generic_teal_square(self, db):
        """The mark being replaced is a CSS-drawn teal rounded square
        with a white chip in it. It has no asset file, so the guard is
        that nothing resolves to a non-brand path — and in particular
        that no role invents a data URI or an inline shape."""
        for res in resolve_all(db):
            if res.url is None:
                continue
            assert res.url.startswith(("/brand/", PUBLIC_UPLOAD_PREFIX)), res.role
            assert not res.url.startswith("data:"), res.role

    def test_a_missing_role_yields_nothing_for_email(self, db):
        for role in WITHOUT_DEFAULT:
            assert resolve_for_email(db, role) is None, role

    def test_missing_is_reported_not_papered_over(self, client):
        assets = _flatten(client.get(ADMIN_BASE).json())
        for role in EXPECTED_MISSING:
            item = assets[role]
            assert item["source"] == "missing"
            assert item["image_url"] is None
            assert item["missing_note"], role
            assert item["can_reset"] is False, (
                "there is no approved default to reset to"
            )


# ===========================================================================
# 4. Public / email URL behaviour
# ===========================================================================


class TestPublicUrls:
    @pytest.mark.parametrize("role", WITH_DEFAULT)
    def test_defaults_are_absolute_and_anonymous(self, db, role):
        url = resolve_for_email(db, role)
        assert url is not None
        assert url.startswith(settings.resolved_public_app_url)
        assert "/brand/" in url

    def test_an_uploaded_asset_has_an_absolute_public_url(self, db, client):
        role = "logo_on_navy"
        _upload(client, role, _png(), "logo.png", "image/png")
        res = resolve(db, role)
        assert res.public_url is not None
        assert res.public_url.startswith("http")
        assert "/api/uploads/platform-artwork/" in res.public_url

    def test_an_uploaded_asset_goes_to_r2_public_directly_when_enabled(
        self, db, client, monkeypatch,
    ):
        """In R2 mode the email URL should be the public bucket origin —
        no redirect through fc-api for every inbox that opens the mail."""
        role = "logo_on_teal"
        _upload(client, role, _png(), "logo.png", "image/png")
        monkeypatch.setattr(
            type(settings), "is_r2_enabled", property(lambda self: True),
        )
        monkeypatch.setattr(settings, "r2_public_base_url", "https://media.test")
        res = resolve(db, role)
        assert res.public_url.startswith("https://media.test/platform-artwork/")

    def test_a_private_upload_url_is_never_offered_to_email(self, db):
        """Defence in depth: if a brand row ever pointed outside the
        public prefix, the email URL must be withheld rather than
        emitted as something that 403s for every recipient."""
        db.add(PlatformArtwork(
            key=storage_key_for("primary_light_logo"),
            image_url="/api/uploads/space-logos/leaked.png",
        ))
        db.flush()
        res = resolve(db, "primary_light_logo")
        assert res.source == SOURCE_CUSTOM
        assert res.public_url is None

    def test_public_endpoint_lists_every_role_including_missing(self, anon_client):
        body = anon_client.get(PUBLIC_BASE).json()
        assert [a["role"] for a in body] == list(ROLE_ORDER)
        by_role = {a["role"]: a for a in body}
        for role in EXPECTED_MISSING:
            assert by_role[role]["source"] == "missing"
            assert by_role[role]["image_url"] is None


# ===========================================================================
# 5. Validation
# ===========================================================================


class TestValidation:
    def test_svg_is_refused_with_a_reason(self, client):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="9" height="9"/></svg>'
        r = _upload(client, "primary_light_logo", svg, "logo.svg", "image/svg+xml")
        assert r.status_code == 400
        assert "SVG" in r.json()["detail"]
        assert "sanitise" in r.json()["detail"]

    def test_a_file_that_is_not_an_image_is_refused(self, client):
        r = _upload(
            client, "primary_light_logo", b"not an image at all",
            "logo.png", "image/png",
        )
        assert r.status_code == 400

    def test_an_empty_file_is_refused(self, client):
        r = _upload(client, "primary_light_logo", b"", "logo.png", "image/png")
        assert r.status_code == 400

    def test_oversized_artwork_is_refused(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.admin.brand_assets.MAX_BRAND_ASSET_BYTES", 128,
        )
        r = _upload(client, "primary_light_logo", _png(), "logo.png", "image/png")
        assert r.status_code == 400
        assert "MB" in r.json()["detail"]

    def test_too_small_is_refused(self, client):
        r = _upload(
            client, "primary_light_logo", _png(64, 64), "logo.png", "image/png",
        )
        assert r.status_code == 400
        assert "at least" in r.json()["detail"]

    def test_a_flat_jpeg_is_refused_where_transparency_matters(self, client):
        r = _upload(
            client, "primary_light_logo", _jpeg(800, 800), "logo.jpg", "image/jpeg",
        )
        assert r.status_code == 400
        assert "Transparency" in r.json()["detail"]

    def test_jpeg_is_accepted_where_a_flat_background_is_correct(self, client):
        r = _upload(
            client, "social_share_image", _jpeg(1200, 630), "card.jpg", "image/jpeg",
        )
        assert r.status_code == 200, r.json()

    def test_webp_is_accepted(self, client):
        r = _upload(
            client, "compact_light_mark", _webp(256, 256), "mark.webp", "image/webp",
        )
        assert r.status_code == 200, r.json()

    def test_a_non_square_favicon_is_refused(self, client):
        r = _upload(
            client, "favicon_app_icon", _png(512, 400), "icon.png", "image/png",
        )
        assert r.status_code == 400
        assert "square" in r.json()["detail"]

    def test_a_social_card_at_the_wrong_ratio_is_refused(self, client):
        r = _upload(
            client, "social_share_image", _jpeg(1200, 1200), "card.jpg", "image/jpeg",
        )
        assert r.status_code == 400
        assert "1.91" in r.json()["detail"]

    def test_the_declared_content_type_is_not_trusted(self, client):
        """A PNG renamed to .jpg is still a PNG, and a JPEG announced as
        a PNG is still a JPEG. The decoder decides."""
        r = _upload(
            client, "social_share_image", _jpeg(1200, 630), "card.png", "image/png",
        )
        assert r.status_code == 200, r.json()

    def test_an_unknown_role_is_404_not_a_new_slot(self, client):
        r = _upload(client, "made_up_role", _png(), "x.png", "image/png")
        assert r.status_code == 404
        assert client.delete(f"{ADMIN_BASE}/made_up_role").status_code == 404


# ===========================================================================
# 6. Authorisation
# ===========================================================================


class TestAuthorisation:
    def test_a_member_cannot_list_replace_or_reset(self, db, member):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: member
        try:
            c = TestClient(app)
            assert c.get(ADMIN_BASE).status_code in (401, 403)
            assert c.post(
                f"{ADMIN_BASE}/primary_light_logo",
                files={"file": ("l.png", _png(), "image/png")},
            ).status_code in (401, 403)
            assert c.delete(
                f"{ADMIN_BASE}/primary_light_logo",
            ).status_code in (401, 403)
        finally:
            app.dependency_overrides.clear()

    def test_an_anonymous_visitor_cannot_reach_the_admin_surface(self, anon_client):
        assert anon_client.get(ADMIN_BASE).status_code in (401, 403)

    def test_an_anonymous_visitor_can_read_the_public_map(self, anon_client):
        assert anon_client.get(PUBLIC_BASE).status_code == 200

    def test_a_member_cannot_mutate_via_the_public_route(self, anon_client):
        assert anon_client.post(PUBLIC_BASE).status_code == 405
        assert anon_client.delete(PUBLIC_BASE).status_code == 405


# ===========================================================================
# 7. The admin surface
# ===========================================================================


class TestAdminSurface:
    def test_groups_render_in_order_and_cover_every_role(self, client):
        body = client.get(ADMIN_BASE).json()
        assert [g["group"] for g in body] == ["full_logos", "compact_system"]
        assert set(_flatten(body)) == set(ROLE_ORDER)
        for g in body:
            assert g["label"] and g["description"]

    def test_storage_keys_and_filenames_are_not_the_admin_ux(self, client):
        """An admin manages "the logo on a dark background", not
        ``brand_logo_on_navy``. The key may not appear as a field."""
        body = client.get(ADMIN_BASE).json()
        for item in _flatten(body).values():
            assert "key" not in item
            assert "storage_key" not in item
            assert "filename" not in item
            assert not item["role"].startswith("brand_")

    def test_each_role_carries_its_guidance(self, client):
        for item in _flatten(client.get(ADMIN_BASE).json()).values():
            assert item["intended_use"]
            assert item["recommended"]
            assert item["accepted_formats"]

    def test_replacing_records_who_and_when(self, client, admin):
        role = "marketing_hero_logo"
        before = datetime.utcnow()
        assert _upload(client, role, _png(), "l.png", "image/png").status_code == 200
        item = _flatten(client.get(ADMIN_BASE).json())[role]
        assert item["source"] == "custom"
        assert item["updated_by"] == (admin.name or admin.email)
        assert datetime.fromisoformat(item["updated_at"]) >= before.replace(
            microsecond=0,
        )

    def test_a_default_backed_role_reports_no_attribution(self, client):
        item = _flatten(client.get(ADMIN_BASE).json())["primary_light_logo"]
        assert item["source"] == "default"
        assert item["updated_by"] is None
        assert item["updated_at"] is None, (
            "an approved default is a file in the repo; claiming it was "
            "updated at a timestamp would be a fiction"
        )

    def test_reset_is_offered_only_where_a_default_exists(self, client):
        assets = _flatten(client.get(ADMIN_BASE).json())
        for role in WITH_DEFAULT:
            assert assets[role]["can_reset"] is True, role
        for role in WITHOUT_DEFAULT:
            assert assets[role]["can_reset"] is False, role

    def test_replacing_twice_leaves_one_row_and_one_current_asset(
        self, db, client,
    ):
        role = "logo_on_teal"
        _upload(client, role, _png(), "first.png", "image/png")
        first = resolve(db, role).url
        _upload(client, role, _png(600, 600), "second.png", "image/png")
        second = resolve(db, role).url

        assert first != second
        rows = db.query(PlatformArtwork).filter(
            PlatformArtwork.key == storage_key_for(role),
        ).all()
        assert len(rows) == 1

    def test_no_thumbnail_is_generated_for_brand_artwork(self, db, client):
        """World Artwork thumbnails photographs into cards. A logo is
        already small and must not be resampled by anything but the
        browser at its final size."""
        role = "primary_light_logo"
        _upload(client, role, _png(), "l.png", "image/png")
        row = db.query(PlatformArtwork).filter(
            PlatformArtwork.key == storage_key_for(role),
        ).one()
        assert row.thumbnail_url is None

    def test_the_world_artwork_list_never_shows_brand_roles(self, client):
        """One table, two vocabularies. Neither may render the other."""
        _upload(client, "primary_light_logo", _png(), "l.png", "image/png")
        keys = {i["key"] for i in client.get("/api/admin/platform-artwork").json()}
        assert not any(k.startswith("brand_") for k in keys)

# ===========================================================================
# 8. The bundled defaults are verified by their pixels, not their names
# ===========================================================================
#
# A filename is a claim; the pixels are the fact. Phase A mapped
# ``marketing_hero_logo`` to ``…transparent-teal.png`` on the strength
# of its name and got it wrong — that file draws the wordmark in teal
# on a transparent canvas, while the approved marketing treatment is
# the gold wordmark on a deep teal gradient. These tests read each
# bundled default and assert what it actually contains, so a future
# re-point to a visually different file fails here rather than shipping.

BRAND_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "frontend" / "public" / "brand"
)

# Artwork geometry, measured from the files: the symbol occupies
# roughly y94–410 and the wordmark sits in a thin band beneath it.
SYMBOL_BAND = (94, 410)
WORDMARK_BAND = (418, 440)


def _classify(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    hi, lo = max(rgb), min(rgb)
    if hi > 225 and (hi - lo) < 28:
        return "white"
    if r > 140 and g > 105 and b < 130 and (r - b) > 50:
        return "gold"
    if (b > r + 20 or g > r + 20) and g > 70:
        return "teal"
    if b >= r and hi < 140:
        return "navy"
    return "other"


def _analyse(filename: str) -> dict:
    """Background kind plus the dominant ink colour in each band.

    Transparent artwork is composited on navy first, because white ink
    on a white matte is the exact mistake this is guarding against.
    Background is sampled per row from the left margin, which the
    artwork never reaches, so a gradient does not read as ink.
    """
    from PIL import Image

    img = Image.open(BRAND_DIR / filename).convert("RGBA")
    width, height = img.size
    transparent = img.getchannel("A").load()[2, 2] == 0

    if transparent:
        flat = Image.alpha_composite(
            Image.new("RGBA", img.size, (12, 24, 38, 255)), img,
        ).convert("RGB")
    else:
        flat = img.convert("RGB")
    px = flat.load()

    if transparent:
        background = "transparent"
    else:
        top, bottom = px[4, int(height * 0.02)], px[4, int(height * 0.98)]
        drift = sum(abs(u - v) for u, v in zip(top, bottom))
        background = (
            f"{_classify(top)}_gradient" if drift > 30 else f"{_classify(top)}_flat"
        )

    def dominant(y0: int, y1: int) -> str:
        counts: dict[str, int] = {}
        for y in range(y0, y1):
            row_bg = px[4, y]
            for x in range(width):
                pixel = px[x, y]
                if sum(abs(u - v) for u, v in zip(pixel, row_bg)) < 90:
                    continue
                key = _classify(pixel)
                counts[key] = counts.get(key, 0) + 1
        counts.pop("other", None)
        return max(counts, key=counts.__getitem__) if counts else "none"

    return {
        "background": background,
        "dragonfly": dominant(*SYMBOL_BAND),
        "wordmark": dominant(*WORDMARK_BAND),
    }


# The approved brand system, as content rather than as filenames.
APPROVED_CONTENT: dict[str, dict[str, str]] = {
    "primary_light_logo": {
        "background": "white_flat", "dragonfly": "navy", "wordmark": "gold",
    },
    "alternate_light_logo": {
        "background": "white_flat", "dragonfly": "teal", "wordmark": "gold",
    },
    # The distinguishing feature is the WHITE wordmark. Its sibling on
    # the teal gradient sets the wordmark in gold and is a different
    # role; swapping them is the mistake this table exists to catch.
    "logo_on_teal": {
        "background": "teal_flat", "dragonfly": "white", "wordmark": "white",
    },
    "logo_on_navy": {
        "background": "navy_flat", "dragonfly": "white", "wordmark": "gold",
    },
    "marketing_hero_logo": {
        "background": "teal_gradient", "dragonfly": "white", "wordmark": "gold",
    },
}


class TestApprovedArtworkContent:
    @pytest.mark.parametrize("role", sorted(APPROVED_CONTENT))
    def test_the_bundled_default_contains_the_approved_artwork(self, role):
        default = BRAND_ASSET_ROLES[role].default_path
        assert default, f"{role} lost its approved default"
        assert _analyse(default.removeprefix("/brand/")) == APPROVED_CONTENT[role]

    def test_every_default_backed_role_is_content_verified(self):
        """No role may hold a bundled default that nothing above checks."""
        assert set(APPROVED_CONTENT) == {
            r for r in ROLE_ORDER if BRAND_ASSET_ROLES[r].default_path
        }

    def test_the_two_teal_treatments_are_not_interchangeable(self):
        """The error this whole suite exists to prevent. Both roles put
        a white dragonfly on teal; they differ in the wordmark and in
        whether the background is flat or a gradient. Reading the
        filename gets this wrong, and an earlier pass did."""
        flat = _analyse(
            BRAND_ASSET_ROLES["logo_on_teal"].default_path.removeprefix("/brand/"),
        )
        gradient = _analyse(
            BRAND_ASSET_ROLES["marketing_hero_logo"]
            .default_path.removeprefix("/brand/"),
        )
        assert flat["wordmark"] == "white"
        assert gradient["wordmark"] == "gold"
        assert flat["background"] == "teal_flat"
        assert gradient["background"] == "teal_gradient"
        assert flat != gradient

    def test_every_full_logo_role_is_filled(self):
        """The five full-logo roles all have approved artwork; only the
        compact and system roles are outstanding."""
        full = [
            r for r in ROLE_ORDER
            if BRAND_ASSET_ROLES[r].group == "full_logos"
        ]
        assert len(full) == 5
        for role in full:
            assert BRAND_ASSET_ROLES[role].default_path, role
            assert role not in EXPECTED_MISSING

    def test_each_role_has_a_distinct_visual_identity(self):
        """No two roles may resolve to artwork that reads the same.
        Identical content across two roles means one of them is filled
        with something that merely resembles what it needs."""
        seen: dict[tuple, str] = {}
        for role, expected in APPROVED_CONTENT.items():
            signature = tuple(sorted(expected.items()))
            assert signature not in seen, (
                f"{role} and {seen.get(signature)} describe the same artwork"
            )
            seen[signature] = role

    def test_no_two_roles_share_one_asset(self):
        """A shared default would mean two roles are the same job, or
        one of them is filled with something that only resembles it."""
        defaults = [
            BRAND_ASSET_ROLES[r].default_path
            for r in ROLE_ORDER
            if BRAND_ASSET_ROLES[r].default_path
        ]
        assert len(defaults) == len(set(defaults))

    def test_every_bundled_default_actually_exists_on_disk(self):
        for role in ROLE_ORDER:
            default = BRAND_ASSET_ROLES[role].default_path
            if default is None:
                continue
            assert (BRAND_DIR / default.removeprefix("/brand/")).is_file(), role
