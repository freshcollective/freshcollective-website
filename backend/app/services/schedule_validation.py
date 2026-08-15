"""Validation for ``PaymentOptionSchedule`` rows — finite plans in particular.

FIP1 introduces cross-field validation for
``schedule_type='recurring_installments'`` so Creator Studio cannot
persist an incoherent plan (missing count, zero amount, unsupported
cadence). The current per-field Pydantic validators in
``creator/schemas.py`` accept each field in isolation; nothing
today validates that an instalment plan actually has an amount and
a count.

Two entry points:

* :func:`validate_recurring_installments_payload` — pass in the
  incoming Pydantic model (or a dict-like) at creator route level,
  BEFORE the row is persisted. Raises ``HTTPException(422)`` on
  invalid input.
* :func:`validate_recurring_installments_row` — pass in a
  ``PaymentOptionSchedule`` ORM instance. Same validation, but for
  callers that only have the persisted row (e.g. a future
  publish-time check). Raises ``ScheduleValidationError``.

Cadence mapping (matches the docstring on ``PaymentOptionSchedule``):

    weekly       → stripe_interval='week',  stripe_interval_count=1
    fortnightly  → stripe_interval='week',  stripe_interval_count=2
    monthly      → stripe_interval='month', stripe_interval_count=1

Any other combination is rejected for FIP1. Adding fortnightly-
monthly hybrids or arbitrary intervals is a Stripe SDK question
that should be answered explicitly when a real product need
appears — not silently allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException


ALLOWED_CADENCES: tuple[tuple[str, int], ...] = (
    ("week", 1),   # weekly
    ("week", 2),   # fortnightly
    ("month", 1),  # monthly
)


# ---------------------------------------------------------------------------
# Creator payload normalisation
# ---------------------------------------------------------------------------
#
# The Creator UI sends a semantic cadence key on ``interval``:
# ``week`` / ``fortnight`` / ``month``. The Stripe API uses a
# two-field cadence: ``stripe_interval`` (``week`` / ``month``) +
# ``stripe_interval_count`` (an integer multiplier). Derive the
# Stripe pair from the semantic key here so the two source-of-truth
# columns on ``PaymentOptionSchedule`` stay consistent + the FIP1
# strict validator has the values it requires on publish.
#
# Also derive ``total_amount_cents`` from ``amount × count`` when
# the Creator UI didn't send it — Creators think in "per-payment
# × number-of-payments", not totals. The stored total makes
# reporting + the strict-equality validator work without further
# UI changes.

_CADENCE_KEY_TO_STRIPE: dict[str, tuple[str, int]] = {
    "week": ("week", 1),
    "weekly": ("week", 1),
    "fortnight": ("week", 2),
    "fortnightly": ("week", 2),
    "biweekly": ("week", 2),
    "month": ("month", 1),
    "monthly": ("month", 1),
}


def derive_stripe_cadence(interval_key: str | None) -> tuple[str, int] | None:
    """Map a Creator-friendly cadence key to Stripe's (interval, count).

    Returns None on unknown / empty input so the caller can leave
    the fields NULL for the validator to reject with a clear
    message rather than guessing. The Creator UI's dropdown emits
    values in this table; other clients that already send the
    Stripe pair directly should bypass this helper.
    """
    if not interval_key:
        return None
    return _CADENCE_KEY_TO_STRIPE.get(interval_key.strip().lower())


def apply_recurring_derivations(target: Any) -> None:
    """Fill in Stripe cadence + total from Creator-supplied fields.

    Mutates ``target`` in place. Safe to call for any payload:

    * ``schedule_type != 'recurring_installments'`` → no-op.
    * ``stripe_interval`` / ``stripe_interval_count`` already set →
      preserved (respects a caller that sends both explicitly).
    * ``total_amount_cents`` already set → preserved (respects a
      caller that supplied an explicit total).

    Works on Pydantic models (via ``setattr``) and SQLAlchemy ORM
    rows alike. Only sets fields that already exist on the target
    — a defensive ``hasattr`` check keeps this helper safe against
    unrelated update payloads (partial patches).
    """
    def _get(name: str) -> Any:
        return getattr(target, name, None)

    def _set_if_writable(name: str, value: Any) -> None:
        if hasattr(target, name):
            setattr(target, name, value)

    if _get("schedule_type") != "recurring_installments":
        return

    # ── Cadence derivation ────────────────────────────────────────
    stripe_interval = _get("stripe_interval")
    stripe_interval_count = _get("stripe_interval_count")
    if not stripe_interval or not stripe_interval_count:
        pair = derive_stripe_cadence(_get("interval"))
        if pair is not None:
            si, sic = pair
            if not stripe_interval:
                _set_if_writable("stripe_interval", si)
            if not stripe_interval_count:
                _set_if_writable("stripe_interval_count", sic)

    # ── Total derivation ──────────────────────────────────────────
    if _get("total_amount_cents") is None:
        amt = _get("installment_amount_cents")
        cnt = _get("installment_count")
        if amt is not None and cnt is not None and amt > 0 and cnt > 0:
            _set_if_writable("total_amount_cents", amt * cnt)


class ScheduleValidationError(ValueError):
    """Raised by :func:`validate_recurring_installments_row` on invalid input."""


@dataclass(frozen=True)
class _Snapshot:
    schedule_type: str | None
    installment_amount_cents: int | None
    installment_count: int | None
    stripe_interval: str | None
    stripe_interval_count: int | None
    total_amount_cents: int | None
    currency: str | None


def _snapshot(obj: Any) -> _Snapshot:
    """Read the fields we care about off a Pydantic model / dict / ORM row."""
    def read(name: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    return _Snapshot(
        schedule_type=read("schedule_type"),
        installment_amount_cents=read("installment_amount_cents"),
        installment_count=read("installment_count"),
        stripe_interval=read("stripe_interval"),
        stripe_interval_count=read("stripe_interval_count"),
        total_amount_cents=read("total_amount_cents"),
        currency=read("currency"),
    )


def _validate_snapshot(s: _Snapshot) -> list[str]:
    """Return a list of validation errors. Empty list = valid."""
    errors: list[str] = []

    if s.installment_amount_cents is None:
        errors.append(
            "installment_amount_cents is required for recurring_installments."
        )
    elif s.installment_amount_cents <= 0:
        errors.append(
            "installment_amount_cents must be greater than zero."
        )

    if s.installment_count is None:
        errors.append(
            "installment_count is required for recurring_installments."
        )
    elif s.installment_count < 2:
        errors.append(
            "installment_count must be at least 2 — a one-payment "
            "'plan' is a pay_in_full schedule."
        )

    if s.stripe_interval is None or s.stripe_interval_count is None:
        errors.append(
            "stripe_interval and stripe_interval_count are required "
            "for recurring_installments."
        )
    else:
        if (s.stripe_interval, s.stripe_interval_count) not in ALLOWED_CADENCES:
            errors.append(
                f"cadence ({s.stripe_interval} × {s.stripe_interval_count}) "
                "is not supported. Supported: weekly (week×1), "
                "fortnightly (week×2), monthly (month×1)."
            )

    if s.currency is not None:
        if not (isinstance(s.currency, str) and len(s.currency) == 3 and s.currency.isalpha()):
            errors.append("currency must be a 3-letter ISO 4217 code.")

    # Cross-check total_amount_cents == per-instalment × count.
    # STRICT equality for v1: the current schema describes equal
    # fixed instalments (no "differently-sized final instalment"
    # field). A tolerance would silently mask Creator input
    # errors and would make the ledger inconsistent with what
    # the member actually pays. When a differently-sized final
    # instalment becomes a product requirement, add an explicit
    # ``final_installment_amount_cents`` column and re-derive the
    # sum here — do not restore a tolerance.
    if (
        s.installment_amount_cents
        and s.installment_count
        and s.total_amount_cents is not None
    ):
        expected = s.installment_amount_cents * s.installment_count
        if s.total_amount_cents != expected:
            errors.append(
                f"total_amount_cents ({s.total_amount_cents}) does not "
                f"equal installment_amount_cents × installment_count "
                f"({expected}). Equal fixed instalments are required "
                "in v1."
            )

    return errors


def validate_recurring_installments_payload(payload: Any) -> None:
    """Validate an incoming create/update payload. Raises HTTPException on error.

    No-op unless ``payload.schedule_type == 'recurring_installments'``.
    Safe to call from every create/update code path without
    conditionally guarding at the callsite.
    """
    snap = _snapshot(payload)
    if snap.schedule_type != "recurring_installments":
        return
    errors = _validate_snapshot(snap)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid recurring_installments schedule.",
                "errors": errors,
            },
        )


def validate_recurring_installments_row(row: Any) -> None:
    """Validate a persisted ``PaymentOptionSchedule`` row.

    Called by future publish-time / plan-creation checks that only
    have the ORM object. Raises ``ScheduleValidationError`` on
    error rather than HTTP exception, because callers of this
    helper are not always HTTP-facing.
    """
    snap = _snapshot(row)
    if snap.schedule_type != "recurring_installments":
        return
    errors = _validate_snapshot(snap)
    if errors:
        raise ScheduleValidationError("; ".join(errors))
