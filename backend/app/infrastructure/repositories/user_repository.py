from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.user_repository import UserRepository
from app.domain.entities.user import User
from app.infrastructure.database.models.user import UserModel


class SQLAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def create(self, user: User) -> User:
        model = UserModel(
            id=user.id,
            email=user.email,
            hashed_password=user.hashed_password,
            full_name=user.full_name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def update(self, user: User) -> User:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user.id)
        )
        model = result.scalar_one()
        model.email = user.email
        model.hashed_password = user.hashed_password
        model.full_name = user.full_name
        model.is_active = user.is_active
        model.is_superuser = user.is_superuser
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def list_all(self, offset: int = 0, limit: int = 50) -> list[User]:
        result = await self._session.execute(
            select(UserModel).order_by(UserModel.created_at.desc()).offset(offset).limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_all(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(UserModel))
        return result.scalar_one()

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(
            id=model.id,
            email=model.email,
            hashed_password=model.hashed_password,
            full_name=model.full_name,
            is_active=model.is_active,
            is_superuser=model.is_superuser,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
