"""Self-serve activation of the free Community plan.

Why this module exists
----------------------
Until now every route into Creator capability was operator-driven or
paid: :func:`app.creator.plan_activation.activate_creator_plan` accepts
only ``source='manual_grant'`` (admin UI) or ``source='stripe_paid'``
(a completed Stripe purchase). The public Community Collective page
advertised a free self-serve start with nothing behind it.

This endpoint is that missing door, and it is deliberately thin.

Why it does NOT write a CreatorSubscription row
-----------------------------------------------
It would be tempting to call ``activate_creator_plan(..., 'community')``
and be done. That would break the free → paid upgrade path:

``activate_creator_plan`` raises ``ActivationConflictError`` when the
user already holds an active subscription for a *different* plan, and
no caller cancels first — ``app/purchases/claim.py`` activates straight
from the Stripe claim and ``app/purchases/routes.py`` surfaces the
conflict as an error. A Community row written here would therefore make
the user's later Creator/Pro purchase fail *after* they had paid.

It is also unnecessary. ``plan_guards.resolve_creator_plan`` already
falls back to the cheapest active ``CreatorPlan`` when a creator has no
subscription row, and Community ($0, seeded active by migration 068) is
that plan. ``effective_collective_allowance`` documents this as the
intended steady state: "every creator falls back to the cheapest active
plan via resolve_creator_plan".

So the free plan needs no row of its own. Promoting the role is the
entire activation, and every Community limit is then enforced by the
existing guards. Buying a paid plan later writes the first subscription
row and takes over plan resolution naturally.

What it does provide
--------------------
``promote_to_creator`` is idempotent and reconciles the World Builders
auto-role membership, so repeat calls heal drift rather than duplicating
anything. Verification is required: creating the Collective this unlocks
is a creator mutation behind ``get_verified_creator_user`` anyway, so
gating here keeps the funnel honest instead of handing someone a role
that dead-ends at the first write.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter
from sqlalchemy.orm import Session

from app.admin.service import promote_to_creator
from app.auth.dependencies import get_verified_current_user
from app.core.database import get_db
from app.core.rate_limit import client_ip_for_rate_limit
from app.creator.plan_guards import resolve_creator_plan
from app.models.user import User

limiter = Limiter(key_func=client_ip_for_rate_limit)

router = APIRouter(prefix="/api/creator/community", tags=["creator-community"])


class CommunityStartResponse(BaseModel):
    """Result of opening the free Community plan.

    ``already_creator`` lets the client distinguish a first activation
    from an idempotent repeat without inspecting roles itself.
    ``plan_slug`` is the plan the guards resolved *after* promotion, so
    the client reports what the backend will actually enforce rather
    than assuming 'community'.
    """
    started: bool
    already_creator: bool
    plan_slug: str | None
    next: str


@router.post("/start", response_model=CommunityStartResponse, status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def start_community_plan(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> CommunityStartResponse:
    """Give the signed-in, email-verified user free Creator capability.

    Idempotent. A Platform Owner (``role='admin'``) is left untouched —
    ``promote_to_creator`` never downgrades admin, and an owner already
    outranks every creator plan.
    """
    already_creator = current_user.role != "user"

    # Pre-flight: confirm the guards will actually resolve a plan before
    # handing out the role. ``resolve_creator_plan`` reaches Community via
    # the cheapest-active-plan fallback, which depends on the
    # ``creator_plans`` row seeded by migration 068 being present and
    # active. If that row were ever missing or deactivated,
    # ``guard_active_collective_limit`` would refuse the very first
    # Collective with "contact support" — a dead-end *after* we had told
    # the visitor they were set up. Refuse here instead, loudly and
    # diagnosably, so the failure lands before the promise.
    #
    # Platform Owners legitimately resolve to no plan, so they skip this.
    if current_user.role != "admin":
        if resolve_creator_plan(current_user, db) is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Free Collectives are temporarily unavailable. Nothing has "
                    "been changed on your account — please try again shortly."
                ),
            )

    promote_to_creator(current_user, db)
    db.commit()
    db.refresh(current_user)

    plan = resolve_creator_plan(current_user, db)

    return CommunityStartResponse(
        started=True,
        already_creator=already_creator,
        plan_slug=plan.slug if plan else None,
        next="/creator-onboarding",
    )
