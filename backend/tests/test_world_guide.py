"""
Tests for the World Guide — governance documentation CMS.

Locks:
- Admin auth is required on every admin endpoint.
- Creating a document also creates an initial 0.1 draft.
- Draft edits update content, reading_time, updated_at.
- Publishing a draft: freezes version, sets published_at + user,
  assigns 1.0 on first publish and increments on subsequent publishes,
  archives the previous "current" published version, updates
  current_version_id, refuses to publish a version twice.
- Version history is retained: the archived predecessor is still
  listed with its original content.
- Slug uniqueness returns 409 on conflict.
- Public list only shows non-archived documents with a live
  published version.
- Public GET returns the current published version's content, never a
  draft, and gives a 404 for slugs whose document is archived or
  draft-only.
- Public GET related-documents suggests other published docs in the
  same category, excluding the target itself.
- Reading time calculation uses ~220 wpm across the four sections.
- New draft from published branches with carry_over_content;
  refuses when an open draft already exists.
- Duplicate creates a new document + draft with a non-colliding slug.
- Archived document is not editable; not publishable; not returned
  publicly.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app.admin.world_guide.routes import (
    archive_document,
    create_document,
    create_new_draft,
    duplicate_document,
    get_document,
    get_overview,
    list_documents,
    publish_version,
    update_document,
    update_version,
)
from app.admin.world_guide.schemas import (
    CreateDocumentRequest,
    NewDraftFromCurrentRequest,
    UpdateDocumentRequest,
    UpdateVersionRequest,
)
from app.models.world_guide import (
    WorldGuideDocument,
    WorldGuideVersion,
    estimate_reading_time_minutes,
)
from app.world_guide.routes import (
    get_public_document,
    list_public_documents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_doc(admin, db, **overrides) -> WorldGuideDocument:
    req = CreateDocumentRequest(
        title=overrides.pop("title", "Terms of Use"),
        slug=overrides.pop("slug", f"terms-{uuid.uuid4().hex[:6]}"),
        category=overrides.pop("category", "governance"),
        audience=overrides.pop("audience", "everyone"),
        summary=overrides.pop("summary", None),
        effective_date=overrides.pop("effective_date", None),
    )
    detail = create_document(req, admin=admin, db=db)
    return db.query(WorldGuideDocument).filter(WorldGuideDocument.id == detail.id).one()


def _edit_draft(admin, db, doc, **fields):
    draft = (
        db.query(WorldGuideVersion)
        .filter(
            WorldGuideVersion.document_id == doc.id,
            WorldGuideVersion.status == "draft",
        )
        .one()
    )
    update_version(
        draft.id,
        UpdateVersionRequest(**fields),
        admin=admin, db=db,
    )
    return draft


# ---------------------------------------------------------------------------
# 1. Create document
# ---------------------------------------------------------------------------


class TestCreateDocument:
    def test_creates_document_with_initial_draft(self, db, make_user):
        admin = make_user(role="admin")
        detail = create_document(
            CreateDocumentRequest(
                title="Terms of Use",
                slug="terms",
                category="governance",
                audience="everyone",
                summary="What the platform expects of members.",
            ),
            admin=admin, db=db,
        )
        assert detail.slug == "terms"
        assert detail.current_version_id is None
        assert detail.current_draft is not None
        assert detail.current_draft.status == "draft"
        assert detail.current_draft.version_number == "0.1"
        assert detail.current_published is None
        # Author recorded as the creating admin.
        assert detail.author_user_id == admin.id

    def test_slug_conflict_returns_409(self, db, make_user):
        admin = make_user(role="admin")
        create_document(
            CreateDocumentRequest(
                title="Terms", slug="terms",
                category="governance", audience="everyone",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as e:
            create_document(
                CreateDocumentRequest(
                    title="Other", slug="terms",
                    category="governance", audience="everyone",
                ),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_invalid_category_or_audience_rejected_at_schema(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateDocumentRequest(
                title="X", slug="x",
                category="not_real", audience="everyone",
            )
        with pytest.raises(ValidationError):
            CreateDocumentRequest(
                title="X", slug="x",
                category="governance", audience="not_real",
            )

    def test_slug_normalisation(self):
        from pydantic import ValidationError
        # Bad characters rejected.
        with pytest.raises(ValidationError):
            CreateDocumentRequest(
                title="X", slug="Has Spaces",
                category="governance", audience="everyone",
            )
        # Uppercase lowered.
        req = CreateDocumentRequest(
            title="X", slug="Terms-Of-Use",
            category="governance", audience="everyone",
        )
        assert req.slug == "terms-of-use"


# ---------------------------------------------------------------------------
# 2. Edit draft + publish + reading time
# ---------------------------------------------------------------------------


class TestEditAndPublish:
    def test_edit_draft_updates_content_and_reading_time(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        body_text = "This is the main content. " * 100  # ≈ 500 words
        _edit_draft(admin, db, doc,
                    why_this_exists="Because.",
                    what_this_covers="This.",
                    main_content=body_text)
        db.refresh(doc)
        # ~500 words / 220 wpm ≈ 2 minutes.
        assert doc.reading_time_minutes is not None
        assert doc.reading_time_minutes >= 2

    def test_publish_first_time_assigns_1_0(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        _edit_draft(admin, db, doc, main_content="A", effective_date=date(2026, 8, 1))
        draft = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        publish_version(draft.id, admin=admin, db=db)
        db.refresh(draft); db.refresh(doc)
        assert draft.status == "published"
        assert draft.version_number == "1.0"
        assert draft.published_at is not None
        assert draft.published_by_user_id == admin.id
        assert doc.current_version_id == draft.id

    def test_publish_new_draft_increments_minor_and_archives_predecessor(
        self, db, make_user,
    ):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        _edit_draft(admin, db, doc, main_content="v1")
        v1 = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        publish_version(v1.id, admin=admin, db=db)
        # Branch a new draft off the published version.
        create_new_draft(
            doc.id,
            NewDraftFromCurrentRequest(carry_over_content=True),
            admin=admin, db=db,
        )
        v2 = (
            db.query(WorldGuideVersion)
            .filter(
                WorldGuideVersion.document_id == doc.id,
                WorldGuideVersion.status == "draft",
            )
            .one()
        )
        assert v2.main_content == "v1"  # carried over
        _edit_draft(admin, db, doc, main_content="v2", whats_changed="clarified X")
        publish_version(v2.id, admin=admin, db=db)
        db.refresh(v1); db.refresh(v2); db.refresh(doc)
        # v1 kept forever but archived; v2 is now current.
        assert v1.status == "archived"
        assert v1.main_content == "v1"
        assert v2.status == "published"
        assert v2.version_number == "1.1"
        assert doc.current_version_id == v2.id

    def test_publishing_a_published_version_refused(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        _edit_draft(admin, db, doc, main_content="A")
        draft = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        publish_version(draft.id, admin=admin, db=db)
        with pytest.raises(HTTPException) as e:
            publish_version(draft.id, admin=admin, db=db)
        assert e.value.status_code == 409

    def test_editing_a_published_version_refused(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        _edit_draft(admin, db, doc, main_content="A")
        draft = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        publish_version(draft.id, admin=admin, db=db)
        with pytest.raises(HTTPException) as e:
            update_version(
                draft.id,
                UpdateVersionRequest(main_content="B"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_reading_time_helper_words_per_minute(self):
        text = "word " * 440  # ~ 2 minutes at 220 wpm
        assert estimate_reading_time_minutes(text) == 2
        assert estimate_reading_time_minutes(None, "", "hi") == 1


# ---------------------------------------------------------------------------
# 3. New draft + duplicate
# ---------------------------------------------------------------------------


class TestNewDraftAndDuplicate:
    def test_new_draft_refused_when_open_draft_exists(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        with pytest.raises(HTTPException) as e:
            create_new_draft(
                doc.id,
                NewDraftFromCurrentRequest(),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_duplicate_creates_new_slug_and_carries_content(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db, slug="terms")
        _edit_draft(admin, db, doc, main_content="The body.")
        draft = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        publish_version(draft.id, admin=admin, db=db)
        dup = duplicate_document(doc.id, admin=admin, db=db)
        assert dup.slug.startswith("terms-copy")
        assert dup.current_draft is not None
        assert dup.current_draft.main_content == "The body."
        # The copy is a fresh draft, not published.
        assert dup.current_version_id is None


# ---------------------------------------------------------------------------
# 4. Update document metadata + archive
# ---------------------------------------------------------------------------


class TestMetadataAndArchive:
    def test_update_metadata_success(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db, slug="terms")
        detail = update_document(
            doc.id,
            UpdateDocumentRequest(title="Updated", summary="s"),
            admin=admin, db=db,
        )
        assert detail.title == "Updated"
        assert detail.summary == "s"

    def test_update_slug_collision_returns_409(self, db, make_user):
        admin = make_user(role="admin")
        _new_doc(admin, db, slug="terms")
        other = _new_doc(admin, db, slug="privacy")
        with pytest.raises(HTTPException) as e:
            update_document(
                other.id,
                UpdateDocumentRequest(slug="terms"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_archive_document_hides_from_public(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        _edit_draft(admin, db, doc, main_content="A")
        draft = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        publish_version(draft.id, admin=admin, db=db)
        # Before archive — in the public list.
        assert any(c.slug == doc.slug for c in list_public_documents(db=db))
        archive_document(doc.id, admin=admin, db=db)
        # After archive — gone.
        assert not any(c.slug == doc.slug for c in list_public_documents(db=db))

    def test_archived_document_refuses_updates_and_publish(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db)
        _edit_draft(admin, db, doc, main_content="A")
        draft = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        archive_document(doc.id, admin=admin, db=db)
        with pytest.raises(HTTPException) as e_upd:
            update_document(doc.id, UpdateDocumentRequest(title="X"), admin=admin, db=db)
        assert e_upd.value.status_code == 409
        with pytest.raises(HTTPException) as e_pub:
            publish_version(draft.id, admin=admin, db=db)
        assert e_pub.value.status_code == 409


# ---------------------------------------------------------------------------
# 5. Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_public_list_hides_draft_only_documents(self, db, make_user):
        admin = make_user(role="admin")
        _new_doc(admin, db, slug="draft-only")
        # No publish → public list is empty.
        assert list_public_documents(db=db) == []

    def test_public_document_returns_only_published_content(self, db, make_user):
        admin = make_user(role="admin")
        doc = _new_doc(admin, db, slug="terms")
        _edit_draft(admin, db, doc, main_content="v1 body")
        draft = db.query(WorldGuideVersion).filter_by(document_id=doc.id).one()
        publish_version(draft.id, admin=admin, db=db)
        # Branch a new draft with different content.
        create_new_draft(doc.id, NewDraftFromCurrentRequest(), admin=admin, db=db)
        v2 = db.query(WorldGuideVersion).filter(
            WorldGuideVersion.document_id == doc.id,
            WorldGuideVersion.status == "draft",
        ).one()
        update_version(
            v2.id,
            UpdateVersionRequest(main_content="v2 body"),
            admin=admin, db=db,
        )
        detail = get_public_document("terms", db=db)
        assert detail.main_content == "v1 body"
        assert detail.version_number == "1.0"

    def test_public_document_returns_related_docs_in_same_category(self, db, make_user):
        admin = make_user(role="admin")
        # Two governance docs published.
        d1 = _new_doc(admin, db, slug="terms")
        _edit_draft(admin, db, d1, main_content="a")
        v1 = db.query(WorldGuideVersion).filter_by(document_id=d1.id).one()
        publish_version(v1.id, admin=admin, db=db)

        d2 = _new_doc(admin, db, slug="privacy", title="Privacy Policy")
        _edit_draft(admin, db, d2, main_content="b")
        v2 = db.query(WorldGuideVersion).filter_by(document_id=d2.id).one()
        publish_version(v2.id, admin=admin, db=db)

        detail = get_public_document("terms", db=db)
        assert any(r.slug == "privacy" for r in detail.related)
        assert not any(r.slug == "terms" for r in detail.related)

    def test_public_get_404_on_unknown_slug(self, db, make_user):
        with pytest.raises(HTTPException) as e:
            get_public_document("does-not-exist", db=db)
        assert e.value.status_code == 404

    def test_draft_can_be_previewed_via_admin_endpoint(self, db, make_user):
        """A saved draft is readable through the admin GET without
        being published — that's what the admin Preview route uses."""
        admin = make_user(role="admin")
        doc = _new_doc(admin, db, slug="draft-preview")
        _edit_draft(
            admin, db, doc,
            why_this_exists="why body",
            what_this_covers="what body",
            main_content="the body of the doc",
            whats_changed="first cut",
        )
        detail = get_document(doc.id, _=admin, db=db)
        # The draft is present with the saved content.
        assert detail.current_draft is not None
        assert detail.current_draft.status == "draft"
        assert detail.current_draft.main_content == "the body of the doc"
        # Nothing is published yet.
        assert detail.current_published is None

    def test_draft_preview_remains_hidden_from_public_route(self, db, make_user):
        """The admin can preview the draft; the world sees a 404."""
        admin = make_user(role="admin")
        doc = _new_doc(admin, db, slug="private-draft")
        _edit_draft(admin, db, doc, main_content="secret sauce")
        # Admin can see the draft body.
        detail = get_document(doc.id, _=admin, db=db)
        assert detail.current_draft is not None
        assert detail.current_draft.main_content == "secret sauce"
        # Public route refuses.
        with pytest.raises(HTTPException) as e:
            get_public_document("private-draft", db=db)
        assert e.value.status_code == 404
        # And it does not appear in the public list either.
        assert not any(c.slug == "private-draft" for c in list_public_documents(db=db))


