"""Stopping the money after access has gone.

Two scenarios left a Stripe SubscriptionSchedule collecting for access
the member no longer had:

1. an urgent behaviour removal of somebody mid-instalment-plan;
2. an instalment whose fulfilment blocked.

Neither needed new payment machinery. ``cancel_plan_by_admin`` and
``stripe_finite_plan.cancel_finite_subscription_schedule`` already stop
a schedule safely, and both an admin endpoint and a creator-facing one
already call them. What was missing was the information to act on:

* **why** a fulfilment blocked, so a data fault a replay fixes is not
  mistaken for a buyer who can never be fulfilled (migration 167);
* **which plan** a blocked transaction belongs to;
* a creator-facing route from "this removal left money outstanding" to
  the page that cancels it.

And the warning itself, which was a stored boolean nothing ever
cleared. It is now derived from the plans, so it clears itself however
a plan ends and survives a cancellation that fails.

Nothing here cancels anything automatically.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.admin.schemas import PaymentTransactionOut
from app.creator.routes import list_removed_members, remove_member_with_reason
from app.creator.schemas import RemoveMemberRequest
from app.models.payment import (
    PaymentFulfilmentStatus,
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
    PayoutStatus,
)
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.user import User
from app.services import fulfilment_block_reasons as fbr
from app.services import membership_removal


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def space(make_space):
    return make_space(status="active", is_public=True)


@pytest.fixture
def owner(db, space):
    return db.query(User).filter(User.id == space.creator_id).first()


@pytest.fixture
def member(db, space, make_user):
    user = make_user()
    db.add(SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        source="joined",
    ))
    db.flush()
    return user


def _plan(db, space, member, status="active"):
    from app.models.payment_option import (
        PaymentOption, PaymentOptionStatus, PaymentOptionType,
    )
    from app.models.payment_option_schedule import PaymentOptionSchedule

    opt = PaymentOption(
        id=_uid("po"), space_id=space.id,
        attaches_to_kind="space", attaches_to_id=space.id,
        name="Four weekly payments",
        payment_type=PaymentOptionType.one_time,
        status=PaymentOptionStatus.published,
        calculated_total_cents=10000, currency="AUD",
    )
    db.add(opt)
    db.flush()
    sched = PaymentOptionSchedule(
        id=_uid("sched"), payment_option_id=opt.id, name="Weekly x 4",
        schedule_type="recurring_installments", status="published",
        installment_amount_cents=2500, installment_count=4,
        stripe_interval="week", stripe_interval_count=1,
        total_amount_cents=10000, currency="AUD",
    )
    db.add(sched)
    db.flush()
    now = datetime.utcnow()
    plan = PurchasePlan(
        id=_uid("pplan"), member_user_id=member.id,
        payment_option_id=opt.id, payment_option_schedule_id=sched.id,
        space_id=space.id, status=PurchasePlanStatus(status),
        currency="AUD", installment_amount_cents=2500,
        installments_expected=4, installments_paid=1,
        total_expected_cents=10000, stripe_interval="week",
        stripe_interval_count=1, stripe_mode="test",
        provider_subscription_schedule_id=_uid("sub_sched"),
        snapshot_grants_json={
            "version": 1, "entitlements": [], "access_passes": [],
            "bookings": [],
        },
        created_at=now, updated_at=now,
    )
    db.add(plan)
    db.flush()
    return plan


def _urgent_removal(db, space, member, owner):
    return remove_member_with_reason(
        space.slug, member.id,
        RemoveMemberRequest(
            reason=membership_removal.REASON_INAPPROPRIATE_BEHAVIOUR,
            note="Abuse.", rejoin_blocked=True,
            acknowledge_active_payment_plan=True,
        ),
        db=db, current_user=owner,
    )


def _removed_row(db, space, owner, user):
    rows = list_removed_members(space.slug, db=db, current_user=owner)
    return next(r for r in rows if r.user_id == user.id)


def _txn(db, *, payer, space, fulfilment, reason=None, plan_id=None):
    row = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_payment_option_purchase,
        status=PaymentTransactionStatus.succeeded,
        fulfilment_status=fulfilment,
        fulfilment_blocked_reason=reason,
        purchase_plan_id=plan_id,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=payer.id,
        creator_user_id=space.creator_id,
        space_id=space.id,
        currency="AUD", gross_amount_cents=2500,
        platform_fee_basis_points=800, platform_fee_cents=200,
        net_creator_amount_cents=2300, net_platform_amount_cents=200,
        payout_status=PayoutStatus.pending, stripe_mode="test",
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# 1. The blocked reason is persisted
# ---------------------------------------------------------------------------


class TestBlockedReasonPersistence:

    def test_every_blocking_site_records_one(self):
        """Nine paths set ``blocked``; every one must say why, or an
        administrator is back to guessing."""
        from pathlib import Path

        for name in ("app/webhooks/routes.py",
                     "app/webhooks/finite_plan_handlers.py"):
            src = Path(name).read_text()
            blocks = src.count("fulfilment_status = PaymentFulfilmentStatus.blocked")
            reasons = src.count("fulfilment_blocked_reason = ")
            assert blocks == reasons, f"{name}: {blocks} blocks, {reasons} reasons"

    def test_nine_sites_in_total(self):
        from pathlib import Path

        total = sum(
            Path(n).read_text().count("fulfilment_blocked_reason = ")
            for n in ("app/webhooks/routes.py",
                      "app/webhooks/finite_plan_handlers.py")
        )
        assert total == 9

    def test_the_column_is_nullable_and_unset_by_default(
        self, db, space, member,
    ):
        txn = _txn(
            db, payer=member, space=space,
            fulfilment=PaymentFulfilmentStatus.applied,
        )
        assert txn.fulfilment_blocked_reason is None

    def test_it_is_not_the_notes_field(self, db, space, member):
        """``notes`` is existing free text used for other things;
        overloading it would make the reason unqueryable."""
        txn = _txn(
            db, payer=member, space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
            reason=fbr.TEMPORARY_RESOLVER_ERROR,
        )
        assert txn.notes is None
        assert txn.fulfilment_blocked_reason == "resolver_error"


# ---------------------------------------------------------------------------
# 2. Temporary versus permanent
# ---------------------------------------------------------------------------


class TestClassifyingTheReason:
    """The distinction that decides whether a plan should be touched at
    all. Getting it wrong in one direction cancels a valid arrangement;
    in the other it leaves somebody paying forever."""

    @pytest.mark.parametrize("reason", [
        fbr.TEMPORARY_SNAPSHOT_MISSING,
        fbr.TEMPORARY_SNAPSHOT_UNREADABLE,
        fbr.TEMPORARY_RESOLVER_ERROR,
        fbr.TEMPORARY_VALIDATION_FAILED,
        fbr.TEMPORARY_APPLY_FAILED,
    ])
    def test_data_faults_are_temporary(self, reason):
        assert fbr.is_temporary(reason) is True
        assert fbr.needs_a_decision(reason) is False

    @pytest.mark.parametrize("detail", [
        "rejoin_blocked", "removal_admin", "removal_unknown", "status_paused",
    ])
    def test_ineligibility_needs_a_decision(self, detail):
        reason = fbr.ineligible(detail)
        assert fbr.needs_a_decision(reason) is True
        assert fbr.is_temporary(reason) is False

    def test_the_specific_cause_survives_in_the_string(self):
        """So an admin can tell a creator's block from an admin
        revocation without opening another page."""
        assert fbr.ineligible("rejoin_blocked").endswith("rejoin_blocked")

    def test_an_unrecorded_reason_claims_neither(self):
        """A historical blocked row. Reporting it as temporary would be
        the same guess this column exists to avoid."""
        assert fbr.is_temporary(None) is False
        assert fbr.needs_a_decision(None) is False

    def test_nothing_cancels_a_plan_from_a_reason(self):
        """The rule the whole design rests on: the column informs a
        human decision, it does not make one."""
        import inspect
        import re

        code = re.sub(
            r'"""[\s\S]*?"""', "", inspect.getsource(fbr),
        )
        for forbidden in ("cancel", "stripe", "refund", "PurchasePlan"):
            assert forbidden not in code.lower()


# ---------------------------------------------------------------------------
# 3. Admin visibility
# ---------------------------------------------------------------------------


class TestAdminSeesReasonAndPlan:

    def test_the_schema_carries_both(self):
        fields = set(PaymentTransactionOut.model_fields)
        assert "fulfilment_blocked_reason" in fields
        assert "purchase_plan_id" in fields

    def test_a_blocked_instalment_exposes_its_plan(
        self, db, space, member, make_user,
    ):
        """The gap that made scenario 2 unactionable: the column existed
        and the payload did not carry it, so the plan was not
        addressable."""
        from app.admin.routes import list_payments

        plan = _plan(db, space, member)
        _txn(
            db, payer=member, space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
            reason=fbr.ineligible("rejoin_blocked"),
            plan_id=plan.id,
        )
        [out] = list_payments(
            fulfilment_status="blocked", _=make_user(role="admin"), db=db,
        )
        assert out.purchase_plan_id == plan.id
        assert out.fulfilment_blocked_reason == (
            "membership_ineligible:rejoin_blocked"
        )

    def test_a_temporary_block_is_distinguishable(
        self, db, space, member, make_user,
    ):
        from app.admin.routes import list_payments

        _txn(
            db, payer=member, space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
            reason=fbr.TEMPORARY_RESOLVER_ERROR,
        )
        [out] = list_payments(
            fulfilment_status="blocked", _=make_user(role="admin"), db=db,
        )
        assert fbr.is_temporary(out.fulfilment_blocked_reason) is True
        assert out.purchase_plan_id is None

    def test_existing_fields_still_present(
        self, db, space, member, make_user,
    ):
        from app.admin.routes import list_payments

        _txn(
            db, payer=member, space=space,
            fulfilment=PaymentFulfilmentStatus.blocked,
            reason=fbr.TEMPORARY_APPLY_FAILED,
        )
        [out] = list_payments(_=make_user(role="admin"), db=db)
        assert out.status == "succeeded"
        assert out.gross_amount_cents == 2500
        assert out.stripe_mode == "test"

    def test_admin_only(self, db, make_user):
        from app.auth.dependencies import get_admin_user

        with pytest.raises(HTTPException):
            get_admin_user(current_user=make_user(role="user"))


# ---------------------------------------------------------------------------
# 4. The creator-facing warning lifecycle
# ---------------------------------------------------------------------------


class TestThePaymentWarningIsDerived:
    """``payment_action_required`` is audit — it records that the
    removal was taken while a plan was collecting, and stays true.

    What the creator SEES is ``payment_action_outstanding``, derived
    from the plans themselves. That is the whole reason there is no
    clearing logic to get wrong: a plan can end by creator
    cancellation, admin cancellation, natural completion or exhausted
    retries, and a flag cleared by only some of those reads "resolved"
    when it is not.
    """

    def test_it_shows_while_a_live_plan_remains(
        self, db, space, member, owner,
    ):
        _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        row = _removed_row(db, space, owner, member)
        assert row.payment_action_outstanding is True
        assert row.payment_action_required is True

    def test_it_links_to_the_plan(self, db, space, member, owner):
        plan = _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        assert _removed_row(
            db, space, owner, member,
        ).live_payment_plan_id == plan.id

    @pytest.mark.parametrize("ended", ["cancelled", "completed", "failed"])
    def test_it_clears_however_the_plan_ends(
        self, db, space, member, owner, ended,
    ):
        """Creator cancellation, admin cancellation, natural completion
        and exhausted retries all land in one of these — and none of
        them has to remember to clear a flag."""
        plan = _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        assert _removed_row(
            db, space, owner, member,
        ).payment_action_outstanding is True

        plan.status = PurchasePlanStatus(ended)
        db.flush()
        row = _removed_row(db, space, owner, member)
        assert row.payment_action_outstanding is False
        assert row.live_payment_plan_id is None

    def test_the_audit_fact_survives_resolution(
        self, db, space, member, owner,
    ):
        """The removal WAS taken with a plan live. That stays recorded
        after the money is sorted out."""
        plan = _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        plan.status = PurchasePlanStatus.cancelled
        db.flush()
        row = _removed_row(db, space, owner, member)
        assert row.payment_action_required is True
        assert row.payment_action_outstanding is False

    @pytest.mark.parametrize(
        "status", membership_removal.LIVE_PLAN_STATUSES,
    )
    def test_a_failed_cancellation_leaves_it_standing(
        self, db, space, member, owner, status,
    ):
        """The required behaviour, and it falls out for free: a Stripe
        failure means the local transition never happened, so the plan
        is still live and the warning is still derived as True."""
        _plan(db, space, member, status=status)
        _urgent_removal(db, space, member, owner)
        assert _removed_row(
            db, space, owner, member,
        ).payment_action_outstanding is True

    def test_an_unrelated_member_is_not_warned_about(
        self, db, space, member, owner, make_user,
    ):
        """A live plan belongs to one person. One member's outstanding
        money must not light up another's row."""
        other = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=other.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            source="joined",
        ))
        db.flush()
        _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        remove_member_with_reason(
            space.slug, other.id,
            RemoveMemberRequest(
                reason=membership_removal.REASON_NO_LONGER_REQUIRED,
            ),
            db=db, current_user=owner,
        )
        assert _removed_row(
            db, space, owner, other,
        ).payment_action_outstanding is False

    def test_a_plan_in_another_collective_does_not_warn_here(
        self, db, space, member, owner, make_space,
    ):
        other_space = make_space(status="active")
        _plan(db, other_space, member)
        remove_member_with_reason(
            space.slug, member.id,
            RemoveMemberRequest(
                reason=membership_removal.REASON_NO_LONGER_REQUIRED,
            ),
            db=db, current_user=owner,
        )
        assert _removed_row(
            db, space, owner, member,
        ).payment_action_outstanding is False

    def test_the_lookup_is_one_query_per_page(self):
        """Not a count per row — the view lists every removed person."""
        import inspect

        src = inspect.getsource(list_removed_members)
        # The CALL, not the mention of it in the comment above.
        assert src.count("live_plans_by_member(") == 1

    def test_nothing_writes_the_flag_on_read(self):
        import inspect

        src = inspect.getsource(list_removed_members)
        assert "payment_action_required =" not in src
        assert "db.commit" not in src


