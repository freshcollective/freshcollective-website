"""Offerings Phase B5 — plan limits, file management API, replacement.

Route handlers are imported and called directly, matching the suite's
convention. The feature flag is therefore bypassed by construction, so
it is tested the same two ways Phase B4 established: the dependency
function itself, and a structural assertion that the router declares it
(see ``test_offering_creator_api.py``).

These tests run in **filesystem storage mode**, which is not a
simplification — ``upload_stream`` and ``download_to_fileobj`` both have
a filesystem branch written to copy in the same bounded chunks as the R2
branch, so the whole upload → claim → inspect → promote cycle is
exercised end to end against real bytes on real disk. Objects written
under ``uploads/offering-files/`` are removed by the ``clean_storage``
fixture whatever the outcome.

Every refusal sits beside a positive control. A limit system that
refused everything would satisfy half this file and fail the rest.
"""

from __future__ import annotations

import io
import os
import pathlib
import uuid
import zipfile
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core import storage
from app.creator import _offering_file_routes as files_api
from app.creator.plan_config import PLANS_BY_SLUG
from app.creator.schemas_offerings import (
    OfferingFileReorderRequest,
    OfferingFileUpdateRequest,
)
from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
    OfferingStatus,
)
from app.services import offering_files as of
from app.services.offering_covers import DEFAULT_COVERS
from app.services import offering_limits as ol
from app.services import offering_upload as ou
from app.services import offering_validation_worker as worker

MB = 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _offerings_available(offerings_enabled):
    """Offerings fully available for every test in this module.

    These call creator handlers **directly**, so they never meet the
    route's ``require_offerings_enabled`` dependency — but Offerings
    Phase C/D's pilot allow-list is enforced inside
    ``_get_owned_space``, which every creator handler resolves through.
    Without this, each test gets the production answer for a Collective
    outside the pilot: 404.

    ``offerings_enabled`` opens both switches. Scope itself is the
    subject of ``test_offering_pilot_allowlist.py``, not of these.
    """


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:16]}"


def _upload(
    data: bytes, filename: str, content_type: str,
) -> UploadFile:
    """A Starlette ``UploadFile`` the handlers accept unmodified."""
    return UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _pdf(size: int = 2048) -> bytes:
    """Bytes that pass the PDF signature and structure checks."""
    body = b"%PDF-1.4\n" + b"x" * max(0, size - 24) + b"\ntrailer\n%%EOF\n"
    return body[:size] if size >= 24 else body


def _zip_of(n: int, *, member_bytes: bytes = b"hello there\n") -> bytes:
    """A ZIP containing ``n`` plain-text members."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(n):
            zf.writestr(f"notes/page-{i}.txt", member_bytes)
    return buf.getvalue()


@pytest.fixture
def plan(db):
    """Seed creator plans and attach one to a user."""
    from app.models.creator_billing import (
        CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
    )

    def _attach(user, slug: str):
        cap = PLANS_BY_SLUG[slug]
        row = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if row is None:
            row = CreatorPlan(
                id=_uid("plan"), slug=slug, name=cap.display_name,
                monthly_price_cents=cap.monthly_price_cents or 0,
                currency="AUD", transaction_fee_basis_points=800,
                collective_limit=cap.active_collective_limit or 1,
                pathway_limit=cap.pathways_max_per_collective,
            )
            db.add(row)
            db.flush()
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=user.id, creator_plan_id=row.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(), source="manual_grant",
        ))
        db.flush()
        return row

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


@pytest.fixture(autouse=True)
def clean_storage():
    """Remove anything written under the Offering namespaces.

    Autouse so a test that refuses an upload half way through still
    leaves no artefact behind — which is also how the "no orphaned
    object" assertions stay meaningful between tests.
    """
    root = storage.UPLOAD_DIR / of.OFFERING_FILES_PREFIX
    before = set()
    if root.exists():
        before = {p for p in root.rglob("*") if p.is_file()}
    yield
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and p not in before:
                p.unlink()
        # Prune the per-Offering directories too. Without this a full
        # suite run leaves several hundred empty directories under
        # ``uploads/`` — harmless and gitignored, but the kind of litter
        # that makes a real leftover file hard to notice.
        for d in sorted(
            (p for p in root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts), reverse=True,
        ):
            try:
                d.rmdir()
            except OSError:
                pass   # not empty — something was deliberately kept


def _stored_keys(offering: Offering) -> set[str]:
    """Storage keys that actually exist on disk for this Offering."""
    root = storage.UPLOAD_DIR / of.OFFERING_FILES_PREFIX / offering.id
    if not root.exists():
        return set()
    return {
        str(p.relative_to(storage.UPLOAD_DIR))
        for p in root.rglob("*") if p.is_file()
    }


class _KeepOpen:
    """A session proxy whose ``close()`` does nothing.

    The worker opens and closes its own sessions, which is correct in
    production and useless in a test: the ``db`` fixture holds everything
    inside one transaction that is rolled back at the end, so a session
    the worker opened for itself would see none of the fixture's rows.
    Handing it this proxy runs the real unit of work — the same claim,
    the same ``FOR UPDATE SKIP LOCKED``, the same two writes — against
    the transaction the test wrote, and leaves the fixture to clean up.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _drive_worker(db, *, times: int = 1):
    """Run the worker's unit of work against the test's transaction."""
    out = []
    for _ in range(times):
        out.append(worker.validate_once(session_factory=lambda: _KeepOpen(db)))
    return out[-1] if times == 1 else out


def _do_upload(db, space, off, owner, data, name, ctype, description=None):
    return files_api.upload_offering_file(
        slug=space.slug, offering_slug=off.slug,
        file=_upload(data, name, ctype), description=description,
        db=db, current_user=owner,
    )


# ---------------------------------------------------------------------------
# Step 1 — limits resolve from the plan, once
# ---------------------------------------------------------------------------


