import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import SESSION_COOKIE, get_current_user
from app.auth.schemas import (
    ChangePasswordRequest,
    CompleteOnboardingRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ProfileResponse,
    ResetPasswordRequest,
    SignupRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.models.platform import CreatorProfile, Space, SpaceMembership
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


import json as _json


def _profile_response(user: User, cp: "CreatorProfile | None") -> ProfileResponse:
    interests: list[str] = []
    if user.interests:
        try:
            interests = _json.loads(user.interests)
        except Exception:
            interests = []
    return ProfileResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        bio=cp.bio if cp else None,
        display_name=cp.display_name if cp else None,
        profile_tagline=cp.profile_tagline if cp else None,
        avatar_url=cp.avatar_url if cp else None,
        is_public=cp.is_public if cp else False,
        has_completed_onboarding=user.onboarding_completed_at is not None,
        interests=interests,
    )


@router.get("/me")
async def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    cp = db.query(CreatorProfile).filter(CreatorProfile.user_id == current_user.id).first()
    return _profile_response(current_user, cp)


@router.patch("/me")
async def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    if payload.name is not None:
        current_user.name = payload.name

    cp = db.query(CreatorProfile).filter(CreatorProfile.user_id == current_user.id).first()

    profile_fields = {
        k: v for k, v in {
            "bio": payload.bio,
            "display_name": payload.display_name,
            "profile_tagline": payload.profile_tagline,
            "is_public": payload.is_public,
        }.items() if v is not None
    }

    if profile_fields:
        if cp is None:
            from uuid import uuid4
            cp = CreatorProfile(
                id=str(uuid4()),
                user_id=current_user.id,
                bio=profile_fields.get("bio"),
                display_name=profile_fields.get("display_name"),
                profile_tagline=profile_fields.get("profile_tagline"),
                is_public=profile_fields.get("is_public", False),
            )
            db.add(cp)
        else:
            for field, value in profile_fields.items():
                setattr(cp, field, value)

    db.commit()
    db.refresh(current_user)
    if cp:
        db.refresh(cp)

    return _profile_response(current_user, cp)


@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    from app.core.storage import delete_file, save_file
    filename = file.filename or "avatar.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(status_code=400, detail="Only JPG, PNG, and WebP images are allowed.")
    data = await file.read()

    cp = db.query(CreatorProfile).filter(CreatorProfile.user_id == current_user.id).first()
    if cp is None:
        from uuid import uuid4
        cp = CreatorProfile(id=str(uuid4()), user_id=current_user.id)
        db.add(cp)
        db.flush()

    if cp.avatar_url:
        old_rel = cp.avatar_url.removeprefix("/api/uploads/")
        delete_file(old_rel)

    rel_path, _, _ = save_file(data, filename, file.content_type or "image/jpeg", "avatars")
    cp.avatar_url = f"/api/uploads/{rel_path}"
    db.commit()
    db.refresh(current_user)
    db.refresh(cp)
    return _profile_response(current_user, cp)


@router.post("/me/complete-onboarding")
async def complete_onboarding(
    payload: CompleteOnboardingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from datetime import datetime
    current_user.onboarding_completed_at = datetime.now()
    current_user.interests = _json.dumps(payload.interests)
    db.commit()
    return {"message": "Welcome to Fresh Collective."}


@router.get("/me/memberships")
async def get_memberships(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = (
        db.query(SpaceMembership, Space)
        .join(Space, Space.id == SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == current_user.id,
            SpaceMembership.status == "active",
        )
        .all()
    )
    return [
        {
            "space_id": space.id,
            "space_name": space.name,
            "space_slug": space.slug,
            "role": membership.role.value if hasattr(membership.role, "value") else str(membership.role),
            "joined_at": membership.joined_at.isoformat(),
            "status": membership.status.value if hasattr(membership.status, "value") else str(membership.status),
        }
        for membership, space in rows
    ]


@router.post("/me/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.core.security import verify_password, hash_password
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password updated successfully."}


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
