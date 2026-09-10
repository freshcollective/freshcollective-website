"""Admin revoke endpoints for member commerce access.

Three entry points:

* ``POST /api/admin/payment-transactions/{txn_id}/revoke`` — the
  canonical action: revoke *every* piece of access created by one
  purchase (AccessPasses, PathwayEntitlements, grant-log records).
  Also removes the auto-joined SpaceMembership **only when no other
  active grant source remains** for that user in that space, so a
  revoke on one purchase never wipes access another purchase / manual
  grant is still providing.
* ``POST /api/admin/access-passes/{pass_id}/revoke`` — surgical
  escape hatch when only one pass needs to be revoked.
* ``POST /api/admin/pathway-entitlements/{entitlement_id}/revoke`` —
  same, for a single entitlement.

All endpoints:

* mark the row terminal — ``AccessPass.status='cancelled'`` /
  ``PathwayEntitlement.status='revoked'`` — and populate the existing
  ``revoked_by_user_id`` / ``revoked_at`` audit columns.
* mark any matching ``AccessGrantRecord`` rows revoked so the FIP3
  overlap queries stay honest.
* are **idempotent**: a second call is a 200 OK no-op.

Deliberately narrow scope
-------------------------
This is the pre-EMBODY minimum: give the operator a way to reverse a
member's commerce access when a real-money purchase needs to be
undone (refund, dispute, mis-purchase). It does **not**:

* touch Stripe. A refund is issued in the Stripe dashboard; revoke
  is what synchronises Fresh Collective state to match. A future
  ``charge.refunded`` webhook handler can call the same helpers.
* revoke plan-derived access. Finite-plan lifecycle owns its own
  revoke path (``finite_plan_lifecycle.revoke_records_for_plan`` +
  webhook handlers). These endpoints refuse when the row is anchored
  to a ``purchase_plan_id`` — Phase 2 will wire plan-cancel from
  admin separately.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.access_grant_record import AccessGrantRecord
from app.models.access_pass import AccessPass, AccessPassStatus
from app.models.payment import PaymentTransaction
from app.models.platform import (
    BookingStatus,
    EntitlementStatus,
    Event,
    EventBooking,
    PathwayEntitlement,
    SpaceMembership,
    SpaceMembershipStatus,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RevokeAccessRequest(BaseModel):
    reason: str | None = None


class RevokeAccessResult(BaseModel):
    id: str
    kind: str
    status: str
    revoked_at: datetime | None
    revoked_by_user_id: str | None
    already_revoked: bool
    grant_records_revoked: int


def _revoke_grant_records_by_txn(
    db: Session, *,
    payment_transaction_id: str | None,
    reason: str,
    now: datetime,
) -> int:
    """Mark AGR rows anchored to ``payment_transaction_id`` as revoked.

    Mirrors :func:`services.access_grant_records.revoke_records_for_plan`
    but keyed on the pay-in-full source (``source_payment_transaction_id``).
    Idempotent — already-revoked rows are left alone.
    """
    if not payment_transaction_id:
        return 0
    rows = (
        db.query(AccessGrantRecord)
        .filter(
            AccessGrantRecord.source_payment_transaction_id == payment_transaction_id,
            AccessGrantRecord.revoked_at.is_(None),
        )
        .all()
    )
    for r in rows:
        r.revoked_at = now
        r.revoked_reason = reason
        r.updated_at = now
    if rows:
        db.flush()
        logger.info(
            "access_grant_records: revoked %d record(s) for payment_transaction=%s reason=%s",
            len(rows), payment_transaction_id, reason,
        )
    return len(rows)


@router.post(
    "/access-passes/{pass_id}/revoke",
    response_model=RevokeAccessResult,
)
def revoke_access_pass(
    pass_id: str,
    body: RevokeAccessRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> RevokeAccessResult:
    """Revoke a member's AccessPass.

    * 404 — row does not exist.
    * 409 — pass is anchored to a ``purchase_plan_id`` (finite plan
      cancel flow is separate; refuse rather than orphan the plan).
    * 200 — pass was already revoked (no-op) or has now been revoked.
    """
    ap: AccessPass | None = (
        db.query(AccessPass)
        .filter(AccessPass.id == pass_id)
        .with_for_update()
        .first()
    )
    if ap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access pass not found.",
        )
    if ap.purchase_plan_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This access pass is anchored to a finite payment plan. "
                "Cancel the plan through the finite-plan lifecycle flow; "
                "do not revoke the pass directly."
            ),
        )

    already_revoked = ap.status in (
        AccessPassStatus.cancelled,
        AccessPassStatus.expired,
    ) and ap.revoked_at is not None

    reason_text = (body.reason or "").strip() or "admin_revoke"

    if already_revoked:
        logger.info(
            "admin revoke: AccessPass %s already revoked at %s — no-op",
            ap.id, ap.revoked_at,
        )
        return RevokeAccessResult(
            id=ap.id,
            kind="access_pass",
            status=ap.status.value if hasattr(ap.status, "value") else str(ap.status),
            revoked_at=ap.revoked_at,
            revoked_by_user_id=ap.revoked_by_user_id,
            already_revoked=True,
            grant_records_revoked=0,
        )

    now = datetime.utcnow()
    ap.status = AccessPassStatus.cancelled
    ap.revoked_at = now
    ap.revoked_by_user_id = admin.id
    ap.updated_at = now

    grant_rows = _revoke_grant_records_by_txn(
        db,
        payment_transaction_id=ap.payment_transaction_id,
        reason=reason_text,
        now=now,
    )
    db.commit()
    db.refresh(ap)

    logger.info(
        "admin revoke: AccessPass %s revoked by admin=%s user=%s reason=%r",
        ap.id, admin.id, ap.user_id, reason_text,
    )
    return RevokeAccessResult(
        id=ap.id,
        kind="access_pass",
        status=ap.status.value if hasattr(ap.status, "value") else str(ap.status),
        revoked_at=ap.revoked_at,
        revoked_by_user_id=ap.revoked_by_user_id,
        already_revoked=False,
        grant_records_revoked=grant_rows,
    )


@router.post(
    "/pathway-entitlements/{entitlement_id}/revoke",
    response_model=RevokeAccessResult,
)
def revoke_pathway_entitlement(
    entitlement_id: str,
    body: RevokeAccessRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> RevokeAccessResult:
    """Revoke a member's PathwayEntitlement.

    * 404 — row does not exist.
    * 409 — entitlement is anchored to a ``purchase_plan_id`` (see
      :func:`revoke_access_pass` for rationale).
    * 200 — entitlement was already revoked (no-op) or has now been
      revoked.

    The matching ``AccessGrantRecord`` rows for this pathway/user
    are located via the AccessPass that shares the same
    ``payment_transaction_id`` (pay-in-full anchoring). If no
    AccessPass links back, only the entitlement row is touched — the
    AGR log stays consistent because the fulfilment always writes an
    AGR per (user, target, source), so the join by
    ``source_payment_transaction_id`` picks it up.
    """
    ent: PathwayEntitlement | None = (
        db.query(PathwayEntitlement)
        .filter(PathwayEntitlement.id == entitlement_id)
        .with_for_update()
        .first()
    )
    if ent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pathway entitlement not found.",
        )
    if ent.purchase_plan_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This entitlement is anchored to a finite payment plan. "
                "Cancel the plan through the finite-plan lifecycle flow; "
                "do not revoke the entitlement directly."
            ),
        )

    already_revoked = (
        ent.status == EntitlementStatus.revoked and ent.revoked_at is not None
    )
    reason_text = (body.reason or "").strip() or "admin_revoke"

    if already_revoked:
        logger.info(
            "admin revoke: PathwayEntitlement %s already revoked at %s — no-op",
            ent.id, ent.revoked_at,
        )
        return RevokeAccessResult(
            id=ent.id,
            kind="pathway_entitlement",
            status=ent.status.value if hasattr(ent.status, "value") else str(ent.status),
            revoked_at=ent.revoked_at,
            revoked_by_user_id=ent.revoked_by_user_id,
            already_revoked=True,
            grant_records_revoked=0,
        )

    now = datetime.utcnow()
    ent.status = EntitlementStatus.revoked
    ent.revoked_at = now
    ent.revoked_by_user_id = admin.id
    ent.updated_at = now

    # Locate the anchoring pay-in-full transaction via the AccessPass
    # that fulfilment wrote against the same payment. Falls back to
    # the entitlement's own Stripe session/PI columns only if no
    # AccessPass points at it.
    anchoring_txn_id: str | None = None
    anchoring_pass = (
        db.query(AccessPass)
        .filter(
            AccessPass.pathway_entitlement_id == ent.id,
            AccessPass.payment_transaction_id.is_not(None),
        )
        .first()
    )
    if anchoring_pass is not None:
        anchoring_txn_id = anchoring_pass.payment_transaction_id

    grant_rows = _revoke_grant_records_by_txn(
        db,
        payment_transaction_id=anchoring_txn_id,
        reason=reason_text,
        now=now,
    )
    db.commit()
    db.refresh(ent)

    logger.info(
        "admin revoke: PathwayEntitlement %s revoked by admin=%s user=%s reason=%r",
        ent.id, admin.id, ent.user_id, reason_text,
    )
    return RevokeAccessResult(
        id=ent.id,
        kind="pathway_entitlement",
        status=ent.status.value if hasattr(ent.status, "value") else str(ent.status),
        revoked_at=ent.revoked_at,
        revoked_by_user_id=ent.revoked_by_user_id,
        already_revoked=False,
        grant_records_revoked=grant_rows,
    )


# ---------------------------------------------------------------------------
# Whole-purchase revoke — the canonical action
# ---------------------------------------------------------------------------


class RevokePurchaseResult(BaseModel):
    payment_transaction_id: str
    access_passes_revoked: int
    entitlements_revoked: int
    grant_records_revoked: int
    membership_removed: bool
    # Future confirmed EventBookings released back to capacity as
    # part of the revoke — deliberately excludes past / in-progress
    # sessions so historical attendance stays as history. Zero on
    # idempotent second calls or when the purchase never granted a
    # pass that a booking was consumed against.
    future_bookings_released: int
    already_revoked: bool


def _user_has_other_active_grant_in_space(
    db: Session, *,
    user_id: str,
    space_id: str,
    excluding_txn_id: str,
) -> bool:
    """Any active ``AccessGrantRecord`` for this user against a
    target that lives in this space, from a source other than the
    txn being revoked?

    "Target lives in this space" is resolved by joining through the
    target row (``target_pathway_id`` → ``pathways.space_id``, or
    ``target_series_id`` → ``event_series.space_id``). Restricts the
    overlap check to grants that actually would still let the buyer
    do something in the collective — a grant for a different
    collective doesn't preserve this membership.
    """
    from app.models.platform import EventSeries, Pathway

    pathway_hit = (
        db.query(AccessGrantRecord.id)
        .join(Pathway, Pathway.id == AccessGrantRecord.target_pathway_id)
        .filter(
            AccessGrantRecord.user_id == user_id,
            AccessGrantRecord.revoked_at.is_(None),
            AccessGrantRecord.source_payment_transaction_id != excluding_txn_id,
            Pathway.space_id == space_id,
        )
        .first()
    )
    if pathway_hit:
        return True
    series_hit = (
        db.query(AccessGrantRecord.id)
        .join(EventSeries, EventSeries.id == AccessGrantRecord.target_series_id)
        .filter(
            AccessGrantRecord.user_id == user_id,
            AccessGrantRecord.revoked_at.is_(None),
            AccessGrantRecord.source_payment_transaction_id != excluding_txn_id,
            EventSeries.space_id == space_id,
        )
        .first()
    )
    return series_hit is not None


@router.post(
    "/payment-transactions/{txn_id}/revoke",
    response_model=RevokePurchaseResult,
)
def revoke_purchase(
    txn_id: str,
    body: RevokeAccessRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> RevokePurchaseResult:
    """Revoke every piece of access created by one purchase.

    Scope:

    1. Every ``AccessPass`` where ``payment_transaction_id == txn_id``
       is flipped to ``cancelled`` with audit stamps.
    2. Every ``PathwayEntitlement`` reachable via those passes
       (``AccessPass.pathway_entitlement_id``) is flipped to
       ``revoked`` with audit stamps.
    3. Every ``AccessGrantRecord`` whose
       ``source_payment_transaction_id == txn_id`` is marked revoked.
    4. The buyer's ``SpaceMembership`` is flipped to ``removed`` only
       when no other active AGR remains for the buyer against a
       pathway or series inside the same space — so a revoke on one
       purchase never wipes access another purchase or a manual
       grant is still providing.

    Errors:

    * 404 — no such txn.
    * 409 — txn is anchored to a ``purchase_plan_id`` (finite-plan
      cancel flow is separate).
    * 200 — either revoked in this call, or already revoked
      (``already_revoked=True`` — no rows were touched).
    """
    txn: PaymentTransaction | None = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.id == txn_id)
        .with_for_update()
        .first()
    )
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment transaction not found.",
        )
    if txn.purchase_plan_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This transaction belongs to a finite payment plan. "
                "Cancel the plan through the finite-plan lifecycle flow; "
                "do not revoke the purchase directly."
            ),
        )
    if txn.payer_user_id is None or txn.space_id is None:
        # Defensive — every real member purchase carries both.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This transaction is missing payer_user_id or space_id and "
                "cannot be revoked through this endpoint."
            ),
        )

    reason_text = (body.reason or "").strip() or "admin_revoke_purchase"
    now = datetime.utcnow()

    access_passes = (
        db.query(AccessPass)
        .filter(AccessPass.payment_transaction_id == txn.id)
        .all()
    )
    entitlement_ids: set[str] = {
        ap.pathway_entitlement_id for ap in access_passes
        if ap.pathway_entitlement_id is not None
    }

    passes_revoked = 0
    for ap in access_passes:
        if ap.status == AccessPassStatus.cancelled and ap.revoked_at is not None:
            continue
        ap.status = AccessPassStatus.cancelled
        ap.revoked_by_user_id = admin.id
        ap.revoked_at = now
        ap.updated_at = now
        passes_revoked += 1

    # Release future confirmed bookings that were consumed from
    # this purchase's AccessPasses back to gathering capacity. Past
    # or in-progress sessions (``Event.starts_at <= now``) are left
    # confirmed so historical attendance survives.
    #
    # Deliberately no ``used_credits`` restoration — the pass is
    # being cancelled entirely; accounting on a cancelled pass is
    # inert and restoring would inflate a phantom balance on a
    # revoked entitlement.
    #
    # Idempotent: on a second admin call, ``revoked_pass_ids`` may
    # still be non-empty (the passes exist, just already cancelled),
    # but no future confirmed bookings will be linked to them, so
    # ``future_bookings_released`` returns 0.
    future_bookings_released = 0
    revoked_pass_ids = [ap.id for ap in access_passes]
    if revoked_pass_ids:
        future_bookings = (
            db.query(EventBooking)
            .join(Event, Event.id == EventBooking.event_id)
            .filter(
                EventBooking.access_pass_id.in_(revoked_pass_ids),
                EventBooking.status == BookingStatus.confirmed,
                Event.starts_at > now,
            )
            .all()
        )
        for booking in future_bookings:
            booking.status = BookingStatus.cancelled
            booking.cancelled_at = now
            future_bookings_released += 1

    entitlements_revoked = 0
    if entitlement_ids:
        ents = (
            db.query(PathwayEntitlement)
            .filter(PathwayEntitlement.id.in_(entitlement_ids))
            .all()
        )
        for ent in ents:
            if ent.status == EntitlementStatus.revoked and ent.revoked_at is not None:
                continue
            ent.status = EntitlementStatus.revoked
            ent.revoked_by_user_id = admin.id
            ent.revoked_at = now
            ent.updated_at = now
            entitlements_revoked += 1

    grant_records_revoked = _revoke_grant_records_by_txn(
        db,
        payment_transaction_id=txn.id,
        reason=reason_text,
        now=now,
    )

    # Idempotency signal — a second admin call touches zero rows
    # across every mutation surface, including the booking release.
    already_revoked = (
        passes_revoked == 0
        and entitlements_revoked == 0
        and grant_records_revoked == 0
        and future_bookings_released == 0
    )

    membership_removed = False
    if not already_revoked:
        # Only reconsider the SpaceMembership when we actually
        # revoked something on this pass. Source-aware: leave the
        # membership if any other active AGR keeps the buyer in
        # the space.
        has_other = _user_has_other_active_grant_in_space(
            db,
            user_id=txn.payer_user_id,
            space_id=txn.space_id,
            excluding_txn_id=txn.id,
        )
        if not has_other:
            membership = (
                db.query(SpaceMembership)
                .filter(
                    SpaceMembership.user_id == txn.payer_user_id,
                    SpaceMembership.space_id == txn.space_id,
                )
                .first()
            )
            # Only remove auto-joined purchase memberships. Do NOT
            # touch invited/joined/creator_owner/auto_role rows —
            # those represent a different intent.
            if (
                membership is not None
                and membership.status == SpaceMembershipStatus.active
                and membership.source == "purchase"
            ):
                membership.status = SpaceMembershipStatus.removed
                membership_removed = True

    db.commit()

    logger.info(
        "admin revoke: purchase txn=%s revoked by admin=%s user=%s space=%s "
        "passes=%d entitlements=%d agr=%d future_bookings_released=%d "
        "membership_removed=%s reason=%r",
        txn.id, admin.id, txn.payer_user_id, txn.space_id,
        passes_revoked, entitlements_revoked, grant_records_revoked,
        future_bookings_released, membership_removed, reason_text,
    )
    return RevokePurchaseResult(
        payment_transaction_id=txn.id,
        access_passes_revoked=passes_revoked,
        entitlements_revoked=entitlements_revoked,
        grant_records_revoked=grant_records_revoked,
        membership_removed=membership_removed,
        future_bookings_released=future_bookings_released,
        already_revoked=already_revoked,
    )
