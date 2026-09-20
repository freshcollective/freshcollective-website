"""What a member is actually being asked to pay.

One projection of a ``PaymentOptionSchedule``, shared by every member-
facing surface that offers a Payment Option for purchase — the Series
sidebar and the Collective joining doors.

It exists because the joining doors were first written to read
``override_total_cents`` / ``calculated_total_cents`` off the Option.
Those are authoring fields; in production they are frequently ``NULL``
because the commerce UI treats grants and schedules as the source of
truth, so every door rendered "No price set" while the real prices sat
on the schedules a click away. Two surfaces, two ideas of what a price
is, is the bug — so there is now one.

The commitment is always the schedule's, never the Option's:

* ``pay_in_full``            → ``total_amount_cents``
* ``recurring_installments`` → ``installment_amount_cents`` ×
  ``installment_count``, totalling ``total_amount_cents``

``is_member_checkoutable`` comes from the same predicate the checkout
endpoint enforces, so a surface can never advertise a schedule the
backend would refuse.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.payment_option import PaymentOption
from app.models.payment_option_schedule import PaymentOptionSchedule


def published_schedules_by_option(
    db: Session, option_ids: list[str],
) -> dict[str, list[PaymentOptionSchedule]]:
    """Published schedules for these Options, in creator order."""
    out: dict[str, list[PaymentOptionSchedule]] = {}
    if not option_ids:
        return out
    rows = (
        db.query(PaymentOptionSchedule)
        .filter(
            PaymentOptionSchedule.payment_option_id.in_(option_ids),
            PaymentOptionSchedule.status == "published",
        )
        .order_by(
            PaymentOptionSchedule.position, PaymentOptionSchedule.created_at,
        )
        .all()
    )
    for s in rows:
        out.setdefault(s.payment_option_id, []).append(s)
    return out


def schedule_view(
    schedule: PaymentOptionSchedule, option: PaymentOption,
) -> dict:
    """The member-facing shape of one payment method.

    Matches ``MemberPaymentOptionScheduleOut`` field for field so both
    surfaces can be rendered by the same client component.
    """
    # Imported here: ``spaces.routes`` imports this module's callers,
    # and the predicate lives there beside the checkout guards.
    from app.spaces.routes import _schedule_is_member_checkoutable

    return {
        "id": schedule.id,
        "name": schedule.name,
        "schedule_type": schedule.schedule_type,
        "total_amount_cents": schedule.total_amount_cents or 0,
        "installment_amount_cents": schedule.installment_amount_cents,
        "installment_count": schedule.installment_count,
        # Prefer the human ``interval``; fall back to
        # ``stripe_interval`` so the client's cadence formatter says
        # "weekly" rather than the generic "recurring".
        "interval": schedule.interval or schedule.stripe_interval,
        "currency": schedule.currency or "AUD",
        "is_member_checkoutable": _schedule_is_member_checkoutable(
            schedule, option,
        ),
    }


def headline_price_cents(
    schedules: list[dict], option: PaymentOption,
) -> int | None:
    """The single number to show beside an Option's name.

    The pay-in-full total where one is offered, because that is the
    commitment most people compare on; otherwise the total of the
    cheapest checkoutable plan. Falls back to the Option's own
    ``effective_price_cents`` only when no schedule can describe the
    price at all — a shape that should not occur for a purchasable
    Option, but which must degrade to a number rather than to silence.
    """
    checkoutable = [s for s in schedules if s["is_member_checkoutable"]]
    pay_in_full = [
        s for s in checkoutable if s["schedule_type"] == "pay_in_full"
    ]
    if pay_in_full:
        return pay_in_full[0]["total_amount_cents"]
    if checkoutable:
        return min(s["total_amount_cents"] for s in checkoutable)
    return option.effective_price_cents