class TestResolvedLimits:
    """The approved table, read back through the resolver."""

    @pytest.mark.parametrize(
        "slug,files,file_mb,bundle_mb,zips",
        [
            ("community", 1, 10, 10, False),
            ("creator", 50, 25, 75, True),
            ("pro", 50, 50, 150, True),
        ],
    )
    def test_each_plan_resolves_its_approved_allowance(
        self, db, owner_space, slug, files, file_mb, bundle_mb, zips,
    ):
        _space, owner = owner_space(slug)
        limits = ol.resolve_offering_limits(owner, db)
        assert limits.max_files == files
        assert limits.max_file_bytes == file_mb * MB
        assert limits.max_bundle_bytes == bundle_mb * MB
        assert limits.zip_bundles_allowed is zips

    def test_an_unrestricted_plan_lands_on_the_platform_ceiling(
        self, db, owner_space,
    ):
        """Not on "no limit" — the instance is 512 MB whoever is uploading."""
        _space, owner = owner_space("founding-creator")
        limits = ol.resolve_offering_limits(owner, db)
        assert limits.max_file_bytes == of.MAX_OFFERING_FILE_BYTES
        assert limits.max_bundle_bytes == of.MAX_OFFERING_BUNDLE_BYTES
        assert limits.max_files == of.MAX_OFFERING_FILE_COUNT

    def test_no_plan_at_all_still_resolves_to_the_ceiling(self, db):
        """A Platform Owner has no creator plan. It must not mean unbounded."""
        limits = ol.resolve_offering_limits(None, db)
        assert limits.max_file_bytes == of.MAX_OFFERING_FILE_BYTES
        assert limits.max_files == of.MAX_OFFERING_FILE_COUNT

    def test_the_platform_ceiling_is_never_exceeded_by_any_plan(self):
        """Whatever the plan table says, the instance bound wins."""
        for cap in PLANS_BY_SLUG.values():
            if cap.offering_file_max_bytes is not None:
                assert cap.offering_file_max_bytes <= of.MAX_OFFERING_FILE_BYTES
            if cap.offering_bundle_max_bytes is not None:
                assert (
                    cap.offering_bundle_max_bytes
                    <= of.MAX_OFFERING_BUNDLE_BYTES
                )
            if cap.offering_files_max is not None:
                assert cap.offering_files_max <= of.MAX_OFFERING_FILE_COUNT

    def test_the_ceiling_accommodates_the_most_generous_plan(self):
        """The B4→B5 conflict: a 25-file ceiling would have halved a paid
        plan's stated 50-file allowance. Resolved upwards."""
        assert of.MAX_OFFERING_FILE_COUNT >= 50
        assert PLANS_BY_SLUG["pro"].offering_files_max == 50

    def test_limits_come_from_the_collectives_owner_not_the_caller(
        self, db, owner_space, make_user, plan,
    ):
        """Management is owner-only today, so these coincide — the test
        pins the premise so a delegated role later cannot silently give a
        helper their own plan's allowance.

        The Collective is owned by a Community creator; the other user is
        on Portfolio. ``limits_for_space`` must report the owner's single
        file, not the visitor's fifty.
        """
        space, _owner = owner_space("community")
        other = make_user(role="creator")
        plan(other, "pro")

        assert ol.limits_for_space(space, db).max_files == 1
        assert ol.resolve_offering_limits(other, db).max_files == 50


# ---------------------------------------------------------------------------
# Step 1 — Community's single-file and no-ZIP rules
# ---------------------------------------------------------------------------


