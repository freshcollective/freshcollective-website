"""
/api/client/* — routes accessible to any authenticated user (role: user or admin).

Add member-facing features here as the platform grows:
  - GET  /api/client/profile
  - GET  /api/client/real-journey
  - GET  /api/client/rooms
  etc.
"""

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.client.schemas import MemberProfileResponse
from app.models.user import User

router = APIRouter(prefix="/api/client", tags=["client"])


@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user)) -> MemberProfileResponse:
    """Return the authenticated member's profile."""
    return MemberProfileResponse.model_validate(current_user)


# ---------------------------------------------------------------------------
# Placeholder stubs — replace with real implementations as features are built
# ---------------------------------------------------------------------------

@router.get("/real-journey")
async def get_real_journey(current_user: User = Depends(get_current_user)) -> dict:
    return {"status": "coming_soon", "message": "REAL Journey content will be available here."}


@router.get("/rooms")
async def get_rooms(current_user: User = Depends(get_current_user)) -> dict:
    return {"status": "coming_soon", "message": "The Rooms will be available here."}


@router.get("/heart")
async def get_heart(current_user: User = Depends(get_current_user)) -> dict:
    return {"status": "coming_soon", "message": "The Heart live layer will be available here."}
