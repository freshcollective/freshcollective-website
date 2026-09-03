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

    # SEC-008 / SEC-015 — server-side session revocation. Every JWT
    # issued after the SEC-008 rollout carries a ``sv`` claim equal
    # to the user's ``session_version`` at issue time. Password
    # change, password reset, and logout-all all bump that counter;
    # any older token now fails this check and forces re-login.
    # Missing / non-integer / mismatched values are all treated the
    # same (generic 401) to avoid leaking session state. Legacy
    # pre-rollout JWTs land here with no ``sv`` claim and are
    # correctly refused — a one-time re-login for all existing
    # sessions is the intended deployment posture.
    token_sv = payload.get("sv")
    # ``bool`` is a subclass of ``int`` in Python, so ``True == 1``
    # would otherwise let a crafted ``{"sv": true}`` token pass
    # whenever the user's real version is 1 (the default). Reject
    # explicitly. Everything else (missing, string, None, float, list)
    # naturally fails the isinstance check.
    if (
        isinstance(token_sv, bool)
        or not isinstance(token_sv, int)
        or token_sv != user.session_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
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

    # Safety-net reconciliation of auto-role memberships (e.g. the
    # World Builders auto-grant for active Creators). Idempotent and
    # short-circuits fast when nothing needs doing. Never raises.
    from app.services.creator_eligibility import reconcile_at_session_time
    reconcile_at_session_time(user, db)

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
