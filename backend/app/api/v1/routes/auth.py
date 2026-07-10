import dataclasses

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_auth_service
from app.application.services.auth_service import AuthService
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserResponse

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    body: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    user = await auth_service.register(body.email, body.password, body.full_name)
    return UserResponse.model_validate(dataclasses.asdict(user))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Obtain access and refresh tokens",
)
async def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await auth_service.login(body.email, body.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh(
    body: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await auth_service.refresh(body.refresh_token)
