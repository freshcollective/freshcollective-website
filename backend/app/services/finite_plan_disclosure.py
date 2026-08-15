"""Finite payment plan disclosure text (FIP2).

Composes the payment-plan disclosure paragraph Stripe Checkout
displays under the submit button in ``mode='setup'``. Purpose: make
the financial commitment unmistakable so a member cannot interpret
the setup Session as merely "saving a card".

The text is generated entirely from the immutable
``PurchasePlan`` snapshot + the Payment Option name — no client-
supplied commercial wording, no Creator-editable copy. All numbers
(amount, count, total, cadence) come from the plan row fixed at
purchase time.

The disclosure is passed to
``stripe.checkout.Session.create(..., custom_text={"submit": {"message": ...}})``.
Stripe caps the message at 1200 chars; our composed text is well
under 300.
"""

from __future__ import annotations

from app.models.purchase_plan import PurchasePlan


# ---------------------------------------------------------------------------
# Cadence word lookup
# ---------------------------------------------------------------------------

# Maps a (stripe_interval, stripe_interval_count) pair to the
# adverb we display to the member ("weekly" etc.). Only the three
# cadences FIP1 validation accepts appear here — an unknown pair
# should never reach this function, but the fallback is safe.
_CADENCE_ADVERB: dict[tuple[str, int], str] = {
    ("week", 1):  "weekly",
    ("week", 2):  "fortnightly",
    ("month", 1): "monthly",
}


def _cadence_adverb(stripe_interval: str, stripe_interval_count: int) -> str:
    """Return the adverb for the given cadence pair.

    Falls back to a defensive human phrase — e.g. ``every 3 weeks``
    for an unrecognised pair — so the disclosure never renders as
    a bare ``(None)``. FIP1 validation should prevent this branch
    from firing in production.
    """
    hit = _CADENCE_ADVERB.get((stripe_interval, stripe_interval_count))
    if hit is not None:
        return hit
    unit = "week" if stripe_interval == "week" else "month"
    if stripe_interval_count == 1:
        return f"{unit}ly"
    plural = f"{unit}s"
    return f"every {stripe_interval_count} {plural}"


# ---------------------------------------------------------------------------
# Currency formatting
# ---------------------------------------------------------------------------


_CURRENCY_SYMBOL: dict[str, str] = {
    "AUD": "A$",
    "USD": "US$",
    "NZD": "NZ$",
    "CAD": "C$",
    "GBP": "£",
    "EUR": "€",
}


def _format_money(cents: int, currency: str) -> str:
    """Format integer cents into a human string with a currency symbol.

    * Whole-dollar amounts drop the trailing ``.00`` (``A$20`` not
      ``A$20.00``) — matches everyday retail formatting.
    * Sub-dollar amounts show two decimals (``A$34.50``).
    * Unknown currency codes fall back to ``CUR 20.00`` — legible,
      never misleading.
    """
    code = (currency or "").upper()
    symbol = _CURRENCY_SYMBOL.get(code)
    dollars = cents / 100
    if dollars == int(dollars):
        amount_str = f"{int(dollars)}"
    else:
        amount_str = f"{dollars:.2f}"
    if symbol is None:
        return f"{code} {amount_str}" if code else amount_str
    return f"{symbol}{amount_str}"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------


def compose_setup_disclosure(
    *, plan: PurchasePlan, option_name: str,
) -> str:
    """Return the Stripe Checkout ``custom_text.submit.message``.

    Reads only immutable snapshot values on ``plan``. ``option_name``
    is required — the caller (finite-plan orchestrator) has the
    Payment Option loaded and passes its ``.name`` in. We do not
    load it here so this helper stays pure/testable.
    """
    per_payment = _format_money(plan.installment_amount_cents, plan.currency)
    total       = _format_money(plan.total_expected_cents,     plan.currency)
    cadence     = _cadence_adverb(plan.stripe_interval, plan.stripe_interval_count)
    count       = plan.installments_expected
    remaining   = count - 1

    # Singular/plural for the "followed by N …" clause.
    if remaining == 1:
        followup = f"1 {cadence} payment of {per_payment}"
    else:
        followup = f"{remaining} {cadence} payments of {per_payment}"

    return (
        f"{option_name} — {per_payment} {cadence} × {count} payments "
        f"({total} total). "
        f"By saving your payment details, you authorise Fresh Collective "
        f"to start this payment plan. "
        f"Your first {per_payment} payment will be charged after setup, "
        f"followed by {followup}. "
        f"Access begins after the first payment succeeds."
    )
