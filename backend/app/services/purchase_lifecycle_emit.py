"""Purchase / payment-plan lifecycle emit helpers (R3).

One module owns the shared resolution logic (member-facing experience
name + primary member URL + repair URL) and the five emits R3
introduces. Domain services (webhook handlers, ``finite_plan_lifecycle``)
call these helpers immediately after the state transition they own has
been recorded on the session but before commit — matching the R2A/R2B
pattern where the emit is transactional with the domain change and the
caller schedules routing after commit.

Never raises out. Any comms failure (unknown event, resolver errors,
etc.) is caught and logged so a payment/access lifecycle transition is
never blocked by a downstream communication failure. Product lifecycle
is authoritative; comms is downstream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.models.platform import EventSeries, Pathway, Space
from app.models.purchase_plan import PurchasePlan
from app.models.user import User

if TYPE_CHECKING:
    from app.comms.models import CommunicationEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PurchaseCommsContext:
    """Fields common to every R3 email/in-app payload.

    ``member_url`` is the primary post-purchase / post-recovery
    destination — deep-linked to the affected experience where a
    single primary destination is honest, or ``/dashboard`` when the
    payment option grants multiple experiences with no honest single
    landing. See A4 in R3 audit.

    ``repair_url`` is the deep-link to the affected experience whose
    ``PlanRecoveryBanner`` / ``RepairPaymentCta`` starts the
    authenticated repair flow. Falls back to ``/dashboard`` when the
    experience cannot be resolved. Only meaningful for failure /
    suspension events.
    """
    first_name: str
    experience_name: str
    member_url: str
    repair_url: str


def _first_name(user: User) -> str:
    if not user.name:
        return ""
    return user.name.strip().split(" ", 1)[0]


def _origin() -> str:
    from app.core.config import settings
    return settings.frontend_origin.rstrip("/")


def _member_url_for_option(db: Session, option: PaymentOption | None) -> str:
    """Deep-link to the member surface for the option's affected
    experience, or ``/dashboard`` when we can't honestly resolve one."""
    origin = _origin()
    fallback = f"{origin}/dashboard"
    if option is None or not option.attaches_to_id:
        return fallback

    space = db.query(Space).filter(Space.id == option.space_id).one_or_none()
    if space is None:
        return fallback
    kind = (option.attaches_to_kind or "").lower()
    if kind == "pathway":
        pw = db.query(Pathway).filter(Pathway.id == option.attaches_to_id).one_or_none()
        if pw is None:
            return fallback
        return f"{origin}/spaces/{space.slug}/pathways/{pw.slug}"
    if kind == "series":
        series = db.query(EventSeries).filter(EventSeries.id == option.attaches_to_id).one_or_none()
        if series is None:
            return fallback
        return f"{origin}/spaces/{space.slug}/gathering-series/{series.slug}"
    # Any other attach kind (future: standalone gathering bundle,
    # etc.) — fall back to dashboard rather than invent a URL.
    return fallback


def resolve_context(
    db: Session,
    *,
    user: User,
    payment_option: PaymentOption | None,
) -> PurchaseCommsContext:
    experience_name = ""
    if payment_option is not None and payment_option.name:
        experience_name = payment_option.name
    member_url = _member_url_for_option(db, payment_option)
    # R3 A5: repair CTA links to the affected experience (its existing
    # PlanRecoveryBanner starts the authenticated repair flow). Same URL
    # as ``member_url`` — no separate global "my plans" surface exists.
    repair_url = member_url
    return PurchaseCommsContext(
        first_name=_first_name(user),
        experience_name=experience_name,
        member_url=member_url,
        repair_url=repair_url,
    )


# ---------------------------------------------------------------------------
# Emit helpers — one per event
# ---------------------------------------------------------------------------


