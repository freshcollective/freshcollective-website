from datetime import datetime

from pydantic import BaseModel


class AdminUserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    email: str
    name: str | None
    role: str
    created_at: datetime


class RoleUpdateRequest(BaseModel):
    role: str

    def validate_role(self) -> str:
        if self.role not in ("user", "admin"):
            raise ValueError("Role must be 'user' or 'admin'.")
        return self.role


class CreatorBillingRow(BaseModel):
    model_config = {"from_attributes": True}

    user_id: str
    name: str | None
    email: str
    current_plan_name: str
    current_plan_slug: str
    monthly_price_cents: int
    currency: str
    transaction_fee_basis_points: int
    # `None` means unlimited — reserved for the platform owner. The
    # source of truth is `plan_guards.effective_collective_allowance`
    # so the display can never disagree with the guard.
    collective_limit: int | None
    subscription_status: str
    collectives_used: int
    pathways_used: int
    joined_at: datetime
    # `True` when this row is the platform owner's. Owner access is
    # inherent to the account and does not depend on any
    # `CreatorSubscription` row — a historical cancelled sub for a
    # Community plan (say) is preserved in the DB unchanged, but the
    # effective-access columns (Access / Status / Ends) render as owner
    # access, not as the historical sub's cancelled state.
    is_platform_owner: bool = False


# ---------------------------------------------------------------------------
# Payment Transactions
# ---------------------------------------------------------------------------

class AdminPaymentSummary(BaseModel):
    """Platform-wide payment summary for admin dashboard."""
    # Revenue totals (succeeded transactions only, excluding creator subscription payments)
    total_gross_amount_cents: int
    total_platform_fee_cents: int
    total_creator_net_amount_cents: int
    total_processing_fee_cents: int

    # Payout tracking
    pending_payout_cents: int   # net_creator for pending-payout succeeded transactions

    # Transaction counts by status
    succeeded_count: int
    refunded_count: int
    disputed_count: int
    pending_count: int
    failed_count: int


class PaymentTransactionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    transaction_type: str
    status: str
    payment_provider: str

    payer_user_id: str | None
    creator_user_id: str | None
    space_id: str | None
    pathway_id: str | None
    entitlement_id: str | None
    creator_plan_id: str | None
    creator_subscription_id: str | None

    currency: str
    gross_amount_cents: int
    platform_fee_basis_points: int
    platform_fee_cents: int
    processing_fee_cents: int | None
    net_creator_amount_cents: int | None
    net_platform_amount_cents: int | None

    # Provider IDs intentionally included for admin visibility
    # (do NOT expose provider secret keys — only IDs for lookup)
    provider_checkout_session_id: str | None
    provider_payment_intent_id: str | None
    provider_charge_id: str | None
    provider_invoice_id: str | None
    provider_subscription_id: str | None

    payment_option_id: str | None = None
    payment_option_schedule_id: str | None = None

    notes: str | None
    stripe_mode: str
    payout_status: str
    payout_marked_at: datetime | None
    payout_reference: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Grant access — non-financial admin action replacing the old
# "Manual purchase" flow. See docs comment on POST /api/admin/entitlements/grant.
# ---------------------------------------------------------------------------

# Structured grant reasons. Kept in sync with the CHECK constraint on
# `pathway_entitlements.grant_reason` (migration 081). "other" is the only
# reason that requires a note; the note is recommended for every reason.
GRANT_REASONS: tuple[str, ...] = (
    "comp",         # Complimentary access
    "beta",         # Beta or testing access
    "migration",    # Migration from another system
    "correction",   # Purchase correction (fix a broken paid purchase)
    "replacement",  # Replacement access (post-refund, lost access, etc.)
    "other",        # Anything else — note required
)


class GrantPathwayAccessRequest(BaseModel):
    """Body of ``POST /api/admin/entitlements/grant``.

    ``member_user_id`` intentionally replaces the old ``payer_user_id``
    field so no code path can accidentally treat this as a payment.
    """

    member_user_id: str
    pathway_id: str
    reason: str
    note: str | None = None


