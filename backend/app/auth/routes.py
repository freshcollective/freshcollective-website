import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile, status
from slowapi import Limiter
from sqlalchemy.orm import Session

from app.core.rate_limit import client_ip_for_rate_limit

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
limiter = Limiter(key_func=client_ip_for_rate_limit)

COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


def set_session_cookie(response: Response, token: str) -> None:
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
    # Community Care — suspension (Stage 2C) and cancellation (Stage 2D)
    # both block sign-in. Suspension is temporary and reversible;
    # cancellation is terminal. The message distinguishes them so the
    # person hears the truth about the state of their account.
    from app.community_care.shared import is_user_cancelled, is_user_suspended
    if is_user_suspended(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account access is temporarily suspended pending review.",
        )
    if is_user_cancelled(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been cancelled.",
        )
    token = service.create_session_token(user)
    set_session_cookie(response, token)
    return UserResponse.model_validate(user)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    payload: SignupRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> UserResponse:
    existing = service.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with those details already exists. Try logging in instead.",
        )
    user = service.create_user(db, payload.name, payload.email, payload.password)
    service.emit_welcome_after_signup(
        db, user, background_tasks=background_tasks,
    )
    token = service.create_session_token(user)
    set_session_cookie(response, token)
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
        has_completed_creator_onboarding=user.creator_onboarded_at is not None,
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


@router.post("/me/complete-creator-onboarding")
async def complete_creator_onboarding(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Mark the short Creator-specific welcome as complete. Idempotent.

    Independent of ``complete-onboarding`` (the Member orientation).
    Called by ``/creator-onboarding`` when the visitor clicks the
    "Build your first Collective" CTA.
    """
    from datetime import datetime
    if current_user.creator_onboarded_at is None:
        current_user.creator_onboarded_at = datetime.now()
        db.commit()
    return {"message": "Creator onboarding complete."}


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

    result = [
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

    # Also include spaces the user owns via creator_id but has no membership row for.
    # This handles collectives created before auto-membership was introduced.
    membership_space_ids = {space.id for _, space in rows}
    owned_spaces = db.query(Space).filter(Space.creator_id == current_user.id).all()
    for space in owned_spaces:
        if space.id not in membership_space_ids:
            result.append({
                "space_id": space.id,
                "space_name": space.name,
                "space_slug": space.slug,
                "role": "creator",
                "joined_at": space.created_at.isoformat(),
                "status": "active",
            })

    return result


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
        # Development convenience — mirror the link into the log so
        # operators without email delivery can still complete the flow.
        # The email path below is the primary delivery mechanism in
        # production; the log fallback is best-effort and never
        # prevents email from being sent.
        if not settings.is_production:
            logger.warning("\n========================================")
            logger.warning("PASSWORD RESET LINK (development):")
            logger.warning(reset_url)
            logger.warning("========================================\n")
        # R2A: delivery flows exclusively through the Communications
        # Layer. Emit the event; ``_route_event_bg`` (via
        # ``schedule_routing_if_needed``) creates the intent and
        # dispatches it inline through the Resend provider.
        from app.comms import Source, emit as comms_emit
        from app.comms.rollout import schedule_routing_if_needed
        # Look up the user id from email — needed so the resolver can
        # target the account owner. Missing user is fine (the email
        # gate above already gates on token existence).
        reset_user = db.query(User).filter(User.email == payload.email).first()
        ev = comms_emit(
            db,
            event_type="account.password_reset_requested",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=reset_user.id if reset_user else None,
            subject_type="password_reset",
            payload={"reset_url": reset_url},
        )
        db.commit()
        schedule_routing_if_needed(
            None,  # forgot-password has no BackgroundTasks parameter — sync route is fine
            ev,
            "account.password_reset_requested",
        )

    # Response copy stays deliberately vague so this endpoint doesn't
    # leak whether an address is registered.
    return {
        "message": (
            "If that email is registered, we've sent a link to reset your password. "
            "Check your inbox for a message from Fresh Collective."
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
    set_session_cookie(response, token)
    return UserResponse.model_validate(user)
