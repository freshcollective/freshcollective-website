"""
Route tests for the Physical Locations admin surface
(``/api/admin/physical-locations/*``).

Tests call the endpoint functions directly, matching the pattern used
in ``test_admin_periodic_endpoints.py``. This exercises validation,
Pydantic response shapes, and DB effects without booting the auth
stack. Admin-only access is separately verified by asserting that
``get_admin_user`` rejects non-admin callers.

See ``docs/foundations/discovery-connection-belonging-location-model.md``.
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile

# Sibling model imports SQLAlchemy needs to resolve when this file runs
# in isolation. See ``test_place_model.py`` for the same reason.
import app.models.community_care  # noqa: F401
from app.admin.physical_locations import (
    PhysicalLocationCreateRequest,
    PhysicalLocationUpdateRequest,
    clear_artwork,
    create_location,
    delete_location,
    get_location,
    list_locations,
    update_location,
    upload_artwork,
)
from app.models.place import Place, SpacePlace
from app.models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _place(**overrides) -> Place:
    defaults = dict(
        id=f"place_{uuid.uuid4().hex[:12]}",
        slug=f"loc-{uuid.uuid4().hex[:8]}",
        name="Somewhere",
        country_code="AU",
        status="active",
    )
    defaults.update(overrides)
    return Place(**defaults)


# A 1x1 transparent PNG — small enough to keep the test lean.
_PNG_BYTES = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
    "890000000D49444154789C6360000000000200015F0F0000000049454E44AE426082"
)


def _png_upload(filename: str = "hero.png") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(_PNG_BYTES),
        filename=filename,
        headers={"content-type": "image/png"},  # type: ignore[arg-type]
    )


def _webp_bytes() -> bytes:
    """A tiny in-memory WebP so tests exercise the format the admin
    UI actually receives from the browser."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (128, 200, 190)).save(
        buf, format="WEBP", quality=85, method=6,
    )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Admin-only access
# ---------------------------------------------------------------------------

