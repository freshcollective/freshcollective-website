"""
Shared money floors for the Commerce section.

**Design invariants:**

- Amounts are integer **minor units** throughout ("cents"), never floats.
  The column names say ``_cents`` and mean it.

- :data:`MIN_PAID_CHARGE_CENTS` is the smallest amount FC will ask a
  payment provider to charge. It exists because Stripe refuses very
  small amounts — typically below 50 minor units — and the refusal
  arrives as a provider error at the moment of purchase, which is the
  worst possible place to discover it. Rejecting earlier turns a 502
  into a sentence a person can act on.

- The floor is a single conservative constant rather than a per-currency
  table. That holds because FC settles through one platform Stripe
  account (there is no Connect account per creator), and because the
  supported-currency list deliberately excludes zero-decimal currencies
  such as JPY, where 100 minor units would mean something very
  different. 100 sits above every relevant provider minimum with room to
  spare, so one number is honest for all of them.

  If either of those changes — Connect accounts with their own
  settlement currencies, or a zero-decimal currency — this constant has
  to become a function of currency, and the comment above is the reason
  why.

- The floor applies to what is **actually charged**. A discount lowers
  that amount, so a discounted charge is measured against this floor and
  not the list price it came from.
"""

from __future__ import annotations

#: The smallest charge FC will send to a payment provider, in minor
#: units. Conservative: roughly double the typical provider minimum, and
#: a round "one dollar" in every two-decimal currency FC supports.
MIN_PAID_CHARGE_CENTS: int = 100
