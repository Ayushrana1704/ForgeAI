from datetime import datetime, timezone
from typing import ClassVar
from uuid import UUID, uuid4

import structlog

from app.application.interfaces.user_repository import UserRepository
from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.domain.entities.user import User
from app.schemas.auth import TokenResponse

logger = structlog.get_logger(__name__)


class AuthService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

    async def register(
        self,
        email: str,
        password: str,
        full_name: str | None,
    ) -> User:
        email = email.lower().strip()

        if await self._user_repo.get_by_email(email):
            raise ConflictException(f"Email '{email}' is already registered")

        now = datetime.now(timezone.utc)
        user = User(
            id=uuid4(),
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            is_active=True,
            is_superuser=False,
            created_at=now,
            updated_at=now,
        )
        created = await self._user_repo.create(user)
        logger.info("user_registered", user_id=str(created.id))
        return created

    async def login(self, email: str, password: str) -> TokenResponse:
        email = email.lower().strip()
        user = await self._user_repo.get_by_email(email)

        # Always run verify_password — even against a dummy hash when the user
        # does not exist — so response time is constant regardless of whether
        # the email is registered. This prevents timing-based enumeration.
        stored_hash = user.hashed_password if user else DUMMY_HASH
        credentials_valid = verify_password(password, stored_hash)

        if not user or not credentials_valid:
            logger.warning("login_failed", email=email, reason="invalid_credentials")
            raise UnauthorizedException("Invalid email or password")

        if not user.is_active:
            logger.warning("login_failed", email=email, reason="account_deactivated")
            raise UnauthorizedException("Account is deactivated")

        logger.info("login_success", user_id=str(user.id))
        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            token_type="bearer",
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise UnauthorizedException("Invalid token payload")

        user = await self._user_repo.get_by_id(UUID(user_id_str))
        if not user or not user.is_active:
            raise UnauthorizedException("User not found or deactivated")

        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            token_type="bearer",
        )

    async def get_current_user(self, token: str) -> User:
        payload = decode_token(token, expected_type="access")
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise UnauthorizedException("Invalid token payload")

        user = await self._user_repo.get_by_id(UUID(user_id_str))
        if not user:
            raise UnauthorizedException("User not found")
        if not user.is_active:
            raise UnauthorizedException("Account is deactivated")

        return user
