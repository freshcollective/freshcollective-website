"""Invariants over the canonical creator plan capability records.

Small, targeted assertions that catch regressions where a copy or
policy change to `plan_config.py` accidentally moves a rule the wider
product depends on.
"""

from __future__ import annotations

from app.creator.plan_config import (
    COMMUNITY,
    CREATOR,
    ORGANISATION,
    PRO,
)


# ---------------------------------------------------------------------------
# Community — the free, non-commercial entry plan
# ---------------------------------------------------------------------------


def test_community_is_free():
    assert COMMUNITY.monthly_price_cents == 0


def test_community_is_self_serve_no_approval_required():
    """Product rule (2026-08-21): Community does not require approval.

    Historically the capability record had ``approval_required=True``,
    but nothing in the backend actually gated on it. Ordinary creators
    picking the Community plan must not be blocked behind manual admin
    approval — they self-serve from the same Build Your Collective
    ritual as paid plans.
    """
    assert COMMUNITY.is_self_service is True
    assert COMMUNITY.approval_required is False


def test_community_forbids_paid_offers():
    assert COMMUNITY.paid_offers_enabled is False
    assert COMMUNITY.commercial_use is False
    # Fee is N/A because paid offers aren't allowed.
    assert COMMUNITY.transaction_fee_basis_points is None


def test_community_capacity_is_one_collective_up_to_100_members():
    assert COMMUNITY.active_collective_limit == 1
    assert COMMUNITY.member_allowance_per_collective == 100


def test_community_pathways_cap_is_five():
    """The homepage pricing card claims Community is limited to "Up to
    5 Pathways". That claim must be backed by the canonical config —
    if this ever changes, the homepage bullet in ``HomePricing.tsx``
    needs to update in the same PR."""
    assert COMMUNITY.pathways_max_per_collective == 5


# ---------------------------------------------------------------------------
# Creator + Pro — the two commercial plans that drive the pricing story
# ---------------------------------------------------------------------------


def test_creator_price_and_fee():
    """Homepage pricing copy quotes these directly. If either changes,
    ``frontend/src/lib/creatorPlanPricing.ts`` must update in the same
    PR — the FE mirror is a hand-maintained copy."""
    assert CREATOR.monthly_price_cents == 1900
    assert CREATOR.transaction_fee_basis_points == 800


def test_pro_price_and_fee():
    assert PRO.monthly_price_cents == 7900
    assert PRO.transaction_fee_basis_points == 300


def test_pro_fee_is_lower_than_creator_fee():
    """The whole break-even story on the homepage assumes Pro's fee is
    lower than Creator's. Guard against an accidental swap."""
    assert PRO.transaction_fee_basis_points < CREATOR.transaction_fee_basis_points


# ---------------------------------------------------------------------------
# Organisation — sales-led, not self-serve
# ---------------------------------------------------------------------------


def test_organisation_is_not_self_service_or_purchasable():
    assert ORGANISATION.is_self_service is False
    assert ORGANISATION.is_purchasable is False
    assert ORGANISATION.monthly_price_cents is None  # "Talk to us"
