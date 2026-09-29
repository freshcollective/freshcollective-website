"""Turn Stripe's account objects into the one state FC stores.

The only place that knows Stripe's response shape. Pure: no database, no
network, no clock. Callers fetch the objects, pass them here, and write
the result — which keeps the precedence rules testable against recorded
Stripe responses rather than against a live account.

Both API surfaces are needed, and not as primary-plus-fallback. v2 owns
the capability statuses and the requirement entries; v1 owns
``details_submitted``, the external-account count and the payout
schedule, none of which appear anywhere in the v2 account object. A
projection built from v2 alone cannot tell ``action_required`` from
``onboarding``.

Every rule below was verified against a real recipient + express account
taken through Stripe-hosted onboarding, not inferred from type
definitions. Two observations shape the whole thing:

* ``stripe_transfers`` is gated by identity and ToS acceptance;
  ``payouts`` is gated by those *plus* ``external_account``. The states
  genuinely diverge, and the gap is dangerous rather than cosmetic — see
  :data:`OnboardingState.transfers_only`.
* ``awaiting_action_from`` on each requirement entry is the only field
  that separates "the creator must do something" from "Stripe is
  checking". A non-empty list of due requirements cannot: it does not say
  who must act.

There is no ``rejected`` capability status. Rejection arrives as
``restricted`` with a ``restricted_other`` code and a ``contact_stripe``
resolution, which is why :data:`OnboardingState.restricted` covers both
"Stripe must be contacted" and the conservative fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.creator_stripe_account import (
    CapabilityStatus,
    CreatorStripeAccount,
    OnboardingState,
)

# Codes that mean the account can never receive transfers, whatever the
# creator does. Distinguished from a plain restriction because the
# creator-facing consequence is the opposite: do not invite a retry.
TERMINAL_CODES = frozenset({
    "unsupported_business",
    "unsupported_country",
    "unsupported_entity_type",
})

#: Stripe's own word for "there is nothing that would fix this".
TERMINAL_RESOLUTIONS = frozenset({"no_resolution"})

#: The creator cannot resolve these themselves.
CONTACT_STRIPE_CODES = frozenset({"restricted_other"})

#: Stripe is working; the creator should be asked for nothing.
IN_REVIEW_CODES = frozenset({
    "requirements_pending_verification",
    "determining_status",
})


@dataclass(frozen=True)
class ProjectedState:
    """What FC stores about a creator's Stripe account.

    Field-for-field what :class:`CreatorStripeAccount` persists, minus the
    identity columns the caller already knows. ``apply_to`` writes it.
    """

    onboarding_state: str

    transfers_status: str | None = None
    transfers_status_codes: list[str] = field(default_factory=list)
    payouts_status: str | None = None
    payouts_status_codes: list[str] = field(default_factory=list)

    transfers_enabled: bool = False
    payouts_enabled: bool = False

    details_submitted: bool = False
    currently_due_json: list[dict[str, Any]] = field(default_factory=list)
    requirements_deadline: datetime | None = None

    external_account_count: int = 0
    payout_interval: str | None = None
    payout_delay_days: int | None = None
    debit_negative_balances: bool | None = None

    dashboard: str | None = None
    fees_collector: str | None = None
    losses_collector: str | None = None
    requirements_collector: str | None = None

    def apply_to(self, row: CreatorStripeAccount) -> CreatorStripeAccount:
        """Copy this projection onto a row. Deliberately does not touch
        identity, ``connect_payouts_enabled_at`` or the sync diagnostics —
        a projection reports what Stripe says; it never decides whether a
        creator's money should route through Connect."""
        for name in (
            "onboarding_state",
            "transfers_status", "transfers_status_codes",
            "payouts_status", "payouts_status_codes",
            "transfers_enabled", "payouts_enabled",
            "details_submitted", "currently_due_json", "requirements_deadline",
            "external_account_count", "payout_interval", "payout_delay_days",
            "debit_negative_balances",
            "dashboard", "fees_collector", "losses_collector",
            "requirements_collector",
        ):
            setattr(row, name, getattr(self, name))
        return row


# ---------------------------------------------------------------------------
# Reading the Stripe objects
# ---------------------------------------------------------------------------