class TestCommunityRestrictions:

    def test_a_community_creator_may_upload_one_file(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("community")
        off = offering(space)
        out = _do_upload(db, space, off, owner, _pdf(), "guide.pdf", "application/pdf")
        assert out["validation_status"] == FVS.pending.value
        assert out["status_label"] == "Checking"

    def test_a_second_file_is_refused_on_community(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("community")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(), "one.pdf", "application/pdf")
        with pytest.raises(HTTPException) as exc:
            _do_upload(db, space, off, owner, _pdf(), "two.pdf", "application/pdf")
        assert exc.value.status_code == 422
        assert exc.value.detail["reason"] == "too_many_files"

    def test_the_same_second_file_is_accepted_on_creator(
        self, db, owner_space, offering,
    ):
        """The positive control — the refusal above is the plan, not a bug."""
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(), "one.pdf", "application/pdf")
        out = _do_upload(db, space, off, owner, _pdf(), "two.pdf", "application/pdf")
        assert out["validation_status"] == FVS.pending.value

    def test_community_cannot_upload_a_zip(self, db, owner_space, offering):
        space, owner = owner_space("community")
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            _do_upload(
                db, space, off, owner, _zip_of(2), "bundle.zip", "application/zip",
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["reason"] == "zip_not_permitted"

    def test_a_refused_zip_leaves_no_stored_object(
        self, db, owner_space, offering,
    ):
        """Refused before the transfer, so there is nothing to clean up."""
        space, owner = owner_space("community")
        off = offering(space)
        with pytest.raises(HTTPException):
            _do_upload(
                db, space, off, owner, _zip_of(2), "bundle.zip", "application/zip",
            )
        assert _stored_keys(off) == set()

    def test_creator_can_upload_a_zip(self, db, owner_space, offering):
        space, owner = owner_space("creator")
        off = offering(space)
        out = _do_upload(
            db, space, off, owner, _zip_of(3), "bundle.zip", "application/zip",
        )
        assert out["resource_count"] == 3


# ---------------------------------------------------------------------------
# Step 1 — counting
# ---------------------------------------------------------------------------


class TestResourceCounting:

    def test_a_zip_counts_its_members_not_itself(self):
        import tempfile
        fd, p = tempfile.mkstemp(suffix=".zip")
        os.write(fd, _zip_of(7))
        os.close(fd)
        try:
            assert ou.count_resources(p, "bundle.zip") == 7
        finally:
            os.unlink(p)

    def test_directory_entries_are_not_resources(self):
        import tempfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("folder/", b"")
            zf.writestr("folder/a.txt", b"hi")
            zf.writestr("folder/b.txt", b"hi")
        fd, p = tempfile.mkstemp(suffix=".zip")
        os.write(fd, buf.getvalue())
        os.close(fd)
        try:
            assert ou.count_resources(p, "bundle.zip") == 2
        finally:
            os.unlink(p)

    def test_an_office_package_counts_once(self):
        """A .docx is a ZIP of XML. Its parts are machinery, not resources."""
        fixture = pathlib.Path(__file__).parent / "fixtures" / "offerings" / "genuine.docx"
        with zipfile.ZipFile(fixture) as zf:
            assert len(zf.infolist()) > 5   # genuinely many internal parts
        assert ou.count_resources(str(fixture), "genuine.docx") == 1

    def test_a_plain_file_counts_once(self):
        import tempfile
        fd, p = tempfile.mkstemp(suffix=".pdf")
        os.write(fd, _pdf())
        os.close(fd)
        try:
            assert ou.count_resources(p, "guide.pdf") == 1
        finally:
            os.unlink(p)

    def test_a_zip_cannot_evade_the_file_allowance(
        self, db, owner_space, offering,
    ):
        """A 60-member archive is 60 resources against a 50 ceiling."""
        space, owner = owner_space("creator")
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            _do_upload(
                db, space, off, owner, _zip_of(60), "many.zip", "application/zip",
            )
        assert exc.value.detail["reason"] == "too_many_files"

    def test_an_unreadable_zip_is_refused_rather_than_counted_as_one(self):
        import tempfile
        fd, p = tempfile.mkstemp(suffix=".zip")
        os.write(fd, b"PK\x03\x04 not really a zip at all")
        os.close(fd)
        try:
            with pytest.raises(HTTPException) as exc:
                ou.count_resources(p, "broken.zip")
            assert exc.value.detail["reason"] == "unreadable"
        finally:
            os.unlink(p)

    def test_the_fifty_file_ceiling_is_reachable_and_enforced(
        self, db, owner_space, offering,
    ):
        """49 + 1 passes; the 51st resource does not."""
        space, owner = owner_space("pro")
        off = offering(space)
        _do_upload(db, space, off, owner, _zip_of(49), "a.zip", "application/zip")
        _do_upload(db, space, off, owner, _pdf(), "fiftieth.pdf", "application/pdf")
        usage = ol.bundle_usage(db, offering=off)
        assert usage.resources == 50
        with pytest.raises(HTTPException) as exc:
            _do_upload(db, space, off, owner, _pdf(), "one-too-many.pdf", "application/pdf")
        assert exc.value.detail["reason"] == "too_many_files"


# ---------------------------------------------------------------------------
# Step 1 — sizes
# ---------------------------------------------------------------------------


class TestSizeLimits:

    def test_a_file_over_the_plans_per_file_limit_is_refused(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")       # 25 MB per file
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            _do_upload(
                db, space, off, owner, _pdf(26 * MB), "big.pdf", "application/pdf",
            )
        assert exc.value.status_code == 413
        assert exc.value.detail["reason"] == "file_too_large"

    def test_the_same_file_is_accepted_on_portfolio(
        self, db, owner_space, offering,
    ):
        """26 MB: over Creator's 25, inside Portfolio's 50."""
        space, owner = owner_space("pro")
        off = offering(space)
        out = _do_upload(
            db, space, off, owner, _pdf(26 * MB), "big.pdf", "application/pdf",
        )
        assert out["byte_size"] == 26 * MB

    def test_the_total_bundle_limit_is_enforced(
        self, db, owner_space, offering,
    ):
        """Creator: 75 MB total, 25 MB each. Four 20 MB files is 80."""
        space, owner = owner_space("creator")
        off = offering(space)
        for i in range(3):
            _do_upload(
                db, space, off, owner, _pdf(20 * MB), f"f{i}.pdf", "application/pdf",
            )
        assert ol.bundle_usage(db, offering=off).bytes_used == 60 * MB
        with pytest.raises(HTTPException) as exc:
            _do_upload(
                db, space, off, owner, _pdf(20 * MB), "f4.pdf", "application/pdf",
            )
        assert exc.value.detail["reason"] == "bundle_too_large"

    def test_an_oversized_upload_stores_nothing(
        self, db, owner_space, offering,
    ):
        """Refused while being copied, so no object and no row."""
        space, owner = owner_space("community")     # 10 MB
        off = offering(space)
        with pytest.raises(HTTPException):
            _do_upload(
                db, space, off, owner, _pdf(11 * MB), "big.pdf", "application/pdf",
            )
        assert _stored_keys(off) == set()
        assert db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).count() == 0

    def test_an_empty_file_is_refused(self, db, owner_space, offering):
        space, owner = owner_space("creator")
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            _do_upload(db, space, off, owner, b"", "empty.pdf", "application/pdf")
        assert exc.value.detail["reason"] == "empty_file"

    def test_zip_decompression_limits_are_separate_from_plan_limits(self):
        """Approved: inspection budgets are not storage allowances.

        The budget bounds what we will *inspect*; the plan bounds what a
        creator may *store*. Neither is derived from the other, and the
        budget is far larger because a legitimate 10 MB archive may
        expand well past any plan's bundle limit.
        """
        from app.services.offering_validation import InspectionBudget
        b = InspectionBudget()
        assert b.max_decompressed_bytes > of.MAX_OFFERING_BUNDLE_BYTES
        assert b.max_entries > of.MAX_OFFERING_FILE_COUNT
        # And no plan field is expressed in terms of a budget field.
        for cap in PLANS_BY_SLUG.values():
            assert cap.offering_bundle_max_bytes != b.max_decompressed_bytes


# ---------------------------------------------------------------------------
# Step 1 / 7 — downgrade
# ---------------------------------------------------------------------------


class TestDowngrade:

    def _downgrade(self, db, owner, slug):
        from app.models.creator_billing import (
            CreatorPlan, CreatorSubscription, CreatorSubscriptionStatus,
        )
        db.query(CreatorSubscription).filter(
            CreatorSubscription.user_id == owner.id,
        ).update({"status": CreatorSubscriptionStatus.cancelled})
        cap = PLANS_BY_SLUG[slug]
        row = db.query(CreatorPlan).filter(CreatorPlan.slug == slug).first()
        if row is None:
            row = CreatorPlan(
                id=_uid("plan"), slug=slug, name=cap.display_name,
                monthly_price_cents=0, currency="AUD",
                transaction_fee_basis_points=0, collective_limit=1,
            )
            db.add(row)
            db.flush()
        db.add(CreatorSubscription(
            id=_uid("sub"), user_id=owner.id, creator_plan_id=row.id,
            status=CreatorSubscriptionStatus.active,
            starts_at=datetime.utcnow(), source="manual_grant",
        ))
        db.flush()

    def test_a_downgrade_deletes_nothing(self, db, owner_space, offering):
        space, owner = owner_space("creator")
        off = offering(space)
        for i in range(3):
            _do_upload(db, space, off, owner, _pdf(), f"f{i}.pdf", "application/pdf")
        keys_before = _stored_keys(off)

        self._downgrade(db, owner, "community")

        rows = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
            OfferingFile.superseded_at.is_(None),
        ).all()
        assert len(rows) == 3, "no file row was removed"
        assert _stored_keys(off) == keys_before, "no object was deleted"
        assert db.query(Offering).filter(Offering.id == off.id).one()

    def test_a_downgrade_blocks_the_next_upload(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(), "kept.pdf", "application/pdf")
        self._downgrade(db, owner, "community")
        with pytest.raises(HTTPException) as exc:
            _do_upload(db, space, off, owner, _pdf(), "new.pdf", "application/pdf")
        assert exc.value.detail["reason"] == "too_many_files"

    def test_a_downgrade_does_not_revoke_an_entitlement(
        self, db, owner_space, offering, make_user,
    ):
        space, owner = owner_space("creator")
        off = offering(
            space, status=OfferingStatus.published.value,
            pricing_kind=OfferingPricingKind.one_time.value, price_cents=1500,
        )
        _do_upload(db, space, off, owner, _pdf(), "f.pdf", "application/pdf")
        row = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        row.validation_status = FVS.passed.value
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="one_time_purchase", status="active",
        ))
        db.flush()

        self._downgrade(db, owner, "community")

        from app.uploads.authorization import authorize_upload
        # Still downloadable. The plan governs new uploads, never what
        # somebody already bought.
        authorize_upload(row.storage_key, buyer, db)

    def test_a_downgrade_does_not_convert_a_paid_offering_to_free(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(
            space, pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=2500, status=OfferingStatus.published.value,
        )
        self._downgrade(db, owner, "community")
        again = db.query(Offering).filter(Offering.id == off.id).one()
        assert again.pricing_kind == OfferingPricingKind.one_time.value
        assert again.price_cents == 2500

    def test_an_over_limit_offering_cannot_be_newly_published(
        self, db, owner_space, offering,
    ):
        """Publishing is a new action, so it meets the current plan."""
        from app.services import offering_readiness
        space, owner = owner_space("creator")
        off = offering(
            space,
            cover_image_url=DEFAULT_COVERS[0].url,
            pricing_kind=OfferingPricingKind.free.value,
        )
        for i in range(2):
            _do_upload(db, space, off, owner, _pdf(), f"f{i}.pdf", "application/pdf")
        for r in db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).all():
            r.validation_status = FVS.passed.value
        db.flush()

        ready = offering_readiness.evaluate(
            db, offering=off, space=space, owner=owner,
        )
        assert ready.ready, ready.unmet_ids

        self._downgrade(db, owner, "community")
        after = offering_readiness.evaluate(
            db, offering=off, space=space, owner=owner,
        )
        assert not after.ready
        assert "within_plan_limits" in after.unmet_ids


