"""Codebase-contract regression: the internal DB plan slug ``pro``
must render as "Creator Portfolio" (never "Pro") on creator-facing
surfaces.

Internal / admin surfaces continue to use the DB name. This test
locks the mapping helper in place + ensures the two creator-facing
files consult it rather than reading ``plan.name`` directly for the
title.
"""

from __future__ import annotations

from pathlib import Path


_FRONTEND_ROOT = Path(__file__).resolve().parent.parent.parent / "frontend"
_HELPER = _FRONTEND_ROOT / "src/lib/creatorPlanDisplay.ts"
_BILLING = _FRONTEND_ROOT / "src/app/creator-studio/billing/page.tsx"
_ACCOUNT = _FRONTEND_ROOT / "src/app/creator-studio/account/AccountTabbedShell.tsx"


def test_mapping_helper_maps_pro_to_creator_portfolio():
    assert _HELPER.exists(), f"Missing helper: {_HELPER}"
    src = _HELPER.read_text(encoding="utf-8")
    assert "'pro'" in src or '"pro"' in src
    assert "'Creator Portfolio'" in src or '"Creator Portfolio"' in src


def test_billing_page_uses_creator_facing_name_for_plan_title():
    """Both the Current Plan card and the plan-comparison Card call
    the mapping helper — direct ``plan.name`` / ``current_plan.name``
    reads without the helper would surface "Pro" to the creator."""
    assert _BILLING.exists()
    src = _BILLING.read_text(encoding="utf-8")
    assert "creatorFacingPlanName(current_plan.slug, current_plan.name)" in src
    assert "creatorFacingPlanName(plan.slug, plan.name)" in src


def test_account_tabbed_shell_uses_creator_facing_name():
    assert _ACCOUNT.exists()
    src = _ACCOUNT.read_text(encoding="utf-8")
    assert "creatorFacingPlanName(plan.slug, plan.name)" in src


def test_billing_page_no_stale_future_update_copy():
    """The "future update" placeholder was removed once the upgrade
    endpoint went live. Its return would misrepresent the current
    state."""
    assert _BILLING.exists()
    src = _BILLING.read_text(encoding="utf-8")
    assert "future update" not in src
    assert "Automatic plan upgrades will be available" not in src


def test_billing_page_wires_upgrade_button_to_existing_endpoint():
    """The upgrade CTA must invoke the existing
    ``UpgradeSubscriptionButton`` (which posts to
    ``/api/creator/billing/upgrade``), NOT a fresh checkout that would
    create a second Stripe subscription."""
    assert _BILLING.exists()
    src = _BILLING.read_text(encoding="utf-8")
    assert "UpgradeSubscriptionButton" in src
    assert "Upgrade to " in src

    # And the client component actually posts to the upgrade endpoint.
    actions_file = _FRONTEND_ROOT / "src/app/creator-studio/billing/BillingActions.tsx"
    assert actions_file.exists()
    actions_src = actions_file.read_text(encoding="utf-8")
    assert "'/api/creator/billing/upgrade'" in actions_src
