"""
Canonical creator plan configuration (single source of truth).

The DB table `creator_plans` stores pricing and the fields needed for the
admin plan-editor UI. All *capability* rules (whether paid offers are
allowed, which Location scope applies, whether the collective needs approval,
etc.) live here so the app has one place to look up "what does this plan
allow?".

Plan slugs used across the platform:
    community    Free  — non-commercial, one collective, up to 100 members
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
    # Maximum number of Pathways per Collective. `None` means no cap
    # (Creator / Pro / Organisation). Community caps at 5.
    pathways_max_per_collective: Optional[int] = None
    # Maximum number of Offerings per Collective. `None` means no cap.
    # Community caps at 5.
    #
    # Scoped per Collective to match ``pathways_max_per_collective`` and
    # ``member_allowance_per_collective`` — the convention is that things
    # *inside* a Collective are capped per Collective, while the number of
    # Collectives themselves is capped per account
    # (``active_collective_limit``).
    #
    # The approved product rule is "five Offerings across all Collectives a
    # Community creator owns". Those are the same number here, because
    # Community's ``active_collective_limit`` is 1 and Offering management is
    # owner-only — so a Community creator can hold Offerings in at most one
    # Collective. Following the convention therefore delivers the intent
    # without inventing a second quota model. See the Phase B4 notes if
    # Community's collective allowance ever rises above 1, at which point
    # the two readings diverge and this becomes a real decision.
    offerings_max_per_collective: Optional[int] = None

    # ── Offering file allowances ───────────────────────────────────────
    #
    # `None` on these four means "no plan-specific cap — the platform
    # ceiling applies", matching `pathways_max_per_collective` and
    # `offerings_max_per_collective` above rather than the "unresolved,
    # awaiting a decision" reading in the module docstring. The
    # distinction matters because a byte limit is not only a commercial
    # choice: fc-api runs on a 0.5-CPU / 512 MB instance, so there is an
    # *infrastructure* ceiling that no plan may exceed and no account may
    # bypass. See `app.services.offering_limits`, which resolves a plan
    # against `MAX_OFFERING_*` in `app.services.offering_files` by taking
    # the smaller of the two. An unrestricted plan therefore lands on the
    # platform ceiling, never on "no limit at all".

    #: Downloadable resources in one Offering's current bundle. Files
    #: inside a ZIP count individually; an Office package counts once.
    #: Community 1, Creator / Portfolio 50.
    offering_files_max: Optional[int] = None

    #: Largest single upload. Community 10 MB, Creator 25 MB,
    #: Portfolio 50 MB.
    offering_file_max_bytes: Optional[int] = None

    #: Largest total for one Offering's current bundle. Community 10 MB,
    #: Creator 75 MB, Portfolio 150 MB.
    offering_bundle_max_bytes: Optional[int] = None

    #: May this plan sell a ZIP bundle at all? Community may not — a
    #: single file is its whole allowance, so an archive would be a way
    #: to ship fifty resources inside the one permitted upload.
    offering_zip_bundles_enabled: bool = False

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
    pathways_max_per_collective=5,   # capped at five Pathways
    offerings_max_per_collective=5,  # capped at five Offerings
    # One downloadable resource, 10 MB, no archives. The three work
    # together: without the ZIP prohibition, "one file" would mean "one
    # archive containing as many files as you like", and the file
    # allowance would enforce nothing.
    offering_files_max=1,
    offering_file_max_bytes=10 * 1024 * 1024,
    offering_bundle_max_bytes=10 * 1024 * 1024,
    offering_zip_bundles_enabled=False,
    location_scope="community_only",
    analytics_level="basic",
    paid_offers_enabled=False,
    pathways_enabled=True,   # community may run non-commercial pathways
    gatherings_enabled=True,
    resources_enabled=True,
    automations_enabled=False,
    commercial_use=False,
    # Product rule (2026-08-21): Community is self-serve and does not
    # require manual admin approval. Historically the flag was set True
    # but nothing in the codebase gated on it — it was only surfaced
    # for display. The flip is a semantic correction, not a policy
    # change to enforcement.
    approval_required=False,
    is_self_service=True,
    is_purchasable=True,
    transaction_fee_basis_points=None,  # N/A — no paid offers on Community
    storage_allowance_mb=None,  # TBD — surfaced as "To be defined" in UI
    card_headline=(
        "One non-commercial collective for up to 100 members."
    ),
    card_features=(
        "One active collective",
        "Up to 100 members",
        "One Creator",
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
    # No cap on how many Offerings, but a real cap on each one's bundle.
    offering_files_max=50,
    offering_file_max_bytes=25 * 1024 * 1024,
    offering_bundle_max_bytes=75 * 1024 * 1024,
    offering_zip_bundles_enabled=True,
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
    transaction_fee_basis_points=800,  # 8% on Creator paid offers
    storage_allowance_mb=None,          # TBD
    card_headline=(
        "One paid collective with commercial tools for up to 500 members."
    ),
    card_features=(
        "One active collective",
        "Up to 500 members",
        "One Creator",
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
    # Same file count as Creator; double the per-file and total size.
    # Customer-facing this plan is "Creator Portfolio" — see
    # ``frontend/src/lib/creatorPlanDisplay.ts``. The slug stays ``pro``.
    offering_files_max=50,
    offering_file_max_bytes=50 * 1024 * 1024,
    offering_bundle_max_bytes=150 * 1024 * 1024,
    offering_zip_bundles_enabled=True,
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
    # 4% from the 2026-10 pricing review. This constant is only the
    # fallback for a plan with no ``creator_plans`` row; checkout reads
    # the database row, so the live change is a World Management edit.
    # Both are updated together so they cannot disagree.
    transaction_fee_basis_points=400,  # 4% on Pro paid offers (lower tier)
    storage_allowance_mb=None,          # TBD
    card_headline=(
        "Up to five collectives with greater capacity, collaboration and growth tools."
    ),
    card_features=(
        "Up to 5 active collectives",
        "Pooled member allowance across collectives",
        "Multiple Creators per collective",
        "Full Atlas Location selection",
        "Paid memberships, pathways and resources",
        "Advanced analytics and automations",
    ),
)

FOUNDING_CREATOR = PlanCapability(
    slug="founding-creator",
    display_name="Founding Creator",
    tagline="Fresh Collective founder commercial terms.",
    positioning=(
        "Internal / complimentary plan for Fresh Collective founders "
        "and comped creators. Assigned manually by Fresh Collective; "
        "never shown in self-service plan selection."
    ),
    monthly_price_cents=0,
    active_collective_limit=None,           # unrestricted
    member_allowance_per_collective=None,   # unrestricted
    pooled_member_allowance=None,           # unrestricted
    caretaker_limit_per_collective=None,    # unrestricted
    pathways_max_per_collective=None,       # unrestricted
    offerings_max_per_collective=None,      # unrestricted
    # Unrestricted by plan. The four Offering allowances stay None, which
    # resolves to the *platform* ceiling rather than to no limit — a
    # founder's upload runs on the same 512 MB instance as everyone
    # else's, so the infrastructure bound is not a commercial perk to
    # waive. In practice this plan therefore gets the Portfolio
    # allowance; see ``app.services.offering_limits``.
    offering_files_max=None,
    offering_file_max_bytes=None,
    offering_bundle_max_bytes=None,
    offering_zip_bundles_enabled=True,
    storage_allowance_mb=None,              # unrestricted
    location_scope="atlas_full",
    analytics_level="advanced",
    paid_offers_enabled=True,
    pathways_enabled=True,
    gatherings_enabled=True,
    resources_enabled=True,
    automations_enabled=True,
    commercial_use=True,
    approval_required=False,
    # is_self_service + is_purchasable both False: never surfaced in
    # self-service signup, never billed via Stripe. Assignment is
    # manual via admin Change-Plan flow, mirroring Organisation's
    # handling (but with commercial abilities enabled, unlike
    # Organisation which has TBD tailored terms).
    is_self_service=False,
    is_purchasable=False,
    transaction_fee_basis_points=0,   # explicit 0% — no fallback path
    card_headline="Fresh Collective founder — no monthly charge, 0% fee.",
    card_features=(
        "0% transaction fee",
        "No monthly platform charge",
        "Unrestricted Collectives, pathways, and members",
        "Assigned by Fresh Collective",
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
    # Tailored terms, so no plan-specific Offering caps are asserted
    # here; these resolve to the platform ceiling like Founding Creator's.
    offering_files_max=None,
    offering_file_max_bytes=None,
    offering_bundle_max_bytes=None,
    offering_zip_bundles_enabled=True,
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


ALL_PLANS: tuple[PlanCapability, ...] = (
    COMMUNITY, CREATOR, PRO, FOUNDING_CREATOR, ORGANISATION,
)
PURCHASABLE_PLANS: tuple[PlanCapability, ...] = tuple(
    p for p in ALL_PLANS if p.is_purchasable
)
PLANS_BY_SLUG: dict[str, PlanCapability] = {p.slug: p for p in ALL_PLANS}

# Slugs that admin plan-CRUD is allowed to create in the DB. Every
# recognised slug MUST have a PlanCapability constant above — otherwise
# every capability lookup would return None at runtime and the guard
# system would silently permit actions on that plan. Organisation is
# deliberately excluded: it's a synthetic capability-only entry (no DB
# row) rendered via ``_creator_plan_out(None, ORGANISATION)`` in the
# billing endpoint.
RECOGNISED_PLAN_SLUGS: frozenset[str] = frozenset({
    "community",
    "creator",
    "pro",
    "founding-creator",
})


def get_plan_capability(slug: str | None) -> PlanCapability | None:
    """Look up capability record by slug. Returns None if the slug is
    unknown — callers should treat that as "no capability, fall back to
    Community-equivalent restrictions or refuse the action". Never guess."""
    if not slug:
        return None
    return PLANS_BY_SLUG.get(slug)


