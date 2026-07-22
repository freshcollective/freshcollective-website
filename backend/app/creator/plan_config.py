"""
Canonical creator plan configuration (single source of truth).

The DB table `creator_plans` stores pricing and the fields needed for the
admin plan-editor UI. All *capability* rules (whether paid offers are
allowed, which Location scope applies, whether the collective needs approval,
etc.) live here so the app has one place to look up "what does this plan
allow?".

Plan slugs used across the platform:
    community    Free  — non-commercial, one approved collective, up to 100 members
    creator      $19   — commercial, one collective, up to 500 members
    pro          $79   — commercial, up to 5 collectives, pooled member allowance TBD
    organisation Talk to us — not a self-service plan; flagged as a lead pathway

Platform Owner is deliberately NOT represented in this file. Platform Owner
is a separate account type and does not belong to any creator plan (see
docs/permissions-matrix.md).

Values marked `None` on numeric fields mean the number is intentionally
unresolved and awaiting a product decision. Do not substitute a guessed
value — surface `None` to the caller so the UI can show "To be defined".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Location scope
# ---------------------------------------------------------------------------
#
# 'community_only'        — only COMMUNITY Locations (intentionally smaller,
#                           more intimate gathering places). Community plan.
# 'atlas_full'            — every active ATLAS Location. Creator and Pro.
# 'atlas_and_cornerstones' — Atlas + Cornerstones. Reserved for Platform
#                           Owner. No creator plan uses this scope.
# ---------------------------------------------------------------------------

LocationScope = str  # 'community_only' | 'atlas_full' | 'atlas_and_cornerstones'


# ---------------------------------------------------------------------------
# Analytics level
# ---------------------------------------------------------------------------
#
# 'basic'    — collective home stats only.
# 'standard' — plus member and pathway breakdowns.
# 'advanced' — full analytics + cohort/retention (Pro).
# ---------------------------------------------------------------------------

AnalyticsLevel = str  # 'basic' | 'standard' | 'advanced'


# ---------------------------------------------------------------------------
# Plan capability dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanCapability:
    """Immutable capability record for one plan.

    Numeric fields typed as `Optional[int]`: `None` means "unresolved,
    awaiting decision". Do not treat `None` as "unlimited" — Platform
    Owner is the only account with true "unlimited" and Owner does not
    resolve through this table.
    """

    # Identity
    slug: str
    display_name: str

    # Positioning
    tagline: str
    positioning: str

    # Pricing
    monthly_price_cents: Optional[int]  # None for Organisation ("Talk to us")
    currency: str = "AUD"

    # Numeric capacity
    active_collective_limit: Optional[int] = None
    member_allowance_per_collective: Optional[int] = None
    pooled_member_allowance: Optional[int] = None
    caretaker_limit_per_collective: Optional[int] = None
    storage_allowance_mb: Optional[int] = None

    # Categorical capabilities
    location_scope: LocationScope = "atlas_full"
    analytics_level: AnalyticsLevel = "basic"

    # Boolean capabilities
    paid_offers_enabled: bool = False
    pathways_enabled: bool = False
    gatherings_enabled: bool = False
    resources_enabled: bool = False
    automations_enabled: bool = False
    commercial_use: bool = False
    approval_required: bool = False
    is_self_service: bool = True    # False for Organisation
    is_purchasable: bool = True     # False for Organisation

    # Fees
    transaction_fee_basis_points: Optional[int] = None

    # UI copy shown on the plan card
    card_headline: str = ""
    card_features: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------


COMMUNITY = PlanCapability(
    slug="community",
    display_name="Community",
    tagline="Contribute freely.",
    positioning=(
        "For people contributing a genuine community to the Fresh Collective "
        "world without using it as a commercial business."
    ),
    monthly_price_cents=0,
    active_collective_limit=1,
    member_allowance_per_collective=100,
    caretaker_limit_per_collective=1,
    location_scope="community_only",
    analytics_level="basic",
    paid_offers_enabled=False,
    pathways_enabled=True,   # community may run non-commercial pathways
    gatherings_enabled=True,
    resources_enabled=True,
    automations_enabled=False,
    commercial_use=False,
    approval_required=True,
    is_self_service=True,
    is_purchasable=True,
    transaction_fee_basis_points=None,  # N/A — no paid offers on Community
    storage_allowance_mb=None,  # TBD — surfaced as "To be defined" in UI
    card_headline=(
        "One approved, non-commercial collective for up to 100 members."
    ),
    card_features=(
        "One approved active collective",
        "Up to 100 members",
        "One caretaker",
        "Community Location choices",
        "Community, pathway, gathering and resource basics",
        "No paid offers",
    ),
)

CREATOR = PlanCapability(
    slug="creator",
    display_name="Creator",
    tagline="Begin creating commercially.",
    positioning="For creators beginning to build a commercial collective.",
    monthly_price_cents=1900,
    active_collective_limit=1,
    member_allowance_per_collective=500,
    caretaker_limit_per_collective=1,
    location_scope="atlas_full",
    analytics_level="standard",
    paid_offers_enabled=True,
    pathways_enabled=True,
    gatherings_enabled=True,
    resources_enabled=True,
    automations_enabled=False,
    commercial_use=True,
    approval_required=False,
    is_self_service=True,
    is_purchasable=True,
    transaction_fee_basis_points=None,  # TBD — higher tier (%)
    storage_allowance_mb=None,          # TBD
    card_headline=(
        "One paid collective with commercial tools for up to 500 members."
    ),
    card_features=(
        "One active collective",
        "Up to 500 members",
        "One caretaker",
        "Full Atlas Location selection",
        "Paid memberships, pathways and resources",
        "Standard analytics",
    ),
)

PRO = PlanCapability(
    slug="pro",
    display_name="Pro",
    tagline="Grow a serious collective business.",
    positioning="For established creators growing a serious collective business.",
    monthly_price_cents=7900,
    active_collective_limit=5,
    member_allowance_per_collective=None,   # pooled instead
    pooled_member_allowance=None,           # TBD
    caretaker_limit_per_collective=None,    # TBD — multiple
    location_scope="atlas_full",
    analytics_level="advanced",
    paid_offers_enabled=True,
    pathways_enabled=True,
    gatherings_enabled=True,
    resources_enabled=True,
    automations_enabled=True,
    commercial_use=True,
    approval_required=False,
    is_self_service=True,
    is_purchasable=True,
    transaction_fee_basis_points=None,  # TBD — lower tier (%)
    storage_allowance_mb=None,          # TBD
    card_headline=(
        "Up to five collectives with greater capacity, collaboration and growth tools."
    ),
    card_features=(
        "Up to 5 active collectives",
        "Pooled member allowance across collectives",
        "Multiple caretakers per collective",
        "Full Atlas Location selection",
        "Paid memberships, pathways and resources",
        "Advanced analytics and automations",
    ),
)

ORGANISATION = PlanCapability(
    slug="organisation",
    display_name="Organisation",
    tagline="Expand with tailored support.",
    positioning=(
        "For organisations requiring larger-scale access, teams, tailored "
        "implementation or enterprise support."
    ),
    monthly_price_cents=None,               # "Talk to us"
    active_collective_limit=None,
    member_allowance_per_collective=None,
    pooled_member_allowance=None,
    caretaker_limit_per_collective=None,
    location_scope="atlas_full",
    analytics_level="advanced",
    paid_offers_enabled=True,
    pathways_enabled=True,
    gatherings_enabled=True,
    resources_enabled=True,
    automations_enabled=True,
    commercial_use=True,
    approval_required=False,
    is_self_service=False,
    is_purchasable=False,
    transaction_fee_basis_points=None,      # TBD (tailored)
    storage_allowance_mb=None,              # TBD
    card_headline="Tailored support for larger teams and organisations.",
    card_features=(
        "Custom capacity and team access",
        "Tailored implementation and onboarding",
        "Enterprise support",
    ),
)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


ALL_PLANS: tuple[PlanCapability, ...] = (COMMUNITY, CREATOR, PRO, ORGANISATION)
PURCHASABLE_PLANS: tuple[PlanCapability, ...] = tuple(
    p for p in ALL_PLANS if p.is_purchasable
)
PLANS_BY_SLUG: dict[str, PlanCapability] = {p.slug: p for p in ALL_PLANS}


def get_plan_capability(slug: str | None) -> PlanCapability | None:
    """Look up capability record by slug. Returns None if the slug is
    unknown — callers should treat that as "no capability, fall back to
    Community-equivalent restrictions or refuse the action". Never guess."""
    if not slug:
        return None
    return PLANS_BY_SLUG.get(slug)


