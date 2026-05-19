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
