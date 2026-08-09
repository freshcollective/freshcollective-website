"""Commit 2 — folder CRUD + unified Library endpoint.

Also verifies the ``resource`` block already accepts ``media_asset_id``
end-to-end via the existing block create route, so the frontend can
point a Library file into a resource card without any backend enum
or schema change.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.creator.routes import (
    create_library_folder,
    create_step_block,
    delete_library_folder,
    list_library,
    list_library_folders,
    update_library_folder,
)
from app.creator.schemas import (
    LibraryFolderCreateRequest,
    LibraryFolderUpdateRequest,
    StepBlockCreateRequest,
)
from app.models.platform import (
    CreatorMediaAsset,
    LibraryFolder,
    MediaStatus,
    MediaType,
    Pathway,
    PathwayStep,
    PathwayType,
    SpaceResource,
    StepContentType,
)


def _make_pathway_and_step(db, space) -> PathwayStep:
    p = Pathway(
        id=f"pw_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="p",
        status="active",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    s = PathwayStep(
        id=f"pst_{uuid.uuid4().hex[:12]}",
        pathway_id=p.id,
        slug=f"step-{uuid.uuid4().hex[:8]}",
        title="s",
        position=0,
        content_type=StepContentType.text,
    )
    db.add(s)
    db.flush()
    return s


def _make_asset(db, space, *, title: str, media_type: MediaType, folder_id: str | None = None) -> CreatorMediaAsset:
    a = CreatorMediaAsset(
        id=f"cma_{uuid.uuid4().hex[:12]}",
        space_id=space.id,
        uploaded_by_user_id=space.creator_id,
        title=title,
        description=None,
        original_filename=f"{title}.bin",
        stored_filename=f"{title}.bin",
        storage_path="uploads/x",
        file_url=f"/api/uploads/{title}",
        mime_type="application/octet-stream",
        media_type=media_type,
        file_size_bytes=1,
        extension=".bin",
        status=MediaStatus.active,
        folder_id=folder_id,
    )
    db.add(a)
    db.flush()
    return a


def _make_link(db, space, *, title: str, folder_id: str | None = None) -> SpaceResource:
    r = SpaceResource(
        id=uuid.uuid4().hex,
        space_id=space.id,
        created_by_id=space.creator_id,
        title=title,
        description=None,
        resource_type="link",
        url=f"https://{title}.test",
        status="published",
        folder_id=folder_id,
    )
    db.add(r)
    db.flush()
    return r


# ---------------------------------------------------------------------------
# Folder CRUD
# ---------------------------------------------------------------------------


class TestFolderCrud:
    def test_create_folder_gets_bottom_position(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        # Existing folder at position 0
        db.add(LibraryFolder(
            id="flr_a", space_id=space.id, name="A", position=0,
        ))
        db.commit()

        result = create_library_folder(
            slug=space.slug,
            body=LibraryFolderCreateRequest(name="B"),
            db=db, current_user=creator,
        )
        # Auto position — one past current max (which is 0)
        assert result["position"] == 1

    def test_list_folders_includes_item_counts(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        f = LibraryFolder(id="flr_x", space_id=space.id, name="X", position=0)
        db.add(f)
        db.flush()
        _make_asset(db, space, title="one", media_type=MediaType.image, folder_id=f.id)
        _make_link(db, space, title="two", folder_id=f.id)
        db.commit()

        rows = list_library_folders(slug=space.slug, db=db, current_user=creator)
        assert len(rows) == 1
        assert rows[0]["item_count"] == 2

    def test_rename_folder(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        f = LibraryFolder(id="flr_r", space_id=space.id, name="Old", position=0)
        db.add(f)
        db.commit()

        result = update_library_folder(
            slug=space.slug, folder_id=f.id,
            body=LibraryFolderUpdateRequest(name="New"),
            db=db, current_user=creator,
        )
        assert result["name"] == "New"

    def test_deleting_folder_leaves_items_intact(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        f = LibraryFolder(id="flr_d", space_id=space.id, name="D", position=0)
        db.add(f)
        db.flush()
        asset = _make_asset(
            db, space, title="keep", media_type=MediaType.image, folder_id=f.id,
        )
        db.commit()

        delete_library_folder(
            slug=space.slug, folder_id=f.id, db=db, current_user=creator,
        )
        db.refresh(asset)
        # Item survives — dropped back to "All items".
        assert asset.folder_id is None


# ---------------------------------------------------------------------------
# Unified Library endpoint
# ---------------------------------------------------------------------------


class TestLibraryListing:
    def test_returns_both_files_and_links_by_default(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_asset(db, space, title="alpha", media_type=MediaType.image)
        _make_link(db, space, title="beta")
        db.commit()

        result = list_library(
            slug=space.slug, db=db, current_user=creator,
        )
        kinds = sorted(item["kind"] for item in result["items"])
        assert kinds == ["file", "link"]
        assert result["total"] == 2

    def test_type_filter_narrows_to_images(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_asset(db, space, title="pic", media_type=MediaType.image)
        _make_asset(db, space, title="clip", media_type=MediaType.video)
        _make_link(db, space, title="doc")
        db.commit()

        result = list_library(
            slug=space.slug, type="image", db=db, current_user=creator,
        )
        titles = [item["title"] for item in result["items"]]
        assert titles == ["pic"]

    def test_type_filter_link_returns_only_links(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_asset(db, space, title="pic", media_type=MediaType.image)
        _make_link(db, space, title="only-link")
        db.commit()

        result = list_library(
            slug=space.slug, type="link", db=db, current_user=creator,
        )
        titles = [item["title"] for item in result["items"]]
        assert titles == ["only-link"]

    def test_folder_filter_selects_a_folder(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        f = LibraryFolder(id="flr_a", space_id=space.id, name="A", position=0)
        db.add(f)
        db.flush()
        _make_asset(
            db, space, title="in-folder",
            media_type=MediaType.image, folder_id=f.id,
        )
        _make_asset(db, space, title="loose", media_type=MediaType.image)
        db.commit()

        result = list_library(
            slug=space.slug, folder=f.id, db=db, current_user=creator,
        )
        titles = [item["title"] for item in result["items"]]
        assert titles == ["in-folder"]

    def test_folder_none_selects_uncategorised_only(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        f = LibraryFolder(id="flr_a", space_id=space.id, name="A", position=0)
        db.add(f)
        db.flush()
        _make_asset(
            db, space, title="in-folder",
            media_type=MediaType.image, folder_id=f.id,
        )
        _make_asset(db, space, title="loose", media_type=MediaType.image)
        db.commit()

        result = list_library(
            slug=space.slug, folder="none", db=db, current_user=creator,
        )
        titles = [item["title"] for item in result["items"]]
        assert titles == ["loose"]

    def test_search_matches_title(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_asset(db, space, title="unique-worksheet", media_type=MediaType.image)
        _make_asset(db, space, title="other", media_type=MediaType.image)
        db.commit()

        result = list_library(
            slug=space.slug, q="worksheet", db=db, current_user=creator,
        )
        titles = [item["title"] for item in result["items"]]
        assert titles == ["unique-worksheet"]

    def test_response_always_includes_folders_list(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        db.add(LibraryFolder(id="flr_x", space_id=space.id, name="X", position=0))
        db.add(LibraryFolder(id="flr_y", space_id=space.id, name="Y", position=1))
        db.commit()

        result = list_library(slug=space.slug, db=db, current_user=creator)
        assert [f["name"] for f in result["folders"]] == ["X", "Y"]

    def test_file_item_carries_media_type_and_url(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        _make_asset(db, space, title="pic", media_type=MediaType.image)
        db.commit()

        result = list_library(slug=space.slug, db=db, current_user=creator)
        item = result["items"][0]
        assert item["kind"] == "file"
        assert item["file"]["media_type"] == "image"
        assert item["file"]["url"].startswith("/api/uploads/")


# ---------------------------------------------------------------------------
# resource block can point at a media asset (was: SpaceResource only)
# ---------------------------------------------------------------------------


class TestResourceBlockAcceptsMediaAsset:
    def test_create_resource_block_with_media_asset_id(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _make_pathway_and_step(db, space)
        asset = _make_asset(
            db, space, title="worksheet",
            media_type=MediaType.document,
        )
        db.commit()

        # Pass through the exact schema the block editor uses. No
        # block_type-based gate — a resource block may cite either
        # resource_id or media_asset_id.
        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="resource",
                media_asset_id=asset.id,
            ),
            db=db, current_user=creator,
        )
        assert block.block_type == "resource"
        assert block.media_asset_id == asset.id
        assert block.resource_id is None
        # And the response snapshot exposes the linked media_asset so
        # the frontend can render a card from it.
        assert block.media_asset is not None
        assert block.media_asset.id == asset.id