def _safe_emit(fn):
    """Decorator that logs+swallows any exception so a comms failure
    never propagates out to the payment/access lifecycle."""
    def _wrapped(*args, **kwargs) -> "CommunicationEvent | None":
        try:
            return fn(*args, **kwargs)
        except Exception:  # pragma: no cover — safety net
            logger.exception(
                "purchase_lifecycle_emit: %s raised; comms is downstream, "
                "payment/access lifecycle unaffected.",
                fn.__name__,
            )
            return None
    _wrapped.__name__ = fn.__name__
    _wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
    return _wrapped


@_safe_emit
def emit_purchase_completed(
    db: Session,
    *,
    user: User,
    payment_option: PaymentOption | None,
    payment_mode: str,           # 'single' | 'plan'
    amount_cents: int | None,
    currency: str | None,
    plan: PurchasePlan | None = None,
) -> "CommunicationEvent | None":
    """Emit for a single successful purchase or a FIP first-instalment.

    Idempotency contract: the caller has already confirmed this is the
    single fulfilment write (not a replay). For single-pay the caller
    checks ``txn.fulfilment_status``; for FIP first the caller checks
    ``plan.status == pending_setup`` and the invoice uniqueness index.
    """
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":      ctx.first_name,
        "experience_name": ctx.experience_name,
        "member_url":      ctx.member_url,
        "payment_mode":    payment_mode,
        "amount_cents":    amount_cents,
        "currency":        currency,
    }
    if plan is not None and payment_mode == "plan":
        payload["installments_paid"]     = plan.installments_paid
        payload["installments_expected"] = plan.installments_expected
    return comms_emit(
        db,
        event_type="purchase.completed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan" if plan else "payment_transaction",
        subject_id=plan.id if plan else None,
        payload=payload,
    )


@_safe_emit
def emit_instalment_failed(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
) -> "CommunicationEvent | None":
    """Emit on the ``active → payment_problem`` transition. Grace
    deadline (``plan.grace_expires_at``) carried in payload so the
    template can name the date without querying the plan again."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    grace_iso = plan.grace_expires_at.isoformat() if plan.grace_expires_at else None
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "repair_url":            ctx.repair_url,
        "amount_cents":          plan.installment_amount_cents,
        "currency":              plan.currency,
        "grace_expires_at":      grace_iso,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="payment.instalment_failed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )


@_safe_emit
def emit_access_suspended(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
) -> "CommunicationEvent | None":
    """Emit on the ``payment_problem → suspended`` transition."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "repair_url":            ctx.repair_url,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="access.suspended",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )


@_safe_emit
def emit_payment_recovered(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
    was_suspended: bool,
) -> "CommunicationEvent | None":
    """Emit on the ``{payment_problem, suspended} → active`` transition
    from a NON-final instalment. ``was_suspended`` distinguishes "access
    remains active" (grace recovery) from "access is active again"
    (post-suspension recovery)."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "was_suspended":         bool(was_suspended),
        "amount_cents":          plan.installment_amount_cents,
        "currency":              plan.currency,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="payment.recovered",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )


@_safe_emit
def emit_plan_completed(
    db: Session,
    *,
    user: User,
    plan: PurchasePlan,
    payment_option: PaymentOption | None,
) -> "CommunicationEvent | None":
    """Emit on the ``* → completed`` transition (final scheduled
    instalment lands). If completion also happened to recover from
    payment_problem/suspended, callers should suppress the
    ``payment.recovered`` emit — completion is the more meaningful
    member moment."""
    from app.comms import Source, emit as comms_emit
    ctx = resolve_context(db, user=user, payment_option=payment_option)
    payload = {
        "first_name":            ctx.first_name,
        "experience_name":       ctx.experience_name,
        "member_url":            ctx.member_url,
        "currency":              plan.currency,
        "total_paid_cents":      plan.total_expected_cents,
        "installments_paid":     plan.installments_paid,
        "installments_expected": plan.installments_expected,
    }
    return comms_emit(
        db,
        event_type="purchase.plan_completed",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="purchase_plan",
        subject_id=plan.id,
        context={"plan_id": plan.id},
        payload=payload,
    )
