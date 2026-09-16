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
"""

from __future__ import annotations

from pathlib import Path


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

    assert "CREATE_COLLECTIVE_HREF = '/for-creators'" in dashboard_src, (
        "dashboard/page.tsx: expected the constant "
        "``CREATE_COLLECTIVE_HREF = '/for-creators'`` to define the "
        "Create-a-Collective destination. Both CTAs (empty-state + "
        "section-header) must use it — see the 2026-09-16 creator "
        "onboarding-discoverability fix."
    )
    assert 'href="/for-creators">Create a Collective' in hero_src, (
        "home/HomeHero.tsx: expected the public hero CTA to route to "
        "``/for-creators``. If the destination has changed, update "
        "``CREATE_COLLECTIVE_HREF`` in dashboard/page.tsx to match."
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
    assert "action={cards.length > 0 ? <CreateCollectiveLink /> : null}" in dashboard_src, (
        "dashboard/page.tsx: expected the Your Collectives Section "
        "to wire ``<CreateCollectiveLink />`` into its ``action`` "
        "slot for the populated-state header. Removing this hides "
        "the creator pathway from members who already have "
        "Collectives."
    )
