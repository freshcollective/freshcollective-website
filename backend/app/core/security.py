from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A valid bcrypt hash used only for constant-time comparison when a user isn't found.
# Prevents timing-based email enumeration attacks.
_TIMING_SAFE_HASH = "$2a$12$LCKz9TBMc.NJY5eIcLVdw.vM9gf.4lB0fU9a7JY.Kp4U2vU8WIaWq"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def verify_password_timing_safe(plain: str, hashed: str | None) -> bool:
    """Always runs bcrypt even if hashed is None to prevent timing attacks."""
    return verify_password(plain, hashed if hashed else _TIMING_SAFE_HASH) and hashed is not None


def create_access_token(data: dict[str, Any]) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {**data, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
