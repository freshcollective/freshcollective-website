"""Persistent Media Storage Stage B — R2 mode routing tests.

Locks in three invariants for ``app.core.storage`` under R2 mode:

  1. The public bucket owns ``platform-artwork/*`` keys — and nothing
     else. Every other subdir (avatars, covers, logos, pathway-covers,
     event-thumbnails, media/…, steps/…, atlas-locations/…,
     place-artwork/…, world-guide) lands in the private bucket.

  2. save_file / save_media_file / delete_file all use the shared
     ``_bucket_for_key`` decision — so a caller that switches subdir
     transparently switches bucket, without a per-endpoint bucket
     argument to keep in sync.

  3. Filesystem fallback still runs when R2 mode is disabled — tests
     that monkeypatch ``UPLOAD_DIR`` (test_uploads_public_prefix,
     test_security_headers, test_physical_locations_routes,
     test_world_guide) continue to work without R2 credentials.

Uses ``unittest.mock`` in preference to ``moto`` so the test suite
does not gain another dependency. boto3 itself is already a runtime
dep of ``app.core.storage`` in R2 mode.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core import storage as storage_module
from app.core.config import settings


# ---------------------------------------------------------------------------
# Fixtures — flip R2 mode on, replace the boto3 client with a mock
# ---------------------------------------------------------------------------


@pytest.fixture
def r2_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Enable R2 mode on ``settings`` for the duration of the test,
    and swap the cached client factory for a MagicMock. Cache is
    reset on entry AND exit so no test leaks a mock client into a
    later test's real credential lookup."""
    monkeypatch.setattr(settings, "r2_account_id", "test-account", raising=False)
    monkeypatch.setattr(settings, "r2_access_key_id", "test-access", raising=False)
    monkeypatch.setattr(settings, "r2_secret_access_key", "test-secret", raising=False)
    monkeypatch.setattr(settings, "r2_bucket_private", "fc-media-test", raising=False)
    monkeypatch.setattr(settings, "r2_bucket_public", "fc-media-public-test", raising=False)
    monkeypatch.setattr(
        settings, "r2_public_base_url", "https://pub-test.r2.dev", raising=False,
    )

    client = MagicMock(name="R2Client")
    # Deterministic pre-signed URL so redirect tests can assert on it.
    client.generate_presigned_url.return_value = (
        "https://test-account.r2.cloudflarestorage.com/fc-media-test/foo?sig=fake"
    )

    # Clear any real cached client from a prior test, then swap the
    # factory itself so nothing in storage.py touches boto3 during
    # this test. monkeypatch restores the original ``_r2_client``
    # after the test, so no explicit teardown clear is needed.
    storage_module.reset_r2_client_cache()
    monkeypatch.setattr(storage_module, "_r2_client", lambda: client)
    yield client


# ---------------------------------------------------------------------------
# 1. Bucket routing — the sole authoritative map
# ---------------------------------------------------------------------------


class TestBucketRouting:
    def test_platform_artwork_prefix_routes_to_public(self, r2_client: MagicMock) -> None:
        assert (
            storage_module._bucket_for_key("platform-artwork/hero/xyz.png")
            == "fc-media-public-test"
        )

    @pytest.mark.parametrize("key", [
        "avatars/abc.png",
        "covers/abc.png",
        "logos/some-space/abc.png",
        "pathway-covers/abc.png",
        "event-thumbnails/abc.png",
        "media/some-space/abc.png",
        "media/some-space/community/abc.png",
        "steps/step-id/abc.pdf",
        # Atlas + place artwork are curated but not publicly served
        # today — the auth-gated /api/uploads/* route owns them, so
        # they must land in the PRIVATE bucket regardless of intent.
        "atlas-locations/melbourne/hero.png",
        "place-artwork/melbourne/hero.png",
        "world-guide/some-image.png",
        # Defensive — anything that resembles but does not exactly
        # match the ``platform-artwork/`` prefix must NOT be treated
        # as public.
        "platform-artworks-fake/abc.png",
        "not-platform-artwork/abc.png",
    ])
    def test_everything_else_routes_to_private(
        self, r2_client: MagicMock, key: str,
    ) -> None:
        assert storage_module._bucket_for_key(key) == "fc-media-test"


# ---------------------------------------------------------------------------
# 2. save_file — R2 mode writes to the correct bucket
# ---------------------------------------------------------------------------


