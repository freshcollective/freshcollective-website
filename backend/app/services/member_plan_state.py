"""FIP4B1 — shared helper: does this member have a finite payment
plan that needs their attention for THIS pathway / series?

Called from every member-facing surface that could otherwise
render a standard purchase CTA for a resource the viewer already
has a live-but-troubled finite-plan agreement over. The helper
answers "which plan?" — the caller builds the ``MemberPlanState``
response object from that plan.

Design notes:

* Per-viewer only. Never invoked for anonymous callers.
* Considers plans whose PaymentOption grants the target resource,
  via either the modern ``PaymentOptionGrant`` rows OR the legacy
  attaches_to / grants_pathway_id fields.
* Returns the FIRST matching plan whose status is in
  ``('payment_problem', 'suspended')``. In practice Rule D
  guarantees at most one such plan per (member, option) — but the
  helper takes the highest-severity match (``suspended`` before
  ``payment_problem``) if multiple options with grant overlap
  somehow coexist.
* Does NOT expose provider ids. Callers should shape their
  response using ``MemberPlanState`` only.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.models.payment_option_grant import (
    GRANT_KIND_EVENT_SERIES, GRANT_KIND_PATHWAY,
)
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.user import User


_RECOVERY_STATUSES = (
    PurchasePlanStatus.payment_problem,
    PurchasePlanStatus.suspended,
)


def _plan_grants_pathway(plan_option: PaymentOption, pathway_id: str) -> bool:
    """Does this Payment Option grant this specific pathway?"""
    # Modern grant rows
    for g in (plan_option.grants or []):
        if g.grant_kind == GRANT_KIND_PATHWAY and g.pathway_id == pathway_id:
            return True
    # Legacy shadow fields
    if plan_option.grants_pathway_id == pathway_id:
        return True
    if plan_option.attaches_to_kind == "pathway" and plan_option.attaches_to_id == pathway_id:
        return True
    return False


def _plan_grants_series(plan_option: PaymentOption, series_id: str) -> bool:
    """Does this Payment Option grant this specific event series?"""
    for g in (plan_option.grants or []):
        if g.grant_kind == GRANT_KIND_EVENT_SERIES and g.series_id == series_id:
            return True
    if plan_option.attaches_to_kind == "event_series" and plan_option.attaches_to_id == series_id:
        return True
    return False


def find_recovery_plan_for_pathway(
    db: Session, *, user: User, pathway_id: str,
) -> PurchasePlan | None:
    """Return the member's PurchasePlan that needs attention AND
    grants this pathway (or None). Suspended plans are returned in
    preference to payment_problem ones — the more urgent state
    wins if both somehow coexist."""
    return _find_recovery_plan(db, user=user, pathway_id=pathway_id)


def find_recovery_plan_for_series(
    db: Session, *, user: User, series_id: str,
) -> PurchasePlan | None:
    """Series equivalent of ``find_recovery_plan_for_pathway``."""
    return _find_recovery_plan(db, user=user, series_id=series_id)


def _find_recovery_plan(
    db: Session, *,
    user: User,
    pathway_id: str | None = None,
    series_id: str | None = None,
) -> PurchasePlan | None:
    if pathway_id is None and series_id is None:
        raise ValueError("_find_recovery_plan: pathway_id or series_id required")
    plans = (
        db.query(PurchasePlan)
        .filter(
            PurchasePlan.member_user_id == user.id,
            PurchasePlan.status.in_(_RECOVERY_STATUSES),
        )
        .all()
    )
    if not plans:
        return None

    matched: list[PurchasePlan] = []
    for p in plans:
        po = (
            db.query(PaymentOption)
            .filter(PaymentOption.id == p.payment_option_id)
            .first()
        )
        if po is None:
            continue
        if pathway_id and _plan_grants_pathway(po, pathway_id):
            matched.append(p)
        elif series_id and _plan_grants_series(po, series_id):
            matched.append(p)

    if not matched:
        return None
    # Suspended wins over payment_problem so the more urgent
    # message + stronger CTA-suppression fires when both coexist.
    matched.sort(
        key=lambda p: 0 if p.status == PurchasePlanStatus.suspended else 1,
    )
    return matched[0]


def build_member_plan_state(db: Session, plan: PurchasePlan):
    """Compose the wire-shape MemberPlanState from a plan row.
    Import kept local to avoid a schema→services cycle."""
    from app.spaces.schemas import MemberPlanState
    po = (
        db.query(PaymentOption)
        .filter(PaymentOption.id == plan.payment_option_id)
        .first()
    )
    return MemberPlanState(
        status=plan.status.value,
        payment_option_name=po.name if po else None,
        installments_paid=plan.installments_paid,
        installments_expected=plan.installments_expected,
        grace_expires_at=plan.grace_expires_at,
        suspended_at=plan.suspended_at,
        recovery_required=True,
    )
