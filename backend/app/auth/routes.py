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
    VerifyEmailRequest,
)
from app.models.platform import CreatorProfile, Space, SpaceMembership
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=client_ip_for_rate_limit)

COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


def _user_response(user: User) -> UserResponse:
    """Build the wire-shape ``UserResponse`` carrying SEC-009's
    ``email_verified_at`` in ISO form. Used by every endpoint that
    returns the current user to the frontend so the verification
    banner can flip on/off correctly."""
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        email_verified_at=(
            user.email_verified_at.isoformat()
            if user.email_verified_at is not None
            else None
        ),
    )


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
    return _user_response(user)


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

    # SEC-009 — new accounts start unverified. Issue the verification
    # token + email; do NOT emit ``account.welcome_after_signup``
    # here. The existing welcome email fires from the verify endpoint
    # so a new account's lifetime email count is exactly two: verify,
    # then welcome-after-verify. See SEC-009 investigation §6 for the
    # single-email-at-signup product decision.
    raw = service.create_email_verification_token(db, user)
    if raw:
        service.emit_email_verification_requested(
            db, user, raw, background_tasks=background_tasks,
        )
    else:
        # Cooldown / already-verified — for a brand-new account this
        # cannot happen. Committed defensively so the caller sees no
        # asymmetry.
        db.commit()

    token = service.create_session_token(user)
    set_session_cookie(response, token)
    return _user_response(user)


@router.post("/verify-email")
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    payload: VerifyEmailRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """SEC-009 — consume a verification token.

    Deliberately does NOT require authentication. A user might click
    the link from a device where they never signed in (email on
    phone, browsing on desktop). Verification is proven by possession
    of the raw token; the endpoint simply flips
    ``users.email_verified_at`` for the token's owner.

    Failure branches collapse into a single generic 400 so a caller
    cannot enumerate token state (missing / expired / used /
    invalidated all indistinguishable). Rate-limited via SEC-010's
    ``client_ip_for_rate_limit``.

    On success, emits ``account.welcome_after_signup`` so the person
    gets their "you're in, here's what's next" email now that we can
    confirm the address is theirs.
    """
    user = service.consume_email_verification_token(db, payload.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This verification link is invalid or has expired. "
                "Please request a new one."
            ),
        )
    # Post-verify welcome — the existing warm onboarding email now
    # fires once the address is confirmed. Not fatal if it fails.
    try:
        service.emit_welcome_after_signup(
            db, user, background_tasks=background_tasks,
        )
    except Exception:
        logger.exception(
            "welcome_after_signup emit failed post-verify for user %s", user.id,
        )
    return {"verified": True}


@router.post("/verify-email/resend")
@limiter.limit("5/minute")
async def verify_email_resend(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """SEC-009 — issue a fresh verification email for the caller.

    Returns the same generic success shape whether we actually sent a
    new email or suppressed the request (cooldown / already verified /
    user gone). Prevents the caller from distinguishing those states
    via the response, matching the anti-enumeration stance of
    ``/forgot-password``.

    Per-IP rate-limit via SEC-010's ``client_ip_for_rate_limit`` +
    per-account cooldown enforced inside
    ``create_email_verification_token``.
    """
    raw = service.create_email_verification_token(db, current_user)
    if raw is not None:
        service.emit_email_verification_requested(
            db, current_user, raw, background_tasks=background_tasks,
        )
    else:
        # Nothing to commit here — the helper committed a flush-only
        # state that will roll back with the request. Explicit commit
        # keeps the response contract stable.
        db.commit()
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"message": "Logged out."}


@router.post("/logout-all")
@limiter.limit("5/minute")
async def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """SEC-008 / SEC-015 — self-service "sign out of every device".

    Bumps the caller's ``session_version`` so every JWT currently
    outstanding (this device included) is refused on its next
    authenticated request, then clears the current-device cookie.
    Deliberately does NOT issue a replacement token — the caller
    must sign in again from any device they still want to use, and
    an attacker holding a stolen token loses access on the token's
    next use.

    Rate-limited via SEC-010's ``client_ip_for_rate_limit`` at
    5/minute per IP.
    """
    service.bump_session_version(current_user)
    db.commit()
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"message": "Signed out of every device."}


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
        email_verified_at=(
            user.email_verified_at.isoformat()
            if user.email_verified_at is not None
            else None
        ),
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
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """SEC-006 Gate 2 + SEC-008 / SEC-015.

    Requires the current password, then rotates it. On success the
    user's ``session_version`` is bumped so every previously-issued
    JWT (including any that may have been stolen) is invalidated on
    its next authenticated request. The caller's cookie is then
    replaced with a fresh JWT carrying the new ``sv`` so the current
    device stays signed in seamlessly.

    Rate-limited via SEC-010's ``client_ip_for_rate_limit`` at
    5/minute per IP. FastAPI/Pydantic validation runs before the
    limiter body, so malformed 422 payloads do NOT consume the
    bucket.

    Wrong-current-password requests raise 400 BEFORE any mutation —
    password_hash, session_version, and the session cookie are all
    unchanged in the failure path.
    """
    from app.core.security import verify_password, hash_password
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    current_user.password_hash = hash_password(payload.new_password)
    service.bump_session_version(current_user)
    db.commit()
    # Rotate the caller's session cookie so THIS device stays signed
    # in with a JWT that carries the new session_version. Every other
    # session (or a stolen token) will 401 on its next request.
    set_session_cookie(response, service.create_session_token(current_user))
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
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    # SEC-006 Phase B — per-client IP throttle on the consume endpoint.
    # Uses the SEC-010 ``client_ip_for_rate_limit`` key function
    # configured on this router's Limiter, so BFF-mediated callers
    # are keyed on the authenticated browser IP claim rather than
    # fc-web's egress. Anti-enumeration and single-use / expiry /
    # invalidation semantics inside ``consume_password_reset_token``
    # are unchanged.
    user = service.consume_password_reset_token(db, payload.token, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Please request a new one.",
        )
    token = service.create_session_token(user)
    set_session_cookie(response, token)
    return _user_response(user)
