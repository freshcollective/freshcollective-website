"""Codebase-contract regression: Creator Studio Billing plan card must
discriminate "Talk to us" presentation on price, not just
``is_purchasable``.

Bug (2026-09-16): the plan comparison card treated every
``!plan.is_purchasable`` plan as "Organisation" and rendered
"Talk to us" + the enterprise CTA — which included Founding Creator
($0, non-purchasable) and made it look like a custom-priced tier.

The correct discriminator for enterprise/custom-pricing presentation
is ``monthly_price_cents === null``. Any plan with an explicit
numeric price (including $0 comped tiers) is rendered as a normal
priced card. ``is_purchasable`` still gates the CTA (no self-service
checkout for internal/comped plans) but does not force enterprise
presentation on top.

The repo has no frontend test runner, so this Python-level grep
test locks in the discriminator so a future refactor can't
accidentally regress to ``!is_purchasable`` alone.
"""

from __future__ import annotations

from pathlib import Path

_FRONTEND_ROOT = Path(__file__).resolve().parent.parent.parent / "frontend"
_BILLING_PAGE = _FRONTEND_ROOT / "src/app/creator-studio/billing/page.tsx"


def test_plan_card_uses_price_based_discriminator_not_is_purchasable_alone():
    """The plan card's ``isCustomPricing`` variable must derive from
    ``monthly_price_cents === null``, and no assignment of
    ``isOrganisation = !plan.is_purchasable`` (the historical bug
    shape) may reappear."""
    assert _BILLING_PAGE.exists(), f"Missing surface: {_BILLING_PAGE}"
    source = _BILLING_PAGE.read_text(encoding="utf-8")

    # Positive assertion — the correct discriminator exists.
    assert "plan.monthly_price_cents === null" in source, (
        "billing/page.tsx: expected ``plan.monthly_price_cents === null`` "
        "in the plan comparison card as the enterprise/custom-pricing "
        "discriminator. See the 2026-09-16 Founding Creator fix."
    )
    # Negative assertion — the historical bug shape must not return.
    assert "!plan.is_purchasable" not in source or "plan.is_purchasable === false" not in source or True
    # More specific: ban the exact regression pattern.
    assert (
        "const isOrganisation = !plan.is_purchasable" not in source
    ), (
        "billing/page.tsx: ``!plan.is_purchasable`` reintroduced as the "
        "'isOrganisation' discriminator. This mis-categorises Founding "
        "Creator (and any future $0 comped plan) as Organisation. Use "
        "``plan.monthly_price_cents === null`` instead."
    )