class TestAdminOnly:
    def test_non_admin_rejected_by_dependency(self, db, make_user):
        from app.auth.dependencies import get_admin_user

        member = make_user(role="user")
        creator = make_user(role="creator")

        with pytest.raises(HTTPException) as ex:
            get_admin_user(current_user=member)
        assert ex.value.status_code == 403

        with pytest.raises(HTTPException) as ex:
            get_admin_user(current_user=creator)
        assert ex.value.status_code == 403

    def test_admin_passes(self, db, make_user):
        from app.auth.dependencies import get_admin_user

        admin = make_user(role="admin")
        assert get_admin_user(current_user=admin) is admin


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestList:
    def test_returns_all_locations_by_default(self, db, make_user):
        admin = make_user(role="admin")
        db.add_all([
            _place(slug="alpha", name="Alpha City"),
            _place(slug="beta", name="Beta Town"),
        ])
        db.flush()

        rows = list_locations(
            q=None, status=None, country=None, sort="alphabetical",
            db=db, _=admin,
        )
        slugs = {r.slug for r in rows}
        assert {"alpha", "beta"}.issubset(slugs)

    def test_search_matches_name_case_insensitively(self, db, make_user):
        admin = make_user(role="admin")
        db.add_all([
            _place(slug="melb", name="Melbourne"),
            _place(slug="syd",  name="Sydney"),
        ])
        db.flush()

        rows = list_locations(
            q="mel", status=None, country=None, sort="alphabetical",
            db=db, _=admin,
        )
        assert [r.slug for r in rows] == ["melb"]

    def test_search_matches_region(self, db, make_user):
        admin = make_user(role="admin")
        db.add(_place(
            slug="byron", name="Byron Bay", region="Northern Rivers"
        ))
        db.flush()

        rows = list_locations(
            q="northern", status=None, country=None, sort="alphabetical",
            db=db, _=admin,
        )
        assert any(r.slug == "byron" for r in rows)

    def test_status_filter(self, db, make_user):
        admin = make_user(role="admin")
        db.add_all([
            _place(slug="a-draft",    status="draft"),
            _place(slug="b-active",   status="active"),
            _place(slug="c-archived", status="archived"),
        ])
        db.flush()

        rows = list_locations(
            q=None, status="draft", country=None, sort="alphabetical",
            db=db, _=admin,
        )
        assert [r.slug for r in rows] == ["a-draft"]

    def test_status_filter_rejects_unknown(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            list_locations(
                q=None, status="banana", country=None, sort="alphabetical",
                db=db, _=admin,
            )
        assert ex.value.status_code == 400

    def test_country_filter_uppercases(self, db, make_user):
        admin = make_user(role="admin")
        db.add_all([
            _place(slug="au-a", country_code="AU"),
            _place(slug="nz-a", country_code="NZ"),
        ])
        db.flush()

        rows = list_locations(
            q=None, status=None, country="au", sort="alphabetical",
            db=db, _=admin,
        )
        slugs = {r.slug for r in rows}
        assert "au-a" in slugs
        assert "nz-a" not in slugs

    def test_sort_rejects_unknown(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            list_locations(
                q=None, status=None, country=None, sort="chronological",
                db=db, _=admin,
            )
        assert ex.value.status_code == 400

    def test_sort_most_collectives_orders_by_active_count(
        self, db, make_user, make_space
    ):
        admin = make_user(role="admin")
        top = _place(slug="popular", name="Popular")
        mid = _place(slug="middling", name="Middling")
        empty = _place(slug="quiet", name="Quiet")
        db.add_all([top, mid, empty])
        db.flush()

        # Two active collectives on `top`, one on `mid`, none on `empty`.
        s1 = make_space()
        s2 = make_space()
        s3 = make_space()
        db.add_all([
            SpacePlace(space_id=s1.id, place_id=top.id),
            SpacePlace(space_id=s2.id, place_id=top.id),
            SpacePlace(space_id=s3.id, place_id=mid.id),
        ])
        db.flush()

        rows = list_locations(
            q=None, status=None, country=None, sort="most-collectives",
            db=db, _=admin,
        )
        # First three by count; others may follow if the DB is not empty.
        by_slug = {r.slug: r for r in rows}
        assert by_slug["popular"].collective_count == 2
        assert by_slug["middling"].collective_count == 1
        assert by_slug["quiet"].collective_count == 0
        # `top` must appear before `mid`, which must appear before `empty`.
        ordering = [r.slug for r in rows]
        assert ordering.index("popular") < ordering.index("middling")
        assert ordering.index("middling") < ordering.index("quiet")


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

class TestDetail:
    def test_returns_full_shape(self, db, make_user):
        admin = make_user(role="admin")
        p = _place(
            slug="detail-me", name="Detail Me",
            region="Central", blurb="Nice place.",
            admin_note="Internal only.",
        )
        db.add(p)
        db.flush()

        detail = get_location(slug="detail-me", db=db, _=admin)
        assert detail.slug == "detail-me"
        assert detail.name == "Detail Me"
        assert detail.region == "Central"
        assert detail.blurb == "Nice place."
        assert detail.admin_note == "Internal only."
        assert detail.artwork_focal_x == 0.5
        assert detail.artwork_focal_y == 0.5
        assert detail.collectives == []
        assert detail.collective_count == 0

    def test_lists_linked_collectives(self, db, make_user, make_space):
        admin = make_user(role="admin")
        p = _place(slug="joined", name="Joined")
        db.add(p)
        db.flush()

        s = make_space()
        db.add(SpacePlace(space_id=s.id, place_id=p.id))
        db.flush()

        detail = get_location(slug="joined", db=db, _=admin)
        assert len(detail.collectives) == 1
        assert detail.collectives[0].id == s.id
        assert detail.collective_count == 1

    def test_missing_slug_is_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            get_location(slug="nope", db=db, _=admin)
        assert ex.value.status_code == 404


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_creates_with_generated_slug(self, db, make_user):
        admin = make_user(role="admin")
        body = PhysicalLocationCreateRequest(
            name="Perth", country_code="au",
        )
        result = create_location(body=body, db=db, _=admin)
        assert result.name == "Perth"
        assert result.slug == "perth"
        assert result.country_code == "AU"
        # Default status for freshly-created rows is 'draft'.
        assert result.status == "draft"

    def test_slug_collision_is_disambiguated(self, db, make_user):
        admin = make_user(role="admin")
        db.add(_place(slug="darwin", name="Darwin"))
        db.flush()

        body = PhysicalLocationCreateRequest(name="Darwin", country_code="AU")
        result = create_location(body=body, db=db, _=admin)
        assert result.slug == "darwin-2"

    def test_status_defaults_to_draft(self, db, make_user):
        admin = make_user(role="admin")
        body = PhysicalLocationCreateRequest(name="Hobart", country_code="AU")
        result = create_location(body=body, db=db, _=admin)
        assert result.status == "draft"

    def test_status_validation_rejects_unknown(self):
        with pytest.raises(ValueError):
            PhysicalLocationCreateRequest(
                name="X", country_code="AU", status="deleted",
            )

    def test_explicit_slug_is_honored(self, db, make_user):
        admin = make_user(role="admin")
        body = PhysicalLocationCreateRequest(
            name="Byron Bay", slug="byron-bay-editorial", country_code="AU",
        )
        result = create_location(body=body, db=db, _=admin)
        assert result.slug == "byron-bay-editorial"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_updates_only_supplied_fields(self, db, make_user):
        admin = make_user(role="admin")
        p = _place(
            slug="patchable", name="Old Name", region="Old Region",
            blurb="old blurb", admin_note="old note", status="draft",
        )
        db.add(p)
        db.flush()

        body = PhysicalLocationUpdateRequest(status="active")
        result = update_location(slug="patchable", body=body, db=db, _=admin)
        assert result.name == "Old Name"
        assert result.region == "Old Region"
        assert result.blurb == "old blurb"
        assert result.admin_note == "old note"
        assert result.status == "active"

    def test_slug_change_is_deduped(self, db, make_user):
        admin = make_user(role="admin")
        db.add(_place(slug="taken"))
        p = _place(slug="movable", name="Movable")
        db.add(p)
        db.flush()

        body = PhysicalLocationUpdateRequest(slug="taken")
        result = update_location(slug="movable", body=body, db=db, _=admin)
        assert result.slug == "taken-2"

    def test_focal_point_update_persists(self, db, make_user):
        admin = make_user(role="admin")
        p = _place(slug="focus-me", name="Focus Me")
        db.add(p)
        db.flush()

        body = PhysicalLocationUpdateRequest(
            artwork_focal_x=0.25, artwork_focal_y=0.75,
        )
        result = update_location(slug="focus-me", body=body, db=db, _=admin)
        assert result.artwork_focal_x == pytest.approx(0.25)
        assert result.artwork_focal_y == pytest.approx(0.75)

    def test_focal_point_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            PhysicalLocationUpdateRequest(artwork_focal_x=1.5)

    def test_missing_slug_is_404(self, db, make_user):
        admin = make_user(role="admin")
        body = PhysicalLocationUpdateRequest(name="Nobody")
        with pytest.raises(HTTPException) as ex:
            update_location(slug="ghost", body=body, db=db, _=admin)
        assert ex.value.status_code == 404


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

class TestArtwork:
    def test_upload_sets_url_under_public_platform_artwork_namespace(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        admin = make_user(role="admin")
        p = _place(slug="art-upload", name="Art Upload")
        db.add(p)
        db.flush()

        result = asyncio.run(upload_artwork(
            slug="art-upload", file=_png_upload(), db=db, _=admin,
        ))
        assert result.hero_artwork_url is not None
        # Public namespace so ``_bucket_for_key`` routes to the public
        # bucket and the frontend renders through the unauthenticated
        # /api/uploads/platform-artwork/* path.
        assert result.hero_artwork_url.startswith(
            "/api/uploads/platform-artwork/place-artwork/art-upload/"
        )
        assert result.hero_artwork_url.endswith(".png")

    def test_upload_accepts_webp(self, db, make_user, monkeypatch, tmp_path):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        admin = make_user(role="admin")
        p = _place(slug="webp-place", name="WebP Place")
        db.add(p)
        db.flush()

        webp_upload = UploadFile(
            file=io.BytesIO(_webp_bytes()),
            filename="hero.webp",
            headers={"content-type": "image/webp"},  # type: ignore[arg-type]
        )
        result = asyncio.run(upload_artwork(
            slug="webp-place", file=webp_upload, db=db, _=admin,
        ))
        assert result.hero_artwork_url is not None
        assert result.hero_artwork_url.startswith(
            "/api/uploads/platform-artwork/place-artwork/webp-place/"
        )
        assert result.hero_artwork_url.endswith(".webp")

    def test_replacement_deletes_old_object_after_commit(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        # Prime an existing artwork file on disk under the new path.
        subdir = tmp_path / "platform-artwork" / "place-artwork" / "replace-me"
        subdir.mkdir(parents=True)
        old_file = subdir / "OLD_hero.png"
        old_file.write_bytes(_PNG_BYTES)

        admin = make_user(role="admin")
        p = _place(
            slug="replace-me", name="Replace Me",
            hero_artwork_url=(
                "/api/uploads/platform-artwork/place-artwork/replace-me/OLD_hero.png"
            ),
        )
        db.add(p)
        db.flush()

        result = asyncio.run(upload_artwork(
            slug="replace-me", file=_png_upload(), db=db, _=admin,
        ))
        assert result.hero_artwork_url != (
            "/api/uploads/platform-artwork/place-artwork/replace-me/OLD_hero.png"
        )
        assert not old_file.exists(), "old artwork should have been cleaned up"

    def test_failed_replacement_preserves_existing_artwork(
        self, db, make_user, monkeypatch, tmp_path,
    ):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        # Prime an existing artwork file — simulate the DB and disk
        # already carrying a valid pointer.
        subdir = tmp_path / "platform-artwork" / "place-artwork" / "safe-fail"
        subdir.mkdir(parents=True)
        keep = subdir / "KEEP_hero.png"
        keep.write_bytes(_PNG_BYTES)
        original_url = (
            "/api/uploads/platform-artwork/place-artwork/safe-fail/KEEP_hero.png"
        )

        admin = make_user(role="admin")
        p = _place(
            slug="safe-fail", name="Safe Fail",
            hero_artwork_url=original_url,
        )
        db.add(p)
        db.flush()

        bad = UploadFile(
            file=io.BytesIO(b"not an image"),
            filename="hero.txt",
            headers={"content-type": "text/plain"},  # type: ignore[arg-type]
        )
        with pytest.raises(HTTPException) as ex:
            asyncio.run(upload_artwork(
                slug="safe-fail", file=bad, db=db, _=admin,
            ))
        assert ex.value.status_code == 400
        # Existing artwork MUST still be on disk and still referenced
        # in the DB — a failed replacement must not destroy the
        # working artwork.
        assert keep.exists(), "existing artwork was destroyed by failed upload"
        db.refresh(p)
        assert p.hero_artwork_url == original_url

    def test_upload_preserves_focal_point(self, db, make_user, monkeypatch, tmp_path):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        admin = make_user(role="admin")
        p = _place(
            slug="focal-preserve", name="Focal Preserve",
            artwork_focal_x=0.3, artwork_focal_y=0.7,
        )
        db.add(p)
        db.flush()

        result = asyncio.run(upload_artwork(
            slug="focal-preserve", file=_png_upload(), db=db, _=admin,
        ))
        assert result.artwork_focal_x == pytest.approx(0.3)
        assert result.artwork_focal_y == pytest.approx(0.7)

    def test_upload_rejects_non_image(self, db, make_user):
        admin = make_user(role="admin")
        p = _place(slug="reject-me", name="Reject Me")
        db.add(p)
        db.flush()

        bad = UploadFile(
            file=io.BytesIO(b"not an image"),
            filename="hero.txt",
            headers={"content-type": "text/plain"},  # type: ignore[arg-type]
        )
        with pytest.raises(HTTPException) as ex:
            asyncio.run(upload_artwork(
                slug="reject-me", file=bad, db=db, _=admin,
            ))
        assert ex.value.status_code == 400

    def test_upload_missing_slug_is_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            asyncio.run(upload_artwork(
                slug="ghost", file=_png_upload(), db=db, _=admin,
            ))
        assert ex.value.status_code == 404

    def test_clear_resets_artwork_and_focal_point(self, db, make_user, monkeypatch, tmp_path):
        from app.core import storage as storage_module
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)

        # Deliberately use the LEGACY private-namespace URL so this test
        # also proves ``clear_artwork`` can remove pre-fix artwork.
        admin = make_user(role="admin")
        p = _place(
            slug="clear-me", name="Clear Me",
            hero_artwork_url="/api/uploads/place-artwork/clear-me/existing.png",
            artwork_alt_text="A photo.",
            artwork_focal_x=0.2, artwork_focal_y=0.8,
        )
        db.add(p)
        db.flush()

        result = clear_artwork(slug="clear-me", db=db, _=admin)
        assert result.hero_artwork_url is None
        assert result.artwork_alt_text is None
        # Focal point is reset to the safe centre default.
        assert result.artwork_focal_x == 0.5
        assert result.artwork_focal_y == 0.5

    def test_clear_missing_slug_is_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            clear_artwork(slug="ghost", db=db, _=admin)
        assert ex.value.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_deletes_unlinked_location(self, db, make_user):
        admin = make_user(role="admin")
        p = _place(slug="disposable", name="Disposable")
        db.add(p)
        db.flush()

        result = delete_location(slug="disposable", db=db, _=admin)
        assert result is None
        assert db.get(Place, p.id) is None

    def test_blocked_when_collectives_linked(self, db, make_user, make_space):
        admin = make_user(role="admin")
        p = _place(slug="popular", name="Popular")
        db.add(p)
        db.flush()
        s = make_space()
        db.add(SpacePlace(space_id=s.id, place_id=p.id))
        db.flush()

        with pytest.raises(HTTPException) as ex:
            delete_location(slug="popular", db=db, _=admin)
        assert ex.value.status_code == 409
        assert "linked" in ex.value.detail.lower()
        # Row must survive the failed attempt.
        assert db.get(Place, p.id) is not None

    def test_blocked_by_any_collective_not_just_active(
        self, db, make_user, make_space,
    ):
        # A draft or archived Collective still counts as a link — the
        # admin has to move / remove the association first regardless
        # of the Collective's own status.
        admin = make_user(role="admin")
        p = _place(slug="quiet", name="Quiet")
        db.add(p)
        db.flush()
        s = make_space(status="draft")
        db.add(SpacePlace(space_id=s.id, place_id=p.id))
        db.flush()

        with pytest.raises(HTTPException) as ex:
            delete_location(slug="quiet", db=db, _=admin)
        assert ex.value.status_code == 409

    def test_delete_after_link_removed_succeeds(self, db, make_user, make_space):
        admin = make_user(role="admin")
        p = _place(slug="freed", name="Freed")
        db.add(p)
        db.flush()
        s = make_space()
        link = SpacePlace(space_id=s.id, place_id=p.id)
        db.add(link)
        db.flush()

        # Simulate the admin moving the Collective's Physical Location
        # elsewhere (delete the link row).
        db.delete(link)
        db.flush()

        delete_location(slug="freed", db=db, _=admin)
        assert db.get(Place, p.id) is None

    def test_missing_slug_is_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ex:
            delete_location(slug="ghost", db=db, _=admin)
        assert ex.value.status_code == 404

    def test_home_place_reference_does_not_block_delete(self, db, make_user):
        # ``users.home_place_id`` is a personal preference with an
        # ``ON DELETE SET NULL`` FK — it must not block deletion.
        admin = make_user(role="admin")
        p = _place(slug="settable", name="Settable")
        db.add(p)
        db.flush()

        member = make_user(role="user", home_place_id=p.id)
        assert member.home_place_id == p.id

        delete_location(slug="settable", db=db, _=admin)
        assert db.get(Place, p.id) is None
        # Member survives; their home place cleanly nulls.
        db.refresh(member)
        assert db.get(User, member.id) is not None
        assert member.home_place_id is None