def _d(value: Any) -> dict[str, Any]:
    """Coerce a StripeObject / mapping / None to a plain dict.

    Stripe objects support mapping access but are not dicts, and absent
    sub-objects come back as ``None`` rather than empty — both are normal
    and neither should raise here.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _capability(v2: dict[str, Any], name: str) -> dict[str, Any]:
    """``configuration.recipient.capabilities.stripe_balance.<name>``."""
    recipient = _d(_d(v2.get("configuration")).get("recipient"))
    stripe_balance = _d(_d(recipient.get("capabilities")).get("stripe_balance"))
    return _d(stripe_balance.get(name))


def _status(capability: dict[str, Any]) -> str | None:
    status = capability.get("status")
    return str(status) if status else None


def _codes(capability: dict[str, Any]) -> list[str]:
    """``status_details[].code``. Empty when the capability is active."""
    return [
        str(detail.get("code"))
        for detail in (_d_list(capability.get("status_details")))
        if detail.get("code")
    ]


def _resolutions(capability: dict[str, Any]) -> list[str]:
    return [
        str(detail.get("resolution"))
        for detail in (_d_list(capability.get("status_details")))
        if detail.get("resolution")
    ]


def _d_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    return [_d(item) for item in value]


def _requirement_entries(v2: dict[str, Any]) -> list[dict[str, Any]]:
    """Requirement entries, reduced to the fields FC actually reasons about.

    Kept as entries rather than flattened to descriptions because
    ``awaiting_action_from`` drives the state machine and ``errors`` is
    what lets FC tell a creator *why* a submitted document was refused.
    """
    entries = []
    for raw in _d_list(_d(v2.get("requirements")).get("entries")):
        impact = _d(raw.get("impact"))
        entries.append({
            "description": raw.get("description"),
            "awaiting_action_from": raw.get("awaiting_action_from"),
            "restricts_capabilities": [
                r.get("capability")
                for r in _d_list(impact.get("restricts_capabilities"))
            ],
            "errors": _d_list(raw.get("errors")) or [],
        })
    return entries


def _requirements_deadline(v2: dict[str, Any]) -> datetime | None:
    """``requirements.summary.minimum_deadline.time`` when Stripe gives one.

    Observed as ``null`` alongside ``status: "past_due"`` on a fresh
    account, and the whole ``summary`` as ``null`` once nothing is due, so
    both absences are expected rather than exceptional.
    """
    summary = _d(_d(v2.get("requirements")).get("summary"))
    raw = _d(summary.get("minimum_deadline")).get("time")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    try:
        # RFC 3339, as the v2 API renders timestamps.
        text = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _external_account_count(v1: dict[str, Any]) -> int:
    """v1 only — the v2 account object has no external-account surface.

    ``total_count`` was observed as ``null`` on an account with no bank
    account attached, so the length of ``data`` is the reliable reading and
    ``total_count`` is used only when it is actually a number.
    """
    external = _d(v1.get("external_accounts"))
    total = external.get("total_count")
    if isinstance(total, int):
        return total
    return len(_d_list(external.get("data")))


# ---------------------------------------------------------------------------
# The state rules
# ---------------------------------------------------------------------------


def _is_terminal(capability: dict[str, Any]) -> bool:
    if _status(capability) == CapabilityStatus.unsupported.value:
        return True
    if TERMINAL_CODES.intersection(_codes(capability)):
        return True
    return bool(TERMINAL_RESOLUTIONS.intersection(_resolutions(capability)))


def _needs_stripe(capability: dict[str, Any]) -> bool:
    return bool(CONTACT_STRIPE_CODES.intersection(_codes(capability)))


def _in_review(capability: dict[str, Any]) -> bool:
    if _status(capability) == CapabilityStatus.pending.value:
        return True
    return bool(IN_REVIEW_CODES.intersection(_codes(capability)))


def derive_onboarding_state(
    *,
    stripe_account_id: str | None,
    v2: dict[str, Any] | None,
    v1: dict[str, Any] | None,
) -> str:
    """The single creator-facing state, by verified precedence.

    Evaluated top down, first match wins. Order is load-bearing in two
    places:

    * ``transfers_only`` must be reached before ``action_required``. Both
      match when transfers are live and a bank account is outstanding, and
      only one of them tells the creator the thing that matters.
    * the terminal states come before the good ones, so an account that
      cannot be supported is never described as merely needing attention.

    Falls back to ``restricted`` rather than to anything reassuring: an
    unrecognised combination is a reason to withhold routing, not to
    assume it is fine.
    """
    if not stripe_account_id:
        return OnboardingState.not_started.value

    account = _d(v2)
    legacy = _d(v1)

    if account.get("closed") is True:
        return OnboardingState.closed.value

    transfers = _capability(account, "stripe_transfers")
    payouts = _capability(account, "payouts")

    # Terminal: nothing the creator does will help.
    if _is_terminal(transfers) or _is_terminal(payouts):
        return OnboardingState.unsupported.value

    # Blocked in a way only Stripe can lift.
    if _needs_stripe(transfers) or _needs_stripe(payouts):
        return OnboardingState.restricted.value

    transfers_active = _status(transfers) == CapabilityStatus.active.value
    payouts_active = _status(payouts) == CapabilityStatus.active.value

    if transfers_active and payouts_active:
        return OnboardingState.ready.value

    # Money can come in but cannot leave. Checked before
    # ``action_required`` on purpose — see the docstring.
    if transfers_active and not payouts_active:
        return OnboardingState.transfers_only.value

    entries = _requirement_entries(account)
    outstanding = [e for e in entries if e.get("awaiting_action_from")]
    awaiting_stripe_only = bool(outstanding) and all(
        e["awaiting_action_from"] == "stripe" for e in outstanding
    )

    if _in_review(transfers) or _in_review(payouts) or awaiting_stripe_only:
        return OnboardingState.verifying.value

    if legacy.get("details_submitted") is not True:
        return OnboardingState.onboarding.value

    if any(e["awaiting_action_from"] == "user" for e in outstanding):
        return OnboardingState.action_required.value

    return OnboardingState.restricted.value


def project(
    *,
    stripe_account_id: str | None,
    v2: Any = None,
    v1: Any = None,
) -> ProjectedState:
    """Build the full stored projection from Stripe's two account objects.

    ``v2`` is a ``v2.core.Account`` (or its dict form) retrieved with
    ``include=["configuration.recipient", "requirements", "defaults"]``.
    ``v1`` is a v1 ``Account`` for the same id. Either may be ``None``
    when no Stripe account exists yet.
    """
    if not stripe_account_id:
        return ProjectedState(onboarding_state=OnboardingState.not_started.value)

    account = _d(v2)
    legacy = _d(v1)

    transfers = _capability(account, "stripe_transfers")
    payouts = _capability(account, "payouts")
    transfers_status = _status(transfers)
    payouts_status = _status(payouts)

    payout_settings = _d(_d(legacy.get("settings")).get("payouts"))
    schedule = _d(payout_settings.get("schedule"))
    responsibilities = _d(_d(account.get("defaults")).get("responsibilities"))

    return ProjectedState(
        onboarding_state=derive_onboarding_state(
            stripe_account_id=stripe_account_id, v2=account, v1=legacy,
        ),
        transfers_status=transfers_status,
        transfers_status_codes=_codes(transfers),
        payouts_status=payouts_status,
        payouts_status_codes=_codes(payouts),
        # Derived, never read from Stripe as a boolean — the CHECK
        # constraints on the table hold these to the statuses above.
        transfers_enabled=transfers_status == CapabilityStatus.active.value,
        payouts_enabled=payouts_status == CapabilityStatus.active.value,
        details_submitted=legacy.get("details_submitted") is True,
        currently_due_json=_requirement_entries(account),
        requirements_deadline=_requirements_deadline(account),
        external_account_count=_external_account_count(legacy),
        payout_interval=schedule.get("interval"),
        payout_delay_days=schedule.get("delay_days"),
        debit_negative_balances=payout_settings.get("debit_negative_balances"),
        dashboard=account.get("dashboard"),
        fees_collector=responsibilities.get("fees_collector"),
        losses_collector=responsibilities.get("losses_collector"),
        requirements_collector=responsibilities.get("requirements_collector"),
    )
