import dataclasses

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user, get_user_repo, require_superuser
from app.core.exceptions import ConflictException
from app.domain.entities.user import User
from app.infrastructure.repositories.user_repository import SQLAlchemyUserRepository
from app.schemas.common import PaginatedResponse
from app.schemas.user import UpdateMeRequest, UserResponse

router = APIRouter()


@router.get("/me", response_model=UserResponse, summary="Get the authenticated user's profile")
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(dataclasses.asdict(current_user))


@router.put("/me", response_model=UserResponse, summary="Update the authenticated user's profile")
async def update_me(
    body: UpdateMeRequest,
    current_user: User = Depends(get_current_user),
    user_repo: SQLAlchemyUserRepository = Depends(get_user_repo),
) -> UserResponse:
    if body.email is not None:
        new_email = body.email.lower().strip()
        if new_email != current_user.email:
            # Guard against the unique constraint surfacing as an unhandled
            # IntegrityError (which would produce a 500 instead of 409).
            if await user_repo.get_by_email(new_email):
                raise ConflictException("Email address is already in use")
        current_user.email = new_email

    if body.full_name is not None:
        current_user.full_name = body.full_name

    # updated_at is managed by TimestampMixin's onupdate=func.now() at the DB
    # level — no need to set it here. It will be refreshed after flush().
    updated = await user_repo.update(current_user)
    return UserResponse.model_validate(dataclasses.asdict(updated))


@router.get(
    "",
    response_model=PaginatedResponse[UserResponse],
    summary="[Admin] List all users",
)
async def list_users(
    offset: int = 0,
    limit: int = 50,
    _: User = Depends(require_superuser),
    user_repo: SQLAlchemyUserRepository = Depends(get_user_repo),
) -> PaginatedResponse[UserResponse]:
    users = await user_repo.list_all(offset=offset, limit=limit)
    total = await user_repo.count_all()
    return PaginatedResponse(
        items=[UserResponse.model_validate(dataclasses.asdict(u)) for u in users],
        total=total,
        offset=offset,
        limit=limit,
    )
