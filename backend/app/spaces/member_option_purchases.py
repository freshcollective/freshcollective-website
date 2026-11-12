"""What the viewer has already bought, for the Ways to Join cards.

Why this exists
---------------
A Payment Option the member had already purchased carried a correct
"You've purchased this" banner and, directly beneath it, "Purchase Test
Gathering Experience" and "Start payment plan". The banner came from
Stage 4B's booking attribution; the buttons came from the catalogue,
which has never known anything about the viewer.

So this module answers the viewer-shaped question the cards actually
need: *have I bought this Option, and on what terms?*

Two things it is careful not to do.

**It does not invent a repurchase rule.** Whether a second purchase is
allowed is already decided by ``checkout_orchestration``'s Rules A-D,
and the till enforces them with a 409. This reads the same predicate —
``find_same_option_hold`` — so a button disappears exactly when it would
have been refused, and stays when a repurchase is legitimate. A
completed, cancelled, failed or suspended plan is deliberately absent
from Rule D, so none of those suppresses checkout here either.

**It does not re-price anything.** An active plan's figures come from
the ``PurchasePlan`` row the member agreed to — discounted instalments
included — never from the Option's current price or the code's current
definition. The creator may have edited both since, and a plan is an
agreement, not a view of today's catalogue. ``paid_amount_cents`` uses
the same accounting rule as the creator surface: the contractual sum of
the plan's succeeded transactions.

Read-only, and strictly scoped to one viewer. Nothing here reads
another member's rows, and every caller passes the authenticated user.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.payment import (
    PaymentTransaction, PaymentTransactionStatus,
)
from app.models.payment_option import PaymentOption
from app.models.purchase_plan import PurchasePlan, PurchasePlanStatus
from app.models.user import User
from app.services.checkout_orchestration import find_same_option_hold

#: Plan statuses that still represent a live arrangement, in the order
#: a card should prefer them when a member has more than one plan on
#: one Option. Mirrors Rule D plus ``suspended`` — which does not block
#: repurchase but is certainly the plan the member is living with, and
#: must not be described as finished.
_LIVE_ORDER = (
    PurchasePlanStatus.active,
    PurchasePlanStatus.payment_problem,
    PurchasePlanStatus.suspended,
    PurchasePlanStatus.pending_setup,
)


@dataclass(frozen=True)
class PlanSummary:
    """The member's own agreement, as agreed — not as repriced today."""

    status: str
    currency: str
    #: The instalment figures the member accepted. ``final_cents``
    #: differs only on an uneven discounted plan, where the remainder
    #: rides on the last payment.
    installment_amount_cents: int
    final_installment_amount_cents: int | None
    installments_expected: int
    installments_paid: int
    total_expected_cents: int
    paid_amount_cents: int
    remaining_amount_cents: int
    interval: str | None
    interval_count: int | None
    #: Which of the Option's arrangements this plan is, so the card can
    #: show the one they chose rather than the first on offer.
    payment_option_schedule_id: str | None

    def as_payload(self) -> dict:
        return {
            "status": self.status,
            "currency": self.currency,
            "installment_amount_cents": self.installment_amount_cents,
            "final_installment_amount_cents": self.final_installment_amount_cents,
            "installments_expected": self.installments_expected,
            "installments_paid": self.installments_paid,
            "total_expected_cents": self.total_expected_cents,
            "paid_amount_cents": self.paid_amount_cents,
            "remaining_amount_cents": self.remaining_amount_cents,
            "interval": self.interval,
            "interval_count": self.interval_count,
            "payment_option_schedule_id": self.payment_option_schedule_id,
        }


@dataclass(frozen=True)
class OptionPurchase:
    """The viewer's standing with one Payment Option."""

    payment_option_id: str
    #: ``plan`` when a finite arrangement is in play, ``pay_in_full``
    #: when access came from a single settled purchase.
    kind: str
    #: True when checkout for this Option would be refused today. The
    #: card hides its buy buttons on exactly this signal, so the UI and
    #: the till cannot disagree about whether buying again is possible.
    blocks_repurchase: bool
    plan: PlanSummary | None = None

    def as_payload(self) -> dict:
        return {
            "payment_option_id": self.payment_option_id,
            "kind": self.kind,
            "blocks_repurchase": self.blocks_repurchase,
            "plan": self.plan.as_payload() if self.plan else None,
        }


