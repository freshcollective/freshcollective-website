"""Draft-Collective deletion — end-to-end route + eligibility + R2 cleanup.

Scope for launch (locked deliberately narrow):

  * Only the founder (``Space.creator_id``) may delete.
  * Only draft Collectives (``status == draft``) are eligible.
  * Six commerce/membership counts must all be zero: other members,
    PaymentOption, PaymentTransaction, PathwayEntitlement,
    AccessPass, PurchasePlan.
  * R2 delete runs BEFORE the DB delete; a storage error aborts the
    entire operation and leaves the DB row intact so the creator
    can retry.
  * R2 cleanup is DB-driven — it can only touch keys named in a
    child row of THIS space, so another Collective's files can't be
    caught in the sweep.

Tests use direct route-function invocation (per the pattern in
``test_content_block_url_validation.py``) so the SAVEPOINT-scoped
``db`` fixture is visible to the handler.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import storage as storage_module
from app.creator.routes import _collect_space_r2_keys, delete_space
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.platform import (
    CommunityPost,
    CreatorMediaAsset,
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    PathwayType,
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    SpaceStatus,
)
from app.models.purchase_plan import PurchasePlan
from app.models.user import User


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def draft_space(db: Session, make_user, make_space) -> tuple[Space, User]:
    """A pristine draft Collective owned by ``creator``.

    ``make_space`` defaults to ``status="active"``; here we explicitly
    set draft since delete only ever fires on drafts."""
    creator = make_user(role="creator")
    space = make_space(creator=creator, status="draft")
    db.commit()
    return space, creator


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestEligibleDraftDelete:
    def test_pristine_draft_is_deleted(self, db: Session, draft_space) -> None:
        space, creator = draft_space
        space_id = space.id
        # ``delete_space`` returns 204 (None) on success.
        assert delete_space(slug=space.slug, db=db, current_user=creator) is None
        # Row is gone; cascades handled by DB.
        assert db.query(Space).filter(Space.id == space_id).first() is None

    def test_delete_does_not_touch_a_different_space(
        self, db: Session, make_user, make_space,
    ) -> None:
        # Regression guard: eligibility + cleanup for Space A must
        # not delete or modify Space B, even when both have the
        # same creator.
        creator = make_user(role="creator")
        space_a = make_space(creator=creator, status="draft", slug="space-a")
        space_b = make_space(creator=creator, status="draft", slug="space-b")
        # Give B a media asset — after deleting A, B's row must survive.
        asset = CreatorMediaAsset(
            id=_uid("cma"), space_id=space_b.id, uploaded_by_user_id=creator.id,
            title="Keep me", original_filename="k.png", stored_filename="k.png",
            storage_path="media/space-b/k.png", file_url="/api/uploads/media/space-b/k.png",
            mime_type="image/png", media_type="image", file_size_bytes=1,
            extension=".png",
        )
        db.add(asset)
        db.commit()

        delete_space(slug=space_a.slug, db=db, current_user=creator)

        assert db.query(Space).filter(Space.id == space_a.id).first() is None
        assert db.query(Space).filter(Space.id == space_b.id).first() is not None
        assert (
            db.query(CreatorMediaAsset).filter(CreatorMediaAsset.id == asset.id).first()
            is not None
        )


# ---------------------------------------------------------------------------
# Refusals — ownership + status + eligibility gates
# ---------------------------------------------------------------------------


class TestRefusals:
    def test_active_status_refused(self, db: Session, make_user, make_space) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="active")
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "active" in exc.value.detail

    def test_archived_status_refused(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="archived")
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "archived" in exc.value.detail

    def test_non_owner_creator_role_refused(
        self, db: Session, make_user, make_space,
    ) -> None:
        # A user with SpaceMembership.role=creator on the space is a
        # moderator-equivalent — not the founder. Must be refused.
        founder = make_user(role="creator")
        space = make_space(creator=founder, status="draft")
        other_creator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("mem"), space_id=space.id, user_id=other_creator.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=other_creator)
        assert exc.value.status_code == 403
        assert "owner" in exc.value.detail.lower()

    def test_non_owner_moderator_role_refused(
        self, db: Session, make_user, make_space,
    ) -> None:
        founder = make_user(role="creator")
        space = make_space(creator=founder, status="draft")
        moderator = make_user(role="creator")
        db.add(SpaceMembership(
            id=_uid("mem"), space_id=space.id, user_id=moderator.id,
            role=SpaceRole.moderator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=moderator)
        assert exc.value.status_code == 403

    def test_unrelated_user_refused(
        self, db: Session, make_user, make_space,
    ) -> None:
        founder = make_user(role="creator")
        space = make_space(creator=founder, status="draft")
        stranger = make_user(role="creator")
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=stranger)
        assert exc.value.status_code == 403

    def test_unknown_slug_404(self, db: Session, make_user) -> None:
        creator = make_user(role="creator")
        with pytest.raises(HTTPException) as exc:
            delete_space(slug="does-not-exist", db=db, current_user=creator)
        assert exc.value.status_code == 404


class TestEligibilityCounters:
    """Each of the six blocker counters must independently refuse
    deletion when > 0, even on a pristine-looking draft."""

    def test_other_member_refuses(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        other = make_user()
        db.add(SpaceMembership(
            id=_uid("mem"), space_id=space.id, user_id=other.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "member" in exc.value.detail

    def test_payment_option_refuses(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        pathway = Pathway(
            id=_uid("pw"), space_id=space.id, slug="p1", title="p",
            status="draft", pathway_type=PathwayType.guided_experience,
        )
        db.add(pathway)
        db.flush()
        db.add(PaymentOption(
            id=_uid("po"), space_id=space.id, pathway_id=pathway.id,
            attaches_to_kind="pathway", attaches_to_id=pathway.id,
            name="Test", payment_type=PaymentOptionType.one_time,
            status=PaymentOptionStatus.draft,
            price_per_session_cents=10000, calculated_total_cents=10000,
            currency="AUD",
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "payment option" in exc.value.detail

    def test_payment_transaction_refuses(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        payer = make_user()
        db.add(PaymentTransaction(
            id=_uid("txn"), payer_user_id=payer.id, space_id=space.id,
            creator_user_id=creator.id,
            transaction_type=PaymentTransactionType.gathering_ticket_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            gross_amount_cents=2500, platform_fee_basis_points=800,
            platform_fee_cents=200, net_creator_amount_cents=2300,
            currency="AUD", stripe_mode="test",
            payout_status=PayoutStatus.pending,
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "payment transaction" in exc.value.detail

    def test_pathway_entitlement_refuses(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        pathway = Pathway(
            id=_uid("pw"), space_id=space.id, slug="p1", title="p",
            status="draft", pathway_type=PathwayType.guided_experience,
        )
        db.add(pathway)
        db.flush()
        holder = make_user()
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=holder.id, space_id=space.id,
            pathway_id=pathway.id, source=EntitlementSource.manual_grant,
            status=EntitlementStatus.active,
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "entitlement" in exc.value.detail

    def test_access_pass_refuses(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        holder = make_user()
        db.add(AccessPass(
            id=_uid("ap"), user_id=holder.id, space_id=space.id,
            pass_type=AccessPassType.term_pass,
            source=AccessPassSource.admin_grant,
            status=AccessPassStatus.active,
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "access pass" in exc.value.detail

    def test_purchase_plan_refuses(
        self, db: Session, make_user, make_space, monkeypatch,
    ) -> None:
        # PurchasePlan has RESTRICT FKs to PaymentOption + Schedule,
        # so materialising a real row for a test needs a full
        # commerce chain. The eligibility gate uses a plain count()
        # query; stubbing that query proves the branch fires without
        # the setup overhead. The other five eligibility tests
        # exercise the shared pattern with real rows, so the
        # structural check plus this stub together cover the
        # PurchasePlan branch end-to-end.
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        db.commit()

        original_query = db.query

        class _StubCountQuery:
            def filter(self, *a, **kw): return self
            def count(self): return 1

        def fake_query(model, *args, **kwargs):
            if model is PurchasePlan:
                return _StubCountQuery()
            return original_query(model, *args, **kwargs)

        monkeypatch.setattr(db, "query", fake_query)

        with pytest.raises(HTTPException) as exc:
            delete_space(slug=space.slug, db=db, current_user=creator)
        assert exc.value.status_code == 409
        assert "subscription plan" in exc.value.detail

    def test_source_names_all_six_eligibility_counters(self) -> None:
        # Structural check: the delete handler must query every
        # counter listed in the eligibility contract. If a refactor
        # drops one (e.g., moves it into a helper), this test flags
        # the drift so a stub-based unit test isn't the only line
        # of defence.
        from pathlib import Path
        source = Path(
            "app/creator/routes.py"
        ).read_text() if Path("app/creator/routes.py").exists() else Path(
            "backend/app/creator/routes.py"
        ).read_text()
        for model in (
            "SpaceMembership",
            "PaymentOption",
            "PaymentTransaction",
            "PathwayEntitlement",
            "AccessPass",
            "PurchasePlan",
        ):
            assert (
                f"db.query({model})" in source
            ), f"delete_space missing eligibility counter for {model}"


# ---------------------------------------------------------------------------
# R2 cleanup: keys enumerated from DB, R2-first with abort on failure
# ---------------------------------------------------------------------------


class TestR2KeyCollection:
    def test_only_uploaded_urls_produce_keys(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        space.cover_image_url = "/api/uploads/covers/abc_cover.png"
        space.logo_url = "https://external-site.com/logo.png"  # external — skipped
        db.commit()

        keys = _collect_space_r2_keys(space, db)
        assert "covers/abc_cover.png" in keys
        assert not any("external-site" in k for k in keys)

    def test_media_library_storage_path_included_raw(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft", slug="my-space")
        asset = CreatorMediaAsset(
            id=_uid("cma"), space_id=space.id, uploaded_by_user_id=creator.id,
            title="t", original_filename="f.png", stored_filename="uuid_f.png",
            storage_path="media/my-space/uuid_f.png",
            file_url="/api/uploads/media/my-space/uuid_f.png",
            mime_type="image/png", media_type="image", file_size_bytes=1,
            extension=".png",
        )
        db.add(asset)
        db.commit()

        keys = _collect_space_r2_keys(space, db)
        # The Media Library key comes from ``storage_path`` (already
        # a bare R2 key), NOT from the ``/api/uploads/...`` URL —
        # both would deduplicate but the raw path is authoritative.
        assert "media/my-space/uuid_f.png" in keys

    def test_only_this_space_keys_are_collected(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space_a = make_space(creator=creator, status="draft", slug="a")
        space_b = make_space(creator=creator, status="draft", slug="b")
        space_a.cover_image_url = "/api/uploads/covers/a_cover.png"
        space_b.cover_image_url = "/api/uploads/covers/b_cover.png"
        db.commit()

        keys = _collect_space_r2_keys(space_a, db)
        assert "covers/a_cover.png" in keys
        assert "covers/b_cover.png" not in keys


class TestR2DeleteOrdering:
    def test_delete_calls_r2_then_deletes_db(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        space.cover_image_url = "/api/uploads/covers/x.png"
        db.commit()
        space_id = space.id

        # Patch the ``delete_keys`` reference IN THE ROUTES MODULE
        # (imported by name, so a monkey-patch on ``storage_module``
        # wouldn't affect the reference the handler actually calls).
        from app.creator import routes as routes_module
        with patch.object(routes_module, "delete_keys") as mock_delete:
            delete_space(slug=space.slug, db=db, current_user=creator)

        # R2 delete was called once with the exact collected keys.
        mock_delete.assert_called_once()
        args, _ = mock_delete.call_args
        assert "covers/x.png" in args[0]
        # DB row is gone.
        assert db.query(Space).filter(Space.id == space_id).first() is None

    def test_r2_failure_aborts_db_delete(
        self, db: Session, make_user, make_space,
    ) -> None:
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        space.cover_image_url = "/api/uploads/covers/x.png"
        db.commit()
        space_id = space.id

        from app.creator import routes as routes_module
        with patch.object(
            routes_module,
            "delete_keys",
            side_effect=storage_module.StorageDeleteError("simulated R2 outage"),
        ):
            with pytest.raises(HTTPException) as exc:
                delete_space(slug=space.slug, db=db, current_user=creator)

        assert exc.value.status_code == 500
        assert "NOT deleted" in exc.value.detail
        # DB row is UNTOUCHED — creator can retry.
        assert db.query(Space).filter(Space.id == space_id).first() is not None


# ---------------------------------------------------------------------------
# storage.delete_keys itself — filesystem-mode behaviour
# ---------------------------------------------------------------------------


class TestDeleteKeysFilesystemMode:
    def test_filesystem_delete_of_specific_keys_only(
        self, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)
        # Create three files across two subdirs; ask delete_keys to
        # remove only two of them. The third must survive.
        (tmp_path / "covers").mkdir()
        (tmp_path / "media" / "space-a").mkdir(parents=True)
        (tmp_path / "media" / "space-b").mkdir(parents=True)
        (tmp_path / "covers" / "a.png").write_bytes(b"A")
        (tmp_path / "media" / "space-a" / "x.png").write_bytes(b"X")
        (tmp_path / "media" / "space-b" / "keep.png").write_bytes(b"KEEP")

        storage_module.delete_keys([
            "covers/a.png",
            "media/space-a/x.png",
        ])

        assert not (tmp_path / "covers" / "a.png").exists()
        assert not (tmp_path / "media" / "space-a" / "x.png").exists()
        # Untouched — proves delete_keys never enumerates by prefix.
        assert (tmp_path / "media" / "space-b" / "keep.png").exists()

    def test_missing_files_are_not_errors(
        self, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.setattr(storage_module, "UPLOAD_DIR", tmp_path)
        # Must not raise, even though nothing exists.
        storage_module.delete_keys(["does/not/exist.png"])

    def test_empty_key_list_is_a_noop(self) -> None:
        # Neither R2 nor filesystem is touched.
        storage_module.delete_keys([])
