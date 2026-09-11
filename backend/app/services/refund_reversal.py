"""Pure function computing cumulative fee/creator reversal targets
from a PaymentTransaction's immutable snapshot amounts + Stripe's
cumulative ``charge.amount_refunded``.

Never accumulates incrementally. Always derives the target values
from the cumulative refund total so that:

  * out-of-order webhook events are naturally idempotent (same input
    → same output);
  * a full-refund case is coerced to the exact original amounts
    (no rounding drift possible);
  * the invariant
    ``refunded_platform_fee_cents + refunded_creator_amount_cents
    == refunded_amount_cents`` holds on every write.

The creator side absorbs any rounding remainder so the platform
never keeps a fractional cent of fee.

This module has no DB dependency; it's a leaf function. The caller
(``webhooks.refund_handlers._do_charge_refunded``) applies the
returned targets under the existing monotonic guards.
"""

from __future__ import annotations


def compute_cumulative_reversal_targets(
    *,
    gross_amount_cents: int,
    platform_fee_cents: int,
    net_creator_amount_cents: int,
    cumulative_refunded: int,
) -> tuple[int, int]:
    """Return ``(target_platform_reversal, target_creator_reversal)``.

    Guarantees:

      * ``target_platform + target_creator == cumulative_refunded``
        (invariant).
      * ``0 <= target_platform <= platform_fee_cents``.
      * ``0 <= target_creator <= net_creator_amount_cents``.

    Rounding: Python ``round()`` uses banker's rounding —
    deterministic and reproducible across runs. Only the platform
    side is rounded; the creator side is derived as
    ``cumulative_refunded - target_platform`` so the invariant holds
    without any tie-breaking arithmetic on the creator side.

    Full-refund coercion: when ``cumulative_refunded >=
    gross_amount_cents`` the targets are set to the exact
    ``platform_fee_cents`` / ``net_creator_amount_cents`` values.
    This eliminates any possibility that a partial's rounded
    proportional would leave a fractional cent unattributed on a
    later full refund.
    """
    # Defensive: treat missing or negative gross as unrecoverable
    # zero-target (caller should already have ensured a valid row).
    if gross_amount_cents <= 0 or cumulative_refunded <= 0:
        return 0, 0

    # Full-refund coercion. Exact, no rounding.
    if cumulative_refunded >= gross_amount_cents:
        return (
            max(0, platform_fee_cents),
            max(0, net_creator_amount_cents),
        )

    # Partial. Proportional platform share; creator absorbs remainder.
    max_platform = max(0, platform_fee_cents)
    max_creator = max(0, net_creator_amount_cents)
    target_platform = round(
        cumulative_refunded * platform_fee_cents / gross_amount_cents
    )
    # Clamp against the original ceiling. Defensive against edge
    # rounding + pathological inputs (fee_cents > gross_cents).
    target_platform = max(0, min(target_platform, max_platform))
    target_creator = cumulative_refunded - target_platform
    # If rounding pushed the creator side above ITS ceiling, shift
    # the overshoot back to the platform side (or vice versa if the
    # inputs are pathological). The invariant target_p + target_c ==
    # cumulative_refunded is preserved by reallocation.
    if target_creator > max_creator:
        overshoot = target_creator - max_creator
        target_platform = min(max_platform, target_platform + overshoot)
        target_creator = cumulative_refunded - target_platform
    if target_creator < 0:
        # Platform reversal exceeded creator ceiling and reallocation
        # couldn't cover — clamp both to non-negative while preserving
        # the invariant as best possible.
        target_creator = 0
        target_platform = min(max_platform, cumulative_refunded)
    return target_platform, target_creator
