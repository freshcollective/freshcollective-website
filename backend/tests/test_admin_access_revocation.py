"""Admin revoke endpoints for member commerce access.

Covers:

* Pay-in-full ``AccessPass`` revoke — flips status + audit columns,
  writes matching ``AccessGrantRecord.revoked_at``.
* Pay-in-full ``PathwayEntitlement`` revoke — same plus locates the
  anchoring transaction via the sibling AccessPass.
* Idempotency — a second revoke call is a 200 no-op.
* Refuses to revoke plan-anchored rows (409) — finite-plan lifecycle
  owns its own revoke path.
* 404 when the row does not exist.
* Non-admins are rejected before the endpoint body runs (auth
  dependency behaviour; covered indirectly via the endpoint signature).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.admin.access_revocation import (
    RevokeAccessRequest,
    revoke_access_pass,
    revoke_pathway_entitlement,
    revoke_purchase,
)
from app.models.access_grant_record import AccessGrantRecord
from app.models.access_pass import (
    AccessPass,
    AccessPassSource,
    AccessPassStatus,
    AccessPassType,
)
from app.models.payment_option import (
    PaymentOption,
    PaymentOptionStatus,
    PaymentOptionType,
)
from app.models.payment_option_schedule import PaymentOptionSchedule
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.payment import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import (
    EntitlementSource,
    EntitlementStatus,
    Pathway,
    PathwayEntitlement,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
)
from app.services import access_grant_records as agr


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_stub_plan(db, member, space, pathway) -> PurchasePlan:
    """Minimum-viable ``PurchasePlan`` row (+ its FK parents) so the
    409-on-plan-anchored test can set ``purchase_plan_id`` on an
    access row without tripping the FK."""
    opt = PaymentOption(
        id=_uid("po"), space_id=space.id, pathway_id=None,
        attaches_to_kind="pathway", attaches_to_id=pathway.id,
        name="Test Plan Option",
        payment_type=PaymentOptionType.subscription,
        status=PaymentOptionStatus.published,
        calculated_total_cents=20000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    sched = PaymentOptionSchedule(
        payment_option_id=opt.id,
        name="Weekly x 10", schedule_type="recurring_installments",
        status="published",
        total_amount_cents=20000,
        installment_amount_cents=2000,
        installment_count=10,
        currency="AUD",
    )
    db.add(sched)
    db.flush()
    plan = PurchasePlan(
        id=_uid("pp"),
        member_user_id=member.id,
        payment_option_id=opt.id,
        payment_option_schedule_id=sched.id,
        space_id=space.id,
        installment_amount_cents=2000,
        installments_expected=10,
        total_expected_cents=20000,
        stripe_interval="week",
        stripe_interval_count=1,
        status=PurchasePlanStatus.active,
    )
    db.add(plan)
    db.flush()
    return plan


def _make_pay_in_full_purchase(db, make_user, make_space):
    """Fabricate a completed pay-in-full purchase — the state a
    successful EMBODY Awaken $200 checkout would leave the DB in.

    Returns (member, admin, space, pathway, txn, entitlement, pass).
    """
    admin = make_user(role="admin")
    member = make_user()
    space = make_space()

    pathway = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="Test Pathway", status="active",
        access_type="paid", price_cents=20000,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(pathway)
    db.flush()

    now = datetime.utcnow()

    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=member.id,
        creator_user_id=space.creator_id,
        space_id=space.id,
        pathway_id=pathway.id,
        currency="AUD",
        gross_amount_cents=20000,
        platform_fee_basis_points=800,
        platform_fee_cents=1600,
        net_creator_amount_cents=18400,
        net_platform_amount_cents=1600,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        created_at=now, updated_at=now,
    )
    db.add(txn)
    db.flush()

    entitlement = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now,
        created_at=now, updated_at=now,
    )
    db.add(entitlement)
    db.flush()

    access_pass = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn.id,
        pass_type=AccessPassType.pathway_access,
        status=AccessPassStatus.active,
        valid_from=now,
        grants_pathway_id=pathway.id,
        pathway_entitlement_id=entitlement.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add(access_pass)
    db.flush()

    agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway.id,
        source_type=agr.SOURCE_PAY_IN_FULL,
        source_purchase_plan_id=None,
        source_payment_transaction_id=txn.id,
        granted_at=now,
    )

    # Auto-joined SpaceMembership — matches what
    # ``_auto_join_membership`` writes on every real purchase.
    membership = SpaceMembership(
        id=_uid("sm"),
        user_id=member.id, space_id=space.id,
        role="learner", status=SpaceMembershipStatus.active,
        source="purchase", joined_at=now,
    )
    db.add(membership)
    db.commit()

    return member, admin, space, pathway, txn, entitlement, access_pass


class TestRevokeAccessPass:
    def test_pay_in_full_pass_is_revoked(
        self, db, make_user, make_space,
    ):
        member, admin, _, _, txn, _, ap = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )

        result = revoke_access_pass(
            ap.id, RevokeAccessRequest(reason="refunded"),
            admin=admin, db=db,
        )

        assert result.already_revoked is False
        assert result.kind == "access_pass"
        assert result.status == AccessPassStatus.cancelled.value
        assert result.revoked_by_user_id == admin.id
        assert result.revoked_at is not None
        assert result.grant_records_revoked == 1

        db.refresh(ap)
        assert ap.status == AccessPassStatus.cancelled
        assert ap.revoked_by_user_id == admin.id
        assert ap.revoked_at is not None

        # AGR was marked revoked
        agr_rows = (
            db.query(AccessGrantRecord)
            .filter(AccessGrantRecord.source_payment_transaction_id == txn.id)
            .all()
        )
        assert len(agr_rows) == 1
        assert agr_rows[0].revoked_at is not None
        assert agr_rows[0].revoked_reason == "refunded"

    def test_second_revoke_is_noop(
        self, db, make_user, make_space,
    ):
        member, admin, _, _, _, _, ap = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )
        first = revoke_access_pass(
            ap.id, RevokeAccessRequest(reason="dispute"),
            admin=admin, db=db,
        )
        assert first.already_revoked is False
        first_revoked_at = first.revoked_at

        second = revoke_access_pass(
            ap.id, RevokeAccessRequest(reason="something else"),
            admin=admin, db=db,
        )
        assert second.already_revoked is True
        assert second.revoked_at == first_revoked_at  # not touched
        assert second.grant_records_revoked == 0

    def test_missing_pass_returns_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ei:
            revoke_access_pass(
                "ap_does_not_exist",
                RevokeAccessRequest(),
                admin=admin, db=db,
            )
        assert ei.value.status_code == 404

    def test_plan_anchored_pass_refuses_with_409(
        self, db, make_user, make_space,
    ):
        member, admin, space, pathway, _, _, ap = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )
        plan = _make_stub_plan(db, member, space, pathway)
        ap.purchase_plan_id = plan.id
        db.commit()

        with pytest.raises(HTTPException) as ei:
            revoke_access_pass(
                ap.id, RevokeAccessRequest(),
                admin=admin, db=db,
            )
        assert ei.value.status_code == 409
        assert "finite payment plan" in ei.value.detail.lower()


class TestRevokePathwayEntitlement:
    def test_pay_in_full_entitlement_is_revoked(
        self, db, make_user, make_space,
    ):
        member, admin, _, _, txn, ent, ap = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )

        result = revoke_pathway_entitlement(
            ent.id, RevokeAccessRequest(reason="refund"),
            admin=admin, db=db,
        )

        assert result.already_revoked is False
        assert result.kind == "pathway_entitlement"
        assert result.status == EntitlementStatus.revoked.value
        assert result.revoked_by_user_id == admin.id
        assert result.revoked_at is not None
        assert result.grant_records_revoked == 1

        db.refresh(ent)
        assert ent.status == EntitlementStatus.revoked
        assert ent.revoked_by_user_id == admin.id
        assert ent.revoked_at is not None

    def test_second_revoke_is_noop(
        self, db, make_user, make_space,
    ):
        member, admin, _, _, _, ent, _ = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )
        first = revoke_pathway_entitlement(
            ent.id, RevokeAccessRequest(reason="dispute"),
            admin=admin, db=db,
        )
        assert first.already_revoked is False

        second = revoke_pathway_entitlement(
            ent.id, RevokeAccessRequest(),
            admin=admin, db=db,
        )
        assert second.already_revoked is True
        assert second.revoked_at == first.revoked_at

    def test_missing_entitlement_returns_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ei:
            revoke_pathway_entitlement(
                "pe_missing", RevokeAccessRequest(),
                admin=admin, db=db,
            )
        assert ei.value.status_code == 404

    def test_plan_anchored_entitlement_refuses_with_409(
        self, db, make_user, make_space,
    ):
        member, admin, space, pathway, _, ent, _ = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )
        plan = _make_stub_plan(db, member, space, pathway)
        ent.purchase_plan_id = plan.id
        db.commit()

        with pytest.raises(HTTPException) as ei:
            revoke_pathway_entitlement(
                ent.id, RevokeAccessRequest(),
                admin=admin, db=db,
            )
        assert ei.value.status_code == 409


# ---------------------------------------------------------------------------
# Whole-purchase revoke — canonical action for EMBODY launch
# ---------------------------------------------------------------------------


class TestRevokePurchase:
    def test_revokes_all_access_from_one_txn(
        self, db, make_user, make_space,
    ):
        member, admin, space, pathway, txn, ent, ap = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )

        result = revoke_purchase(
            txn.id, RevokeAccessRequest(reason="refund"),
            admin=admin, db=db,
        )

        assert result.already_revoked is False
        assert result.access_passes_revoked == 1
        assert result.entitlements_revoked == 1
        assert result.grant_records_revoked == 1

        db.refresh(ap)
        db.refresh(ent)
        assert ap.status == AccessPassStatus.cancelled
        assert ap.revoked_by_user_id == admin.id
        assert ent.status == EntitlementStatus.revoked
        assert ent.revoked_by_user_id == admin.id

        agr_rows = (
            db.query(AccessGrantRecord)
            .filter(AccessGrantRecord.source_payment_transaction_id == txn.id)
            .all()
        )
        assert all(r.revoked_at is not None for r in agr_rows)
        assert all(r.revoked_reason == "refund" for r in agr_rows)

    def test_removes_purchase_membership_when_no_other_active_grant(
        self, db, make_user, make_space,
    ):
        member, admin, space, _, txn, _, _ = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )

        result = revoke_purchase(
            txn.id, RevokeAccessRequest(reason="mis-purchase"),
            admin=admin, db=db,
        )
        assert result.membership_removed is True

        m = (
            db.query(SpaceMembership)
            .filter(
                SpaceMembership.user_id == member.id,
                SpaceMembership.space_id == space.id,
            )
            .one()
        )
        assert m.status == SpaceMembershipStatus.removed

    def test_keeps_membership_when_a_second_purchase_still_grants_access(
        self, db, make_user, make_space,
    ):
        """The core source-aware assertion — revoking one purchase
        must NOT wipe access another purchase is still providing."""
        member, admin, space, _, txn_a, _, _ = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )

        # Second purchase from the same buyer in the same space —
        # different pathway, separate txn.
        other_pathway = Pathway(
            id=_uid("pw"), space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="Other Pathway", status="active",
            access_type="paid", price_cents=10000,
            pathway_type=PathwayType.guided_experience,
        )
        db.add(other_pathway)
        db.flush()
        txn_b = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_payment_option_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=member.id,
            creator_user_id=space.creator_id,
            space_id=space.id,
            pathway_id=other_pathway.id,
            currency="AUD", gross_amount_cents=10000,
            platform_fee_basis_points=800,
            platform_fee_cents=800,
            net_creator_amount_cents=9200,
            net_platform_amount_cents=800,
            stripe_mode="test",
            payout_status=PayoutStatus.pending,
        )
        db.add(txn_b)
        db.flush()
        agr.record_pathway_grant(
            db, user_id=member.id, pathway_id=other_pathway.id,
            source_type=agr.SOURCE_PAY_IN_FULL,
            source_purchase_plan_id=None,
            source_payment_transaction_id=txn_b.id,
            granted_at=datetime.utcnow(),
        )
        db.commit()

        # Revoke only the FIRST purchase.
        result = revoke_purchase(
            txn_a.id, RevokeAccessRequest(reason="refund"),
            admin=admin, db=db,
        )
        assert result.membership_removed is False

        m = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.user_id == member.id)
            .one()
        )
        assert m.status == SpaceMembershipStatus.active

    def test_leaves_non_purchase_membership_alone(
        self, db, make_user, make_space,
    ):
        """A membership joined by 'invited' or a manual creator grant
        must NOT be removed even when no other active grant exists."""
        member, admin, space, _, txn, _, _ = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )
        m = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.user_id == member.id)
            .one()
        )
        m.source = "invited"
        db.commit()

        result = revoke_purchase(
            txn.id, RevokeAccessRequest(),
            admin=admin, db=db,
        )
        assert result.membership_removed is False
        db.refresh(m)
        assert m.status == SpaceMembershipStatus.active

    def test_second_revoke_is_noop(
        self, db, make_user, make_space,
    ):
        member, admin, _, _, txn, _, _ = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )
        revoke_purchase(txn.id, RevokeAccessRequest(), admin=admin, db=db)
        result = revoke_purchase(
            txn.id, RevokeAccessRequest(reason="again"),
            admin=admin, db=db,
        )
        assert result.already_revoked is True
        assert result.access_passes_revoked == 0
        assert result.entitlements_revoked == 0
        assert result.grant_records_revoked == 0

    def test_missing_txn_returns_404(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as ei:
            revoke_purchase(
                "txn_missing", RevokeAccessRequest(),
                admin=admin, db=db,
            )
        assert ei.value.status_code == 404

    def test_plan_anchored_txn_refuses_with_409(
        self, db, make_user, make_space,
    ):
        member, admin, space, pathway, txn, _, _ = _make_pay_in_full_purchase(
            db, make_user, make_space,
        )
        plan = _make_stub_plan(db, member, space, pathway)
        txn.purchase_plan_id = plan.id
        db.commit()

        with pytest.raises(HTTPException) as ei:
            revoke_purchase(
                txn.id, RevokeAccessRequest(),
                admin=admin, db=db,
            )
        assert ei.value.status_code == 409


# ---------------------------------------------------------------------------
# Surgical revoke AGR scoping — regression matrix for the fix that
# swaps ``_revoke_grant_records_by_txn`` (whole-txn sweep) for
# ``_revoke_grant_record_for_target`` (single grant) in the surgical
# callers. Whole-purchase revoke continues to use the txn-wide helper.
# ---------------------------------------------------------------------------


def _make_multi_grant_purchase(db, make_user, make_space):
    """Fabricate a single purchase that granted:
      * a Series pass (AccessPass with ``eligible_series_id``)
      * two Pathway grants (each backed by AccessPass +
        PathwayEntitlement, linked via ``pathway_entitlement_id``)

    Three AGR rows are seeded to match the fulfilment natural key
    exactly — one row per (user, target, source). Returns a dict of
    handles the tests poke.
    """
    from app.models.access_pass import (
        AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
    )
    from app.models.payment import (
        PaymentProvider, PaymentTransaction,
        PaymentTransactionStatus, PaymentTransactionType, PayoutStatus,
    )
    from app.models.platform import (
        EventSeries,
        EntitlementSource,
        EntitlementStatus,
        Pathway,
        PathwayEntitlement,
        PathwayType,
    )

    admin = make_user(role="admin")
    member = make_user()
    space = make_space()
    now = datetime.utcnow()

    series = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Term 4",
        starts_at=now + timedelta(days=30),
        ends_at=now + timedelta(days=90),
        status="published",
    )
    db.add(series)

    pathway_a = Pathway(
        id=_uid("pwa"), space_id=space.id,
        slug=f"pwa-{uuid.uuid4().hex[:8]}",
        title="EMBODY In-Person Sessions", status="active",
        access_type="paid", price_cents=10000,
        pathway_type=PathwayType.guided_experience,
    )
    pathway_b = Pathway(
        id=_uid("pwb"), space_id=space.id,
        slug=f"pwb-{uuid.uuid4().hex[:8]}",
        title="Home Practice", status="active",
        access_type="paid", price_cents=10000,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(pathway_a)
    db.add(pathway_b)
    db.flush()

    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=member.id,
        creator_user_id=space.creator_id,
        space_id=space.id,
        currency="AUD",
        gross_amount_cents=20000,
        platform_fee_basis_points=800,
        platform_fee_cents=1600,
        net_creator_amount_cents=18400,
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        created_at=now, updated_at=now,
    )
    db.add(txn)
    db.flush()

    # Two PathwayEntitlements, each with its own linked AccessPass —
    # matches the shape purchase fulfilment produces for a Series-
    # attached option with two pathway grants bundled in.
    ent_a = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway_a.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now, created_at=now, updated_at=now,
    )
    ent_b = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway_b.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now, created_at=now, updated_at=now,
    )
    db.add(ent_a); db.add(ent_b)
    db.flush()

    series_pass = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=now,
        eligible_series_id=series.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    pathway_pass_a = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn.id,
        pass_type=AccessPassType.pathway_access,
        status=AccessPassStatus.active,
        valid_from=now,
        grants_pathway_id=pathway_a.id,
        pathway_entitlement_id=ent_a.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    pathway_pass_b = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn.id,
        pass_type=AccessPassType.pathway_access,
        status=AccessPassStatus.active,
        valid_from=now,
        grants_pathway_id=pathway_b.id,
        pathway_entitlement_id=ent_b.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add(series_pass); db.add(pathway_pass_a); db.add(pathway_pass_b)
    db.flush()

    # One AGR per grant target, matching the fulfilment natural key.
    agr_series = agr.record_series_grant(
        db, user_id=member.id, series_id=series.id,
        source_type=agr.SOURCE_PAY_IN_FULL,
        source_purchase_plan_id=None,
        source_payment_transaction_id=txn.id,
        granted_at=now,
    )
    agr_a = agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway_a.id,
        source_type=agr.SOURCE_PAY_IN_FULL,
        source_purchase_plan_id=None,
        source_payment_transaction_id=txn.id,
        granted_at=now,
    )
    agr_b = agr.record_pathway_grant(
        db, user_id=member.id, pathway_id=pathway_b.id,
        source_type=agr.SOURCE_PAY_IN_FULL,
        source_purchase_plan_id=None,
        source_payment_transaction_id=txn.id,
        granted_at=now,
    )
    db.commit()

    return {
        "admin": admin, "member": member, "space": space,
        "series": series, "pathway_a": pathway_a, "pathway_b": pathway_b,
        "txn": txn, "series_pass": series_pass,
        "pathway_pass_a": pathway_pass_a, "pathway_pass_b": pathway_pass_b,
        "ent_a": ent_a, "ent_b": ent_b,
        "agr_series": agr_series, "agr_a": agr_a, "agr_b": agr_b,
    }


class TestSurgicalRevokeAgrScoping:
    def test_surgical_pathway_revoke_marks_only_that_pathway_agr(
        self, db, make_user, make_space,
    ):
        """The regression pin: revoking one PathwayEntitlement must
        NOT stamp sibling AGR rows revoked."""
        f = _make_multi_grant_purchase(db, make_user, make_space)

        result = revoke_pathway_entitlement(
            f["ent_a"].id, RevokeAccessRequest(reason="test"),
            admin=f["admin"], db=db,
        )
        assert result.already_revoked is False
        assert result.grant_records_revoked == 1

        db.refresh(f["agr_series"])
        db.refresh(f["agr_a"])
        db.refresh(f["agr_b"])
        assert f["agr_a"].revoked_at is not None
        assert f["agr_series"].revoked_at is None
        assert f["agr_b"].revoked_at is None

    def test_surgical_pass_revoke_marks_only_series_agr(
        self, db, make_user, make_space,
    ):
        """Revoking the Series AccessPass must NOT stamp the two
        Pathway AGRs revoked."""
        f = _make_multi_grant_purchase(db, make_user, make_space)

        result = revoke_access_pass(
            f["series_pass"].id, RevokeAccessRequest(reason="test"),
            admin=f["admin"], db=db,
        )
        assert result.already_revoked is False
        assert result.grant_records_revoked == 1

        db.refresh(f["agr_series"])
        db.refresh(f["agr_a"])
        db.refresh(f["agr_b"])
        assert f["agr_series"].revoked_at is not None
        assert f["agr_a"].revoked_at is None
        assert f["agr_b"].revoked_at is None

    def test_surgical_pathway_pass_revoke_marks_only_that_pathway_agr(
        self, db, make_user, make_space,
    ):
        """Pathway-scoped AccessPass revoke (grants_pathway_id set)
        targets only that pathway's AGR — the series AGR and the
        other pathway's AGR remain active."""
        f = _make_multi_grant_purchase(db, make_user, make_space)

        result = revoke_access_pass(
            f["pathway_pass_a"].id, RevokeAccessRequest(reason="test"),
            admin=f["admin"], db=db,
        )
        assert result.already_revoked is False
        assert result.grant_records_revoked == 1

        db.refresh(f["agr_series"])
        db.refresh(f["agr_a"])
        db.refresh(f["agr_b"])
        assert f["agr_a"].revoked_at is not None
        assert f["agr_series"].revoked_at is None
        assert f["agr_b"].revoked_at is None

    def test_whole_purchase_revoke_still_marks_all_remaining_agrs(
        self, db, make_user, make_space,
    ):
        """After a surgical revoke has already stamped one AGR, a
        subsequent whole-purchase revoke stamps the remaining
        unrevoked AGRs — proving the txn-wide helper stayed
        unchanged for the whole-purchase path."""
        f = _make_multi_grant_purchase(db, make_user, make_space)

        # Surgical: only Pathway A.
        revoke_pathway_entitlement(
            f["ent_a"].id, RevokeAccessRequest(reason="phase 1"),
            admin=f["admin"], db=db,
        )
        db.refresh(f["agr_a"])
        pathway_a_stamp = f["agr_a"].revoked_at
        assert pathway_a_stamp is not None

        # Whole purchase.
        result = revoke_purchase(
            f["txn"].id, RevokeAccessRequest(reason="phase 2"),
            admin=f["admin"], db=db,
        )
        # The whole-purchase sweep only touches AGRs that are still
        # unrevoked at call time — that's the series AGR + pathway B.
        assert result.grant_records_revoked == 2

        db.refresh(f["agr_series"])
        db.refresh(f["agr_a"])
        db.refresh(f["agr_b"])
        # All three now revoked.
        assert f["agr_series"].revoked_at is not None
        assert f["agr_a"].revoked_at is not None
        assert f["agr_b"].revoked_at is not None
        # The earlier surgical revoke's timestamp on pathway A is
        # preserved — the sweep skips already-revoked rows.
        assert f["agr_a"].revoked_at == pathway_a_stamp

    def test_repeated_surgical_revoke_is_idempotent(
        self, db, make_user, make_space,
    ):
        f = _make_multi_grant_purchase(db, make_user, make_space)

        first = revoke_pathway_entitlement(
            f["ent_a"].id, RevokeAccessRequest(reason="test"),
            admin=f["admin"], db=db,
        )
        assert first.already_revoked is False
        assert first.grant_records_revoked == 1
        db.refresh(f["agr_a"])
        first_stamp = f["agr_a"].revoked_at

        second = revoke_pathway_entitlement(
            f["ent_a"].id, RevokeAccessRequest(reason="test"),
            admin=f["admin"], db=db,
        )
        assert second.already_revoked is True
        assert second.grant_records_revoked == 0

        db.refresh(f["agr_a"])
        # Second call did not re-stamp the AGR row.
        assert f["agr_a"].revoked_at == first_stamp
        db.refresh(f["agr_series"])
        db.refresh(f["agr_b"])
        assert f["agr_series"].revoked_at is None
        assert f["agr_b"].revoked_at is None

    def test_overlapping_second_purchase_agrs_untouched(
        self, db, make_user, make_space,
    ):
        """Same member holds a second, overlapping purchase that
        granted the same Pathway A. Surgical revoke on the first
        purchase's entitlement touches only the first purchase's
        AGR; the second purchase's AGR for Pathway A stays active."""
        from app.models.payment import (
            PaymentProvider, PaymentTransaction,
            PaymentTransactionStatus, PaymentTransactionType, PayoutStatus,
        )

        f = _make_multi_grant_purchase(db, make_user, make_space)
        now = datetime.utcnow()

        second_txn = PaymentTransaction(
            id=_uid("txn"),
            transaction_type=PaymentTransactionType.member_pathway_purchase,
            status=PaymentTransactionStatus.succeeded,
            payment_provider=PaymentProvider.stripe,
            payer_user_id=f["member"].id,
            creator_user_id=f["space"].creator_id,
            space_id=f["space"].id,
            currency="AUD",
            gross_amount_cents=10000,
            platform_fee_basis_points=800,
            platform_fee_cents=800,
            net_creator_amount_cents=9200,
            stripe_mode="test",
            payout_status=PayoutStatus.pending,
            created_at=now, updated_at=now,
        )
        db.add(second_txn)
        db.flush()

        agr_second = agr.record_pathway_grant(
            db, user_id=f["member"].id, pathway_id=f["pathway_a"].id,
            source_type=agr.SOURCE_PAY_IN_FULL,
            source_purchase_plan_id=None,
            source_payment_transaction_id=second_txn.id,
            granted_at=now,
        )
        db.commit()

        revoke_pathway_entitlement(
            f["ent_a"].id, RevokeAccessRequest(reason="test"),
            admin=f["admin"], db=db,
        )

        db.refresh(f["agr_a"])
        db.refresh(agr_second)
        # First purchase's Pathway A AGR revoked; second purchase's
        # AGR for the same Pathway stays active (different txn).
        assert f["agr_a"].revoked_at is not None
        assert agr_second.revoked_at is None

    def test_surgical_revoke_no_agr_target_is_conservative_noop(
        self, db, make_user, make_space,
    ):
        """Pass with ``payment_transaction_id IS NULL`` (legacy /
        manual) — surgical revoke flips the pass row to cancelled
        and returns ``grant_records_revoked == 0``. No AGR row is
        touched (safer than guessing at a target)."""
        from app.models.access_pass import (
            AccessPass, AccessPassSource, AccessPassStatus, AccessPassType,
        )
        from app.models.platform import Pathway, PathwayType

        admin = make_user(role="admin")
        member = make_user()
        space = make_space()
        pathway = Pathway(
            id=_uid("pw"), space_id=space.id,
            slug=f"pw-{uuid.uuid4().hex[:8]}",
            title="Legacy path", status="active",
            access_type="paid", price_cents=10000,
            pathway_type=PathwayType.guided_experience,
        )
        db.add(pathway)
        db.flush()
        now = datetime.utcnow()
        ap = AccessPass(
            id=_uid("ap"), user_id=member.id, space_id=space.id,
            payment_transaction_id=None,   # <- legacy / manual
            pass_type=AccessPassType.pathway_access,
            status=AccessPassStatus.active,
            valid_from=now,
            grants_pathway_id=pathway.id,
            source=AccessPassSource.admin_grant,
            created_at=now, updated_at=now,
        )
        db.add(ap)
        db.commit()

        result = revoke_access_pass(
            ap.id, RevokeAccessRequest(reason="test"),
            admin=admin, db=db,
        )
        assert result.already_revoked is False
        assert result.grant_records_revoked == 0
        db.refresh(ap)
        assert ap.status == AccessPassStatus.cancelled
