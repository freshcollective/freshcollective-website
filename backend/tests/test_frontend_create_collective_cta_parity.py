"""Codebase-contract regression: the authenticated Your World
dashboard and the public homepage hero MUST route "Create a
Collective" to the same destination.

Discovered during the external-creator live test on 2026-09-16 —
the dashboard's empty state read "You're not part of any
Collectives yet" with no visible way to reach the creator pathway.
The fix added two CTAs to the dashboard; this test guards against
either (a) the destination diverging from the homepage hero, or
(b) the CTAs being removed entirely.

The repo has no frontend test runner, so a Python-level source
grep is the smallest reliable way to enforce the contract.

Refined 2026-10-04: the shared destination is now anchored
(``/for-creators#plans``). Without the anchor the button dropped the
reader at the top of a long marketing page, where the first thing in
reach is the free Community card — which reads as the dashboard having
chosen Community on their behalf.

The dashboard additionally diverges for a reader who is *already* a
Creator, sending them to Creator Studio's plan-aware My World rather
than back through plan selection. That divergence is deliberate and is
asserted below; the parity contract applies to the non-Creator path,
which is the only path the public hero can produce.
"""

from __future__ import annotations

import re
from pathlib import Path


def _code_only(source: str) -> str:
    """``source`` with its comments removed.

    The files checked here *document* what they deliberately do not do —
    the dashboard explains that Community activation is one of the
    chooser's destinations, naming the route in prose. A raw substring
    check for "plan=community" then fails on the explanation rather
    than on a regression, which is a worse test than none: it punishes
    the comment that prevents the bug. Mirrors the ``codeOnly`` helper
    the frontend source-contract tests use.
    """
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(^|[^:])//.*$", r"\1", source, flags=re.MULTILINE)


_FRONTEND_ROOT = Path(__file__).resolve().parent.parent.parent / "frontend"
_DASHBOARD = _FRONTEND_ROOT / "src/app/dashboard/page.tsx"
_HOME_HERO = _FRONTEND_ROOT / "src/components/home/HomeHero.tsx"


def test_dashboard_and_home_hero_share_create_collective_destination():
    """Both surfaces resolve "Create a Collective" to the same href.
    If the destination is renamed (e.g. ``/for-creators`` moves to
    ``/build``), update both call sites in the same PR."""
    assert _DASHBOARD.exists(), f"Missing surface: {_DASHBOARD}"
    assert _HOME_HERO.exists(), f"Missing surface: {_HOME_HERO}"

    dashboard_src = _DASHBOARD.read_text(encoding="utf-8")
    hero_src = _HOME_HERO.read_text(encoding="utf-8")

    assert "PLAN_CHOOSER_HREF = '/for-creators#plans'" in dashboard_src, (
        "dashboard/page.tsx: expected the constant "
        "``PLAN_CHOOSER_HREF = '/for-creators#plans'`` to define the "
        "non-Creator Create-a-Collective destination. Both CTAs "
        "(empty-state + section-header) must resolve through "
        "``createCollectiveHref`` — see the 2026-09-16 creator "
        "onboarding-discoverability fix."
    )
    assert 'href="/for-creators#plans">Create a Collective' in hero_src, (
        "home/HomeHero.tsx: expected the public hero CTA to route to "
        "``/for-creators#plans``. If the destination has changed, "
        "update ``PLAN_CHOOSER_HREF`` in dashboard/page.tsx to match."
    )

    # The dashboard must not silently pick a plan for the reader.
    assert "plan=community" not in _code_only(dashboard_src), (
        "dashboard/page.tsx: Create a Collective must lead to plan "
        "selection, never straight into one plan's activation flow."
    )

    # An existing Creator skips plan selection by design.
    assert "CREATOR_HOME_HREF = '/creator-studio'" in dashboard_src, (
        "dashboard/page.tsx: an existing Creator should reach Creator "
        "Studio's plan-aware My World (which shows the collective "
        "allowance and an at-limit state) rather than being sent back "
        "through first-time plan selection."
    )


def test_dashboard_exposes_create_collective_in_both_states():
    """The dashboard must surface Create a Collective:
      1. as an inline empty-state action (zero-Collective users), and
      2. as a section-header action beside Your Collectives when
         the user already belongs to one or more.
    """
    assert _DASHBOARD.exists()
    dashboard_src = _DASHBOARD.read_text(encoding="utf-8")

    # (1) Empty-state helper renders the CTA. Guards against a
    # future refactor that removes the empty-state component.
    assert "EmptyCollectivesCard" in dashboard_src, (
        "dashboard/page.tsx: expected ``EmptyCollectivesCard`` "
        "component in the empty-state branch of Your Collectives — "
        "it holds the Create-a-Collective CTA for members with zero "
        "Collectives."
    )

    # (2) Populated-state section header renders the CTA via the
    # Section's ``action`` slot.
    assert (
        "action={cards.length > 0 ? <CreateCollectiveLink isCreator={isCreatorOrAdmin} /> : null}"
        in dashboard_src
    ), (
        "dashboard/page.tsx: expected the Your Collectives Section "
        "to wire ``<CreateCollectiveLink />`` into its ``action`` "
        "slot for the populated-state header. Removing this hides "
        "the creator pathway from members who already have "
        "Collectives."
    )
