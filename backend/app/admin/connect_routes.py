"""Admin endpoints for switching a creator's sales over to Connect.

    GET  /api/admin/creators/{user_id}/stripe-connect          readiness
    POST /api/admin/creators/{user_id}/stripe-connect/enable   route their sales
    POST /api/admin/creators/{user_id}/stripe-connect/disable  stop routing new ones

This is the only way ``connect_payouts_enabled_at`` is ever set, and it is an
administrative act on purpose. Onboarding completing does not do it. A webhook
reporting a capability active does not do it. A creator acknowledging the fee
model does not do it. Stripe saying an account is ready is an input to the
decision, never the decision.

Five conditions must hold, and the readiness endpoint lists every one that does
not so an admin can see the whole picture before acting. Two of them —
``payouts_enabled`` and the fee acknowledgement — are also CHECK constraints on
the table, so even a future caller that bypasses this router cannot produce an
unsafe row.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.user import User
from app.services import connect_routing_enablement as enablement

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/creators", tags=["admin-stripe-connect"])


class ConnectReadinessResponse(BaseModel):
    creator_user_id: str
    stripe_mode: str
    #: Whether every condition for enabling routing holds.
    ready_to_enable: bool
    #: Machine-readable reasons it does not. Empty when ready.
    blockers: list[str]

    onboarding_state: str | None = None
    payouts_status: str | None = None
    payouts_enabled: bool = False
    has_stripe_account: bool = False
    fee_disclosure_acknowledged: bool = False
    fee_disclosure_version: str | None = None
    #: Non-null when this creator's sales already route through Connect.
    routing_enabled_at: str | None = None


def _readiness(db: Session, creator_user_id: str) -> ConnectReadinessResponse:
    from app.core.config import settings

    account = enablement.find_account(db, creator_user_id=creator_user_id)
    assessment = enablement.assess(account)
    return ConnectReadinessResponse(
        creator_user_id=creator_user_id,
        stripe_mode=settings.stripe_mode,
        ready_to_enable=assessment.ready,
        blockers=assessment.blockers,
        onboarding_state=account.onboarding_state if account else None,
        payouts_status=account.payouts_status if account else None,
        payouts_enabled=bool(account and account.payouts_enabled),
        has_stripe_account=bool(account and account.stripe_account_id),
        fee_disclosure_acknowledged=bool(
            account and account.fee_disclosure_acknowledged_at is not None
        ),
        fee_disclosure_version=account.fee_disclosure_version if account else None,
        routing_enabled_at=(
            account.connect_payouts_enabled_at.isoformat()
            if account and account.connect_payouts_enabled_at else None
        ),
    )


@router.get(
    "/{creator_user_id}/stripe-connect", response_model=ConnectReadinessResponse,
)
def get_connect_readiness(
    creator_user_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> ConnectReadinessResponse:
    """Whether this creator could be switched over, and what is missing."""
    return _readiness(db, creator_user_id)


@router.post(
    "/{creator_user_id}/stripe-connect/enable",
    response_model=ConnectReadinessResponse,
)
def enable_connect_routing(
    creator_user_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> ConnectReadinessResponse:
    """Route this creator's **future** sales through Connect.

    Purchases and plans already created keep the payout model they were
    snapshotted with, so nothing in flight changes path.
    """
    try:
        enablement.enable_routing(
            db, creator_user_id=creator_user_id, enabled_by_user_id=admin.id,
        )
    except enablement.RoutingEnablementError as exc:
        # 409 with the machine-readable reason, so the caller can say which
        # condition is missing rather than "not allowed".
        raise HTTPException(
            status_code=409, detail={"reason": exc.reason, "message": str(exc)},
        ) from exc
    return _readiness(db, creator_user_id)


@router.post(
    "/{creator_user_id}/stripe-connect/disable",
    response_model=ConnectReadinessResponse,
)
def disable_connect_routing(
    creator_user_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> ConnectReadinessResponse:
    """Stop routing this creator's future sales through Connect.

    Leaves everything already in flight alone: a transfer already owed is still
    owed, and reversing the decision retrospectively would leave a creator paid
    by neither route.
    """
    try:
        enablement.disable_routing(
            db, creator_user_id=creator_user_id, disabled_by_user_id=admin.id,
        )
    except enablement.RoutingEnablementError as exc:
        raise HTTPException(
            status_code=409, detail={"reason": exc.reason, "message": str(exc)},
        ) from exc
    return _readiness(db, creator_user_id)
