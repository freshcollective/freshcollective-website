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