class GrantPathwayAccessResult(BaseModel):
    entitlement_id: str
    entitlement_source: str
    reactivated: bool           # true when a prior revoked entitlement was reactivated
    reason: str
    note: str | None
    granted_at: datetime
    granted_by_user_id: str
    # Denormalised for the success UI
    member_name: str | None
    member_email: str
    pathway_title: str
    space_name: str
    space_slug: str


# ---------------------------------------------------------------------------
# Simple list types (for modal dropdowns)
# ---------------------------------------------------------------------------

class SimpleUserRow(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str | None
    email: str


class SimplePaidPathwayRow(BaseModel):
    id: str
    title: str
    space_id: str
    space_name: str
    space_slug: str
    access_type: str
    price_cents: int
    currency: str
    billing_interval: str | None
    creator_fee_basis_points: int


# ---------------------------------------------------------------------------
# Platform admin — new owner/admin panel
# ---------------------------------------------------------------------------

class MotherWorldMoment(BaseModel):
    """A natural-language moment for the Recent Moments feed.

    Written as a sentence about a person or community, not an audit record.
    See `_collect_recent_moments` in admin/routes.py.
    """
    kind: str          # 'collective' | 'creator' | 'transaction' | 'gathering' | 'signup'
    message: str       # e.g. "Emily created The Writers Loft."
    when: datetime
    href: str | None = None  # optional link into the world


class MotherWorldHealth(BaseModel):
    """Runtime status for the World Health panel. Green/gold/coral only."""
    platform_ok: bool = True
    stripe_ok: bool = False
    webhook_configured: bool = False
    standalone_gathering_sales_enabled: bool = False
    stripe_mode: str = "test"
    # Backup automation isn't wired to a scheduler yet; kept nullable so
    # the UI can render "Manual only" honestly rather than fabricating.
    last_backup_at: datetime | None = None


class AdminPlatformOverview(BaseModel):
    # Collectives
    total_collectives: int
    active_collectives: int
    draft_collectives: int
    archived_collectives: int
    # Users by role
    total_users: int
    admin_users: int
    creator_users: int
    member_users: int
    # Access queue
    pending_access_requests: int
    pending_invitations: int
    # Revenue (succeeded member-purchase transactions)
    total_gross_cents: int
    succeeded_transactions: int
    # Stage 2 (Mother World redesign) additions ------------------------------
    upcoming_gatherings: int = 0
    total_gross_cents_today: int = 0
    total_gross_cents_7d: int = 0
    failed_transactions_7d: int = 0
    recent_moments: list[MotherWorldMoment] = []
    world_health: MotherWorldHealth = MotherWorldHealth()


class AdminCollectiveRow(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    is_public: bool
    has_paid_internal_content: bool
    creator_id: str | None = None
    creator_name: str | None
    creator_email: str | None
    member_count: int
    pathway_count: int
    gathering_count: int
    resource_count: int
    created_at: datetime
    updated_at: datetime
    # Gallery / List additions --------------------------------------------
    # These power the redesigned /admin/collectives page. Every value is
    # derived on the server so the client renders a single, truthful string
    # per collective without recomputing from raw counts.
    cover_image_url: str | None = None
    location_id: str | None = None
    location_name: str | None = None
    # The curated hero artwork of the Atlas Location this collective lives
    # inside. Sourced from Location.hero_artwork_url — the same field the
    # member-facing CollectiveIdentityHeader reads. This is the collective's
    # true visual identity under Atlas v1.2. `Space.island_artwork_url`
    # (migration 064) is a stale column that no form writes to; do not use
    # it as a source anywhere new.
    location_hero_artwork_url: str | None = None
    last_activity_at: datetime | None = None
    next_gathering_at: datetime | None = None
    new_members_7d: int = 0
    health: str = "healthy"           # 'healthy' | 'quiet' | 'needs_attention'
    activity_phrase: str = ""         # e.g. "Active today", "Sleeping since June"


class AdminCreatorCollectiveChip(BaseModel):
    """A small reference to one of a creator's Collectives — enough to
    render a chip on the Creator card / mini-card on the detail page.
    Full detail lives on /admin/collectives/{slug}."""
    id: str
    slug: str
    name: str
    location_name: str | None = None
    location_hero_artwork_url: str | None = None


class AdminCreatorRow(BaseModel):
    id: str
    name: str | None
    email: str
    role: str
    created_at: datetime
    # Kept for backwards compatibility (billing / creator-plan consumers).
    # Non-archived total = published + draft. New surfaces should prefer
    # the two explicit fields below so published and draft never blur.
    collective_count: int
    published_collective_count: int = 0
    draft_collective_count: int = 0
    plan_name: str
    subscription_status: str
    # Gallery / List additions ------------------------------------------------
    # Derived server-side so the client renders one truthful phrase per
    # creator with no recomputation. Health aggregates from each creator's
    # Collectives; the two pages must never disagree about who's healthy.
    avatar_url: str | None = None
    collectives: list[AdminCreatorCollectiveChip] = []
    total_members_reached: int = 0
    last_activity_at: datetime | None = None
    next_gathering_at: datetime | None = None
    new_members_30d: int = 0
    health: str = "new"                # 'flourishing' | 'new' | 'quiet' | 'needs_support'
    activity_phrase: str = ""


class CollectiveRef(BaseModel):
    """Compact reference to a collective — the shape returned inside
    an AdminUserRow's `joined_collectives` / `owned_collectives` lists."""

    id: str
    name: str
    slug: str


class AdminUserRow(BaseModel):
    id: str
    name: str | None
    email: str
    # Derived, human-facing role badges: any subset of
    # ["owner", "admin", "creator", "member"]. Ordered from most
    # privileged to least; the frontend renders each as its own pill.
    roles: list[str]
    created_at: datetime
    # Full lists (not counts) — the Members page shows the actual
    # collective names people belong to and have created, rather than
    # abstract totals.
    joined_collectives: list[CollectiveRef]
    owned_collectives: list[CollectiveRef]


class AdminAccessRequestRow(BaseModel):
    id: str
    space_id: str
    space_name: str
    space_slug: str
    user_id: str
    user_name: str | None
    user_email: str
    status: str
    message: str | None
    created_at: datetime


class AdminInvitationRow(BaseModel):
    id: str
    space_id: str
    space_name: str
    space_slug: str
    email: str
    name: str | None
    role: str
    invited_by_name: str | None
    invited_by_email: str | None
    created_at: datetime


class AdminAccessResponse(BaseModel):
    access_requests: list[AdminAccessRequestRow]
    invitations: list[AdminInvitationRow]


# ---------------------------------------------------------------------------
# Creator plans + subscriptions (Money section)
# ---------------------------------------------------------------------------

class AdminCreatorPlanRow(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    # Nullable: Organisation has no monthly price ("Talk to us").
    monthly_price_cents: int | None
    currency: str
    # Nullable: Community has no transaction fee (no paid offers); Organisation
    # is tailored and TBD.
    transaction_fee_basis_points: int | None
    # Nullable: Organisation has no collective limit (tailored).
    collective_limit: int | None
    is_active: bool
    active_subscriptions: int
    created_at: datetime | None = None

    # Canonical capability fields (from plan_config.PlanCapability). The
    # admin Plan Catalogue uses these to decide which summary cards to
    # show per plan — no slug hardcoding on the frontend.
    plan_type: str = "subscription"  # 'subscription' | 'enterprise'
    paid_offers_enabled: bool = True
    commercial_use: bool = True
    is_purchasable: bool = True
    # Per-collective member allowance sourced from PlanCapability — the
    # same value the enforcement path reads, so the catalogue and the
    # limit checks can never drift.
    member_allowance_per_collective: int | None = None


class AdminCreatorPlanCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    monthly_price_cents: int
    currency: str = "AUD"
    transaction_fee_basis_points: int
    collective_limit: int
    is_active: bool = True


class AdminCreatorPlanEdit(BaseModel):
    """Body of ``PATCH /api/admin/creator-plans/{plan_id}``.

    Every field is optional; the endpoint updates only what is supplied.
    Slug is deliberately not included — it is a stable system identifier
    that other tables and configuration reference by string.
    """

    name: str | None = None
    description: str | None = None
    monthly_price_cents: int | None = None
    transaction_fee_basis_points: int | None = None
    collective_limit: int | None = None
    is_active: bool | None = None


class AdminCreatorSubscriptionRow(BaseModel):
    id: str
    user_id: str
    user_name: str | None
    user_email: str
    plan_id: str
    plan_name: str
    plan_slug: str
    monthly_price_cents: int
    currency: str
    transaction_fee_basis_points: int
    status: str
    starts_at: datetime
    ends_at: datetime | None
    # Access source — 'stripe_paid' or 'manual_grant'. Drives the badge on
    # the Creator Subscriptions page so paid never looks like granted.
    source: str
    grant_reason: str | None = None
    granted_by_user_id: str | None = None
    grant_note: str | None = None
    revoked_at: datetime | None = None
    stripe_subscription_id: str | None
    stripe_customer_id: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Grant creator-plan access — non-financial admin action
# ---------------------------------------------------------------------------

PLAN_GRANT_REASONS: tuple[str, ...] = (
    "comp",         # Complimentary access
    "beta",         # Beta or testing access
    "migration",    # Migration from another system
    "correction",   # Subscription correction
    "temporary",    # Temporary access
    "replacement",  # Replacement access
    "internal",     # Internal use
    "other",        # Anything else — note required
)

# Duration shortcuts the API accepts. `indefinite` is the only way to say
# "no end date" — a missing/empty duration is not treated as indefinite.
PLAN_GRANT_DURATIONS: tuple[str, ...] = (
    "1_month", "3_months", "6_months", "12_months", "indefinite",
)


class GrantPlanAccessRequest(BaseModel):
    creator_user_id: str
    plan_slug: str
    reason: str
    note: str | None = None
    # Exactly one of `duration` or `ends_at` is expected. If both are
    # provided, `ends_at` wins. If neither is provided the API rejects
    # the request — indefinite grants must be explicit.
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    duration: str | None = None


class ExtendPlanAccessRequest(BaseModel):
    # Same either/or rule as GrantPlanAccessRequest.
    ends_at: datetime | None = None
    duration: str | None = None
    note: str | None = None


class RevokePlanAccessRequest(BaseModel):
    reason: str | None = None
    note: str | None = None


class PlanGrantHistoryRow(BaseModel):
    id: str
    action: str
    plan_slug: str
    plan_name: str
    starts_at: datetime | None
    ends_at: datetime | None
    reason: str | None
    note: str | None
    actor_user_id: str | None
    actor_name: str | None
    created_at: datetime


class GrantPlanAccessResult(BaseModel):
    subscription_id: str
    source: str
    status: str
    reason: str
    note: str | None
    starts_at: datetime
    ends_at: datetime | None
    granted_at: datetime
    granted_by_user_id: str
    creator_name: str | None
    creator_email: str
    plan_slug: str
    plan_name: str
    reactivated: bool


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

class AdminRevenueSummary(BaseModel):
    # Fresh Collective revenue
    total_fc_revenue_cents: int
    subscription_revenue_cents: int   # creator sub fees paid to FC
    platform_fee_revenue_cents: int   # platform fees retained from member purchases
    # Gross creator sales (member purchases of creator content)
    total_gross_sales_cents: int
    total_creator_net_cents: int
    # Payout tracking
    paid_out_cents: int
    pending_payout_cents: int
    # Transaction counts (all types)
    succeeded_transactions: int
    refunded_transactions: int
    failed_transactions: int


# ---------------------------------------------------------------------------
# Periodic summary wrappers (Commerce section — Stage 1)
#
# Half-open [starts_at, ends_at) UTC windows, matching the naive UTC
# storage of `PaymentTransaction.created_at`. `starts_at` and `ends_at`
# are `None` only for the "all_time" period. `previous` is `None` for
# "all_time" — never a fabricated zero comparison. See
# `app/core/periods.py` for the exact boundary definitions.
# ---------------------------------------------------------------------------


class PeriodBoundsOut(BaseModel):
    label: str
    starts_at: datetime | None = None   # inclusive
    ends_at: datetime | None = None     # exclusive


class AdminPeriodicPaymentSummary(BaseModel):
    period: str                                  # 'this_month' | 'last_month' | 'this_fy' | 'all_time'
    stripe_mode: str | None = None               # echoes the requested filter for clarity
    current_bounds: PeriodBoundsOut
    current: AdminPaymentSummary
    previous_bounds: PeriodBoundsOut | None = None
    previous: AdminPaymentSummary | None = None


class AdminPeriodicRevenueSummary(BaseModel):
    period: str
    stripe_mode: str | None = None
    current_bounds: PeriodBoundsOut
    current: AdminRevenueSummary
    previous_bounds: PeriodBoundsOut | None = None
    previous: AdminRevenueSummary | None = None


# ---------------------------------------------------------------------------
# Commerce overview (Stage 2)
#
# One-request page shape for /admin/commerce (nee /admin/revenue). Composes
# the periodic revenue summary, a small growth counter, and a short
# "recent movement" list — enough for the calm overview described in the
# Stage 0 IA. Detailed breakdowns live on Transactions.
# ---------------------------------------------------------------------------


class GrowthSummary(BaseModel):
    """Who arrived during the period. Context for financial movement,
    not a KPI in its own right — the frontend renders these quietly.
    """
    new_creators: int      # users with role in {creator, admin}
    new_members: int       # users with role = user
    new_collectives: int   # spaces not archived


class CommerceMovementEvent(BaseModel):
    """A single row in the "Recent movement" list on the Commerce
    overview. Denormalised for display (payer/collective names inlined)
    so the frontend can render without extra lookups.
    """
    id: str
    label: str            # e.g. "Simone joined EMBODY"
    kind: str             # 'subscription' | 'purchase' | 'ticket' | 'refund' | 'adjustment' | 'other'
    amount_cents: int
    currency: str
    status: str           # 'succeeded' | 'refunded' | 'failed' | 'pending' | ...
    occurred_at: datetime
    stripe_mode: str


class CommerceWindow(BaseModel):
    """A single [starts_at, ends_at) window's revenue + growth pair."""
    bounds: PeriodBoundsOut
    revenue: AdminRevenueSummary
    growth: GrowthSummary


class AdminCommerceOverview(BaseModel):
    period: str
    stripe_mode: str                # the mode actually used to filter (echoed)
    test_mode_active: bool          # true when the platform is currently in Stripe test mode
    current: CommerceWindow
    previous: CommerceWindow | None = None
    recent_movements: list[CommerceMovementEvent]


class AdminRevenueByCreatorRow(BaseModel):
    creator_user_id: str
    creator_name: str | None
    creator_email: str
    collective_count: int
    # From member purchases of creator content
    gross_sales_cents: int
    platform_fees_cents: int
    creator_net_cents: int
    # Creator subscription fees paid to FC
    subscription_revenue_cents: int
    # Total FC revenue attributable to this creator
    total_fc_revenue_cents: int
    # Payout tracking
    paid_out_cents: int
    pending_payout_cents: int


# ---------------------------------------------------------------------------
# Transactions ledger (Stage 3)
#
# Denormalised row shape for the Transactions page. Buyer / creator /
# collective / pathway names are inlined so the UI never has to look them
# up. Stripe provider IDs and internal foreign keys are **deliberately
# omitted** — the ledger view is not a debugging surface. The row `id`
# is retained only for React keys; the UI does not render it.
# ---------------------------------------------------------------------------


class LedgerRow(BaseModel):
    id: str                          # React key only — never rendered
    created_at: datetime
    transaction_type: str
    status: str
    payout_status: str
    provider: str                    # 'stripe' | 'manual'
    stripe_mode: str                 # 'test' | 'live'
    # Denormalised names
    payer_name: str | None
    payer_email: str | None
    creator_id: str | None           # for client-side creator filter matching
    creator_name: str | None
    creator_email: str | None
    space_name: str | None
    pathway_title: str | None
    # Money
    currency: str
    gross_amount_cents: int
    platform_fee_cents: int
    net_creator_amount_cents: int | None