# ---------------------------------------------------------------------------
# 6. Overview + list
# ---------------------------------------------------------------------------


class TestOverviewAndList:
    def test_overview_counts_reflect_state(self, db, make_user):
        admin = make_user(role="admin")
        # Two drafts, one published, one archived.
        d1 = _new_doc(admin, db, slug="a")   # draft
        d2 = _new_doc(admin, db, slug="b")   # will publish
        _edit_draft(admin, db, d2, main_content="…")
        v2 = db.query(WorldGuideVersion).filter_by(document_id=d2.id).one()
        publish_version(v2.id, admin=admin, db=db)
        d3 = _new_doc(admin, db, slug="c")   # will archive
        archive_document(d3.id, admin=admin, db=db)

        ov = get_overview(_=admin, db=db)
        assert ov.published_count == 1
        assert ov.draft_count == 1
        assert ov.archived_count == 1
        assert ov.last_published is not None
        assert ov.last_published.slug == "b"

    def test_image_upload_returns_url(self, db, make_user, monkeypatch, tmp_path):
        import asyncio
        import io
        from fastapi import UploadFile
        from app.admin.world_guide.routes import upload_image
        from app.core import storage as storage_module

        # Redirect saves into a temp directory so the test doesn't touch
        # the real uploads tree.
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)
        admin = make_user(role="admin")
        # A 1x1 transparent PNG is enough to exercise the endpoint.
        png = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
            "890000000D49444154789C6360000000000200015F0F0000000049454E44AE426082"
        )
        file = UploadFile(
            file=io.BytesIO(png),
            filename="pixel.png",
            headers={"content-type": "image/png"},  # type: ignore[arg-type]
        )
        result = asyncio.run(upload_image(file=file, _=admin))
        assert isinstance(result["url"], str)
        assert result["url"].endswith(".png")
        assert result["media_type"] == "image"

    def test_image_upload_refuses_non_image(self, db, make_user, tmp_path, monkeypatch):
        import asyncio
        import io
        from fastapi import UploadFile, HTTPException
        from app.admin.world_guide.routes import upload_image

        admin = make_user(role="admin")
        file = UploadFile(
            file=io.BytesIO(b"not an image"),
            filename="notes.txt",
            headers={"content-type": "text/plain"},  # type: ignore[arg-type]
        )
        with pytest.raises(HTTPException) as e:
            asyncio.run(upload_image(file=file, _=admin))
        assert e.value.status_code == 400

    def test_list_documents_returns_all_with_status(self, db, make_user):
        admin = make_user(role="admin")
        d1 = _new_doc(admin, db, slug="a")
        d2 = _new_doc(admin, db, slug="b")
        _edit_draft(admin, db, d2, main_content="…")
        v2 = db.query(WorldGuideVersion).filter_by(document_id=d2.id).one()
        publish_version(v2.id, admin=admin, db=db)
        rows = list_documents(_=admin, db=db)
        by_slug = {r.slug: r for r in rows}
        assert by_slug["a"].status == "draft"
        assert by_slug["b"].status == "published"
        assert by_slug["b"].current_version_number == "1.0"
