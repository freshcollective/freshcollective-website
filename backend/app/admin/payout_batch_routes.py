"""Admin endpoints for manual creator payout batches.

* ``GET  /api/admin/creator-payout-batches/payable`` — summary of what
  Fresh Collective currently owes a specific creator in a currency.
* ``POST /api/admin/creator-payout-batches`` — record a manual payout
  (bank/SEPA transfer) that has already been done. Atomic. Snapshots
  the total; individual transaction membership is recorded in
  ``creator_payout_batch_items``.
* ``POST /api/admin/creator-payout-batches/{id}/cancel`` — correct
  Fresh Collective's internal record. Never reverses a bank transfer.
* ``GET  /api/admin/creator-payout-batches`` — list batches for
  operational review (filterable by creator/status).

All endpoints require ``get_admin_user``.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.creator_payout_batch import (
    CreatorPayoutBatch,
    CreatorPayoutBatchItem,
    CreatorPayoutBatchStatus,
)
from app.models.user import User
from app.services import payout_batch_orchestration as _pbo


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/admin", tags=["admin", "payouts"])


class PayableSummaryResponse(BaseModel):
    creator_user_id: str
    currency: str
    payable_cents: int
    transaction_count: int


class CreateBatchRequest(BaseModel):
    creator_user_id: str = Field(..., min_length=1)
    currency: str = Field(..., min_length=3, max_length=3)
    reference: str = Field(..., min_length=1, max_length=200)
    submitted_total_cents: int = Field(..., ge=0)
    paid_at: datetime
    note: str | None = Field(default=None, max_length=1000)


class CreateBatchResponse(BaseModel):
    batch_id: str
    creator_user_id: str
    currency: str
    total_amount_cents: int
    transaction_count: int
    included_transaction_ids: list[str]


class CancelBatchRequest(BaseModel):
    cancellation_reason: str = Field(..., min_length=1, max_length=500)
    revert_transactions: bool = Field(default=False)


class CancelBatchResponse(BaseModel):
    batch_id: str
    already_cancelled: bool
    reverted_transaction_ids: list[str]


class BatchListRow(BaseModel):
    id: str
    creator_user_id: str
    currency: str
    total_amount_cents: int
    transaction_count: int
    reference: str
    note: str | None
    status: str
    created_at: datetime
    paid_at: datetime
    cancelled_at: datetime | None
    cancellation_reason: str | None


@router.get(
    "/creator-payout-batches/payable",
    response_model=PayableSummaryResponse,
)
def get_payable_summary(
    creator_user_id: str = Query(..., min_length=1),
    currency: str = Query(..., min_length=3, max_length=3),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> PayableSummaryResponse:
    summary = _pbo.compute_payable_summary(
        db,
        creator_user_id=creator_user_id,
        currency=currency,
    )
    return PayableSummaryResponse(
        creator_user_id=creator_user_id,
        currency=currency.upper(),
        payable_cents=summary["payable_cents"],
        transaction_count=summary["transaction_count"],
    )


@router.post(
    "/creator-payout-batches",
    response_model=CreateBatchResponse,
)
def create_payout_batch(
    body: CreateBatchRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CreateBatchResponse:
    creator = db.query(User).filter(User.id == body.creator_user_id).first()
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found.")

    try:
        outcome = _pbo.create_payout_batch(
            db,
            creator=creator,
            currency=body.currency,
            reference=body.reference,
            paid_at=body.paid_at,
            submitted_total_cents=body.submitted_total_cents,
            note=body.note,
            created_by=admin,
        )
    except _pbo.PayoutBatchStalenessError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "The payable amount changed between when you loaded the "
                "page and when you submitted. Refresh and try again. "
                f"({exc})"
            ),
        )
    except _pbo.PayoutBatchNoEligibleError:
        raise HTTPException(
            status_code=409,
            detail="No eligible transactions for this creator and currency.",
        )

    return CreateBatchResponse(
        batch_id=outcome.batch_id,
        creator_user_id=outcome.creator_user_id,
        currency=outcome.currency,
        total_amount_cents=outcome.total_amount_cents,
        transaction_count=outcome.transaction_count,
        included_transaction_ids=outcome.included_transaction_ids,
    )


@router.post(
    "/creator-payout-batches/{batch_id}/cancel",
    response_model=CancelBatchResponse,
)
def cancel_payout_batch(
    batch_id: str,
    body: CancelBatchRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> CancelBatchResponse:
    batch = (
        db.query(CreatorPayoutBatch)
        .filter(CreatorPayoutBatch.id == batch_id)
        .with_for_update()
        .first()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Payout batch not found.")

    outcome = _pbo.cancel_payout_batch(
        db,
        batch=batch,
        cancelled_by=admin,
        cancellation_reason=body.cancellation_reason,
        revert_transactions=body.revert_transactions,
    )
    return CancelBatchResponse(
        batch_id=outcome.batch_id,
        already_cancelled=outcome.already_cancelled,
        reverted_transaction_ids=outcome.reverted_transaction_ids,
    )


@router.get(
    "/creator-payout-batches",
    response_model=list[BatchListRow],
)
def list_payout_batches(
    creator_user_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[BatchListRow]:
    q = db.query(CreatorPayoutBatch)
    if creator_user_id:
        q = q.filter(CreatorPayoutBatch.creator_user_id == creator_user_id)
    if status_filter:
        try:
            status_enum = CreatorPayoutBatchStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown status.")
        q = q.filter(CreatorPayoutBatch.status == status_enum)
    batches = q.order_by(CreatorPayoutBatch.created_at.desc()).limit(limit).all()
    return [
        BatchListRow(
            id=b.id,
            creator_user_id=b.creator_user_id,
            currency=b.currency,
            total_amount_cents=b.total_amount_cents,
            transaction_count=b.transaction_count,
            reference=b.reference,
            note=b.note,
            status=b.status.value,
            created_at=b.created_at,
            paid_at=b.paid_at,
            cancelled_at=b.cancelled_at,
            cancellation_reason=b.cancellation_reason,
        )
        for b in batches
    ]
