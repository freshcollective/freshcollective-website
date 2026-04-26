import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
    verify_password_timing_safe,
)
from app.models.user import PasswordReset, User

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


def create_session_token(user: User) -> str:
    return create_access_token({"sub": user.id, "email": user.email, "role": user.role})


def create_password_reset_token(db: Session, email: str) -> str | None:
    """
    Returns the raw token (for the reset URL) if the user exists, else None.
    Caller must not reveal whether a user exists.
    """
    user = get_user_by_email(db, email)
    if not user:
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
