"""The complete creator journey, start to finish, in one test.

    Create → Details → Cover → About → Upload → Validate
           → Pricing → Preview → Publish → Retire

Every step calls the **production handler** the Creator Studio page
calls, in the order a creator meets them, against a real PostgreSQL
database and real bytes on disk. Nothing is stubbed and no step is
simulated — the validation step drives the actual worker, and the
preview step reads the actual member endpoint.

Why one long test rather than ten short ones
--------------------------------------------

The individual behaviours are covered elsewhere; what is *not* covered
elsewhere is that they compose. Each step here depends on the state the
previous one left behind, so a change that quietly breaks the handoff
between two surfaces — a readiness rule that never clears, a file that
never becomes downloadable, a publish that silently drops pricing —
fails here even when every unit test still passes.

Assertions are made at each step rather than only at the end, so a
failure names the step that broke rather than the last one.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core import storage
from app.creator import _offering_about_routes as about_api
from app.creator import _offering_file_routes as files_api
from app.creator import _offering_routes as api
from app.creator.plan_config import PLANS_BY_SLUG
from app.creator.schemas import AboutBlockCreateRequest
from app.creator.schemas_offerings import (
    OfferingCreateRequest, OfferingUpdateRequest,
)
from app.models.offering import (
    OfferingEntitlement, OfferingFile,
    OfferingFileValidationStatus as FVS, OfferingStatus,
)
from app.services import offering_covers as covers
from app.services import offering_files as of
from app.services import offering_validation_worker as worker
from app.spaces import _offering_member_routes as member_api


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:16]}"


class _KeepOpen:
    """Session proxy whose ``close()`` is a no-op, so the worker's unit
    of work runs against the test's transaction."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _pdf(size: int = 8192) -> bytes:
    return (b"%PDF-1.4\n" + b"x" * max(0, size - 24) + b"\ntrailer\n%%EOF\n")[:size]


def _upload(data: bytes, name: str, ctype: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data), filename=name,
        headers=Headers({"content-type": ctype}),
    )


@pytest.fixture
def creator_collective(db, make_space):
    """A Collective on the Creator plan, with its owner."""
    from app.models.creator_billing import (
        CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
    )
    from app.models.user import User

    space = make_space()
    owner = db.query(User).filter(User.id == space.creator_id).one()
    cap = PLANS_BY_SLUG["creator"]
    row = db.query(CreatorPlan).filter(CreatorPlan.slug == "creator").first()
    if row is None:
        row = CreatorPlan(
            id=_uid("plan"), slug="creator", name=cap.display_name,
            monthly_price_cents=cap.monthly_price_cents or 0, currency="AUD",
            transaction_fee_basis_points=800, collective_limit=1,
        )
        db.add(row)
        db.flush()
    db.add(CreatorSubscription(
        id=_uid("sub"), user_id=owner.id, creator_plan_id=row.id,
        status=CreatorSubscriptionStatus.active,
        starts_at=datetime.utcnow(), source="manual_grant",
    ))
    db.flush()
    return space, owner


