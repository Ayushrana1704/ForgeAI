from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedException

# Argon2id with OWASP-recommended defaults (time_cost=2, memory=65536, parallelism=2).
_ph = PasswordHasher()

# Pre-computed sentinel used by AuthService.login() so that the Argon2 verify
# step always runs, regardless of whether the email exists in the database.
# This prevents timing-based user enumeration attacks.
# Computed once at startup; the ~100 ms cost is paid only on first import.
DUMMY_HASH: str = _ph.hash("__forgeai_sentinel__")


def hash_password(password: str) -> str:
    """Return an Argon2id hash of *password*."""
    return _ph.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*, False otherwise.

    Never raises — all Argon2 error variants are mapped to False.
    """
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except VerificationError:
        # Malformed hash or unsupported algorithm — treat as mismatch.
        return False


def _build_token(subject: str | UUID, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": now + expires_delta,
        "type": token_type,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str | UUID) -> str:
    return _build_token(
        subject,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str | UUID) -> str:
    return _build_token(
        subject,
        "refresh",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate a JWT.

    Raises UnauthorizedException for any failure: expired, malformed, wrong type.
    The caller deliberately receives the same error message in all cases to avoid
    leaking information about why the token was rejected.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        raise UnauthorizedException("Invalid or expired token")

    if payload.get("type") != expected_type:
        raise UnauthorizedException("Invalid or expired token")

    return payload