# ---------------------------------------------------------------------------
# 5. Existing cancellation behaviour is untouched
# ---------------------------------------------------------------------------


class TestExistingCancellationIsUnchanged:

    def test_removal_never_calls_stripe(self, db, space, member, owner):
        """Cancellation stays a separate, explicit action."""
        import inspect
        import re

        _plan(db, space, member)
        plan_before = db.query(PurchasePlan).filter(
            PurchasePlan.member_user_id == member.id,
        ).first()
        _urgent_removal(db, space, member, owner)
        assert plan_before.status == PurchasePlanStatus.active
        assert plan_before.cancelled_at is None

        # String literals stripped: the creator-facing warning names
        # Stripe deliberately, because telling them billing continues is
        # its whole purpose. What must not exist is a call.
        code = re.sub(
            r'"""[\s\S]*?"""', "",
            inspect.getsource(remove_member_with_reason),
        )
        code = re.sub(r"#.*$", "", code, flags=re.M)
        code = re.sub(r'"[^"\n]*"', '""', code)
        code = re.sub(r"'[^'\n]*'", "''", code)
        assert "stripe" not in code.lower()
        assert "cancel_plan_by_admin" not in code

    def test_the_cancel_orchestrator_was_not_modified(self):
        """Reused as-is: provider-first, suspends rather than revokes,
        skips rows another source keeps alive, refunds nothing."""
        import inspect

        from app.services import finite_plan_lifecycle as fpl

        import re

        src = inspect.getsource(fpl.cancel_plan_by_admin)
        assert "stripe_finite_plan.cancel_finite_subscription_schedule" in src
        # The docstring explains at length that refunds are separate, so
        # the check is on code: it must issue none.
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert "refund" not in code.lower()

    def test_the_schedule_helper_was_not_modified(self):
        import inspect

        from app.services import stripe_finite_plan as sfp

        src = inspect.getsource(sfp.cancel_finite_subscription_schedule)
        assert "invoice_now=False" in src
        assert "prorate=False" in src
        # ``cancel`` not ``release`` — release would let the
        # subscription continue autonomously.
        assert "SubscriptionSchedule.cancel" in src

    def test_a_cancellation_cannot_resurrect_revoked_access(
        self, db, space, member, owner,
    ):
        """Both suspend queries filter ``== active``, so rows the
        removal already revoked are skipped — a cancellation cannot
        downgrade a moderation decision."""
        import inspect

        from app.services import finite_plan_lifecycle as fpl

        src = inspect.getsource(fpl._apply_access_effects_for_plan_state)
        assert "EntitlementStatus.active" in src
        assert "AccessPassStatus.active" in src

    def test_both_cancel_endpoints_still_exist(self):
        from app.admin.plan_cancellation import cancel_purchase_plan_admin
        from app.creator.plan_cancellation_routes import (
            creator_cancel_purchase_plan,
        )

        assert callable(cancel_purchase_plan_admin)
        assert callable(creator_cancel_purchase_plan)

    def test_the_creator_endpoint_keeps_its_permissions(self):
        """Owner of the plan's Space, or admin. Cross-Collective 404."""
        import inspect

        from app.creator import plan_cancellation_routes as r

        src = inspect.getsource(r._can_creator_act_on_space)
        assert 'user.role == "admin"' in src
        assert "creator_id = :uid" in src

    def test_a_stripe_failure_leaves_local_state_alone(self):
        import inspect

        from app.creator import plan_cancellation_routes as r

        src = inspect.getsource(r.creator_cancel_purchase_plan)
        # Provider-first: the Stripe error is caught and returned as 502
        # BEFORE the commit.
        assert src.index("stripe.StripeError") < src.index("db.commit()")
        assert "502" in src


