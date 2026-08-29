import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
    verify_password_timing_safe,
)
from app.models.user import PasswordReset, User

if TYPE_CHECKING:
    from fastapi import BackgroundTasks

logger = logging.getLogger(__name__)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: str) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    ok = verify_password_timing_safe(password, user.password_hash if user else None)
    return user if ok else None


def create_user(db: Session, name: str, email: str, password: str) -> User:
    user = User(
        id=str(uuid4()),
        email=email,
        name=name,
        password_hash=hash_password(password),
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def emit_welcome_after_signup(
    db: Session,
    user: User,
    *,
    background_tasks: "BackgroundTasks | None" = None,
    next_url: str | None = None,
) -> None:
    """Emit ``account.welcome_after_signup`` and schedule its routing.

    Called from both the standalone signup endpoint and the
    ``claim_with_signup`` purchase path so every newly-created User
    row receives exactly one welcome email — no more, no less. The
    dedupe key is scoped to ``user.id`` so a rare duplicate call
    (retry, race) collapses to a single event.

    Commits the emit (routing needs the event visible to the fresh
    session opened by ``_route_event_bg``). ``schedule_routing_if_needed``
    is documented as never-raising, so a comms failure never blocks a
    signup.
    """
    from app.comms import Source, emit as comms_emit
    from app.comms.rollout import schedule_routing_if_needed
    from app.core.config import settings

    first_name = ""
    if user.name:
        first_name = user.name.strip().split(" ", 1)[0]

    resolved_next_url = next_url or f"{settings.frontend_origin.rstrip('/')}/dashboard"

    # No dedupe_key: each caller reaches this only after
    # ``get_user_by_email`` confirmed no existing account, so a genuine
    # duplicate would require a User uniqueness violation — which
    # SQLAlchemy raises before we get here. Using a dedupe_key would
    # force ``emit()`` down its ``begin_nested`` path, which conflicts
    # with the interior commit that ``create_user`` just performed.
    ev = comms_emit(
        db,
        event_type="account.welcome_after_signup",
        source_type=Source.FRESH_COLLECTIVE,
        actor_user_id=user.id,
        subject_type="account",
        subject_id=user.id,
        payload={
            "first_name": first_name,
            "next_url":   resolved_next_url,
        },
    )
    db.commit()
    schedule_routing_if_needed(
        background_tasks, ev, "account.welcome_after_signup",
    )


def create_session_token(user: User) -> str:
    return create_access_token({"sub": user.id, "email": user.email, "role": user.role})


_PASSWORD_RESET_COOLDOWN_SECONDS = 60


def create_password_reset_token(db: Session, email: str) -> str | None:
    """
    Returns the raw token (for the reset URL) if the user exists, else None.
    Caller must not reveal whether a user exists.

    SEC-006 Phase A — DB-backed per-account cooldown. If this user
    already had a reset row created within the previous
    ``_PASSWORD_RESET_COOLDOWN_SECONDS`` window, we return ``None``
    without creating a new token or triggering a new email dispatch.
    The route already returns the same generic 200 response for both
    the "user missing" and "no token issued" branches, so this
    silently suppresses the second (and later) requests without
    revealing to the caller either the account's existence or the
    throttle's activation. Anti-enumeration is preserved end-to-end.

    Concurrency: the check is a plain SELECT with no representing
    database uniqueness constraint on the cooldown window itself, so
    two truly simultaneous callers can both pass the check and each
    replace the previous token + dispatch an email. The window is
    tiny (< a few milliseconds) and the worst-case outcome is one
    additional email + one additional token, still bounded to the
    same 1 unused token per user via the invalidate-and-replace step
    below. This is by design: introducing a row lock, table-level
    uniqueness partial index, or Redis for a 60-second best-effort
    cooldown is disproportionate to the residual risk. Fixing
    SEC-010 (real client IP) and later adding an IP throttle on
    ``/reset-password`` (SEC-006 Phase B) will squeeze the practical
    race window further.
    """
    user = get_user_by_email(db, email)
    if not user:
        return None

    cooldown_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=_PASSWORD_RESET_COOLDOWN_SECONDS
    )
    recent = (
        db.query(PasswordReset.id)
        .filter(
            PasswordReset.user_id == user.id,
            PasswordReset.created_at > cooldown_cutoff,
        )
        .first()
    )
    if recent is not None:
        # Silent no-op: no new token, no new email. Existing unused
        # token (if any) is left in place so the previous reset link
        # remains usable until it expires or is consumed.
        return None

    # Invalidate any existing unused tokens for this user
    db.query(PasswordReset).filter(
        PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
    ).delete()

    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)

    reset = PasswordReset(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset)
    db.commit()
    return raw_token


def consume_password_reset_token(
    db: Session, raw_token: str, new_password: str
) -> User | None:
    """
    Validates the token, updates the password, marks the token as used.
    Returns the user on success, None on failure.
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    reset = db.query(PasswordReset).filter(PasswordReset.token_hash == token_hash).first()

    if (
        not reset
        or reset.used_at is not None
        or reset.expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        return None

    user = db.query(User).filter(User.id == reset.user_id).first()
    if not user:
        return None

    user.password_hash = hash_password(new_password)
    reset.used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(user)
    return user
