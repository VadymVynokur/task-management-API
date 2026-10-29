from fastapi import APIRouter, Response, status

from task_management_api.api.deps import ClockDep, CurrentUser, SessionDep, SettingsDep
from task_management_api.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from task_management_api.schemas.user import UserResponse
from task_management_api.services.auth import (
    login_user,
    register_user,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    session: SessionDep,
) -> UserResponse:
    user = await register_user(session, payload)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> TokenResponse:
    return await login_user(session, settings, clock, payload)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> TokenResponse:
    return await rotate_refresh_token(session, settings, clock, payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> Response:
    await revoke_refresh_token(session, settings, clock, user, payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