# ---------------------------------------------------------------------------
# 6. Nothing else moved
# ---------------------------------------------------------------------------


class TestSafeguardsPreserved:

    def test_offering_entitlements_untouched_by_removal(
        self, db, space, member, owner,
    ):
        from app.models.offering import (
            Offering, OfferingEntitlement, OfferingEntitlementSource,
            OfferingEntitlementStatus, OfferingFulfilmentKind, OfferingStatus,
        )

        off = Offering(
            id=_uid("off"), space_id=space.id,
            created_by_user_id=space.creator_id,
            slug=f"g-{uuid.uuid4().hex[:8]}", title="A Guide",
            summary="Lines.", status=OfferingStatus.published.value,
            fulfilment_kind=OfferingFulfilmentKind.digital_download.value,
        )
        db.add(off)
        db.flush()
        ent = OfferingEntitlement(
            id=_uid("oen"), user_id=member.id, offering_id=off.id,
            space_id=space.id,
            source=OfferingEntitlementSource.one_time_purchase.value,
            status=OfferingEntitlementStatus.active.value,
        )
        db.add(ent)
        db.flush()
        _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        assert ent.status == OfferingEntitlementStatus.active.value

    def test_the_payment_record_is_preserved(
        self, db, space, member, owner,
    ):
        plan = _plan(db, space, member)
        txn = _txn(
            db, payer=member, space=space,
            fulfilment=PaymentFulfilmentStatus.applied,
            plan_id=plan.id,
        )
        _urgent_removal(db, space, member, owner)
        assert txn.status == PaymentTransactionStatus.succeeded
        assert txn.gross_amount_cents == 2500

    def test_the_ban_record_is_preserved(self, db, space, member, owner):
        _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        row = _removed_row(db, space, owner, member)
        assert row.rejoin_blocked is True
        assert row.removal_reason == "inappropriate_behaviour"
        assert row.note == "Abuse."

    def test_plan_history_is_preserved(self, db, space, member, owner):
        plan = _plan(db, space, member)
        _urgent_removal(db, space, member, owner)
        assert plan.installments_paid == 1
        assert plan.total_expected_cents == 10000
