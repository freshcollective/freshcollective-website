from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
from jose import JWTError, jwt

from .config import settings

# Pre-computed timing-safe hash: always run bcrypt even when no user is found
# to prevent email-enumeration via timing difference.
_TIMING_SAFE_HASH: bytes = _bcrypt.hashpw(b"__timing_safe__", _bcrypt.gensalt(rounds=4))


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def verify_password_timing_safe(plain: str, hashed: str | None) -> bool:
    """Always runs bcrypt even if hashed is None to prevent timing attacks."""
    if hashed is None:
        _bcrypt.checkpw(plain[:72].encode("utf-8"), _TIMING_SAFE_HASH)
        return False
    return verify_password(plain, hashed)


def create_access_token(data: dict[str, Any]) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {**data, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
