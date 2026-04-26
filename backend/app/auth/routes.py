import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import SESSION_COOKIE, get_current_user
from app.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SignupRequest,
    UserResponse,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = service.authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    token = service.create_session_token(user)
    _set_session_cookie(response, token)
    return UserResponse.model_validate(user)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    payload: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    existing = service.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with those details already exists. Try logging in instead.",
        )
    user = service.create_user(db, payload.name, payload.email, payload.password)
    token = service.create_session_token(user)
    _set_session_cookie(response, token)
    return UserResponse.model_validate(user)


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"message": "Logged out."}


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> dict:
    raw_token = service.create_password_reset_token(db, payload.email)

    if raw_token:
        reset_url = f"{settings.frontend_origin}/reset-password?token={raw_token}"
        if not settings.is_production:
            logger.warning("\n========================================")
            logger.warning("PASSWORD RESET LINK (development only):")
            logger.warning(reset_url)
            logger.warning("========================================\n")
        # TODO: In production, send reset_url via a transactional email service

    return {
        "message": (
            "If that email is registered, a reset link will appear in the server console. "
            "(In production, an email would be sent.)"
        )
    }


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = service.consume_password_reset_token(db, payload.token, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Please request a new one.",
        )
    token = service.create_session_token(user)
    _set_session_cookie(response, token)
    return UserResponse.model_validate(user)
