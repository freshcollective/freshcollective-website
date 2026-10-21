"""Offerings B6/B7 — covers, About blocks, and the member detail page.

Route handlers are called directly, matching the suite's convention. The
feature flag is bypassed by construction, so it is tested structurally
(see ``test_offering_creator_api.py``) rather than by calling through.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core import storage
from app.creator import _offering_about_routes as about_api
from app.creator import _offering_file_routes as files_api
from app.creator import _offering_routes as api
from app.creator.plan_config import PLANS_BY_SLUG
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockReorderRequest,
    AboutBlockUpdateRequest,
)
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
    OfferingStatus,
)
from app.models.platform import (
    PathwayAboutBlock, SpaceMembership, SpaceMembershipStatus,
)
from app.services import offering_covers as covers
from app.services import offering_files as of
from app.spaces import _offering_member_routes as member_api


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:16]}"


def _status(fn, *a, **kw) -> int:
    try:
        fn(*a, **kw)
    except HTTPException as exc:
        return exc.status_code
    return 200


@pytest.fixture
def plan(db):
    from app.models.creator_billing import (
        CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
    )

    def _attach(user, slug: str = "creator"):
        cap = PLANS_BY_SLUG[slug]
        row = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if row is None:
            row = CreatorPlan(
                id=_uid("plan"), slug=slug, name=cap.display_name,
                monthly_price_cents=cap.monthly_price_cents or 0,
                currency="AUD", transaction_fee_basis_points=800,
                collective_limit=1,
            )
            db.add(row)
            db.flush()
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=user.id, creator_plan_id=row.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(), source="manual_grant",
        ))
        db.flush()
    return _attach


@pytest.fixture
def owner_space(db, make_space, plan):
    def _make(plan_slug: str = "creator"):
        from app.models.user import User
        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        plan(owner, plan_slug)
        return space, owner
    return _make


@pytest.fixture
def offering(db):
    def _make(space, **kw) -> Offering:
        d = dict(
            id=_uid("off"), space_id=space.id,
            created_by_user_id=space.creator_id,
            slug=f"g-{uuid.uuid4().hex[:8]}", title="A Gentle Guide",
            summary="Short lines for a card.",
            status=OfferingStatus.draft.value,
        )
        d.update(kw)
        row = Offering(**d)
        db.add(row)
        db.flush()
        return row
    return _make


def _passed_file(db, off, **kw) -> OfferingFile:
    name = kw.pop("name", "workbook.pdf")
    d = dict(
        id=_uid("ofl"), offering_id=off.id,
        storage_key=of.build_storage_key(offering_id=off.id, filename=name),
        original_filename=name, content_type="application/pdf",
        byte_size=2_400_000, sort_order=0,
        validation_status=FVS.passed.value, checks_performed=[],
    )
    d.update(kw)
    row = OfferingFile(**d)
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Default covers
# ---------------------------------------------------------------------------


class TestDefaultCovers:

    def test_the_manifest_has_the_five_approved_covers(self):
        assert len(covers.DEFAULT_COVERS) == 5
        assert {c.key for c in covers.DEFAULT_COVERS} == {
            "workbook-guides", "audio", "spreadsheet",
            "collections", "other-resources",
        }

    def test_every_cover_ships_both_sizes_in_the_repository(self):
        """A manifest entry with no file behind it is a broken picker."""
        assert covers.missing_assets() == []

    def test_the_optimised_files_are_small_enough_to_be_covers(self):
        """Source PNGs were ~2.3 MB each. A cover is chrome — it must not
        cost a member two megabytes of their data to look at a card."""
        for key, path in covers.asset_paths():
            kb = path.stat().st_size / 1024
            limit = 200 if not key.endswith("-thumb.webp") else 80
            assert kb < limit, f"{key} is {kb:.0f} KB"

    def test_covers_live_in_the_public_namespace(self):
        """``platform-artwork/`` routes to the public bucket and an
        unauthenticated route, so a cover renders for a signed-out
        visitor on a public Collective card."""
        for cover in covers.DEFAULT_COVERS:
            assert cover.storage_key.startswith("platform-artwork/")
            assert cover.url.startswith(
                "/api/uploads/platform-artwork/offering-covers/",
            )

    def test_the_endpoint_returns_what_the_picker_needs(self, make_user):
        out = api.list_offering_covers(current_user=make_user(role="creator"))
        assert len(out) == 5
        for entry in out:
            assert set(entry) == {
                "key", "label", "description", "url", "thumbnail_url",
            }
            assert entry["label"] and entry["description"]

    def test_labels_describe_what_is_sold_not_what_is_photographed(self):
        """A creator looking for somewhere to put a meditation should
        find "Audio & meditations", not "headphones on a window seat"."""
        labels = {c.key: c.label for c in covers.DEFAULT_COVERS}
        assert labels["audio"] == "Audio & meditations"
        assert labels["workbook-guides"] == "Workbooks & guides"
        for label in labels.values():
            assert "photo" not in label.lower()

    def test_choosing_a_default_copies_nothing(self, db, owner_space, offering):
        """A default cover is *referenced*. One object serves every
        Offering that picks it — nothing is written into the creator's
        own storage namespace."""
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space()
        off = offering(space)
        chosen = covers.DEFAULT_COVERS[0]

        out = api.update_offering(
            space.slug, off.slug,
            OfferingUpdateRequest(cover_image_url=chosen.url),
            db=db, current_user=owner,
        )
        assert out["cover_image_url"] == chosen.url
        # Nothing under the per-Offering cover namespace.
        root = storage.UPLOAD_DIR / of.OFFERING_COVERS_PREFIX / off.id
        assert not root.exists() or not any(root.iterdir())

    def test_two_offerings_can_share_one_cover(self, db, owner_space, offering):
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space()
        chosen = covers.DEFAULT_COVERS[1]
        for _ in range(2):
            off = offering(space)
            out = api.update_offering(
                space.slug, off.slug,
                OfferingUpdateRequest(cover_image_url=chosen.url),
                db=db, current_user=owner,
            )
            assert out["cover_image_url"] == chosen.url


class TestCoverUpload:

    def _png(self) -> bytes:
        # A minimal but genuine PNG header; the endpoint validates the
        # declared type rather than decoding, so this is enough.
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            + b"\x00" * 64
        )

    def _upload(self, data: bytes, name: str, ctype: str) -> UploadFile:
        return UploadFile(
            file=io.BytesIO(data), filename=name,
            headers=Headers({"content-type": ctype}),
        )

    def test_a_creator_can_upload_their_own_cover(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space()
        off = offering(space)
        out = files_api.upload_offering_cover(
            slug=space.slug, offering_slug=off.slug,
            file=self._upload(self._png(), "mine.png", "image/png"),
            db=db, current_user=owner,
        )
        url = out["cover_image_url"]
        assert url.startswith(f"/api/uploads/{of.OFFERING_COVERS_PREFIX}/{off.id}/")
        # And it satisfies the publication check.
        from app.services.offering_readiness import is_acceptable_cover
        assert is_acceptable_cover(url)
        storage.delete_file(url.removeprefix("/api/uploads/"))

    def test_the_offering_id_is_a_whole_path_segment(
        self, db, owner_space, offering,
    ):
        """``_authorise_offering_cover`` reads the Offering id out of the
        second segment, so the shape is load-bearing."""
        space, owner = owner_space()
        off = offering(space)
        out = files_api.upload_offering_cover(
            slug=space.slug, offering_slug=off.slug,
            file=self._upload(self._png(), "mine.png", "image/png"),
            db=db, current_user=owner,
        )
        key = out["cover_image_url"].removeprefix("/api/uploads/")
        assert key.split("/")[1] == off.id
        storage.delete_file(key)

    @pytest.mark.parametrize("ctype,name", [
        ("image/svg+xml", "x.svg"),
        ("application/pdf", "x.pdf"),
        ("text/html", "x.html"),
    ])
    def test_non_raster_types_are_refused(
        self, db, owner_space, offering, ctype, name,
    ):
        """No SVG: it is a document that can carry script, and a cover
        renders on member-facing pages."""
        space, owner = owner_space()
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            files_api.upload_offering_cover(
                slug=space.slug, offering_slug=off.slug,
                file=self._upload(b"x" * 100, name, ctype),
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 422

    def test_an_oversized_cover_is_refused(self, db, owner_space, offering):
        space, owner = owner_space()
        off = offering(space)
        big = b"\x89PNG\r\n\x1a\n" + b"\0" * (files_api.MAX_COVER_BYTES + 1024)
        with pytest.raises(HTTPException) as exc:
            files_api.upload_offering_cover(
                slug=space.slug, offering_slug=off.slug,
                file=self._upload(big, "big.png", "image/png"),
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 413

    def test_replacing_a_custom_cover_removes_the_old_object(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space()
        off = offering(space)
        first = files_api.upload_offering_cover(
            slug=space.slug, offering_slug=off.slug,
            file=self._upload(self._png(), "a.png", "image/png"),
            db=db, current_user=owner,
        )["cover_image_url"]
        second = files_api.upload_offering_cover(
            slug=space.slug, offering_slug=off.slug,
            file=self._upload(self._png(), "b.png", "image/png"),
            db=db, current_user=owner,
        )["cover_image_url"]
        assert first != second
        old = storage.UPLOAD_DIR / first.removeprefix("/api/uploads/")
        assert not old.is_file(), "the superseded cover was left behind"
        storage.delete_file(second.removeprefix("/api/uploads/"))

    def test_switching_to_a_default_never_deletes_the_shared_asset(
        self, db, owner_space, offering,
    ):
        """The prefix check is what stops a creator's cover change
        deleting a platform asset every other Offering depends on."""
        from app.creator.schemas_offerings import OfferingUpdateRequest
        space, owner = owner_space()
        off = offering(space)
        shared = covers.DEFAULT_COVERS[0]
        api.update_offering(
            space.slug, off.slug,
            OfferingUpdateRequest(cover_image_url=shared.url),
            db=db, current_user=owner,
        )
        out = files_api.upload_offering_cover(
            slug=space.slug, offering_slug=off.slug,
            file=self._upload(self._png(), "mine.png", "image/png"),
            db=db, current_user=owner,
        )
        assert (storage.UPLOAD_DIR / shared.storage_key).is_file(), (
            "uploading a custom cover deleted a shared platform asset"
        )
        storage.delete_file(out["cover_image_url"].removeprefix("/api/uploads/"))

    def test_only_the_owner_may_upload_a_cover(
        self, db, owner_space, offering, make_user,
    ):
        space, _owner = owner_space()
        off = offering(space)
        stranger = make_user(role="creator")
        assert _status(
            files_api.upload_offering_cover,
            slug=space.slug, offering_slug=off.slug,
            file=self._upload(self._png(), "x.png", "image/png"),
            db=db, current_user=stranger,
        ) == 404


# ---------------------------------------------------------------------------
# About blocks
# ---------------------------------------------------------------------------


class TestOfferingAboutBlocks:

    def test_blocks_are_stored_against_the_offering(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space()
        off = offering(space)
        block = about_api.create_offering_about_block(
            slug=space.slug, offering_slug=off.slug,
            body=AboutBlockCreateRequest(block_type="text", content="Hello"),
            db=db, current_user=owner,
        )
        assert block.owner_kind == "offering"
        assert block.owner_id == off.id
        # The legacy Pathway FK stays NULL — setting it would make this
        # row render on a Pathway page.
        assert block.pathway_id is None

    def test_the_same_table_and_block_types_as_pathways(
        self, db, owner_space, offering,
    ):
        """Not a parallel system: the same rows, so the same member-side
        renderer displays them."""
        space, owner = owner_space()
        off = offering(space)
        for kind in ("text", "heading", "image", "columns"):
            about_api.create_offering_about_block(
                slug=space.slug, offering_slug=off.slug,
                body=AboutBlockCreateRequest(block_type=kind),
                db=db, current_user=owner,
            )
        rows = db.query(PathwayAboutBlock).filter(
            PathwayAboutBlock.owner_kind == "offering",
            PathwayAboutBlock.owner_id == off.id,
        ).all()
        assert len(rows) == 4
        assert {str(r.block_type.value) for r in rows} == {
            "text", "heading", "image", "columns",
        }

    def test_blocks_keep_their_order(self, db, owner_space, offering):
        space, owner = owner_space()
        off = offering(space)
        made = [
            about_api.create_offering_about_block(
                slug=space.slug, offering_slug=off.slug,
                body=AboutBlockCreateRequest(block_type="text", content=str(i)),
                db=db, current_user=owner,
            ) for i in range(3)
        ]
        assert [b.position for b in made] == [0, 1, 2]
        out = about_api.reorder_offering_about_blocks(
            slug=space.slug, offering_slug=off.slug,
            body=AboutBlockReorderRequest(ids=[made[2].id, made[0].id, made[1].id]),
            db=db, current_user=owner,
        )
        assert [b.id for b in out] == [made[2].id, made[0].id, made[1].id]

    def test_a_block_can_be_edited_and_deleted(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space()
        off = offering(space)
        block = about_api.create_offering_about_block(
            slug=space.slug, offering_slug=off.slug,
            body=AboutBlockCreateRequest(block_type="text", content="first"),
            db=db, current_user=owner,
        )
        updated = about_api.update_offering_about_block(
            slug=space.slug, offering_slug=off.slug, block_id=block.id,
            body=AboutBlockUpdateRequest(content="second"),
            db=db, current_user=owner,
        )
        assert updated.content == "second"
        about_api.delete_offering_about_block(
            slug=space.slug, offering_slug=off.slug, block_id=block.id,
            db=db, current_user=owner,
        )
        assert about_api.list_offering_about_blocks(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        ) == []

    def test_a_dangerous_link_is_refused(self, db, owner_space, offering):
        """SEC-016-1's URL rules apply here too — the shared helper runs
        the same validators the Series About page uses."""
        space, owner = owner_space()
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            about_api.create_offering_about_block(
                slug=space.slug, offering_slug=off.slug,
                body=AboutBlockCreateRequest(
                    block_type="link", embed_url="javascript:alert(1)",
                ),
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 400

    def test_another_collectives_block_cannot_be_edited(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space()
        mine = offering(space)
        other = offering(space)
        far = about_api.create_offering_about_block(
            slug=space.slug, offering_slug=other.slug,
            body=AboutBlockCreateRequest(block_type="text", content="theirs"),
            db=db, current_user=owner,
        )
        assert _status(
            about_api.update_offering_about_block,
            slug=space.slug, offering_slug=mine.slug, block_id=far.id,
            body=AboutBlockUpdateRequest(content="mine now"),
            db=db, current_user=owner,
        ) == 404

    def test_a_moderator_cannot_edit_the_about_page(
        self, db, owner_space, offering, make_user,
    ):
        """Owner-only, like the rest of Offerings — unlike the Pathway
        About page, which accepts any manager."""
        space, _owner = owner_space()
        off = offering(space)
        moderator = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=moderator.id,
            role="moderator", status=SpaceMembershipStatus.active,
            source="invited", joined_at=datetime.utcnow(),
        ))
        db.flush()
        assert _status(
            about_api.create_offering_about_block,
            slug=space.slug, offering_slug=off.slug,
            body=AboutBlockCreateRequest(block_type="text", content="hi"),
            db=db, current_user=moderator,
        ) == 404

    def test_about_content_is_never_required_to_publish(
        self, db, owner_space, offering,
    ):
        from app.services import offering_readiness
        space, owner = owner_space()
        off = offering(
            space, cover_image_url=covers.DEFAULT_COVERS[0].url,
            pricing_kind=OfferingPricingKind.free.value,
        )
        _passed_file(db, off)
        result = offering_readiness.evaluate(
            db, offering=off, space=space, owner=owner,
        )
        assert result.ready, result.unmet_ids
        assert not any("about" in r.id for r in result.requirements)


# ---------------------------------------------------------------------------
# Member detail page
# ---------------------------------------------------------------------------


class TestMemberOfferingPage:

    @pytest.fixture(autouse=True)
    def _flag_on(self, offerings_enabled):
        """These call the member handler directly, bypassing the route
        dependency — but Phase C/D added an in-request flag check (the
        ``offerings`` area is dropped from ``area_access`` while the
        feature is off), so the flag has to be genuinely on."""

    def _published(self, db, space, **kw) -> Offering:
        off = Offering(
            id=_uid("off"), space_id=space.id,
            created_by_user_id=space.creator_id,
            slug=f"p-{uuid.uuid4().hex[:8]}", title="Morning Pages",
            summary="A gentle daily practice.",
            cover_image_url=covers.DEFAULT_COVERS[0].url,
            status=OfferingStatus.published.value,
            pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=1500, published_at=datetime.utcnow(),
            **kw,
        )
        db.add(off)
        db.flush()
        return off

    def test_a_member_sees_a_published_offering(
        self, db, owner_space, make_user,
    ):
        space, _owner = owner_space()
        off = self._published(db, space)
        _passed_file(db, off)
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        assert out["title"] == "Morning Pages"
        assert out["price_cents"] == 1500
        assert out["file_count"] == 1

    def test_a_draft_is_invisible_to_a_member(
        self, db, owner_space, offering, make_user,
    ):
        """404, not 403 — a stranger must not learn that a Collective is
        preparing something, or confirm a guessed slug."""
        space, _owner = owner_space()
        off = offering(space, status=OfferingStatus.draft.value)
        assert _status(
            member_api.get_member_offering,
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        ) == 404

    def test_the_owner_can_preview_a_draft(
        self, db, owner_space, offering,
    ):
        """The Preview button redirects into this very page, so an owner
        must be able to read their own unpublished Offering."""
        space, owner = owner_space()
        off = offering(space, status=OfferingStatus.draft.value)
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=owner,
        )
        assert out["status"] == "draft"
        assert out["viewer_manages"] is True

    def test_a_retired_offering_still_renders(
        self, db, owner_space, make_user,
    ):
        """It stops selling, not serving. A 404 would look deleted to
        somebody who owns it."""
        space, _owner = owner_space()
        off = self._published(
            db, space, retired_at=datetime.utcnow(),
        )
        off.status = OfferingStatus.retired.value
        db.flush()
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        assert out["status"] == "retired"

    def test_a_non_owner_is_told_what_the_files_are_but_not_where(
        self, db, owner_space, make_user,
    ):
        space, _owner = owner_space()
        off = self._published(db, space)
        _passed_file(db, off, name="guide.pdf", description="A 20-page guide")
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        f = out["files"][0]
        assert f["name"] == "guide.pdf"
        assert f["type_label"] == "PDF"
        assert f["size_label"].endswith("MB")
        assert f["description"] == "A 20-page guide"
        assert f["download_url"] is None, "a storage key leaked to a non-owner"
        assert out["viewer_owns"] is False

    def test_an_owner_is_given_the_download(self, db, owner_space, make_user):
        space, _owner = owner_space()
        off = self._published(db, space)
        row = _passed_file(db, off)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="one_time_purchase", status="active",
        ))
        db.flush()
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=buyer,
        )
        assert out["viewer_owns"] is True
        assert out["files"][0]["download_url"] == f"/api/uploads/{row.storage_key}"

    def test_unapproved_files_are_not_described_to_anyone(
        self, db, owner_space, make_user,
    ):
        """Describing a file a member could not then download is a
        promise the page cannot keep."""
        space, _owner = owner_space()
        off = self._published(db, space)
        _passed_file(db, off, name="ready.pdf")
        _passed_file(
            db, off, name="checking.pdf",
            validation_status=FVS.pending.value, sort_order=1,
        )
        _passed_file(
            db, off, name="refused.pdf",
            validation_status=FVS.rejected.value, sort_order=2,
        )
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        assert [f["name"] for f in out["files"]] == ["ready.pdf"]
        assert out["file_count"] == 1

    def test_a_superseded_file_is_not_listed(self, db, owner_space, make_user):
        space, _owner = owner_space()
        off = self._published(db, space)
        _passed_file(db, off, name="current.pdf")
        _passed_file(
            db, off, name="old.pdf", sort_order=1,
            superseded_at=datetime.utcnow(),
        )
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        assert [f["name"] for f in out["files"]] == ["current.pdf"]

    def test_the_payload_names_the_fulfilment_kind(
        self, db, owner_space, make_user,
    ):
        """The page's "Digital download" statement comes from the record,
        not from an assumption in the UI."""
        space, _owner = owner_space()
        off = self._published(db, space)
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        assert out["fulfilment_kind"] == "digital_download"

    def test_the_payload_never_names_the_commerce_rows(
        self, db, owner_space, make_user,
    ):
        """``can_acquire`` arrived in Phase C/D — acquisition exists now,
        and a field saying whether this viewer may use it is the point.

        What has *not* changed, and is the half of the original B7 test
        worth keeping, is that the payload still names no commerce row.
        That is a real boundary, not tidiness: ``POST /api/checkout``
        takes a Payment Option id and applies the generic option guards,
        while the Offering-specific ones — already owned, retired, no
        downloadable files, the creator's plan no longer permits paid
        selling, the price has moved — live in
        ``POST /api/checkout/offering``. Handing a client the option id
        would hand it a documented way round all five.
        """
        space, _owner = owner_space()
        off = self._published(db, space)
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        for forbidden in (
            "checkout_url", "purchase_url", "stripe",
            "payment_option_id", "payment_option_schedule_id",
        ):
            assert forbidden not in out, forbidden
        # Nor nested anywhere inside it.
        import json
        blob = json.dumps(out, default=str)
        assert "payment_option" not in blob

        # And the affordance that replaced them is present, and
        # answering honestly. ``_published`` builds the row directly
        # with no files, so the right answer here is "no" with a reason
        # — which is also the useful assertion: a published, priced
        # Offering with nothing downloadable must not be acquirable.
        from app.services import offering_acquisition as _acq
        assert out["can_acquire"] is False
        assert out["acquire_blocked"] == _acq.REASON_NO_FILES
        assert out["acquire_message"]

    def test_rich_content_travels_with_the_page(
        self, db, owner_space, make_user,
    ):
        space, owner = owner_space()
        off = self._published(db, space)
        about_api.create_offering_about_block(
            slug=space.slug, offering_slug=off.slug,
            body=AboutBlockCreateRequest(
                block_type="text", content="What's inside",
            ),
            db=db, current_user=owner,
        )
        out = member_api.get_member_offering(
            slug=space.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        )
        assert len(out["about_blocks"]) == 1
        assert out["about_blocks"][0]["content"] == "What's inside"

    def test_another_collectives_offering_is_not_reachable(
        self, db, owner_space, make_user,
    ):
        space_a, _ = owner_space()
        space_b, _ = owner_space()
        off = self._published(db, space_a)
        assert _status(
            member_api.get_member_offering,
            slug=space_b.slug, offering_slug=off.slug,
            db=db, current_user=make_user(),
        ) == 404

    @pytest.mark.parametrize("ctype,expected", [
        ("application/pdf", "PDF"),
        ("audio/mpeg", "Audio"),
        ("application/zip", "ZIP bundle"),
        ("text/csv", "Spreadsheet (CSV)"),
        (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document",
            "Word document",
        ),
    ])
    def test_file_types_are_named_in_words_a_member_understands(
        self, ctype, expected,
    ):
        assert member_api._file_type_label(ctype, "x.bin") == expected

    def test_the_type_comes_from_the_stored_content_type(self):
        """A file named ``notes.pdf`` that is really a ZIP is described
        as what it is."""
        assert member_api._file_type_label(
            "application/zip", "notes.pdf",
        ) == "ZIP bundle"
