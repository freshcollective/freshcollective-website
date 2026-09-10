"""Creator Studio → Payments received: grant-state indicator + booking
cleanup on whole-purchase revoke.

Two contracts pinned here:

1. ``GET /api/creator/payments`` returns ``grant_state`` and
   ``grant_revoked_at`` per row, derived from the combined
   ``AccessPass`` + reachable ``PathwayEntitlement`` universe for
   the transaction. Values: ``intact | partially_revoked |
   fully_revoked | no_grant_records``. A grant row counts as
   admin-revoked iff ``revoked_by_user_id IS NOT NULL`` — this
   distinguishes admin action from natural pass expiry. ``grant_state``
   is orthogonal to Stripe payment ``status``; a refunded payment
   with active grants remains ``intact`` here.

2. ``POST /api/admin/payment-transactions/{txn_id}/revoke`` now
   releases future confirmed ``EventBooking`` rows that were
   consumed against any AccessPass created by the purchase. Past
   or in-progress sessions (``event.starts_at <= now``) are left
   as historical attendance. ``used_credits`` on the (now-cancelled)
   pass is NOT restored. Result carries ``future_bookings_released``
   for the success toast.
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
from app.creator.routes import list_creator_payments
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
from app.auth.dependencies import get_admin_user
from app.models.platform import (
    BookingStatus,
    EntitlementSource,
    EntitlementStatus,
    Event,
    EventBooking,
    EventSeries,
    Pathway,
    PathwayEntitlement,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _make_pathway(db, space, *, title: str = "Test Pathway") -> Pathway:
    p = Pathway(
        id=_uid("pw"), space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title, status="active",
        access_type="one_time", price_cents=20000,
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _make_txn(
    db, *, member, creator, space, pathway=None, gross_cents: int = 20000,
    status: PaymentTransactionStatus = PaymentTransactionStatus.succeeded,
) -> PaymentTransaction:
    now = datetime.utcnow()
    txn = PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=status,
        payment_provider=PaymentProvider.stripe,
        payer_user_id=member.id,
        creator_user_id=creator.id,
        space_id=space.id,
        pathway_id=pathway.id if pathway else None,
        currency="AUD",
        gross_amount_cents=gross_cents,
        platform_fee_basis_points=800,
        platform_fee_cents=int(gross_cents * 0.08),
        net_creator_amount_cents=gross_cents - int(gross_cents * 0.08),
        stripe_mode="test",
        payout_status=PayoutStatus.pending,
        created_at=now, updated_at=now,
    )
    db.add(txn)
    db.flush()
    return txn


def _make_access_pass(
    db, *, member, space, txn, pathway=None,
    pathway_entitlement_id: str | None = None,
) -> AccessPass:
    now = datetime.utcnow()
    ap = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn.id,
        pass_type=AccessPassType.pathway_access,
        status=AccessPassStatus.active,
        valid_from=now,
        grants_pathway_id=pathway.id if pathway else None,
        pathway_entitlement_id=pathway_entitlement_id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add(ap)
    db.flush()
    return ap


def _make_pathway_entitlement(
    db, *, member, space, pathway,
) -> PathwayEntitlement:
    now = datetime.utcnow()
    ent = PathwayEntitlement(
        id=_uid("pe"), user_id=member.id, space_id=space.id,
        pathway_id=pathway.id,
        source=EntitlementSource.one_time_purchase,
        status=EntitlementStatus.active,
        starts_at=now,
        created_at=now, updated_at=now,
    )
    db.add(ent)
    db.flush()
    return ent


def _make_series(db, space, *, title: str = "Term 4 2026") -> EventSeries:
    now = datetime.utcnow()
    s = EventSeries(
        id=_uid("es"), space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title=title,
        starts_at=now + timedelta(days=30),
        ends_at=now + timedelta(days=90),
        status="published",
    )
    db.add(s)
    db.flush()
    return s


def _make_series_pass(
    db, *, member, space, txn, series: EventSeries,
) -> AccessPass:
    """A series-scoped AccessPass on a purchase (no pathway_entitlement
    link). Used to build multi-grant purchases where each grant is a
    distinct row without a shared entitlement."""
    now = datetime.utcnow()
    ap = AccessPass(
        id=_uid("ap"), user_id=member.id, space_id=space.id,
        payment_transaction_id=txn.id,
        pass_type=AccessPassType.term_pass,
        status=AccessPassStatus.active,
        valid_from=now,
        eligible_series_id=series.id,
        source=AccessPassSource.one_time_purchase,
        created_at=now, updated_at=now,
    )
    db.add(ap)
    db.flush()
    return ap


def _add_space_membership(db, *, member, space, source: str = "purchase") -> SpaceMembership:
    m = SpaceMembership(
        id=_uid("sm"),
        user_id=member.id, space_id=space.id,
        role="learner", status=SpaceMembershipStatus.active,
        source=source, joined_at=datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


def _make_event(
    db, space, *, starts_at: datetime, capacity: int | None = 10,
    booking_access_type: str = "included_with_collective",
) -> Event:
    e = Event(
        id=_uid("e"),
        space_id=space.id,
        created_by_id=space.creator_id,
        title="Session",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        is_published=True,
        status="active",
        requires_booking=True,
        capacity=capacity,
        gathering_type="circle",
        attendance_format="online",
        booking_access_type=booking_access_type,
    )
    db.add(e)
    db.flush()
    return e


def _confirm_booking(
    db, *, member, event, access_pass: AccessPass | None = None,
    credits_used: int = 0,
) -> EventBooking:
    b = EventBooking(
        id=_uid("bk"),
        event_id=event.id,
        user_id=member.id,
        status=BookingStatus.confirmed,
        booked_at=datetime.utcnow(),
        access_pass_id=access_pass.id if access_pass else None,
        credits_used=credits_used,
    )
    db.add(b)
    db.flush()
    return b


def _seed_purchase(
    db, make_user, make_space,
    *, member=None, creator=None,
    status: PaymentTransactionStatus = PaymentTransactionStatus.succeeded,
):
    """Fabricate a completed pay-in-full purchase minimal shape:
    member + creator + space + pathway + txn + 1 AccessPass with
    ``pathway_entitlement_id`` linking to a PathwayEntitlement.
    Returns dict with all handles for tests to poke."""
    creator = creator or make_user(role="creator")
    member = member or make_user()
    space = make_space(creator=creator)
    pathway = _make_pathway(db, space)
    txn = _make_txn(
        db, member=member, creator=creator, space=space,
        pathway=pathway, status=status,
    )
    ent = _make_pathway_entitlement(db, member=member, space=space, pathway=pathway)
    ap = _make_access_pass(
        db, member=member, space=space, txn=txn, pathway=pathway,
        pathway_entitlement_id=ent.id,
    )
    _add_space_membership(db, member=member, space=space)
    db.commit()
    return {
        "creator": creator, "admin": make_user(role="admin"),
        "member": member, "space": space,
        "pathway": pathway, "txn": txn, "entitlement": ent, "pass": ap,
    }


def _find_row(rows, txn_id: str):
    matching = [r for r in rows if r.id == txn_id]
    assert len(matching) == 1, f"expected one row for {txn_id}, got {len(matching)}"
    return matching[0]


# ---------------------------------------------------------------------------
# 1. Grant-state derivation
# ---------------------------------------------------------------------------


class TestGrantStateDerivation:
    def test_intact_when_no_admin_revoke(self, db, make_user, make_space):
        s = _seed_purchase(db, make_user, make_space)
        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        assert row.grant_state == "intact"
        assert row.grant_revoked_at is None

    def test_fully_revoked_after_whole_purchase_revoke(self, db, make_user, make_space):
        s = _seed_purchase(db, make_user, make_space)
        revoke_purchase(
            s["txn"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )
        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        assert row.grant_state == "fully_revoked"
        assert row.grant_revoked_at is not None

    def test_partially_revoked_when_only_entitlement_revoked(
        self, db, make_user, make_space,
    ):
        """The exact case the user flagged: a purchase whose grant
        bundle is {AccessPass A, PathwayEntitlement Ent1}. Surgical
        revoke on Ent1 alone leaves A intact — must derive as
        partially_revoked, NOT intact."""
        s = _seed_purchase(db, make_user, make_space)
        revoke_pathway_entitlement(
            s["entitlement"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )
        # Sanity: the pass itself is untouched.
        db.refresh(s["pass"])
        assert s["pass"].revoked_by_user_id is None

        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        assert row.grant_state == "partially_revoked"
        assert row.grant_revoked_at is not None

    def test_partially_revoked_when_only_one_pass_of_two_revoked(
        self, db, make_user, make_space,
    ):
        """Multi-pass purchase (e.g. series pass + additional pathway
        pass). Surgical revoke on one pass → partially_revoked."""
        s = _seed_purchase(db, make_user, make_space)
        # Second pass on the same purchase — Series-scoped, no linked
        # entitlement. This gives us a distinct grant row.
        series = _make_series(db, s["space"])
        ap2 = _make_series_pass(
            db, member=s["member"], space=s["space"], txn=s["txn"],
            series=series,
        )
        db.commit()

        revoke_access_pass(
            ap2.id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )

        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        assert row.grant_state == "partially_revoked"
        assert row.grant_revoked_at is not None

    def test_natural_expiry_stays_intact(self, db, make_user, make_space):
        """``valid_until`` in the past but no ``revoked_by_user_id`` →
        grant_state remains ``intact`` (admin never acted). Distinguishes
        expiry-driven inaccessibility from administrative revoke."""
        s = _seed_purchase(db, make_user, make_space)
        s["pass"].valid_until = datetime.utcnow() - timedelta(days=1)
        db.commit()

        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        assert row.grant_state == "intact"
        assert row.grant_revoked_at is None

    def test_no_grant_records_when_txn_has_no_passes(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        member = make_user()
        space = make_space(creator=creator)
        txn = _make_txn(db, member=member, creator=creator, space=space)
        db.commit()

        rows = list_creator_payments(current_user=creator, db=db)
        row = _find_row(rows, txn.id)
        assert row.grant_state == "no_grant_records"
        assert row.grant_revoked_at is None

    def test_grant_revoked_at_is_earliest_admin_stamp(
        self, db, make_user, make_space,
    ):
        """When multiple grant rows are admin-revoked at different
        moments, ``grant_revoked_at`` reports the earliest."""
        s = _seed_purchase(db, make_user, make_space)
        series = _make_series(db, s["space"])
        ap2 = _make_series_pass(
            db, member=s["member"], space=s["space"], txn=s["txn"],
            series=series,
        )
        db.commit()

        # Revoke the extra pass first (older admin action).
        revoke_access_pass(
            ap2.id, RevokeAccessRequest(reason="early"),
            admin=s["admin"], db=db,
        )
        db.refresh(ap2)
        earlier = ap2.revoked_at
        assert earlier is not None

        # Revoke the original entitlement later.
        revoke_pathway_entitlement(
            s["entitlement"].id, RevokeAccessRequest(reason="later"),
            admin=s["admin"], db=db,
        )

        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        # Universe: 2 passes + 1 entitlement = 3 rows. 2 admin-revoked
        # (ap2 + ent). The main pass is still intact — partial.
        assert row.grant_state == "partially_revoked"
        # Earliest of the two admin revokes is the ap2 revoke.
        assert row.grant_revoked_at == earlier


# ---------------------------------------------------------------------------
# 2. Grant state is independent of Stripe payment status.
# ---------------------------------------------------------------------------


class TestGrantStateVsPaymentStatus:
    def test_refunded_payment_still_intact_when_grants_active(
        self, db, make_user, make_space,
    ):
        """Future-proof: a payment whose Stripe ``status`` was later
        set to ``refunded`` (or ``partially_refunded``) must not
        disable revoke — grant_state stays ``intact`` if no admin
        revoke has run."""
        s = _seed_purchase(db, make_user, make_space)
        s["txn"].status = PaymentTransactionStatus.refunded
        db.commit()

        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        assert row.status == "refunded"
        assert row.grant_state == "intact"

    def test_payment_status_unchanged_after_revoke(
        self, db, make_user, make_space,
    ):
        """The revoke endpoint must not touch ``PaymentTransaction.status``.
        A succeeded payment stays succeeded — the buyer's card was
        genuinely charged; revoking access does not un-charge it."""
        s = _seed_purchase(db, make_user, make_space)
        revoke_purchase(
            s["txn"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )
        db.refresh(s["txn"])
        assert s["txn"].status == PaymentTransactionStatus.succeeded

        rows = list_creator_payments(current_user=s["creator"], db=db)
        row = _find_row(rows, s["txn"].id)
        assert row.status == "succeeded"
        assert row.grant_state == "fully_revoked"

    def test_admin_only_gate_on_revoke_endpoint(
        self, db, make_user, make_space,
    ):
        """Non-admin cannot reach the revoke endpoint even if they're
        the Space owner. Enforced by ``get_admin_user`` — the endpoint
        signature depends on it, so the gate runs before the handler
        body. Frontend hides the button for non-admins; the endpoint
        gate is defence-in-depth. Regression pin so a future widening
        can't sneak past unnoticed."""
        # The Space's own creator has role='creator', not 'admin'.
        creator = make_user(role="creator")
        with pytest.raises(HTTPException) as exc:
            get_admin_user(current_user=creator)
        assert exc.value.status_code == 403

    def test_admin_role_passes_gate(self, db, make_user):
        """Positive companion: an admin user passes the dependency
        and is returned unchanged."""
        admin = make_user(role="admin")
        result = get_admin_user(current_user=admin)
        assert result is admin