# ---------------------------------------------------------------------------
# Step 2 — the API
# ---------------------------------------------------------------------------


class TestFileListing:

    def test_the_list_carries_the_allowance_with_it(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(1024), "a.pdf", "application/pdf")
        out = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )
        assert out["resources_allowed"] == 50
        assert out["bytes_allowed"] == 75 * MB
        assert out["max_file_bytes"] == 25 * MB
        assert out["zip_bundles_allowed"] is True
        assert out["plan_name"] == "Creator"
        assert out["resources_used"] == 1
        assert out["bytes_used"] == 1024

    def test_every_approved_field_is_present(self, db, owner_space, offering):
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(
            db, space, off, owner, _pdf(), "guide.pdf", "application/pdf",
            description="A short practice.",
        )
        one = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )["files"][0]
        for field in (
            "filename", "content_type", "byte_size", "description",
            "validation_status", "status_label", "rejection_reason",
            "available_to_purchasers", "replacement_pending",
        ):
            assert field in one, field
        assert one["description"] == "A short practice."

    @pytest.mark.parametrize(
        "status,label",
        [
            (FVS.pending.value, "Checking"),
            (FVS.passed.value, "Ready"),
            (FVS.rejected.value, "Not accepted"),
            (FVS.error.value, "On hold"),
            (FVS.quarantined.value, "On hold"),
        ],
    )
    def test_the_status_vocabulary_is_the_approved_one(
        self, db, owner_space, offering, status, label,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        row = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        row.validation_status = status
        if status == FVS.quarantined.value:
            row.quarantined_at = datetime.utcnow()
        db.flush()
        one = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )["files"][0]
        assert one["status_label"] == label

    def test_only_a_ready_current_file_is_available_to_purchasers(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        shown = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )["files"][0]
        assert shown["available_to_purchasers"] is False

        row = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        row.validation_status = FVS.passed.value
        db.flush()
        shown = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )["files"][0]
        assert shown["available_to_purchasers"] is True

    def test_a_rejection_reason_is_prose_not_a_code(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        row = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        row.validation_status = FVS.rejected.value
        row.validation_reason = "macro_document"
        db.flush()
        one = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )["files"][0]
        assert "macro" in one["rejection_reason"].lower()
        assert "macro_document" not in one["rejection_reason"]

    def test_an_unknown_reason_code_falls_back_to_safe_prose(
        self, db, owner_space, offering,
    ):
        """A new code must never leak an internal string into the UI."""
        space, owner = owner_space("creator")
        off = offering(space)
        _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        row = db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).one()
        row.validation_status = FVS.rejected.value
        row.validation_reason = "some_future_internal_code"
        db.flush()
        one = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )["files"][0]
        assert "some_future_internal_code" not in one["rejection_reason"]
        assert one["rejection_reason"]

    def test_no_creator_facing_message_implies_a_malware_scan(
        self, db, owner_space, offering,
    ):
        banned = ("virus", "malware", "scan", "antivirus", "clean", "safe")
        texts = list(files_api._REJECTION_PROSE.values()) + [
            files_api._ON_HOLD_MESSAGE,
        ]
        for t in texts:
            low = t.lower()
            for word in banned:
                assert word not in low, (word, t)


