"""Uploading a Collective banner, and keeping the one already there.

The reported symptom was "the banner doesn't reliably save or display,
but the logo works". The banner **saves** — a round trip through the
endpoint and back out of the settings response was correct before any
of this. Two real defects sat beside that, and the display question
turned out to be a precedence one rather than a persistence one.

Fixed here
----------
**The replacement was stored after the old file was deleted.** A
``save_file`` that raised left the Collective with no banner file and a
column still pointing at it: a broken image, from an upload the creator
was told had failed, which they could not undo. Both endpoints had it.

**``covers/`` was a flat shared directory** while logos were already
namespaced per Collective. The uuid prefix made collisions impossible,
so this was never a correctness bug — but a path that says who owns a
file is the arrangement every other upload uses.

Not changed, deliberately
-------------------------
The display hierarchy. Location artwork leads on the Collective pages
and the banner is the documented fallback — see
``CollectiveIdentityHeader`` and ``CollectiveArtworkHeader``. Changing
that is a design decision, not a bug fix, so the settings copy was
corrected to describe what actually happens instead.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_collective_banner_upload.py
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
    get_verified_creator_user,
)
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User

#: A minimal valid-enough PNG. The endpoints check the extension and
#: the storage layer checks the extension and size; neither decodes the
#: image, so the bytes only need to exist.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 128


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


def _stored_file_exists(url: str | None) -> bool:
    """Whether the bytes behind a ``/api/uploads/...`` URL are present.

    Checked on the filesystem because that is what the old ordering
    destroyed: the column kept its value and the file underneath it
    went, which shows up as a broken image rather than a missing URL.
    Skipped as always-true when R2 is configured, since these tests do
    not reach object storage.
    """
    from app.core import storage

    if not url:
        return False
    if storage.settings.is_r2_enabled:  # pragma: no cover - not in tests
        return True
    rel = url.removeprefix("/api/uploads/")
    return (storage.UPLOAD_DIR / rel).exists()


def base(space) -> str:
    return f"/api/creator/spaces/{space.slug}"


def upload(client, space, kind: str, name: str, data: bytes, mime: str):
    return client.post(
        f"{base(space)}/{kind}",
        files={"file": (name, io.BytesIO(data), mime)},
    )


def settings(client, space) -> dict:
    r = client.get(base(space))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


class TestUploadSaveAndRetrieve:
    def test_a_valid_banner_is_stored_and_returned(self, client, db, space):
        r = upload(client, space, "cover", "banner.png", PNG, "image/png")
        assert r.status_code == 200, r.text
        url = r.json()["cover_image_url"]
        assert url and url.startswith("/api/uploads/")

    def test_the_settings_response_carries_it(self, client, db, space):
        """The failure mode that bit us on Gathering Public location:
        stored correctly, absent from the payload the editor reloads."""
        url = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        assert settings(client, space)["cover_image_url"] == url

    def test_the_database_holds_it(self, client, db, space):
        url = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        db.expire_all()
        assert db.get(Space, space.id).cover_image_url == url

    def test_a_jpeg_is_accepted(self, client, db, space):
        """``.jpeg`` as well as ``.jpg`` — the long form is what most
        phones and photo apps produce."""
        for name in ("banner.jpg", "banner.jpeg", "BANNER.JPG"):
            r = upload(client, space, "cover", name, JPG, "image/jpeg")
            assert r.status_code == 200, f"{name}: {r.text}"

    def test_replacing_it_keeps_the_new_one(self, client, db, space):
        first = upload(
            client, space, "cover", "one.png", PNG, "image/png",
        ).json()["cover_image_url"]
        second = upload(
            client, space, "cover", "two.png", PNG, "image/png",
        ).json()["cover_image_url"]
        assert second != first
        assert settings(client, space)["cover_image_url"] == second

    def test_the_path_is_namespaced_to_the_collective(self, client, db, space):
        url = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        assert f"/covers/{space.slug}/" in url, url

    def test_two_collectives_do_not_share_a_directory(
        self, client, db, space, make_space,
    ):
        other = make_space()
        mine = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        app.dependency_overrides.clear()
        theirs_owner = db.query(User).filter(User.id == other.creator_id).one()
        try:
            theirs = upload(
                as_user(db, theirs_owner), other,
                "cover", "banner.png", PNG, "image/png",
            ).json()["cover_image_url"]
        finally:
            app.dependency_overrides.clear()
        assert space.slug in mine
        assert other.slug in theirs
        assert mine != theirs


class TestAFailedReplacementKeepsTheOldBanner:
    def test_a_rejected_extension_changes_nothing(self, client, db, space):
        before = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        bad = upload(client, space, "cover", "x.gif", b"GIF89a", "image/gif")
        assert bad.status_code == 400
        assert settings(client, space)["cover_image_url"] == before

    def test_a_storage_failure_leaves_the_banner_intact(
        self, client, db, space, monkeypatch,
    ):
        """The ordering bug. Storing the replacement first means a
        failure here cannot take the existing file with it."""
        from app.creator import routes

        before = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]

        def explode(*a, **kw):
            raise ValueError("storage is unavailable")

        monkeypatch.setattr(routes, "save_file", explode)
        r = upload(client, space, "cover", "new.png", PNG, "image/png")
        assert r.status_code >= 400, r.status_code

        db.expire_all()
        assert db.get(Space, space.id).cover_image_url == before
        # And the file is still there. The column was never the thing
        # the old ordering destroyed — it kept pointing at a path whose
        # bytes had already been deleted, which is a broken image
        # rather than a missing URL.
        assert _stored_file_exists(before), (
            "the existing banner file was deleted by a failed replacement"
        )

    def test_a_rejected_extension_leaves_the_file_on_disk_too(
        self, client, db, space,
    ):
        before = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        assert upload(
            client, space, "cover", "x.gif", b"GIF89a", "image/gif",
        ).status_code == 400
        assert _stored_file_exists(before)

    def test_an_oversized_replacement_leaves_the_file_on_disk(
        self, client, db, space, monkeypatch,
    ):
        from app.core import storage

        before = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 1024)
        r = upload(client, space, "cover", "big.png", b"\x00" * 4096,
                   "image/png")
        assert r.status_code == 400, r.status_code
        assert "size limit" in r.json()["detail"].lower()
        assert _stored_file_exists(before)
        db.expire_all()
        assert db.get(Space, space.id).cover_image_url == before

    def test_the_old_file_is_only_removed_after_the_new_one_lands(self):
        """Asserted on the source as well: the ordering is the whole
        fix, and an absence of a call is easy to reintroduce."""
        import inspect

        from app.creator import routes

        for fn in (routes.upload_cover_image, routes.upload_logo):
            body = inspect.getsource(fn)
            save_at = body.index("save_file(")
            delete_at = body.index("delete_file(")
            assert save_at < delete_at, (
                f"{fn.__name__} deletes the old file before storing the new one"
            )


class TestTheLogoAndBannerAreIndependent:
    def test_uploading_a_banner_leaves_the_logo(self, client, db, space):
        logo = upload(
            client, space, "logo", "logo.png", PNG, "image/png",
        ).json()["logo_url"]
        upload(client, space, "cover", "banner.png", PNG, "image/png")
        after = settings(client, space)
        assert after["logo_url"] == logo
        assert after["cover_image_url"] is not None

    def test_uploading_a_logo_leaves_the_banner(self, client, db, space):
        banner = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        upload(client, space, "logo", "logo.png", PNG, "image/png")
        after = settings(client, space)
        assert after["cover_image_url"] == banner
        assert after["logo_url"] is not None

    def test_removing_the_logo_leaves_the_banner(self, client, db, space):
        banner = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        upload(client, space, "logo", "logo.png", PNG, "image/png")
        r = client.delete(f"{base(space)}/logo")
        assert r.status_code == 200, r.text
        after = settings(client, space)
        assert after["logo_url"] is None
        assert after["cover_image_url"] == banner

    def test_the_banner_can_be_removed(self, client, db, space):
        """Added in the header-image work: this test previously
        recorded its absence, which was the honest state then."""
        upload(client, space, "cover", "banner.png", PNG, "image/png")
        r = client.delete(f"{base(space)}/cover")
        assert r.status_code == 200, r.text
        assert r.json()["cover_image_url"] is None
        assert settings(client, space)["cover_image_url"] is None

    def test_a_settings_save_does_not_disturb_either_image(
        self, client, db, space,
    ):
        """The PATCH that saves name, tagline and the rest never sends
        an image field, so it cannot overwrite one."""
        banner = upload(
            client, space, "cover", "banner.png", PNG, "image/png",
        ).json()["cover_image_url"]
        logo = upload(
            client, space, "logo", "logo.png", PNG, "image/png",
        ).json()["logo_url"]
        r = client.patch(base(space), json={
            "name": "Renamed Collective", "tagline": "A new line",
        })
        assert r.status_code == 200, r.text
        after = settings(client, space)
        assert after["cover_image_url"] == banner
        assert after["logo_url"] == logo


class TestOtherCollectiveImagesAreUntouched:
    def test_the_island_artwork_is_not_read_or_written(
        self, client, db, space,
    ):
        """World Artwork is strictly out of scope. Asserted rather than
        assumed, because both live on the same row."""
        row = db.get(Space, space.id)
        row.island_artwork_url = "https://cdn.test/island.png"
        row.island_artwork_version = 3
        db.commit()

        upload(client, space, "cover", "banner.png", PNG, "image/png")
        upload(client, space, "logo", "logo.png", PNG, "image/png")
        db.expire_all()

        after = db.get(Space, space.id)
        assert after.island_artwork_url == "https://cdn.test/island.png"
        assert after.island_artwork_version == 3

    def test_the_upload_endpoints_never_mention_world_artwork(self):
        import inspect

        from app.creator import routes

        for fn in (routes.upload_cover_image, routes.upload_logo,
                   routes.clear_logo):
            body = inspect.getsource(fn)
            for forbidden in ("island_artwork", "world_artwork"):
                assert forbidden not in body, f"{fn.__name__}: {forbidden}"


class TestValidation:
    @pytest.mark.parametrize("name,mime", [
        ("x.gif", "image/gif"),
        ("x.svg", "image/svg+xml"),
        ("x.webp", "image/webp"),
        ("x.pdf", "application/pdf"),
        ("x.exe", "application/octet-stream"),
        ("x", "image/png"),
    ])
    def test_the_banner_refuses_an_unsupported_type(
        self, client, db, space, name, mime,
    ):
        r = upload(client, space, "cover", name, PNG, mime)
        assert r.status_code == 400, f"{name} was accepted"
        assert settings(client, space)["cover_image_url"] is None

    def test_an_svg_cannot_be_smuggled_in_under_a_png_name(
        self, client, db, space,
    ):
        """The extension decides, and only jpg/jpeg/png pass — so a
        script-bearing SVG has no route in whatever it claims to be."""
        r = upload(client, space, "cover", "x.svg", b"<svg onload=1>",
                   "image/png")
        assert r.status_code == 400

    def test_an_oversized_upload_is_refused(self, client, db, space, monkeypatch):
        """The storage layer's own ceiling. Lowered for the test rather
        than allocating 200 MB."""
        from app.core import storage

        monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 1024)
        r = upload(client, space, "cover", "big.png", b"\x00" * 4096, "image/png")
        assert r.status_code >= 400, r.status_code
        assert settings(client, space)["cover_image_url"] is None

    def test_a_collective_with_no_banner_reports_none(self, client, db, space):
        body = settings(client, space)
        assert body["cover_image_url"] is None
        assert body["logo_url"] is None


class TestPermissions:
    def test_a_stranger_cannot_upload_a_banner(self, db, space, make_user):
        outsider = make_user(role="creator")
        try:
            r = upload(as_user(db, outsider), space,
                       "cover", "banner.png", PNG, "image/png")
            assert r.status_code in (403, 404), r.status_code
        finally:
            app.dependency_overrides.clear()
        db.expire_all()
        assert db.get(Space, space.id).cover_image_url is None

    def test_an_ordinary_member_cannot_change_the_branding(
        self, db, space, make_user,
    ):
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=member.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        try:
            client = as_user(db, member)
            assert upload(client, space, "cover", "b.png", PNG,
                          "image/png").status_code in (403, 404)
            assert upload(client, space, "logo", "l.png", PNG,
                          "image/png").status_code in (403, 404)
        finally:
            app.dependency_overrides.clear()

    def test_a_moderator_may(self, db, space, make_user):
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=moderator.id, space_id=space.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        try:
            r = upload(as_user(db, moderator), space,
                       "cover", "banner.png", PNG, "image/png")
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

    def test_another_collectives_banner_cannot_be_changed(
        self, client, db, space, make_space,
    ):
        other = make_space()
        r = upload(client, other, "cover", "banner.png", PNG, "image/png")
        assert r.status_code in (403, 404), r.status_code
        db.expire_all()
        assert db.get(Space, other.id).cover_image_url is None