@pytest.fixture(autouse=True)
def clean_storage():
    root = storage.UPLOAD_DIR / of.OFFERING_FILES_PREFIX
    before = {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()
    yield
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p not in before:
                p.unlink()
        for d in sorted(
            (p for p in root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts), reverse=True,
        ):
            try:
                d.rmdir()
            except OSError:
                pass


def test_the_whole_creator_journey(db, creator_collective, make_user):
    space, owner = creator_collective
    sf = lambda: _KeepOpen(db)   # noqa: E731 — the worker's session factory

    # ── 1. Create ────────────────────────────────────────────────────
    created = api.create_offering(
        space.slug, OfferingCreateRequest(title="Morning Pages Workbook"),
        db=db, current_user=owner,
    )
    slug = created["slug"]
    assert created["status"] == OfferingStatus.draft.value
    assert created["file_count"] == 0

    def readiness() -> dict:
        return api.get_offering_readiness(
            space.slug, slug, db=db, current_user=owner,
        )

    unmet = {r["id"] for r in readiness()["requirements"] if not r["met"]}
    assert "cover_image" in unmet and "has_files" in unmet and "pricing" in unmet

    # ── 2. Details ───────────────────────────────────────────────────
    api.update_offering(
        space.slug, slug,
        OfferingUpdateRequest(summary="Twelve weeks of gentle daily pages."),
        db=db, current_user=owner,
    )

    # ── 3. Cover — one of the five curated images ────────────────────
    cover = covers.COVERS_BY_KEY["workbook-guides"]
    detail = api.update_offering(
        space.slug, slug, OfferingUpdateRequest(cover_image_url=cover.url),
        db=db, current_user=owner,
    )
    assert detail["cover_image_url"] == cover.url
    assert "cover_image" not in {
        r["id"] for r in readiness()["requirements"] if not r["met"]
    }

    # ── 4. About — optional rich content ─────────────────────────────
    block = about_api.create_offering_about_block(
        slug=space.slug, offering_slug=slug,
        body=AboutBlockCreateRequest(
            block_type="text", content="What's inside, and who it's for.",
        ),
        db=db, current_user=owner,
    )
    assert block.owner_kind == "offering"

    # ── 5. Upload ────────────────────────────────────────────────────
    uploaded = files_api.upload_offering_file(
        slug=space.slug, offering_slug=slug,
        file=_upload(_pdf(), "workbook.pdf", "application/pdf"),
        description="The twelve-week workbook.",
        db=db, current_user=owner,
    )
    assert uploaded["validation_status"] == FVS.pending.value
    assert uploaded["status_label"] == "Checking"
    assert uploaded["available_to_purchasers"] is False

    # Not publishable while a file is still being checked.
    assert "files_validated" in {
        r["id"] for r in readiness()["requirements"] if not r["met"]
    }

    # ── 6. Validate — the real worker, not a stub ────────────────────
    assert worker.validate_once(session_factory=sf) == FVS.passed.value

    listing = files_api.list_offering_files(
        slug=space.slug, offering_slug=slug, db=db, current_user=owner,
    )
    assert listing["files"][0]["status_label"] == "Ready"
    assert listing["files"][0]["available_to_purchasers"] is True
    assert listing["resources_used"] == 1
    assert listing["resources_allowed"] == 50      # Creator plan
    assert listing["plan_name"] == "Creator"

    # ── 7. Pricing ───────────────────────────────────────────────────
    priced = api.update_offering(
        space.slug, slug,
        OfferingUpdateRequest(pricing_kind="one_time", price_cents=2400),
        db=db, current_user=owner,
    )
    assert priced["pricing_kind"] == "one_time"
    assert priced["price_cents"] == 2400

    # ── 8. Preview — the real member page, while still a draft ───────
    preview = member_api.get_member_offering(
        slug=space.slug, offering_slug=slug, db=db, current_user=owner,
    )
    assert preview["status"] == OfferingStatus.draft.value
    assert preview["viewer_manages"] is True
    assert preview["title"] == "Morning Pages Workbook"
    assert preview["cover_image_url"] == cover.url
    assert preview["price_cents"] == 2400
    assert len(preview["about_blocks"]) == 1
    assert preview["files"][0]["type_label"] == "PDF"
    assert preview["fulfilment_kind"] == "digital_download"

    # A stranger cannot see the draft the owner just previewed.
    stranger = make_user()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        member_api.get_member_offering(
            slug=space.slug, offering_slug=slug, db=db, current_user=stranger,
        )
    assert exc.value.status_code == 404

    # ── 9. Publish ───────────────────────────────────────────────────
    assert readiness()["ready"] is True, readiness()["requirements"]
    published = api.publish_offering(
        space.slug, slug, db=db, current_user=owner,
    )
    assert published["status"] == OfferingStatus.published.value
    assert published["published_at"] is not None

    # Now the stranger can see it.
    public = member_api.get_member_offering(
        slug=space.slug, offering_slug=slug, db=db, current_user=stranger,
    )
    assert public["status"] == OfferingStatus.published.value
    assert public["viewer_owns"] is False
    assert public["files"][0]["download_url"] is None   # not theirs yet

    # ── 10. Somebody acquires it, then the creator retires it ────────
    buyer = make_user()
    db.add(OfferingEntitlement(
        id=_uid("oen"), user_id=buyer.id, offering_id=published["id"],
        space_id=space.id, source="one_time_purchase", status="active",
    ))
    db.flush()

    owned = member_api.get_member_offering(
        slug=space.slug, offering_slug=slug, db=db, current_user=buyer,
    )
    assert owned["viewer_owns"] is True
    assert owned["files"][0]["download_url"] is not None

    retired = api.retire_offering(space.slug, slug, db=db, current_user=owner)
    assert retired["status"] == OfferingStatus.retired.value

    # Retirement stops selling and keeps serving: the purchaser's
    # entitlement and download both survive.
    after = member_api.get_member_offering(
        slug=space.slug, offering_slug=slug, db=db, current_user=buyer,
    )
    assert after["viewer_owns"] is True
    assert after["files"][0]["download_url"] is not None

    row = db.query(OfferingFile).filter(
        OfferingFile.offering_id == published["id"],
    ).one()
    from app.uploads.authorization import authorize_upload
    authorize_upload(row.storage_key, buyer, db)   # still authorised
