"""
/api/admin/* — routes accessible to authenticated users with role='admin' only.

Normal users receive 403 Forbidden.

Add admin-facing features here:
  - GET    /api/admin/users        — list all users
  - PATCH  /api/admin/users/{id}/role — change a user's role
  etc.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.admin import service
from app.admin.schemas import AdminUserResponse, RoleUpdateRequest
from app.auth.dependencies import get_admin_user
from app.core.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[AdminUserResponse]:
    """List all users. Admin only."""
    users = service.list_users(db)
    return [AdminUserResponse.model_validate(u) for u in users]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    payload: RoleUpdateRequest,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AdminUserResponse:
    """Change a user's role. Admin only."""
    if payload.role not in ("user", "admin"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role must be 'user' or 'admin'.",
        )
    user = service.set_user_role(db, user_id, payload.role)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return AdminUserResponse.model_validate(user)


@router.get("/stats")
async def get_stats(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Basic platform stats. Admin only."""
    from app.models.user import User as UserModel

    total = db.query(UserModel).count()
    admins = db.query(UserModel).filter(UserModel.role == "admin").count()
    return {"total_users": total, "admin_count": admins, "member_count": total - admins}
