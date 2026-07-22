from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.community_care.shared import is_creator_cancelled, is_user_cancelled, is_user_suspended
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

SESSION_COOKIE = "fc_session"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
        )

    user_id: str = payload.get("sub", "")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    # Community Care — suspension pending review invalidates every
    # existing session. The token itself is still cryptographically
    # valid, but access is denied while the suspension is active.
    if is_user_suspended(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account access is temporarily suspended pending review.",
        )

    # Cancellation (Stage 2D resolution outcome) is terminal. Refusal
    # here revokes every active session in effect since the token is
    # only useful in exchange for a User row.
    if is_user_cancelled(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been cancelled.",
        )

    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Return the current user if authenticated, None otherwise (no exception raised)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user_id: str = payload.get("sub", "")
    return db.query(User).filter(User.id == user_id).first()


def get_creator_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("creator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creator access required.",
        )
    # Creator-role cancellation (Stage 2D resolution) removes creator
    # capabilities. The person can still sign in and use member-side
    # functionality, but everything guarded here is off-limits.
    if is_creator_cancelled(current_user) and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creator access has been cancelled.",
        )
    return current_user


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user
