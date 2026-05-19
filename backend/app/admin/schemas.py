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
