"""A cover survives the whole editing lifecycle.

The release gate for moving default Offering artwork into World
Settings → World Artwork. Covers are now two columns resolved into one
answer, and the thing most worth proving is not that resolution works
once but that it **keeps working across every edit a creator makes**:
create, choose, upload, reopen, switch category, remove, come back.

Why these are end-to-end rather than unit tests
-----------------------------------------------

The failure this guards against is not a wrong return value — it is a
field quietly lost somewhere between the handler, the response model
and the next read. One was found exactly that way during development:
the Pydantic response model stripped ``custom_cover_url`` and
``default_cover_key``, so the editor received ``undefined`` and could
no longer tell which of the three cover states it was in. A test on the
resolver alone would have passed.

So every step here goes through the production handlers and re-reads
through the production GET, in the order a creator meets them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.creator import _offering_routes as api
from app.creator.schemas_offerings import (
    OfferingCreateRequest,
    OfferingUpdateRequest,
)
from app.models.offering import Offering, OfferingFile
from app.models.offering import OfferingFileValidationStatus as FVS
from app.models.platform import PlatformArtwork
from app.models.user import User
from app.services import offering_covers as covers
from app.services import offering_readiness as readiness
from app.spaces import _offering_member_routes as member_api


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _offerings_available(offerings_enabled):
    """Both switches on; scope is tested elsewhere."""


@pytest.fixture
def owned(db, make_space):
    """A Collective and its owner."""
    space = make_space()
    owner = db.query(User).filter(User.id == space.creator_id).one()
    return space, owner


def _artwork(db, cover: covers.OfferingCover, name: str) -> str:
    """Pretend an administrator uploaded this category's artwork.

    The URL shape is the one ``save_image_with_thumbnail`` produces —
    nested under ``platform-artwork/<artwork_key>/`` with a generated
    filename, which is precisely why an Offering cannot store it.
    """
    url = f"/api/uploads/platform-artwork/{cover.artwork_key}/{uuid.uuid4().hex}_{name}.webp"
    row = (
        db.query(PlatformArtwork)
        .filter(PlatformArtwork.key == cover.artwork_key)
        .first()
    )
    if row is None:
        row = PlatformArtwork(key=cover.artwork_key)
        db.add(row)
    row.image_url = url
    row.thumbnail_url = url.replace(".webp", "-thumb.webp")
    db.flush()
    return url


def _file(db, offering: Offering) -> OfferingFile:
    f = OfferingFile(
        id=_uid("of"), offering_id=offering.id,
        storage_key=f"offering-files/{offering.id}/{uuid.uuid4().hex}_w.pdf",
        original_filename="workbook.pdf", content_type="application/pdf",
        byte_size=8192, sort_order=0, resource_count=1,
        validation_status=FVS.passed.value, validated_at=datetime.utcnow(),
    )
    db.add(f)
    db.flush()
    return f


def _custom_url(offering: Offering) -> str:
    """A URL shaped the way the real cover-upload route writes one."""
    return f"/api/uploads/offering-covers/{offering.id}/{uuid.uuid4().hex}_mine.png"


# ---------------------------------------------------------------------------
# The whole lifecycle, in the order a creator meets it
# ---------------------------------------------------------------------------


def test_the_whole_cover_lifecycle(db, owned):
    """Create → choose → upload → reopen → switch → remove → reopen.

    Assertions at every step rather than only at the end, so a failure
    names the edit that broke rather than the last one.
    """
    space, owner = owned
    audio = covers.COVERS_BY_KEY["audio"]
    workbooks = covers.COVERS_BY_KEY["workbook-guides"]

    # An administrator has uploaded artwork for both categories.
    audio_url = _artwork(db, audio, "audio")
    workbooks_url = _artwork(db, workbooks, "workbook")

    # ── 1. Create. No cover of any kind. ──────────────────────────────
    created = api.create_offering(
        space.slug, OfferingCreateRequest(title="Deep Rest"),
        db=db, current_user=owner,
    )
    slug = created["slug"]
    assert created["cover_image_url"] is None
    assert created["custom_cover_url"] is None
    assert created["default_cover_key"] is None

    def reopen() -> dict:
        """Re-read through the production GET, as the editor does."""
        return api.get_offering(space.slug, slug, db=db, current_user=owner)

    def patch(**fields) -> dict:
        return api.update_offering(
            space.slug, slug, OfferingUpdateRequest(**fields),
            db=db, current_user=owner,
        )

    # ── 2. Choose a category. ─────────────────────────────────────────
    out = patch(default_cover_key=audio.key)
    assert out["default_cover_key"] == audio.key
    assert out["cover_image_url"] == audio_url, "resolves to the shared artwork"
    assert out["custom_cover_url"] is None
    # And it survives a reopen.
    assert reopen()["cover_image_url"] == audio_url

    # ── 3. Upload a custom cover. It wins; the category survives. ─────
    mine = _custom_url(db.query(Offering).filter(Offering.slug == slug).one())
    out = patch(cover_image_url=mine)
    assert out["cover_image_url"] == mine
    assert out["custom_cover_url"] == mine
    assert out["default_cover_key"] == audio.key, (
        "the category must survive a custom upload"
    )

    # ── 4. Reopen. All three fields still there. ──────────────────────
    out = reopen()
    assert out["cover_image_url"] == mine
    assert out["custom_cover_url"] == mine
    assert out["default_cover_key"] == audio.key

    # ── 5. Edit something unrelated. The cover is untouched. ──────────
    out = patch(title="Deep Rest — revised", summary="Six practices.")
    assert out["cover_image_url"] == mine
    assert out["custom_cover_url"] == mine
    assert out["default_cover_key"] == audio.key

    # ── 6. Switch category while a custom cover is in place. ──────────
    #     The shared default behind it changes; what a member sees does
    #     not, because the upload still wins.
    out = patch(default_cover_key=workbooks.key)
    assert out["default_cover_key"] == workbooks.key
    assert out["cover_image_url"] == mine, (
        "switching category changed the displayed cover despite a custom one"
    )

    # ── 7. Remove the custom cover. Falls back to the NEW category. ───
    out = patch(cover_image_url=None)
    assert out["custom_cover_url"] is None
    assert out["default_cover_key"] == workbooks.key
    assert out["cover_image_url"] == workbooks_url, (
        "removing a custom cover should fall back to the chosen category"
    )

    # ── 8. Reopen once more. ──────────────────────────────────────────
    out = reopen()
    assert out["cover_image_url"] == workbooks_url
    assert out["custom_cover_url"] is None
    assert out["default_cover_key"] == workbooks.key

    # ── 9. Clear the category too. Nothing — the gradient state. ──────
    out = patch(default_cover_key=None)
    assert out["cover_image_url"] is None
    assert out["default_cover_key"] is None
    assert reopen()["cover_image_url"] is None


class TestTheFieldsSurviveSerialisation:
    """The gap a direct handler call cannot see.

    Every other test in this file calls the handler and inspects the
    dict it returns. FastAPI does not: it passes that dict through the
    route's ``response_model``, which **drops any key the model does not
    declare**.

    That is not hypothetical. It happened during development — the
    model did not declare ``custom_cover_url`` or ``default_cover_key``,
    so the editor received ``undefined`` for both and could no longer
    tell which of the three cover states it was in. The bug was found by
    an end-to-end HTTP run, and then confirmed invisible to the direct
    tests above: neutering the model again left all of them passing.

    So these assert through the models themselves.
    """

    def test_the_summary_model_keeps_all_three_cover_fields(self):
        from app.creator.schemas_offerings import OfferingSummaryResponse
        for field in ("cover_image_url", "custom_cover_url",
                      "default_cover_key"):
            assert field in OfferingSummaryResponse.model_fields, field

    def test_the_detail_model_keeps_all_three(self):
        from app.creator.schemas_offerings import OfferingDetailResponse
        for field in ("cover_image_url", "custom_cover_url",
                      "default_cover_key"):
            assert field in OfferingDetailResponse.model_fields, field

    def test_a_real_payload_survives_the_detail_model(self, db, owned):
        """The whole round trip: handler → response_model → client.

        Validated the way FastAPI does it, so a field the handler sets
        and the model omits fails here rather than reaching a browser as
        ``undefined``.
        """
        from app.creator.schemas_offerings import OfferingDetailResponse
        space, owner = owned
        audio = covers.COVERS_BY_KEY["audio"]
        audio_url = _artwork(db, audio, "audio")
        created = api.create_offering(
            space.slug, OfferingCreateRequest(title="Serialised"),
            db=db, current_user=owner,
        )
        slug = created["slug"]
        off = db.query(Offering).filter(Offering.slug == slug).one()
        mine = _custom_url(off)
        api.update_offering(
            space.slug, slug,
            OfferingUpdateRequest(default_cover_key=audio.key),
            db=db, current_user=owner,
        )
        raw = api.update_offering(
            space.slug, slug, OfferingUpdateRequest(cover_image_url=mine),
            db=db, current_user=owner,
        )
        # What the client actually receives.
        sent = OfferingDetailResponse.model_validate(raw).model_dump()
        assert sent["cover_image_url"] == mine
        assert sent["custom_cover_url"] == mine
        assert sent["default_cover_key"] == audio.key

        # And the category-only state survives too.
        raw = api.update_offering(
            space.slug, slug, OfferingUpdateRequest(cover_image_url=None),
            db=db, current_user=owner,
        )
        sent = OfferingDetailResponse.model_validate(raw).model_dump()
        assert sent["cover_image_url"] == audio_url
        assert sent["custom_cover_url"] is None
        assert sent["default_cover_key"] == audio.key

    def test_the_list_payload_survives_the_summary_model(self, db, owned):
        """The Offerings list is a different model from the detail page,
        and the editor's card reads the same three fields."""
        from app.creator.schemas_offerings import OfferingSummaryResponse
        space, owner = owned
        audio = covers.COVERS_BY_KEY["audio"]
        audio_url = _artwork(db, audio, "audio")
        created = api.create_offering(
            space.slug, OfferingCreateRequest(title="Listed"),
            db=db, current_user=owner,
        )
        api.update_offering(
            space.slug, created["slug"],
            OfferingUpdateRequest(default_cover_key=audio.key),
            db=db, current_user=owner,
        )
        rows = api.list_offerings(space.slug, db=db, current_user=owner)
        sent = [
            OfferingSummaryResponse.model_validate(r).model_dump()
            for r in rows
        ]
        row = next(r for r in sent if r["slug"] == created["slug"])
        assert row["cover_image_url"] == audio_url
        assert row["default_cover_key"] == audio.key
        assert row["custom_cover_url"] is None

    def test_the_frontend_type_declares_what_the_api_sends(self):
        """The other half of the same contract. A field the API sends and
        the TypeScript type omits is a compile error the moment anything
        reads it — but a field the *type* declares and the API drops is
        silent, so both sides are pinned."""
        import pathlib as _pl
        src = (
            _pl.Path(__file__).resolve().parent.parent.parent
            / "frontend" / "src" / "types" / "platform.ts"
        ).read_text()
        import re
        m = re.search(r"export interface CreatorOffering \{(.*?)\n\}", src, re.S)
        assert m, "CreatorOffering interface not found"
        body = m.group(1)
        for field in ("cover_image_url", "custom_cover_url",
                      "default_cover_key"):
            assert field in body, field