# ---------------------------------------------------------------------------
# 3. Future-booking cleanup on whole-purchase revoke.
# ---------------------------------------------------------------------------


class TestBookingCleanupOnRevoke:
    def test_future_bookings_released_past_bookings_preserved(
        self, db, make_user, make_space,
    ):
        s = _seed_purchase(db, make_user, make_space)
        now = datetime.utcnow()
        # A past session (already happened) — historical attendance.
        past_event = _make_event(
            db, s["space"], starts_at=now - timedelta(days=2),
        )
        past_booking = _confirm_booking(
            db, member=s["member"], event=past_event,
            access_pass=s["pass"], credits_used=1,
        )
        # Two future sessions — both should be released.
        future_event_a = _make_event(
            db, s["space"], starts_at=now + timedelta(days=1),
        )
        future_event_b = _make_event(
            db, s["space"], starts_at=now + timedelta(days=8),
        )
        future_booking_a = _confirm_booking(
            db, member=s["member"], event=future_event_a,
            access_pass=s["pass"], credits_used=1,
        )
        future_booking_b = _confirm_booking(
            db, member=s["member"], event=future_event_b,
            access_pass=s["pass"], credits_used=1,
        )
        db.commit()

        result = revoke_purchase(
            s["txn"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )
        assert result.future_bookings_released == 2

        db.refresh(past_booking)
        db.refresh(future_booking_a)
        db.refresh(future_booking_b)
        assert past_booking.status == BookingStatus.confirmed
        assert past_booking.cancelled_at is None
        assert future_booking_a.status == BookingStatus.cancelled
        assert future_booking_a.cancelled_at is not None
        assert future_booking_b.status == BookingStatus.cancelled
        assert future_booking_b.cancelled_at is not None

    def test_capacity_reopens_when_future_booking_released(
        self, db, make_user, make_space,
    ):
        s = _seed_purchase(db, make_user, make_space)
        now = datetime.utcnow()
        event = _make_event(
            db, s["space"], starts_at=now + timedelta(days=1),
            capacity=1,
        )
        _confirm_booking(
            db, member=s["member"], event=event,
            access_pass=s["pass"], credits_used=1,
        )
        db.commit()

        # Before revoke: 1 confirmed booking.
        before = (
            db.query(EventBooking)
            .filter(
                EventBooking.event_id == event.id,
                EventBooking.status == BookingStatus.confirmed,
            )
            .count()
        )
        assert before == 1

        revoke_purchase(
            s["txn"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )

        after = (
            db.query(EventBooking)
            .filter(
                EventBooking.event_id == event.id,
                EventBooking.status == BookingStatus.confirmed,
            )
            .count()
        )
        assert after == 0  # capacity is fully re-opened

    def test_used_credits_not_restored_on_cancelled_pass(
        self, db, make_user, make_space,
    ):
        """The pass is being cancelled entirely — accounting on a
        cancelled pass is inert. The whole-purchase revoke must not
        decrement used_credits (that would inflate a phantom balance
        on a revoked entitlement)."""
        s = _seed_purchase(db, make_user, make_space)
        s["pass"].total_credits = 10
        s["pass"].used_credits = 3
        now = datetime.utcnow()
        event = _make_event(
            db, s["space"], starts_at=now + timedelta(days=2),
        )
        _confirm_booking(
            db, member=s["member"], event=event,
            access_pass=s["pass"], credits_used=1,
        )
        db.commit()

        revoke_purchase(
            s["txn"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )
        db.refresh(s["pass"])
        assert s["pass"].used_credits == 3  # unchanged
        assert s["pass"].status == AccessPassStatus.cancelled

    def test_idempotent_second_revoke_releases_zero_bookings(
        self, db, make_user, make_space,
    ):
        s = _seed_purchase(db, make_user, make_space)
        now = datetime.utcnow()
        event = _make_event(
            db, s["space"], starts_at=now + timedelta(days=1),
        )
        _confirm_booking(
            db, member=s["member"], event=event, access_pass=s["pass"],
        )
        db.commit()

        first = revoke_purchase(
            s["txn"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )
        assert first.future_bookings_released == 1
        assert first.already_revoked is False

        second = revoke_purchase(
            s["txn"].id, RevokeAccessRequest(reason="test"),
            admin=s["admin"], db=db,
        )
        assert second.future_bookings_released == 0
        assert second.already_revoked is True

    def test_overlapping_purchases_independent(
        self, db, make_user, make_space,
    ):
        """Revoking one purchase must not release bookings tied to a
        different purchase's access passes."""
        creator = make_user(role="creator")
        member = make_user()
        admin = make_user(role="admin")
        space = make_space(creator=creator)
        pathway_a = _make_pathway(db, space, title="Path A")
        pathway_b = _make_pathway(db, space, title="Path B")
        _add_space_membership(db, member=member, space=space)

        txn_a = _make_txn(
            db, member=member, creator=creator, space=space,
            pathway=pathway_a,
        )
        pass_a = _make_access_pass(
            db, member=member, space=space, txn=txn_a, pathway=pathway_a,
        )
        txn_b = _make_txn(
            db, member=member, creator=creator, space=space,
            pathway=pathway_b,
        )
        pass_b = _make_access_pass(
            db, member=member, space=space, txn=txn_b, pathway=pathway_b,
        )
        now = datetime.utcnow()
        event_a = _make_event(
            db, space, starts_at=now + timedelta(days=1),
        )
        event_b = _make_event(
            db, space, starts_at=now + timedelta(days=2),
        )
        booking_a = _confirm_booking(
            db, member=member, event=event_a, access_pass=pass_a,
        )
        booking_b = _confirm_booking(
            db, member=member, event=event_b, access_pass=pass_b,
        )
        db.commit()

        # Revoke purchase A only.
        result = revoke_purchase(
            txn_a.id, RevokeAccessRequest(reason="test"),
            admin=admin, db=db,
        )
        assert result.future_bookings_released == 1

        db.refresh(booking_a)
        db.refresh(booking_b)
        assert booking_a.status == BookingStatus.cancelled
        assert booking_b.status == BookingStatus.confirmed  # untouched
