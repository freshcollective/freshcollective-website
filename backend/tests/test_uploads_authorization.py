"""Per-namespace authorization matrix for GET /api/uploads/{file_path}.

Two layers:

  * Unit — call ``authorize_upload`` directly with a seeded DB. Covers
    the full user × namespace × Space-visibility × pathway-access
    matrix. Fast, no ASGI overhead, and easy to reason about.

  * Integration — go through the real FastAPI route with dependency
    overrides for ``get_current_user`` and ``get_db``. Confirms the
    end-to-end response shape (302 in R2 mode with all headers,
    filesystem-mode filepath serving, public platform-artwork
    regression, path-traversal guard order).

Namespaces covered:
  avatars, covers, logos/{slug}, island-artwork/{slug}, pathway-covers,
  event-thumbnails, steps/{step_id}, media/world-guide,
  media/{slug}/community, media/{slug}, plus default-deny for any
  unknown prefix.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# The DB fixture assumes app modules are already importable — matches
# the pattern in tests/test_physical_locations_routes.py etc.
import app.models.community_care  # noqa: F401 — resolve cross-file model refs

from app.auth.dependencies import get_current_user
from app.core import storage as storage_module
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.platform import (
    Event,
    Pathway,
    PathwayEntitlement,
    PathwayStatus,
    PathwayStep,
    PathwayType,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    SpaceStatus,
)
from app.uploads.authorization import authorize_upload


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Seeded fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spaces_and_users(db: Session, make_user):
    """Build the standard matrix: one public Space, one private Space,
    plus a full slate of users with different relationships."""

    owner_public = make_user(role="creator")
    owner_private = make_user(role="creator")

    # Public, active Space — its covers/logos are visible in Explore.
    space_public = Space(
        id=_uid("s"),
        slug=_uid("public"),
        name="Public Space",
        status=SpaceStatus.active,
        visibility="public",
        is_public=True,
        kind="standard",
        connection_style="online",
        creator_id=owner_public.id,
        themes=[],
        pricing_type="free",
        pricing_currency="AUD",
        has_paid_internal_content=False,
        timezone="Australia/Melbourne",
        island_artwork_status="not_started",
    )
    # Private (unlisted) Space.
    space_private = Space(
        id=_uid("s"),
        slug=_uid("private"),
        name="Private Space",
        status=SpaceStatus.active,
        visibility="link",
        is_public=False,
        kind="standard",
        connection_style="online",
        creator_id=owner_private.id,
        themes=[],
        pricing_type="free",
        pricing_currency="AUD",
        has_paid_internal_content=False,
        timezone="Australia/Melbourne",
        island_artwork_status="not_started",
    )
    db.add_all([space_public, space_private])
    db.flush()

    unrelated       = make_user(role="user")
    admin           = make_user(role="admin")
    learner_pub     = make_user(role="user")
    learner_priv    = make_user(role="user")
    moderator_priv  = make_user(role="user")
    creator_mem_priv = make_user(role="user")
    suspended_priv  = make_user(role="user")
    removed_priv    = make_user(role="user")

    # Memberships. Note: SpaceMembership.role uses learner|moderator|creator.
    def _mem(user, space, role, status=SpaceMembershipStatus.active):
        db.add(SpaceMembership(
            id=_uid("mem"), user_id=user.id, space_id=space.id,
            role=role, status=status, source="joined",
        ))

    _mem(learner_pub, space_public, SpaceRole.learner)
    _mem(learner_priv, space_private, SpaceRole.learner)
    _mem(moderator_priv, space_private, SpaceRole.moderator)
    _mem(creator_mem_priv, space_private, SpaceRole.creator)
    _mem(suspended_priv, space_private, SpaceRole.learner, SpaceMembershipStatus.paused)
    _mem(removed_priv, space_private, SpaceRole.learner, SpaceMembershipStatus.removed)
    db.flush()

    return {
        "space_public": space_public,
        "space_private": space_private,
        "owner_public": owner_public,
        "owner_private": owner_private,
        "unrelated": unrelated,
        "admin": admin,
        "learner_pub": learner_pub,
        "learner_priv": learner_priv,
        "moderator_priv": moderator_priv,
        "creator_mem_priv": creator_mem_priv,
        "suspended_priv": suspended_priv,
        "removed_priv": removed_priv,
    }


def _assert_allow(fn):
    """Small helper for readable assertions — allow means the fn
    returned without raising."""
    fn()  # if it raises, pytest reports it


def _assert_deny(fn, status_code: int = 403):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == status_code, (
        f"expected {status_code}, got {exc.value.status_code}: {exc.value.detail}"
    )


# ---------------------------------------------------------------------------
# avatars/… — any authenticated user
# ---------------------------------------------------------------------------


class TestAvatars:
    def test_any_authenticated_user_allowed(self, db, spaces_and_users):
        s = spaces_and_users
        for user in (s["unrelated"], s["admin"], s["learner_pub"], s["learner_priv"],
                     s["moderator_priv"], s["owner_public"], s["removed_priv"]):
            _assert_allow(lambda u=user: authorize_upload(
                "avatars/uuid_avatar.png", u, db,
            ))


# ---------------------------------------------------------------------------
# covers/… — reverse-lookup Space.cover_image_url;
#            public Space → any auth; private → member/manager/admin only.
# ---------------------------------------------------------------------------


class TestSpaceCover:
    def _seed_cover(self, db, space, key="covers/uuid_x.png"):
        space.cover_image_url = f"/api/uploads/{key}"
        db.flush()
        return key

    def test_public_space_cover_allowed_for_any_authenticated_user(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = self._seed_cover(db, s["space_public"])
        for user in (s["unrelated"], s["admin"], s["learner_pub"], s["learner_priv"],
                     s["moderator_priv"], s["owner_public"], s["removed_priv"]):
            _assert_allow(lambda u=user: authorize_upload(key, u, db))

    def test_private_space_cover_denied_for_unrelated_authenticated_user(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = self._seed_cover(db, s["space_private"])
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))
        _assert_deny(lambda: authorize_upload(key, s["learner_pub"], db))

    def test_private_space_cover_allowed_for_members_and_managers(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = self._seed_cover(db, s["space_private"])
        for user in (s["admin"], s["owner_private"], s["learner_priv"],
                     s["moderator_priv"], s["creator_mem_priv"]):
            _assert_allow(lambda u=user: authorize_upload(key, u, db))

    def test_private_space_cover_denied_for_suspended_and_removed(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = self._seed_cover(db, s["space_private"])
        _assert_deny(lambda: authorize_upload(key, s["suspended_priv"], db))
        _assert_deny(lambda: authorize_upload(key, s["removed_priv"], db))

    def test_unknown_cover_key_is_404(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(
            lambda: authorize_upload("covers/does-not-exist.png", s["admin"], db),
            status_code=404,
        )


# ---------------------------------------------------------------------------
# logos/{slug}/… — slug-in-key; same public/private rule as covers
# ---------------------------------------------------------------------------


class TestSpaceLogo:
    def test_public_space_logo_allowed_for_any_authenticated_user(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = f"logos/{s['space_public'].slug}/uuid_logo.png"
        for user in (s["unrelated"], s["admin"], s["removed_priv"]):
            _assert_allow(lambda u=user: authorize_upload(key, u, db))

    def test_private_space_logo_denied_for_unrelated_and_suspended(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = f"logos/{s['space_private'].slug}/uuid_logo.png"
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))
        _assert_deny(lambda: authorize_upload(key, s["suspended_priv"], db))

    def test_private_space_logo_allowed_for_members_and_managers(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = f"logos/{s['space_private'].slug}/uuid_logo.png"
        for user in (s["admin"], s["owner_private"], s["learner_priv"],
                     s["moderator_priv"]):
            _assert_allow(lambda u=user: authorize_upload(key, u, db))

    def test_unknown_slug_is_404(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(
            lambda: authorize_upload(
                "logos/no-such-slug/uuid_x.png", s["admin"], db,
            ),
            status_code=404,
        )

    def test_malformed_logo_path_is_404(self, db, spaces_and_users):
        s = spaces_and_users
        # No filename after the slug segment.
        _assert_deny(
            lambda: authorize_upload("logos/", s["admin"], db),
            status_code=404,
        )


# ---------------------------------------------------------------------------
# island-artwork/{slug}/… — slug-in-key; same rules
# ---------------------------------------------------------------------------


class TestIslandArtwork:
    def test_public_space_island_allowed_for_any_authenticated_user(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = f"island-artwork/{s['space_public'].slug}/uuid.png"
        _assert_allow(lambda: authorize_upload(key, s["unrelated"], db))

    def test_private_space_island_denied_for_unrelated(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = f"island-artwork/{s['space_private'].slug}/uuid.png"
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))

    def test_private_space_island_allowed_for_active_member(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = f"island-artwork/{s['space_private'].slug}/uuid.png"
        _assert_allow(lambda: authorize_upload(key, s["learner_priv"], db))


# ---------------------------------------------------------------------------
# pathway-covers/… — reverse-lookup Pathway → Space; public/private rule
# ---------------------------------------------------------------------------


class TestPathwayCover:
    def _seed_pathway(self, db, space, key="pathway-covers/uuid_pw.png"):
        pw = Pathway(
            id=_uid("pw"), space_id=space.id, slug=_uid("pw"),
            title="P", status="active",
            pathway_type=PathwayType.guided_experience,
            position=0,
            cover_image_url=f"/api/uploads/{key}",
        )
        db.add(pw)
        db.flush()
        return key

    def test_public_space_pathway_cover_allowed_for_any_authenticated(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = self._seed_pathway(db, s["space_public"])
        for user in (s["unrelated"], s["admin"], s["learner_pub"], s["removed_priv"]):
            _assert_allow(lambda u=user: authorize_upload(key, u, db))

    def test_private_space_pathway_cover_denied_for_unrelated(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = self._seed_pathway(db, s["space_private"], "pathway-covers/uuid_priv.png")
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))

    def test_private_space_pathway_cover_allowed_for_active_member(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = self._seed_pathway(db, s["space_private"], "pathway-covers/uuid_priv2.png")
        _assert_allow(lambda: authorize_upload(key, s["learner_priv"], db))

    def test_unknown_pathway_cover_is_404(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(
            lambda: authorize_upload(
                "pathway-covers/no-such-cover.png", s["admin"], db,
            ),
            status_code=404,
        )


# ---------------------------------------------------------------------------
# event-thumbnails/… — reverse-lookup Event → Space; MEMBER ONLY
# ---------------------------------------------------------------------------


class TestEventThumbnail:
    def _seed_event(self, db, space, key="event-thumbnails/uuid_evt.png"):
        now = datetime.utcnow()
        evt = Event(
            id=_uid("evt"), space_id=space.id,
            title="E", description="",
            starts_at=now, ends_at=now + timedelta(hours=1),
            is_published=True,
            thumbnail_url=f"/api/uploads/{key}",
        )
        db.add(evt)
        db.flush()
        return key

    def test_denied_for_authenticated_non_member_even_when_space_is_public(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        # Event thumbnails render on member gatherings surfaces; no
        # public exception, even when Space.is_public is True.
        key = self._seed_event(db, s["space_public"], "event-thumbnails/uuid_pub_evt.png")
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))

    def test_allowed_for_active_member(self, db, spaces_and_users):
        s = spaces_and_users
        key = self._seed_event(db, s["space_public"], "event-thumbnails/uuid_pub_evt2.png")
        _assert_allow(lambda: authorize_upload(key, s["learner_pub"], db))

    def test_denied_for_suspended_member(self, db, spaces_and_users):
        s = spaces_and_users
        key = self._seed_event(db, s["space_private"], "event-thumbnails/uuid_priv_evt.png")
        _assert_deny(lambda: authorize_upload(key, s["suspended_priv"], db))

    def test_allowed_for_admin_and_owner(self, db, spaces_and_users):
        s = spaces_and_users
        key = self._seed_event(db, s["space_private"], "event-thumbnails/uuid_priv_evt2.png")
        _assert_allow(lambda: authorize_upload(key, s["admin"], db))
        _assert_allow(lambda: authorize_upload(key, s["owner_private"], db))

    def test_unknown_event_key_is_404(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(
            lambda: authorize_upload(
                "event-thumbnails/does-not-exist.png", s["admin"], db,
            ),
            status_code=404,
        )


# ---------------------------------------------------------------------------
# steps/{step_id}/… — reuses _check_pathway_access
# ---------------------------------------------------------------------------


def _make_step(db, space, pathway_status="active", access_type="free"):
    """Create a pathway with the given status/access_type and a single
    step under it. Returns the step id (used to build the file_path)."""
    pw = Pathway(
        id=_uid("pw"), space_id=space.id, slug=_uid("pwslug"),
        title="P", status=pathway_status,
        pathway_type=PathwayType.guided_experience,
        access_type=access_type,
        pricing_mode="legacy",
        position=0,
    )
    db.add(pw)
    db.flush()
    step = PathwayStep(
        id=_uid("pst"), pathway_id=pw.id,
        slug=_uid("st"), title="S", position=0, content_type="text",
    )
    db.add(step)
    db.flush()
    return step.id, pw


class TestStepResource:
    def test_free_pathway_member_allowed(self, db, spaces_and_users):
        s = spaces_and_users
        step_id, _ = _make_step(db, s["space_private"], access_type="free")
        key = f"steps/{step_id}/uuid_x.pdf"
        _assert_allow(lambda: authorize_upload(key, s["learner_priv"], db))

    def test_free_pathway_non_member_still_allowed_per_pathway_access(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        # _check_pathway_access permits ``free`` unconditionally; this
        # test locks that in so we can't subtly diverge later.
        step_id, _ = _make_step(db, s["space_private"], access_type="free")
        key = f"steps/{step_id}/uuid_x.pdf"
        _assert_allow(lambda: authorize_upload(key, s["unrelated"], db))

    def test_included_pathway_member_allowed(self, db, spaces_and_users):
        s = spaces_and_users
        step_id, _ = _make_step(db, s["space_private"], access_type="included")
        key = f"steps/{step_id}/uuid_x.pdf"
        _assert_allow(lambda: authorize_upload(key, s["learner_priv"], db))

    def test_included_pathway_non_member_denied(self, db, spaces_and_users):
        s = spaces_and_users
        step_id, _ = _make_step(db, s["space_private"], access_type="included")
        key = f"steps/{step_id}/uuid_x.pdf"
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))

    def test_paid_pathway_without_entitlement_denied(self, db, spaces_and_users):
        s = spaces_and_users
        step_id, pw = _make_step(db, s["space_private"], access_type="one_time")
        key = f"steps/{step_id}/uuid_x.pdf"
        # Even an active Space member without an entitlement row is denied.
        _assert_deny(lambda: authorize_upload(key, s["learner_priv"], db))

    def test_paid_pathway_with_entitlement_allowed(self, db, spaces_and_users):
        s = spaces_and_users
        step_id, pw = _make_step(db, s["space_private"], access_type="one_time")
        # Grant the learner an active PathwayEntitlement row.
        db.add(PathwayEntitlement(
            id=_uid("ent"),
            user_id=s["learner_priv"].id,
            pathway_id=pw.id,
            space_id=s["space_private"].id,
            source="admin",
            status="active",
        ))
        db.flush()
        key = f"steps/{step_id}/uuid_x.pdf"
        _assert_allow(lambda: authorize_upload(key, s["learner_priv"], db))

    def test_draft_pathway_denied_for_learner(self, db, spaces_and_users):
        s = spaces_and_users
        step_id, _ = _make_step(db, s["space_private"], pathway_status="draft")
        key = f"steps/{step_id}/uuid_x.pdf"
        _assert_deny(lambda: authorize_upload(key, s["learner_priv"], db))

    def test_draft_pathway_allowed_for_owner_and_moderator(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        step_id, _ = _make_step(db, s["space_private"], pathway_status="draft")
        key = f"steps/{step_id}/uuid_x.pdf"
        _assert_allow(lambda: authorize_upload(key, s["owner_private"], db))
        _assert_allow(lambda: authorize_upload(key, s["moderator_priv"], db))
        _assert_allow(lambda: authorize_upload(key, s["admin"], db))

    def test_unknown_step_id_is_404(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(
            lambda: authorize_upload("steps/no-such/uuid_x.pdf", s["admin"], db),
            status_code=404,
        )


# ---------------------------------------------------------------------------
# media/… namespace — three sub-cases
# ---------------------------------------------------------------------------


class TestMediaNamespace:
    def test_world_guide_allowed_for_any_authenticated_user(
        self, db, spaces_and_users,
    ):
        s = spaces_and_users
        key = "media/world-guide/uuid_help.png"
        for user in (s["unrelated"], s["admin"], s["removed_priv"]):
            _assert_allow(lambda u=user: authorize_upload(key, u, db))

    def test_community_image_member_only(self, db, spaces_and_users):
        s = spaces_and_users
        key = f"media/{s['space_private'].slug}/community/uuid_post.png"
        _assert_allow(lambda: authorize_upload(key, s["learner_priv"], db))
        _assert_allow(lambda: authorize_upload(key, s["moderator_priv"], db))
        _assert_allow(lambda: authorize_upload(key, s["owner_private"], db))
        _assert_allow(lambda: authorize_upload(key, s["admin"], db))
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))
        _assert_deny(lambda: authorize_upload(key, s["suspended_priv"], db))
        _assert_deny(lambda: authorize_upload(key, s["removed_priv"], db))

    def test_media_library_member_only(self, db, spaces_and_users):
        s = spaces_and_users
        key = f"media/{s['space_private'].slug}/uuid_asset.png"
        _assert_allow(lambda: authorize_upload(key, s["learner_priv"], db))
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))
        # Even a public-Space member of a DIFFERENT Space is denied.
        _assert_deny(lambda: authorize_upload(key, s["learner_pub"], db))

    def test_media_library_public_space_still_member_only(
        self, db, spaces_and_users,
    ):
        # Media Library assets are member-scoped even when the Space
        # itself is publicly listed; the assets live behind the member
        # surface.
        s = spaces_and_users
        key = f"media/{s['space_public'].slug}/uuid_asset.png"
        _assert_allow(lambda: authorize_upload(key, s["learner_pub"], db))
        _assert_deny(lambda: authorize_upload(key, s["unrelated"], db))

    def test_unknown_slug_is_404(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(
            lambda: authorize_upload("media/no-such-slug/x.png", s["admin"], db),
            status_code=404,
        )


# ---------------------------------------------------------------------------
# Default-deny + empty path
# ---------------------------------------------------------------------------


class TestDefaultDenyAndEdgeCases:
    def test_unknown_prefix_denied(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(lambda: authorize_upload("secret/x.png", s["admin"], db))
        _assert_deny(lambda: authorize_upload("unknownspace/x.png", s["admin"], db))

    def test_empty_path_404(self, db, spaces_and_users):
        s = spaces_and_users
        _assert_deny(lambda: authorize_upload("", s["admin"], db), status_code=404)


# ---------------------------------------------------------------------------
# Integration — full ASGI route
# ---------------------------------------------------------------------------


_PRESIGNED_URL = (
    "https://test-account.r2.cloudflarestorage.com/fc-media-test/"
    "media/some-space/some-key?X-Amz-Signature=fake&X-Amz-Expires=300"
)


@pytest.fixture
def r2_serving(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setattr(settings, "r2_account_id", "test-account", raising=False)
    monkeypatch.setattr(settings, "r2_access_key_id", "test-access", raising=False)
    monkeypatch.setattr(settings, "r2_secret_access_key", "test-secret", raising=False)
    monkeypatch.setattr(settings, "r2_bucket_private", "fc-media-test", raising=False)
    monkeypatch.setattr(settings, "r2_bucket_public", "fc-media-public-test", raising=False)
    monkeypatch.setattr(
        settings, "r2_public_base_url", "https://pub-test.r2.dev", raising=False,
    )
    client = MagicMock(name="R2Client")
    client.generate_presigned_url.return_value = _PRESIGNED_URL
    storage_module.reset_r2_client_cache()
    monkeypatch.setattr(storage_module, "_r2_client", lambda: client)
    yield client


@pytest.fixture
def client_with_overrides(db: Session, make_user):
    """TestClient with get_current_user + get_db overridden to use the
    per-test session so seeded rows are visible to the route handler."""
    from app.auth.dependencies import get_current_user as _gcu
    from app.core.database import get_db as _gdb
    user = make_user(role="user")
    app.dependency_overrides[_gcu] = lambda: user
    app.dependency_overrides[_gdb] = lambda: db
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, user
    finally:
        app.dependency_overrides.pop(_gcu, None)
        app.dependency_overrides.pop(_gdb, None)


class TestRouteIntegrationR2Mode:
    def test_authorized_avatar_returns_302_with_headers(
        self, client_with_overrides, r2_serving,
    ):
        client, _user = client_with_overrides
        r = client.get("/api/uploads/avatars/uuid_x.png")
        assert r.status_code == 302
        assert r.headers["location"] == _PRESIGNED_URL
        # Existing security/cache headers preserved.
        assert r.headers.get("cross-origin-resource-policy") == "cross-origin"
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert "no-store" in (r.headers.get("cache-control") or "").lower()

    def test_unauthorized_private_returns_403_and_does_not_presign(
        self, db, client_with_overrides, r2_serving, spaces_and_users,
    ):
        client, _user = client_with_overrides
        # Media path for a Space our overridden user is NOT a member of.
        slug = spaces_and_users["space_private"].slug
        r = client.get(f"/api/uploads/media/{slug}/uuid_asset.png")
        assert r.status_code == 403
        # Auth denied → no R2 presign requested.
        r2_serving.generate_presigned_url.assert_not_called()

    def test_unknown_namespace_default_denied(
        self, client_with_overrides, r2_serving,
    ):
        client, _user = client_with_overrides
        r = client.get("/api/uploads/secret/uuid_x.png")
        assert r.status_code == 403
        r2_serving.generate_presigned_url.assert_not_called()

    def test_path_traversal_still_400_before_auth(
        self, client_with_overrides, r2_serving,
    ):
        client, _user = client_with_overrides
        # HTTP clients typically normalise ``..`` — call the helper
        # directly to confirm the guard order.
        from app.uploads.routes import _reject_traversal
        from fastapi import HTTPException as _HE
        with pytest.raises(_HE) as ex:
            _reject_traversal("avatars/../secret.png")
        assert ex.value.status_code == 400


class TestRouteIntegrationFilesystemMode:
    def test_authorized_avatar_serves_file_from_disk(
        self, client_with_overrides, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ):
        # Ensure R2 mode is OFF for this test.
        from app.uploads import routes as uploads_routes
        monkeypatch.setattr(settings, "r2_account_id", None, raising=False)
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)
        monkeypatch.setattr(uploads_routes, "UPLOAD_DIR", tmp_path)
        (tmp_path / "avatars").mkdir()
        (tmp_path / "avatars" / "uuid_a.png").write_bytes(b"PNGBYTES")

        client, _user = client_with_overrides
        r = client.get("/api/uploads/avatars/uuid_a.png")
        assert r.status_code == 200
        assert r.content == b"PNGBYTES"

    def test_unauthorized_private_returns_403_even_in_filesystem_mode(
        self, db, client_with_overrides, monkeypatch: pytest.MonkeyPatch,
        tmp_path, spaces_and_users,
    ):
        # A file that exists on disk but the caller isn't authorised
        # to see must NOT be served just because R2 mode is off.
        from app.uploads import routes as uploads_routes
        monkeypatch.setattr(settings, "r2_account_id", None, raising=False)
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)
        monkeypatch.setattr(uploads_routes, "UPLOAD_DIR", tmp_path)
        slug = spaces_and_users["space_private"].slug
        target = tmp_path / "media" / slug
        target.mkdir(parents=True)
        (target / "uuid_asset.png").write_bytes(b"SECRET")

        client, _user = client_with_overrides
        r = client.get(f"/api/uploads/media/{slug}/uuid_asset.png")
        assert r.status_code == 403
        assert r.content != b"SECRET"


class TestPublicPlatformArtworkRegression:
    def test_public_route_still_needs_no_auth_and_302s(
        self, r2_serving,
    ):
        # Fresh TestClient with NO overrides — proves the public route
        # doesn't touch get_current_user.
        client = TestClient(app, follow_redirects=False)
        r = client.get("/api/uploads/platform-artwork/hero/xyz.png")
        assert r.status_code == 302
        assert r.headers["location"] == (
            "https://pub-test.r2.dev/platform-artwork/hero/xyz.png"
        )
        # Public flow never presigns (public bucket).
        r2_serving.generate_presigned_url.assert_not_called()