class TestCustomCoversSurviveEverything:

    def test_a_custom_cover_survives_repeated_saves(self, db, owned):
        """The editor autosaves. Ten saves must not lose the cover."""
        space, owner = owned
        created = api.create_offering(
            space.slug, OfferingCreateRequest(title="Repeated"),
            db=db, current_user=owner,
        )
        slug = created["slug"]
        off = db.query(Offering).filter(Offering.slug == slug).one()
        mine = _custom_url(off)
        api.update_offering(
            space.slug, slug, OfferingUpdateRequest(cover_image_url=mine),
            db=db, current_user=owner,
        )
        for i in range(10):
            out = api.update_offering(
                space.slug, slug,
                OfferingUpdateRequest(summary=f"draft {i}"),
                db=db, current_user=owner,
            )
            assert out["custom_cover_url"] == mine, i
            assert out["cover_image_url"] == mine, i

    def test_a_custom_cover_is_unaffected_by_artwork_changes(self, db, owned):
        """An administrator replacing shared artwork — repeatedly — must
        never alter a creator-customised cover."""
        space, owner = owned
        audio = covers.COVERS_BY_KEY["audio"]
        _artwork(db, audio, "first")
        created = api.create_offering(
            space.slug, OfferingCreateRequest(title="Mine"),
            db=db, current_user=owner,
        )
        slug = created["slug"]
        off = db.query(Offering).filter(Offering.slug == slug).one()
        mine = _custom_url(off)
        api.update_offering(
            space.slug, slug,
            OfferingUpdateRequest(default_cover_key=audio.key),
            db=db, current_user=owner,
        )
        api.update_offering(
            space.slug, slug, OfferingUpdateRequest(cover_image_url=mine),
            db=db, current_user=owner,
        )
        for name in ("second", "third", "fourth"):
            _artwork(db, audio, name)
            out = api.get_offering(
                space.slug, slug, db=db, current_user=owner,
            )
            assert out["cover_image_url"] == mine, name

    def test_a_custom_cover_is_what_a_member_sees(self, db, owned):
        """Through the member surfaces, not just the creator's."""
        space, owner = owned
        audio = covers.COVERS_BY_KEY["audio"]
        _artwork(db, audio, "shared")
        off = Offering(
            id=_uid("off"), space_id=space.id, created_by_user_id=owner.id,
            slug=f"o-{uuid.uuid4().hex[:8]}", title="Seen",
            summary="x", status="published", pricing_kind="free",
            default_cover_key=audio.key, published_at=datetime.utcnow(),
        )
        db.add(off)
        db.flush()
        _file(db, off)
        mine = _custom_url(off)
        off.cover_image_url = mine
        db.flush()

        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["cover_image_url"] == mine
        detail = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=None,
        )
        assert detail["cover_image_url"] == mine

    def test_a_custom_cover_satisfies_readiness_without_a_category(
        self, db, owned,
    ):
        """A creator who only ever uploads their own image can publish."""
        space, owner = owned
        off = Offering(
            id=_uid("off"), space_id=space.id, created_by_user_id=owner.id,
            slug=f"o-{uuid.uuid4().hex[:8]}", title="Own art",
            summary="x", status="draft", pricing_kind="free",
        )
        db.add(off)
        db.flush()
        off.cover_image_url = _custom_url(off)
        db.flush()
        assert readiness.has_acceptable_cover(off) is True
        _file(db, off)
        result = readiness.evaluate(
            db, offering=off, space=space, owner=owner,
        )
        assert "cover_image" not in result.unmet_ids


