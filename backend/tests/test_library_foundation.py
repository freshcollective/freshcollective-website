"""Foundation tests for the unified Library (commit 1).

Covers just the model + endpoint plumbing added in the folders
migration + folder_id FK. Folder CRUD, the aggregating endpoint, and
the resource-block extension are covered in later tests.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.creator.routes import (
    _resolve_library_folder,
    _serialise_media,
    _serialise_resource,
    create_space_resource,
    update_media,
    update_space_resource,
)
from app.creator.schemas import (
    MediaAssetUpdateRequest,
    ResourceCreateRequest,
    ResourceUpdateRequest,
)
from app.models.platform import (
    CreatorMediaAsset,
    LibraryFolder,
    MediaStatus,
    MediaType,
    SpaceResource,
)


def _make_folder(db, space, *, name: str = "Onboarding") -> LibraryFolder:
    f = LibraryFolder(
        id=f"flr_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        name=name,
        position=0,
    )
    db.add(f)
    db.flush()
    return f


def _make_asset(db, space, *, folder: LibraryFolder | None = None) -> CreatorMediaAsset:
    a = CreatorMediaAsset(
        id=f"cma_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        uploaded_by_user_id=space.creator_id,
        title="an asset",
        description=None,
        original_filename="x.png",
        stored_filename="x.png",
        storage_path="uploads/media/x.png",
        file_url="/api/uploads/media/x.png",
        mime_type="image/png",
        media_type=MediaType.image,
        file_size_bytes=1,
        extension=".png",
        status=MediaStatus.active,
        folder_id=folder.id if folder else None,
    )
    db.add(a)
    db.flush()
    return a


def _make_resource(db, space, *, folder: LibraryFolder | None = None) -> SpaceResource:
    r = SpaceResource(
        id=uuid.uuid4().hex,
        space_id=space.id,
        created_by_id=space.creator_id,
        title="a link",
        description=None,
        resource_type="link",
        url="https://example.test",
        status="draft",
        folder_id=folder.id if folder else None,
    )
    db.add(r)
    db.flush()
    return r


class TestModelDefaults:
    def test_new_asset_has_null_folder_by_default(self, db, make_space):
        space = make_space()
        a = _make_asset(db, space)
        db.commit(); db.refresh(a)
        assert a.folder_id is None

    def test_new_resource_has_null_folder_by_default(self, db, make_space):
        space = make_space()
        r = _make_resource(db, space)
        db.commit(); db.refresh(r)
        assert r.folder_id is None


class TestSerialisation:
    def test_media_response_carries_folder_id(self, db, make_space):
        space = make_space()
        folder = _make_folder(db, space)
        a = _make_asset(db, space, folder=folder)
        db.commit()
        payload = _serialise_media(a, 0)
        assert payload["folder_id"] == folder.id

    def test_resource_response_carries_folder_id(self, db, make_space):
        space = make_space()
        folder = _make_folder(db, space)
        r = _make_resource(db, space, folder=folder)
        db.commit()
        payload = _serialise_resource(r, 0)
        assert payload["folder_id"] == folder.id


class TestResolveLibraryFolder:
    def test_null_folder_returns_none(self, db, make_space):
        space = make_space()
        assert _resolve_library_folder(None, space, db) is None

    def test_empty_string_returns_none(self, db, make_space):
        space = make_space()
        assert _resolve_library_folder("", space, db) is None

    def test_valid_folder_returns_its_id(self, db, make_space):
        space = make_space()
        folder = _make_folder(db, space)
        db.commit()
        assert _resolve_library_folder(folder.id, space, db) == folder.id

    def test_unknown_folder_400(self, db, make_space):
        space = make_space()
        with pytest.raises(HTTPException) as exc:
            _resolve_library_folder("flr_nope", space, db)
        assert exc.value.status_code == 400

    def test_cross_space_folder_400(self, db, make_space):
        space_a = make_space()
        space_b = make_space()
        folder = _make_folder(db, space_a)
        db.commit()
        # Trying to attach to a folder owned by another Collective
        # must be rejected — otherwise creators could cross-link.
        with pytest.raises(HTTPException) as exc:
            _resolve_library_folder(folder.id, space_b, db)
        assert exc.value.status_code == 400


class TestUpdateMediaFolder:
    def test_move_media_to_folder(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        folder = _make_folder(db, space)
        a = _make_asset(db, space)
        db.commit()

        result = update_media(
            slug=space.slug, media_id=a.id,
            body=MediaAssetUpdateRequest(folder_id=folder.id),
            db=db, current_user=creator,
        )
        assert result["folder_id"] == folder.id

    def test_move_media_out_of_folder(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        folder = _make_folder(db, space)
        a = _make_asset(db, space, folder=folder)
        db.commit()

        # Explicit null → back to "All items"
        result = update_media(
            slug=space.slug, media_id=a.id,
            body=MediaAssetUpdateRequest(folder_id=None),
            db=db, current_user=creator,
        )
        # ``folder_id`` was in model_fields_set → cleared to None
        assert result["folder_id"] is None

    def test_omitting_folder_id_leaves_it_unchanged(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        folder = _make_folder(db, space)
        a = _make_asset(db, space, folder=folder)
        db.commit()

        # Only title touched — folder untouched
        result = update_media(
            slug=space.slug, media_id=a.id,
            body=MediaAssetUpdateRequest(title="renamed"),
            db=db, current_user=creator,
        )
        assert result["folder_id"] == folder.id


class TestCreateAndUpdateResourceFolder:
    def test_create_link_in_folder(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        folder = _make_folder(db, space)
        db.commit()

        result = create_space_resource(
            slug=space.slug,
            body=ResourceCreateRequest(
                title="Notion doc",
                url="https://notion.so/x",
                resource_type="link",
                folder_id=folder.id,
            ),
            db=db, current_user=creator,
        )
        assert result["folder_id"] == folder.id

    def test_update_resource_folder(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        folder = _make_folder(db, space)
        r = _make_resource(db, space)
        db.commit()

        result = update_space_resource(
            slug=space.slug, resource_id=r.id,
            body=ResourceUpdateRequest(folder_id=folder.id),
            db=db, current_user=creator,
        )
        assert result["folder_id"] == folder.id


class TestFolderDeleteCascade:
    def test_deleting_folder_moves_items_to_all_items(
        self, db, make_user, make_space,
    ):
        # ON DELETE SET NULL on the FK: dropping a folder empties it
        # back to "All items", never deleting the referenced content.
        space = make_space()
        folder = _make_folder(db, space)
        a = _make_asset(db, space, folder=folder)
        r = _make_resource(db, space, folder=folder)
        db.commit()

        db.delete(folder)
        db.commit()
        db.refresh(a); db.refresh(r)
        assert a.folder_id is None
        assert r.folder_id is None
