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
    collective_limit: int
    subscription_status: str
    collectives_used: int
    pathways_used: int
    joined_at: datetime


class AdminPlanChangeRequest(BaseModel):
    creator_plan_slug: str
    note: str | None = None


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

    notes: str | None
    payout_status: str
    payout_marked_at: datetime | None
    payout_reference: str | None
    created_at: datetime
    updated_at: datetime


class ManualPaymentCreateRequest(BaseModel):
    transaction_type: str
    status: str = "succeeded"
    payment_provider: str = "manual"

    payer_user_id: str | None = None
    creator_user_id: str | None = None
    space_id: str | None = None
    pathway_id: str | None = None
    entitlement_id: str | None = None
    creator_plan_id: str | None = None
    creator_subscription_id: str | None = None

    currency: str = "AUD"
    gross_amount_cents: int
    platform_fee_basis_points: int = 0
    platform_fee_cents: int = 0
    net_creator_amount_cents: int | None = None
    net_platform_amount_cents: int | None = None

    notes: str | None = None


# ---------------------------------------------------------------------------
# Manual purchase simulation
# ---------------------------------------------------------------------------

class ManualPathwayPurchaseRequest(BaseModel):
    payer_user_id: str
    pathway_id: str
    notes: str | None = None


class ManualPathwayPurchaseResult(BaseModel):
    transaction_id: str
    entitlement_id: str
    entitlement_source: str

    payer_name: str | None
    payer_email: str
    pathway_title: str
    space_name: str
    space_slug: str

    currency: str
    gross_amount_cents: int
    platform_fee_basis_points: int
    platform_fee_cents: int
    net_creator_amount_cents: int
    net_platform_amount_cents: int


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


class AdminCollectiveRow(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    is_public: bool
    has_paid_internal_content: bool
    creator_name: str | None
    creator_email: str | None
    member_count: int
    pathway_count: int
    gathering_count: int
    resource_count: int
    created_at: datetime
    updated_at: datetime


class AdminCreatorRow(BaseModel):
    id: str
    name: str | None
    email: str
    role: str
    created_at: datetime
    collective_count: int
    plan_name: str
    subscription_status: str


class AdminUserRow(BaseModel):
    id: str
    name: str | None
    email: str
    role: str
    created_at: datetime
    joined_collectives: int
    owned_collectives: int


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
    monthly_price_cents: int
    currency: str
    transaction_fee_basis_points: int
    collective_limit: int
    is_active: bool
    active_subscriptions: int
    created_at: datetime


class AdminCreatorPlanCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    monthly_price_cents: int
    currency: str = "AUD"
    transaction_fee_basis_points: int
    collective_limit: int
    is_active: bool = True


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
    stripe_subscription_id: str | None
    stripe_customer_id: str | None
    created_at: datetime
    updated_at: datetime


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