class TestSaveFileR2Mode:
    def test_public_artwork_upload_uses_public_bucket(
        self, r2_client: MagicMock,
    ) -> None:
        rel, kind, size = storage_module.save_file(
            data=b"PNGBYTES",
            original_name="hero.png",
            mime_type="image/png",
            subdir="platform-artwork/onboarding",
        )
        assert rel.startswith("platform-artwork/onboarding/")
        assert rel.endswith(".png")
        assert size == 8
        r2_client.put_object.assert_called_once()
        call = r2_client.put_object.call_args
        assert call.kwargs["Bucket"] == "fc-media-public-test"
        assert call.kwargs["Key"] == rel
        assert call.kwargs["Body"] == b"PNGBYTES"
        assert call.kwargs["ContentType"] == "image/png"

    def test_avatar_upload_uses_private_bucket(
        self, r2_client: MagicMock,
    ) -> None:
        rel, _, _ = storage_module.save_file(
            data=b"JPGBYTES",
            original_name="me.jpg",
            mime_type="image/jpeg",
            subdir="avatars",
        )
        assert rel.startswith("avatars/")
        r2_client.put_object.assert_called_once()
        assert r2_client.put_object.call_args.kwargs["Bucket"] == "fc-media-test"

    def test_missing_mime_falls_back_to_octet_stream(
        self, r2_client: MagicMock,
    ) -> None:
        storage_module.save_file(
            data=b"PDF",
            original_name="doc.pdf",
            mime_type="",
            subdir="steps/step-1",
        )
        assert (
            r2_client.put_object.call_args.kwargs["ContentType"]
            == "application/octet-stream"
        )

    def test_key_structure_preserved(self, r2_client: MagicMock) -> None:
        rel, _, _ = storage_module.save_file(
            data=b"x",
            original_name="my file (v2).png",
            mime_type="image/png",
            subdir="covers",
        )
        # ``{uuid}_{sanitised}.ext`` under the subdir. Sanitisation
        # replaces spaces and parens with underscores.
        parts = rel.split("/")
        assert parts[0] == "covers"
        assert parts[1].endswith(".png")
        assert "_my_file_v2_.png" in parts[1] or "_my_file_v2.png" in parts[1]


# ---------------------------------------------------------------------------
# 3. save_media_file — always private (media/{slug}/…)
# ---------------------------------------------------------------------------


class TestSaveMediaFileR2Mode:
    def test_media_library_upload_uses_private_bucket(
        self, r2_client: MagicMock,
    ) -> None:
        storage_path, file_url, media_type, filename, size = (
            storage_module.save_media_file(
                data=b"IMG",
                original_name="picture.png",
                mime_type="image/png",
                space_slug="natural-leader-hub",
            )
        )
        assert storage_path.startswith("media/natural-leader-hub/")
        assert file_url == f"/api/uploads/{storage_path}"
        assert media_type == "image"
        r2_client.put_object.assert_called_once()
        assert r2_client.put_object.call_args.kwargs["Bucket"] == "fc-media-test"
        assert r2_client.put_object.call_args.kwargs["Key"] == storage_path


# ---------------------------------------------------------------------------
# 4. delete_file — routes to the correct bucket
# ---------------------------------------------------------------------------


class TestDeleteFileR2Mode:
    def test_delete_platform_artwork_hits_public_bucket(
        self, r2_client: MagicMock,
    ) -> None:
        storage_module.delete_file("platform-artwork/hero/abc.png")
        r2_client.delete_object.assert_called_once_with(
            Bucket="fc-media-public-test",
            Key="platform-artwork/hero/abc.png",
        )

    def test_delete_avatar_hits_private_bucket(
        self, r2_client: MagicMock,
    ) -> None:
        storage_module.delete_file("avatars/uuid_face.jpg")
        r2_client.delete_object.assert_called_once_with(
            Bucket="fc-media-test",
            Key="avatars/uuid_face.jpg",
        )

    def test_empty_rel_path_is_noop(self, r2_client: MagicMock) -> None:
        storage_module.delete_file("")
        r2_client.delete_object.assert_not_called()

    def test_delete_swallows_r2_error(self, r2_client: MagicMock) -> None:
        r2_client.delete_object.side_effect = RuntimeError("network")
        # Must NOT raise — deletion is best-effort by design.
        storage_module.delete_file("avatars/whatever.png")


# ---------------------------------------------------------------------------
# 5. save_image_with_thumbnail — both objects land in the same bucket
# ---------------------------------------------------------------------------