def _pick_plan(plans: list[PurchasePlan]) -> PurchasePlan | None:
    """The plan this member is actually living with.

    An Option can carry several arrangements and a member can have more
    than one plan row against it over time — a retry after abandonment,
    a cancelled term followed by a fresh one. A live arrangement always
    wins over a finished one, and the most recent wins within a band,
    so the card never describes last term's cancelled plan as the
    member's agreement.
    """
    if not plans:
        return None
    for status in _LIVE_ORDER:
        band = [p for p in plans if p.status == status]
        if band:
            return max(band, key=lambda p: p.created_at)
    return max(plans, key=lambda p: p.created_at)


def _plan_summary(db: Session, plan: PurchasePlan) -> PlanSummary:
    paid = (
        db.query(func.coalesce(func.sum(PaymentTransaction.gross_amount_cents), 0))
        .filter(
            PaymentTransaction.purchase_plan_id == plan.id,
            PaymentTransaction.status == PaymentTransactionStatus.succeeded,
        )
        .scalar()
    ) or 0
    paid = int(paid)
    total = int(plan.total_expected_cents)
    return PlanSummary(
        status=plan.status.value if hasattr(plan.status, "value") else plan.status,
        currency=plan.currency,
        installment_amount_cents=int(plan.installment_amount_cents),
        final_installment_amount_cents=(
            int(plan.final_installment_amount_cents)
            if plan.final_installment_amount_cents is not None else None
        ),
        installments_expected=int(plan.installments_expected),
        installments_paid=int(plan.installments_paid),
        total_expected_cents=total,
        paid_amount_cents=paid,
        remaining_amount_cents=max(total - paid, 0),
        interval=plan.stripe_interval,
        interval_count=plan.stripe_interval_count,
        payment_option_schedule_id=plan.payment_option_schedule_id,
    )


def purchases_for_options(
    db: Session, *,
    user: User | None,
    payment_option_ids: list[str],
    now: datetime,
) -> list[OptionPurchase]:
    """The viewer's standing with each of these Options.

    Returns an entry only where there is something to say: a live or
    historical plan, or an existing purchase that bars buying again.
    Options the viewer has never bought are simply absent, so a card
    with no entry renders exactly as it did before.

    ``user`` of ``None`` returns nothing at all — a signed-out reader
    has no purchases, and this must never be answerable about somebody
    else.
    """
    if user is None or not payment_option_ids:
        return []

    options = (
        db.query(PaymentOption)
        .filter(PaymentOption.id.in_(payment_option_ids))
        .all()
    )
    plans_by_option: dict[str, list[PurchasePlan]] = {}
    for plan in (
        db.query(PurchasePlan)
        .filter(
            PurchasePlan.member_user_id == user.id,
            PurchasePlan.payment_option_id.in_(payment_option_ids),
        )
        .all()
    ):
        plans_by_option.setdefault(plan.payment_option_id, []).append(plan)

    out: list[OptionPurchase] = []
    for option in options:
        hold = find_same_option_hold(
            db, user=user, payment_option=option, now=now,
        )
        plan = _pick_plan(plans_by_option.get(option.id, []))
        if hold is None and plan is None:
            continue
        # A plan describes the arrangement; a pass or entitlement hold
        # with no plan behind it is a purchase settled in one go.
        kind = "plan" if plan is not None else "pay_in_full"
        out.append(OptionPurchase(
            payment_option_id=option.id,
            kind=kind,
            blocks_repurchase=hold is not None,
            plan=_plan_summary(db, plan) if plan is not None else None,
        ))
    return out


def held_option_ids_in_space(
    db: Session, *,
    user: User | None,
    space_id: str,
    now: datetime,
) -> set[str]:
    """Options in this Collective the viewer already holds.

    The same verdict as :func:`purchases_for_options`, keyed by id, for
    callers that decide which cards to offer before they know which
    Options they are about to render. Empty for a signed-out reader.
    """
    if user is None:
        return set()
    option_ids = [
        row[0] for row in
        db.query(PaymentOption.id)
        .filter(PaymentOption.space_id == space_id)
        .all()
    ]
    return {
        pur.payment_option_id
        for pur in purchases_for_options(
            db, user=user, payment_option_ids=option_ids, now=now,
        )
        if pur.blocks_repurchase
    }
