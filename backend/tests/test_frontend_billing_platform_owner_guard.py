"""Codebase-contract regression: Creator Studio surfaces that special-
case ``billing.is_platform_owner`` MUST also check ``current_plan``.

Bug history: an admin with an active CreatorSubscription hit two
Creator Studio surfaces that both short-circuited on
``billing.is_platform_owner`` alone and buried the real plan card
behind "Platform Owner — no creator subscription plan attached" copy.
Fixed on 2026-09-15 in ``/creator-studio/billing/page.tsx`` and
``/creator-studio/account/AccountTabbedShell.tsx``.

We have no frontend test runner in this repo, so this test guards
against re-regression by inspecting the source of both surfaces and
asserting that every occurrence of ``billing.is_platform_owner`` in a
routing / short-circuit context is paired with a
``current_plan === null`` check. If a future change reintroduces the
unconditional short-circuit, this test fails at CI time before the
change reaches production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_FRONTEND_ROOT = Path(__file__).resolve().parent.parent.parent / "frontend"

# Files that render or route to Platform Owner-styled UI. Add new
# entries here whenever another Creator Studio surface starts keying
# on billing.is_platform_owner.
_SURFACES = [
    "src/app/creator-studio/billing/page.tsx",
    "src/app/creator-studio/account/AccountTabbedShell.tsx",
]


@pytest.mark.parametrize("relpath", _SURFACES)
def test_platform_owner_branch_pairs_with_current_plan_check(relpath: str):
    """Every ``if (billing.is_platform_owner ...)`` on a Creator
    Studio surface must include a ``current_plan === null`` (or
    equivalent ``!billing.current_plan``) predicate in the same
    condition — otherwise admins with an active subscription lose
    their plan card to the historical Platform Owner short-circuit."""
    path = _FRONTEND_ROOT / relpath
    assert path.exists(), f"Missing surface: {path}"
    source = path.read_text(encoding="utf-8")

    # Match every ``if (...billing.is_platform_owner...)`` conditional
    # on a single line. Both surfaces use single-line conditions today;
    # if a future refactor splits one across multiple lines, extend
    # the regex.
    pattern = re.compile(
        r"if\s*\([^)]*billing\.is_platform_owner[^)]*\)",
        re.MULTILINE,
    )
    matches = pattern.findall(source)
    assert matches, (
        f"{relpath}: no ``billing.is_platform_owner`` conditional found. "
        "The surface list is stale; remove this file from _SURFACES or "
        "update the check."
    )
    for m in matches:
        assert (
            "current_plan === null" in m
            or "!billing.current_plan" in m
            or "billing.current_plan === null" in m
        ), (
            f"{relpath}: platform-owner conditional {m!r} is missing "
            "the current_plan guard. Admins with an active "
            "CreatorSubscription must fall through to the real plan "
            "card — see the 2026-09-15 regression fix."
        )