class TestSaveImageWithThumbnailR2Mode:
    def test_platform_artwork_thumbnail_also_public(
        self, r2_client: MagicMock,
    ) -> None:
        # A 2x2 solid PNG — enough for Pillow to open + resize.
        png_2x2 = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd4"
            "9a730000001649444154789c63fccfc0c0c0c0c0c4c0c0c0c0c000000d1d01"
            "036ac29be90000000049454e44ae426082"
        )
        hero_rel, thumb_rel = storage_module.save_image_with_thumbnail(
            data=png_2x2,
            original_name="hero.png",
            mime_type="image/png",
            subdir="platform-artwork/onboarding",
        )
        assert hero_rel.startswith("platform-artwork/onboarding/")
        # Thumbnail retains the shared ``{uuid}_{sanitised}`` filename
        # shape from save_file; the ``thumb_`` prefix appears inside
        # the sanitised name, not at the start of the whole key.
        assert thumb_rel.startswith("platform-artwork/onboarding/")
        assert "thumb_hero" in thumb_rel
        # Both bytes streams went to the public bucket.
        assert r2_client.put_object.call_count == 2
        for call in r2_client.put_object.call_args_list:
            assert call.kwargs["Bucket"] == "fc-media-public-test"

    def test_invalid_source_raises_before_any_storage_write(
        self, r2_client: MagicMock,
    ) -> None:
        """Thumbnail bytes are generated BEFORE any storage write, so
        a source Pillow can't decode raises without leaving orphan
        R2 objects behind."""
        with pytest.raises(Exception):
            storage_module.save_image_with_thumbnail(
                data=b"\x89PNGnot-a-real-png",
                original_name="broken.png",
                mime_type="image/png",
                subdir="platform-artwork/atlas-locations/x",
            )
        r2_client.put_object.assert_not_called()

    def test_thumbnail_write_failure_deletes_the_just_written_hero(
        self, r2_client: MagicMock, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the hero write succeeds but the thumbnail write raises,
        the just-written hero must be cleaned up so we do not leak an
        orphan object."""
        png_2x2 = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd4"
            "9a730000001649444154789c63fccfc0c0c0c0c0c4c0c0c0c0c000000d1d01"
            "036ac29be90000000049454e44ae426082"
        )

        # First put_object succeeds (hero), second raises (thumbnail).
        call_count = {"n": 0}
        def _put_object(**_kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise RuntimeError("simulated thumbnail write failure")
            return None
        r2_client.put_object.side_effect = _put_object

        with pytest.raises(RuntimeError, match="thumbnail"):
            storage_module.save_image_with_thumbnail(
                data=png_2x2,
                original_name="hero.png",
                mime_type="image/png",
                subdir="platform-artwork/atlas-locations/y",
            )
        # Compensating delete for the hero must have fired.
        r2_client.delete_object.assert_called_once()
        deleted_key = r2_client.delete_object.call_args.kwargs["Key"]
        assert deleted_key.startswith("platform-artwork/atlas-locations/y/")


# ---------------------------------------------------------------------------
# 6. Filesystem fallback — R2 mode disabled by default
# ---------------------------------------------------------------------------


class TestFilesystemFallbackWhenR2Disabled:
    def test_r2_disabled_when_all_creds_unset(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No R2 env vars set → is_r2_enabled must be False.
        monkeypatch.setattr(settings, "r2_account_id", None, raising=False)
        monkeypatch.setattr(settings, "r2_access_key_id", None, raising=False)
        monkeypatch.setattr(settings, "r2_secret_access_key", None, raising=False)
        monkeypatch.setattr(settings, "r2_bucket_private", None, raising=False)
        monkeypatch.setattr(settings, "r2_bucket_public", None, raising=False)
        monkeypatch.setattr(settings, "r2_public_base_url", None, raising=False)
        assert settings.is_r2_enabled is False

    def test_r2_disabled_when_any_cred_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Set five of six — is_r2_enabled must still return False.
        # Missing-any-one fails closed, which is the safe default.
        monkeypatch.setattr(settings, "r2_account_id", "acc", raising=False)
        monkeypatch.setattr(settings, "r2_access_key_id", "a", raising=False)
        monkeypatch.setattr(settings, "r2_secret_access_key", "b", raising=False)
        monkeypatch.setattr(settings, "r2_bucket_private", "priv", raising=False)
        monkeypatch.setattr(settings, "r2_bucket_public", "pub", raising=False)
        monkeypatch.setattr(settings, "r2_public_base_url", None, raising=False)
        assert settings.is_r2_enabled is False

    def test_filesystem_write_still_works(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ) -> None:
        monkeypatch.setattr(settings, "r2_account_id", None, raising=False)
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)
        rel, _, _ = storage_module.save_file(
            data=b"PNG",
            original_name="test.png",
            mime_type="image/png",
            subdir="avatars",
        )
        target = tmp_path / rel
        assert target.exists()
        assert target.read_bytes() == b"PNG"