class TestDescriptionsAndOrder:

    def test_a_description_can_be_set_and_cleared(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        up = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        out = files_api.update_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=up["id"],
            body=OfferingFileUpdateRequest(description="Ten minutes of quiet."),
            db=db, current_user=owner,
        )
        assert out["description"] == "Ten minutes of quiet."
        out = files_api.update_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=up["id"],
            body=OfferingFileUpdateRequest(description=None),
            db=db, current_user=owner,
        )
        assert out["description"] is None

    def test_a_patch_cannot_change_validation_state(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        up = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        with pytest.raises(Exception):
            OfferingFileUpdateRequest(validation_status="passed")
        out = files_api.update_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=up["id"],
            body=OfferingFileUpdateRequest(description="x"),
            db=db, current_user=owner,
        )
        assert out["validation_status"] == FVS.pending.value

    def test_reordering_sets_positions(self, db, owner_space, offering):
        space, owner = owner_space("creator")
        off = offering(space)
        a = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        b = _do_upload(db, space, off, owner, _pdf(), "b.pdf", "application/pdf")
        c = _do_upload(db, space, off, owner, _pdf(), "c.pdf", "application/pdf")
        out = files_api.reorder_offering_files(
            slug=space.slug, offering_slug=off.slug,
            body=OfferingFileReorderRequest(
                file_ids=[c["id"], a["id"], b["id"]],
            ),
            db=db, current_user=owner,
        )
        assert [f["id"] for f in out["files"]] == [c["id"], a["id"], b["id"]]

    def test_an_incomplete_order_is_refused(self, db, owner_space, offering):
        space, owner = owner_space("creator")
        off = offering(space)
        a = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        _do_upload(db, space, off, owner, _pdf(), "b.pdf", "application/pdf")
        with pytest.raises(HTTPException) as exc:
            files_api.reorder_offering_files(
                slug=space.slug, offering_slug=off.slug,
                body=OfferingFileReorderRequest(file_ids=[a["id"]]),
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["reason"] == "incomplete_order"

    def test_another_offerings_file_cannot_be_ordered_into_this_one(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        mine = offering(space)
        other = offering(space)
        a = _do_upload(db, space, mine, owner, _pdf(), "a.pdf", "application/pdf")
        far = _do_upload(db, space, other, owner, _pdf(), "z.pdf", "application/pdf")
        with pytest.raises(HTTPException) as exc:
            files_api.reorder_offering_files(
                slug=space.slug, offering_slug=mine.slug,
                body=OfferingFileReorderRequest(
                    file_ids=[a["id"], far["id"]],
                ),
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 422


class TestRemoval:

    def test_removing_takes_a_file_out_of_the_bundle(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        up = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        files_api.remove_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=up["id"],
            db=db, current_user=owner,
        )
        row = db.query(OfferingFile).filter(OfferingFile.id == up["id"]).one()
        assert row.superseded_at is not None
        assert row.superseded_by_id is None, "removal, not replacement"
        assert row.is_current is False

    def test_removing_does_not_delete_the_stored_object(
        self, db, owner_space, offering,
    ):
        """Approved: superseded files are retained for now."""
        space, owner = owner_space("creator")
        off = offering(space)
        up = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        before = _stored_keys(off)
        files_api.remove_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=up["id"],
            db=db, current_user=owner,
        )
        assert _stored_keys(off) == before

    def test_removal_frees_the_allowance(self, db, owner_space, offering):
        space, owner = owner_space("community")
        off = offering(space)
        up = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        files_api.remove_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=up["id"],
            db=db, current_user=owner,
        )
        # The one permitted slot is free again.
        out = _do_upload(db, space, off, owner, _pdf(), "b.pdf", "application/pdf")
        assert out["validation_status"] == FVS.pending.value

    def test_a_removed_file_is_not_downloadable_by_a_purchaser(
        self, db, owner_space, offering, make_user,
    ):
        from app.uploads.authorization import authorize_upload
        space, owner = owner_space("creator")
        off = offering(space)
        up = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        row = db.query(OfferingFile).filter(OfferingFile.id == up["id"]).one()
        row.validation_status = FVS.passed.value
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="free", status="active",
        ))
        db.flush()
        authorize_upload(row.storage_key, buyer, db)   # fine while current

        files_api.remove_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=up["id"],
            db=db, current_user=owner,
        )
        with pytest.raises(HTTPException) as exc:
            authorize_upload(row.storage_key, buyer, db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Step 2 — security
# ---------------------------------------------------------------------------


class TestUploadSecurity:

    def test_an_unsupported_type_is_refused(self, db, owner_space, offering):
        space, owner = owner_space("creator")
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            _do_upload(
                db, space, off, owner, b"MZ\x90\x00", "tool.exe",
                "application/octet-stream",
            )
        assert exc.value.detail["reason"] == "forbidden_type"
        assert _stored_keys(off) == set()

    def test_a_double_extension_cannot_slip_through(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            _do_upload(
                db, space, off, owner, _pdf(), "invoice.pdf.exe", "application/pdf",
            )
        assert exc.value.detail["reason"] == "forbidden_type"

    def test_a_mismatched_content_type_is_refused(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        with pytest.raises(HTTPException) as exc:
            _do_upload(db, space, off, owner, _pdf(), "guide.pdf", "application/zip")
        assert exc.value.detail["reason"] == "content_type_mismatch"

    def test_a_macro_document_is_refused_with_actionable_advice(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        fixture = (
            pathlib.Path(__file__).parent / "fixtures" / "offerings" / "genuine.xlsm"
        )
        with pytest.raises(HTTPException) as exc:
            _do_upload(
                db, space, off, owner, fixture.read_bytes(), "book.xlsm",
                "application/vnd.ms-excel.sheet.macroEnabled.12",
            )
        assert exc.value.detail["reason"] == "macro_document"
        assert ".xlsx" in exc.value.detail["message"]

    def test_another_creators_offering_is_a_404_not_a_403(
        self, db, owner_space, offering, make_user,
    ):
        """Cross-Collective requests must not disclose that it exists."""
        space, owner = owner_space("creator")
        off = offering(space)
        stranger = make_user(role="creator")
        with pytest.raises(HTTPException) as exc:
            files_api.list_offering_files(
                slug=space.slug, offering_slug=off.slug,
                db=db, current_user=stranger,
            )
        assert exc.value.status_code == 404

    def test_a_draft_offering_does_not_bypass_ownership(
        self, db, owner_space, offering, make_user,
    ):
        space, owner = owner_space("creator")
        off = offering(space, status=OfferingStatus.draft.value)
        stranger = make_user(role="creator")
        with pytest.raises(HTTPException) as exc:
            _do_upload(db, space, off, stranger, _pdf(), "a.pdf", "application/pdf")
        assert exc.value.status_code == 404

    def test_a_retired_offering_does_not_bypass_ownership(
        self, db, owner_space, offering, make_user,
    ):
        space, owner = owner_space("creator")
        off = offering(
            space, status=OfferingStatus.retired.value,
            retired_at=datetime.utcnow(),
        )
        stranger = make_user(role="creator")
        with pytest.raises(HTTPException) as exc:
            files_api.list_offering_files(
                slug=space.slug, offering_slug=off.slug,
                db=db, current_user=stranger,
            )
        assert exc.value.status_code == 404

    def test_a_file_id_from_another_offering_is_a_404(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        mine = offering(space)
        other = offering(space)
        far = _do_upload(db, space, other, owner, _pdf(), "z.pdf", "application/pdf")
        with pytest.raises(HTTPException) as exc:
            files_api.update_offering_file(
                slug=space.slug, offering_slug=mine.slug, file_id=far["id"],
                body=OfferingFileUpdateRequest(description="mine now"),
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 404

    def test_no_upload_is_immediately_downloadable(
        self, db, owner_space, offering, make_user,
    ):
        """Not for a purchaser, not for the owner, not for an admin."""
        from app.uploads.authorization import authorize_upload
        space, owner = owner_space("creator")
        off = offering(space)
        up = _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        row = db.query(OfferingFile).filter(OfferingFile.id == up["id"]).one()
        assert row.validation_status == FVS.pending.value

        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="free", status="active",
        ))
        db.flush()
        admin = make_user(role="admin")

        for who in (buyer, owner, admin):
            with pytest.raises(HTTPException) as exc:
                authorize_upload(row.storage_key, who, db)
            assert exc.value.status_code == 403, who.id

    def test_the_default_column_value_is_the_safe_one(self, db, owner_space, offering):
        """A row written by any future code path is pending, not passed."""
        space, _owner = owner_space("creator")
        off = offering(space)
        row = OfferingFile(
            id=_uid("ofl"), offering_id=off.id,
            storage_key=of.build_storage_key(offering_id=off.id, filename="x.pdf"),
            original_filename="x.pdf", content_type="application/pdf",
            byte_size=10,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        assert row.validation_status == FVS.pending.value
        assert row.resource_count == 1


class TestTemporaryFiles:

    def _temp_upload_files(self) -> set[str]:
        import tempfile
        d = pathlib.Path(tempfile.gettempdir())
        return {p.name for p in d.glob("fc-offering-*")}

    def test_a_successful_upload_leaves_no_temporary_file(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        before = self._temp_upload_files()
        _do_upload(db, space, off, owner, _pdf(4096), "a.pdf", "application/pdf")
        assert self._temp_upload_files() - before == set()

    def test_a_refused_upload_leaves_no_temporary_file(
        self, db, owner_space, offering,
    ):
        """The cleanup is a ``finally``, so there is one exit, not two."""
        space, owner = owner_space("community")
        off = offering(space)
        before = self._temp_upload_files()
        with pytest.raises(HTTPException):
            _do_upload(
                db, space, off, owner, _pdf(11 * MB), "big.pdf", "application/pdf",
            )
        assert self._temp_upload_files() - before == set()

    def test_an_interrupted_read_leaves_no_temporary_file(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        before = self._temp_upload_files()

        class Broken(io.RawIOBase):
            def read(self, n=-1):
                raise OSError("connection reset mid-upload")

        broken = UploadFile(
            file=Broken(), filename="a.pdf",
            headers=Headers({"content-type": "application/pdf"}),
        )
        with pytest.raises(OSError):
            files_api.upload_offering_file(
                slug=space.slug, offering_slug=off.slug, file=broken,
                description=None, db=db, current_user=owner,
            )
        assert self._temp_upload_files() - before == set()
        assert _stored_keys(off) == set()
        assert db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).count() == 0


class TestTransferFailure:

    def test_a_failed_transfer_writes_no_row(
        self, db, owner_space, offering, monkeypatch,
    ):
        space, owner = owner_space("creator")
        off = offering(space)

        def boom(*a, **kw):
            raise RuntimeError("multipart upload aborted")

        monkeypatch.setattr(storage, "upload_stream", boom)
        with pytest.raises(RuntimeError):
            _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        assert db.query(OfferingFile).filter(
            OfferingFile.offering_id == off.id,
        ).count() == 0

    def test_a_failure_after_the_transfer_removes_the_object(
        self, db, owner_space, offering, monkeypatch,
    ):
        """The compensating delete — no object nothing can reach."""
        space, owner = owner_space("creator")
        off = offering(space)

        deleted: list[str] = []
        real_delete = storage.delete_file
        monkeypatch.setattr(
            storage, "delete_file",
            lambda k: (deleted.append(k), real_delete(k)),
        )

        # Fail at the last possible moment: after R2, inside the commit.
        real_commit = db.commit
        calls = {"n": 0}

        def flaky_commit():
            calls["n"] += 1
            raise RuntimeError("commit failed")

        monkeypatch.setattr(db, "commit", flaky_commit)
        with pytest.raises(RuntimeError):
            _do_upload(db, space, off, owner, _pdf(), "a.pdf", "application/pdf")
        monkeypatch.setattr(db, "commit", real_commit)

        assert len(deleted) == 1, "the stored object was not cleaned up"
        assert _stored_keys(off) == set(), "an orphaned object was left behind"


class TestConcurrencyLimit:

    def test_the_number_of_simultaneous_uploads_is_bounded(self):
        assert ou.MAX_CONCURRENT_UPLOADS == 2

    def test_an_upload_beyond_the_limit_is_shed_with_429(self):
        """429, not 503 — a 503 would be captured as a Sentry event."""
        held = []
        try:
            for _ in range(ou.MAX_CONCURRENT_UPLOADS):
                cm = ou.upload_slot()
                cm.__enter__()
                held.append(cm)
            with pytest.raises(HTTPException) as exc:
                with ou.upload_slot():
                    pass
            assert exc.value.status_code == 429
            assert exc.value.detail["reason"] == "upload_busy"
        finally:
            for cm in held:
                cm.__exit__(None, None, None)

    def test_a_slot_is_released_even_when_the_body_raises(self):
        with pytest.raises(ValueError):
            with ou.upload_slot():
                raise ValueError("boom")
        # If the slot leaked, acquiring every slot below would fail.
        held = []
        try:
            for _ in range(ou.MAX_CONCURRENT_UPLOADS):
                cm = ou.upload_slot()
                cm.__enter__()
                held.append(cm)
        finally:
            for cm in held:
                cm.__exit__(None, None, None)


class TestRequestSizePrecheck:

    def test_the_matcher_covers_both_upload_endpoints(self):
        from app.main import _is_offering_file_upload as m
        assert m("POST", "/api/creator/spaces/s/offerings/o/files")
        assert m("POST", "/api/creator/spaces/s/offerings/o/files/f1/replace")

    def test_it_does_not_touch_other_surfaces(self):
        from app.main import _is_offering_file_upload as m
        assert not m("GET", "/api/creator/spaces/s/offerings/o/files")
        assert not m("POST", "/api/creator/spaces/s/offerings")
        assert not m("POST", "/api/uploads/avatars")
        assert not m("POST", "/api/creator/spaces/s/pathways/p/steps/x/resources")

    def test_the_ceiling_allows_the_largest_plan_file_plus_framing(self):
        from app.main import _MAX_UPLOAD_REQUEST_BYTES
        assert _MAX_UPLOAD_REQUEST_BYTES > of.MAX_OFFERING_FILE_BYTES

    def _run(self, *, method, path, content_length):
        """Invoke the middleware itself, with a minimal ASGI request.

        Calling the function rather than asserting on its matcher: the
        point of this layer is that it answers **before** the body is
        read, so the test must prove that ``call_next`` is never reached.
        """
        import asyncio
        from starlette.requests import Request
        from app.main import limit_offering_upload_size

        headers = []
        if content_length is not None:
            headers.append((b"content-length", str(content_length).encode()))
        scope = {
            "type": "http", "method": method, "path": path,
            "headers": headers, "query_string": b"",
        }

        reached = {"call_next": False}

        async def call_next(_request):
            reached["call_next"] = True
            from starlette.responses import JSONResponse as JR
            return JR(status_code=200, content={"ok": True})

        response = asyncio.run(
            limit_offering_upload_size(Request(scope), call_next),
        )
        return response, reached["call_next"]

    def test_an_oversized_declared_body_is_refused_before_it_is_read(self):
        response, reached = self._run(
            method="POST",
            path="/api/creator/spaces/s/offerings/o/files",
            content_length=of.MAX_OFFERING_FILE_BYTES * 4,
        )
        assert response.status_code == 413
        assert reached is False, "the body was handed on to be parsed"

    def test_an_acceptable_body_passes_through(self):
        response, reached = self._run(
            method="POST",
            path="/api/creator/spaces/s/offerings/o/files",
            content_length=2 * 1024 * 1024,
        )
        assert response.status_code == 200
        assert reached is True

    def test_a_missing_content_length_is_passed_on_to_the_counting_check(self):
        """Content-Length is client-supplied, so it is not trusted as
        proof of anything. An omitted header gets through here and is
        caught downstream by the check that counts what actually arrives."""
        response, reached = self._run(
            method="POST",
            path="/api/creator/spaces/s/offerings/o/files",
            content_length=None,
        )
        assert reached is True
        assert response.status_code == 200

    def test_other_endpoints_are_not_affected_by_the_ceiling(self):
        response, reached = self._run(
            method="POST", path="/api/uploads/avatars",
            content_length=of.MAX_OFFERING_FILE_BYTES * 4,
        )
        assert reached is True
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Step 5 — replacement
# ---------------------------------------------------------------------------


class TestReplacement:

    def _approved(self, db, space, off, owner, name="original.pdf"):
        up = _do_upload(db, space, off, owner, _pdf(1000), name, "application/pdf")
        row = db.query(OfferingFile).filter(OfferingFile.id == up["id"]).one()
        row.validation_status = FVS.passed.value
        db.flush()
        return row

    def test_the_original_stays_available_while_the_replacement_is_checked(
        self, db, owner_space, offering, make_user,
    ):
        from app.uploads.authorization import authorize_upload
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="one_time_purchase", status="active",
        ))
        db.flush()

        new = files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(1200), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )

        db.refresh(original)
        assert original.superseded_at is None, "original was superseded too early"
        assert original.validation_status == FVS.passed.value
        authorize_upload(original.storage_key, buyer, db)   # still works

        repl = db.query(OfferingFile).filter(
            OfferingFile.id == new["id"],
        ).one()
        assert repl.validation_status == FVS.pending.value
        assert repl.replaces_file_id == original.id
        with pytest.raises(HTTPException):
            authorize_upload(repl.storage_key, buyer, db)

    def test_a_replacement_shares_its_targets_slot(
        self, db, owner_space, offering,
    ):
        """Otherwise a Community creator could never replace anything."""
        space, owner = owner_space("community")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(1100), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        usage = ol.bundle_usage(db, offering=off)
        assert usage.resources == 1, "the replacement took a second slot"

    def test_a_slot_under_replacement_is_charged_the_larger_version(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)   # 1000 bytes
        files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(5000), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        usage = ol.bundle_usage(db, offering=off)
        assert usage.bytes_used == 5000, "not the sum, and not the smaller"

    def test_a_successful_replacement_switches_the_version(
        self, db, owner_space, offering, make_user,
    ):
        from app.uploads.authorization import authorize_upload
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        new = files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(1200), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        db.commit()

        # Drive the worker's real unit of work.
        assert _drive_worker(db) == FVS.passed.value

        db.expire_all()
        original = db.query(OfferingFile).filter(
            OfferingFile.id == original.id,
        ).one()
        repl = db.query(OfferingFile).filter(OfferingFile.id == new["id"]).one()
        assert repl.validation_status == FVS.passed.value
        assert original.superseded_at is not None
        assert original.superseded_by_id == repl.id
        assert repl.sort_order == 0, "the replacement inherited the position"

        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="one_time_purchase", status="active",
        ))
        db.commit()
        # The purchaser gets the new version at no extra cost...
        authorize_upload(repl.storage_key, buyer, db)
        # ...and not the old one.
        with pytest.raises(HTTPException):
            authorize_upload(original.storage_key, buyer, db)

    def test_a_failed_replacement_preserves_the_original(
        self, db, owner_space, offering, make_user,
    ):
        """The promise: a failed replacement never leaves purchasers
        without access to the previously approved file."""
        from app.uploads.authorization import authorize_upload
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        buyer = make_user()
        db.add(OfferingEntitlement(
            id=_uid("oen"), user_id=buyer.id, offering_id=off.id,
            space_id=space.id, source="one_time_purchase", status="active",
        ))

        # A CSV whose first cell is a formula — a genuine rejection.
        bad = b"name,amount\n=cmd|'/c calc'!A1,5\n"
        new = files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(bad, "rates.csv", "text/csv"),
            description=None, db=db, current_user=owner,
        )
        db.commit()

        assert _drive_worker(db) == FVS.rejected.value

        db.expire_all()
        original = db.query(OfferingFile).filter(
            OfferingFile.id == original.id,
        ).one()
        repl = db.query(OfferingFile).filter(OfferingFile.id == new["id"]).one()
        assert repl.validation_status == FVS.rejected.value
        assert original.superseded_at is None, "the original was taken away"
        assert original.validation_status == FVS.passed.value
        authorize_upload(original.storage_key, buyer, db)

    def test_two_live_replacements_for_one_file_are_refused(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(1100), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        with pytest.raises(HTTPException) as exc:
            files_api.replace_offering_file(
                slug=space.slug, offering_slug=off.slug, file_id=original.id,
                file=_upload(_pdf(1200), "v3.pdf", "application/pdf"),
                description=None, db=db, current_user=owner,
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["reason"] == "replacement_in_flight"

    def test_the_database_refuses_a_second_pending_replacement(
        self, db, owner_space, offering,
    ):
        """The partial unique index, not just the application check."""
        from sqlalchemy.exc import IntegrityError
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        for n in (1, 2):
            db.add(OfferingFile(
                id=_uid("ofl"), offering_id=off.id,
                storage_key=of.build_storage_key(
                    offering_id=off.id, filename=f"v{n}.pdf",
                ),
                original_filename=f"v{n}.pdf", content_type="application/pdf",
                byte_size=100, replaces_file_id=original.id,
            ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_a_file_under_replacement_cannot_be_removed(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(1100), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        with pytest.raises(HTTPException) as exc:
            files_api.remove_offering_file(
                slug=space.slug, offering_slug=off.slug, file_id=original.id,
                db=db, current_user=owner,
            )
        assert exc.value.status_code == 409

    def test_the_list_flags_a_pending_replacement(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(1100), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        shown = files_api.list_offering_files(
            slug=space.slug, offering_slug=off.slug, db=db, current_user=owner,
        )["files"]
        by_id = {f["id"]: f for f in shown}
        assert by_id[original.id]["replacement_pending"] is True
        assert by_id[original.id]["available_to_purchasers"] is True

    def test_a_replacement_cannot_itself_be_replaced_while_pending(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        original = self._approved(db, space, off, owner)
        new = files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=original.id,
            file=_upload(_pdf(1100), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        with pytest.raises(HTTPException) as exc:
            files_api.replace_offering_file(
                slug=space.slug, offering_slug=off.slug, file_id=new["id"],
                file=_upload(_pdf(1300), "v3.pdf", "application/pdf"),
                description=None, db=db, current_user=owner,
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["reason"] == "target_is_replacement"

    def test_a_replacement_inherits_the_description_unless_given_one(
        self, db, owner_space, offering,
    ):
        space, owner = owner_space("creator")
        off = offering(space)
        up = _do_upload(
            db, space, off, owner, _pdf(1000), "a.pdf", "application/pdf",
            description="The original note.",
        )
        row = db.query(OfferingFile).filter(OfferingFile.id == up["id"]).one()
        row.validation_status = FVS.passed.value
        db.flush()
        new = files_api.replace_offering_file(
            slug=space.slug, offering_slug=off.slug, file_id=row.id,
            file=_upload(_pdf(1100), "v2.pdf", "application/pdf"),
            description=None, db=db, current_user=owner,
        )
        assert new["description"] == "The original note."
