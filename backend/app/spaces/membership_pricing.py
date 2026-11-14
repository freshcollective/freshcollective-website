"""Does belonging to this Collective have to be paid for?

Why this module exists
----------------------
``Space.pricing_type`` advertises a membership price.
``Space.join_policy`` decides whether the free Join button works. They
are independent columns, and ``POST /api/spaces/{slug}/join`` has only
ever read the second — so a Collective set to ``paid_monthly`` with the
default ``join_policy = 'open'`` advertises A$29/month and then admits
people for nothing. The model comment says as much: the pricing columns
are "display/config only; payment processing is separate."

Stage 5A closes that. This module is the question itself, kept in one
place and pure, so the join door, the About page and the eventual
checkout cannot hold different opinions about whether a Collective is
paid.

Pricing and joining stay distinct
---------------------------------
Deliberately **not** done here: rewriting ``join_policy``. The two
answer different questions — *what does it cost* and *who may ask* — and
a Collective may legitimately require both a fee and an invitation.
``paid_membership_required`` is therefore an additional condition on
joining, never a replacement for the policy, and never written to the
database. See ``join_policy`` for the other half.

Why enforcement is behind the billing flag
------------------------------------------
Refusing a free join is only honest once there is something to pay. One
flag — ``paid_collective_membership_enabled`` — governs **both** the
refusal here and the checkout that Stage 5A.1 adds, so the two cannot
diverge: the gate can never be live without a way to pay, and the
checkout can never be live while the free door is still open. With the
flag off, every Collective joins exactly as it does today.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Final

from app.core.config import settings

#: Pricing types that mean "membership costs money, on an ongoing or
#: one-off basis". ``invite_only`` is absent on purpose: it restricts who
#: may join, not what joining costs, and the invitation flow already
#: enforces it. ``coming_soon`` is absent too — it is retired, and it
#: never meant a price was collectable.
PAID_MEMBERSHIP_PRICING_TYPES: Final[frozenset[str]] = frozenset({
    "paid_monthly",
    "paid_annual",
    "paid_one_time",
})

#: Returned to the client when free joining is refused because
#: membership is paid. A stable string the UI can branch on without
#: parsing prose, matching ``join_policy.REASON_PURCHASE_REQUIRED``'s
#: convention.
REASON_MEMBERSHIP_PAYMENT_REQUIRED: Final = "join_membership_payment_required"


def is_paid_membership(pricing_type: object) -> bool:
    """Does this pricing type mean membership has to be paid for?

    Takes the raw stored value, so a legacy or unexpected string answers
    ``False`` rather than raising — this is read on a public page, and a
    surprise value should not break it.
    """
    return isinstance(pricing_type, str) and (
        pricing_type.strip() in PAID_MEMBERSHIP_PRICING_TYPES
    )


def billing_enabled() -> bool:
    """Is paid Collective membership switched on for this deployment?

    Read through a function rather than inlined at each call site so
    tests can monkeypatch one place, and so the flag's name appears once.
    """
    return bool(settings.paid_collective_membership_enabled)


def free_join_blocked_by_payment(pricing_type: object) -> bool:
    """Should free self-service joining be refused on payment grounds?

    True only when membership is paid **and** billing is live. Both
    halves matter: the first is the creator's choice, the second is
    whether this deployment can honour it. Answering True while no
    checkout exists would make a paid Collective unjoinable by any
    route, which is worse than the gap it closes.
    """
    return is_paid_membership(pricing_type) and billing_enabled()


# ---------------------------------------------------------------------------
# The transition date
# ---------------------------------------------------------------------------
#
# ``Space.paid_membership_effective_at`` is the moment belonging here
# starts having to be paid for. A creator chooses a *day*; the sweep
# needs an *instant*; the two are connected by the Collective's own
# timezone, exactly as a discount code's expiry is
# (``discount_pricing.resolve_expiry_instant``, whose shape these
# mirror deliberately).
#
# The difference from an expiry is which end of the day is meant. An
# expiry runs to the end of the chosen day — a code picked for the 31st
# works all of the 31st. A transition *begins* on the chosen day: "from
# 1 January, membership costs A$29" means members have through the 31st
# of December and the new rule holds the moment the 1st starts. So this
# resolves to the START of the local day where the expiry resolves to
# the start of the following one.


def transition_instant(
    effective_on: date | None, timezone_name: str | None,
) -> datetime | None:
    """The UTC instant a transition chosen for ``effective_on`` begins.

    Midnight at the start of that local day, returned UTC-naive to
    match the ``DateTime(timezone=False)`` storage convention.

    Melbourne, 1 Jan 2027 (AEDT, UTC+11):
        → 1 Jan 2027 00:00 +11:00
        → 2026-12-31 13:00 UTC

    So existing members have through the whole of 31 December where
    they live, and the requirement holds the moment the 1st begins
    there — not when the 1st begins in UTC, thirteen hours later.
    """
    if effective_on is None:
        return None
    from app.services.discount_pricing import collective_timezone

    tz = collective_timezone(timezone_name)
    start_of_day_local = datetime.combine(effective_on, time.min, tzinfo=tz)
    return start_of_day_local.astimezone(UTC).replace(tzinfo=None)


def transition_date_in_timezone(
    effective_at: datetime | None, timezone_name: str | None,
) -> date | None:
    """The calendar day a stored transition instant represents.

    The inverse of :func:`transition_instant`, so a creator is shown
    back the date they chose rather than whatever the instant looks
    like in the reader's timezone. Exact rather than approximate: the
    stored instant *is* the start of the chosen local day, so reading
    it back in that timezone lands on the day itself whatever the
    offset — no stepping back a microsecond, which an expiry needs and
    this does not.
    """
    if effective_at is None:
        return None
    from app.services.discount_pricing import collective_timezone

    tz = collective_timezone(timezone_name)
    return effective_at.replace(tzinfo=UTC).astimezone(tz).date()