class TestChangingCategoryUpdatesTheSharedDefault:

    def test_switching_category_switches_the_resolved_image(self, db, owned):
        """With no custom cover, the displayed image follows the choice."""
        space, owner = owned
        a = covers.COVERS_BY_KEY["audio"]
        b = covers.COVERS_BY_KEY["spreadsheet"]
        a_url, b_url = _artwork(db, a, "a"), _artwork(db, b, "b")
        created = api.create_offering(
            space.slug, OfferingCreateRequest(title="Switch"),
            db=db, current_user=owner,
        )
        slug = created["slug"]
        assert api.update_offering(
            space.slug, slug, OfferingUpdateRequest(default_cover_key=a.key),
            db=db, current_user=owner,
        )["cover_image_url"] == a_url
        assert api.update_offering(
            space.slug, slug, OfferingUpdateRequest(default_cover_key=b.key),
            db=db, current_user=owner,
        )["cover_image_url"] == b_url

    def test_switching_to_a_category_with_no_artwork_yields_the_gradient(
        self, db, owned,
    ):
        """Not a broken image, and not the previous category's picture —
        which would show a member artwork for something else."""
        space, owner = owned
        a = covers.COVERS_BY_KEY["audio"]
        empty = covers.COVERS_BY_KEY["collections"]
        a_url = _artwork(db, a, "a")
        created = api.create_offering(
            space.slug, OfferingCreateRequest(title="Empty next"),
            db=db, current_user=owner,
        )
        slug = created["slug"]
        assert api.update_offering(
            space.slug, slug, OfferingUpdateRequest(default_cover_key=a.key),
            db=db, current_user=owner,
        )["cover_image_url"] == a_url
        out = api.update_offering(
            space.slug, slug,
            OfferingUpdateRequest(default_cover_key=empty.key),
            db=db, current_user=owner,
        )
        assert out["default_cover_key"] == empty.key
        assert out["cover_image_url"] is None, (
            "an empty category must not inherit the previous one's artwork"
        )

    def test_every_category_resolves_independently(self, db, owned):
        """Five categories, five images, no cross-talk."""
        space, owner = owned
        urls = {
            c.key: _artwork(db, c, c.key) for c in covers.DEFAULT_COVERS
        }
        created = api.create_offering(
            space.slug, OfferingCreateRequest(title="Each"),
            db=db, current_user=owner,
        )
        slug = created["slug"]
        for c in covers.DEFAULT_COVERS:
            out = api.update_offering(
                space.slug, slug,
                OfferingUpdateRequest(default_cover_key=c.key),
                db=db, current_user=owner,
            )
            assert out["cover_image_url"] == urls[c.key], c.key
