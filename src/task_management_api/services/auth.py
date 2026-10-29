from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from task_management_api.core.clock import Clock
from task_management_api.core.config import Settings
from task_management_api.core.exceptions import AppError
from task_management_api.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from task_management_api.core.time import ensure_utc
from task_management_api.enums import UserRole
from task_management_api.models.refresh_token import RefreshToken
from task_management_api.models.user import User
from task_management_api.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


async def register_user(
    session: AsyncSession,
    data: RegisterRequest,
) -> User:
    existing = await session.scalar(select(User).where(User.username == data.username))
    if existing is not None:
        raise AppError(409, "Username already registered")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role=UserRole.user,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(409, "Username already registered") from exc
    await session.refresh(user)
    return user


async def authenticate_user(
    session: AsyncSession,
    data: LoginRequest,
) -> User:
    user = await session.scalar(select(User).where(User.username == data.username))
    if user is None or not verify_password(data.password, user.password_hash):
        raise AppError(401, "Invalid username or password")
    return user


def _issue_token_pair(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    user: User,
) -> TokenResponse:
    now = clock.now()
    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
        settings=settings,
        now=now,
    )
    refresh_token, expires_at = create_refresh_token(
        user_id=user.id,
        settings=settings,
        now=now,
    )
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=expires_at,
            created_at=now,
        )
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def login_user(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    data: LoginRequest,
) -> TokenResponse:
    user = await authenticate_user(session, data)
    tokens = _issue_token_pair(session, settings, clock, user)
    await session.commit()
    return tokens


def _decode_refresh_token(
    token: str,
    settings: Settings,
    clock: Clock,
) -> dict[str, object]:
    try:
        return decode_token(
            token,
            settings=settings,
            expected_type="refresh",
            now=clock.now(),
        )
    except TokenError as exc:
        raise AppError(401, "Invalid refresh token") from exc


async def rotate_refresh_token(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    refresh_token: str,
) -> TokenResponse:
    payload = _decode_refresh_token(refresh_token, settings, clock)
    now = clock.now()
    token_hash = hash_token(refresh_token)
    stored_token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )

    if (
        stored_token is None
        or str(stored_token.user_id) != payload["sub"]
        or stored_token.revoked_at is not None
        or ensure_utc(stored_token.expires_at) <= now
    ):
        raise AppError(401, "Invalid refresh token")

    user = await session.get(User, stored_token.user_id)
    if user is None:
        raise AppError(401, "Invalid refresh token")

    stored_token.revoked_at = now
    tokens = _issue_token_pair(session, settings, clock, user)
    await session.commit()
    return tokens


async def revoke_refresh_token(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    user: User,
    refresh_token: str,
) -> None:
    payload = _decode_refresh_token(refresh_token, settings, clock)
    if payload["sub"] != str(user.id):
        raise AppError(401, "Invalid refresh token")

    stored_token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
    )
    if stored_token is None:
        raise AppError(401, "Invalid refresh token")

    if stored_token.revoked_at is None:
        stored_token.revoked_at = clock.now()
        await session.commit()
