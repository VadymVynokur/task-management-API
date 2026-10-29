import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from task_management_api.core.clock import Clock, get_clock
from task_management_api.core.config import Settings, get_settings
from task_management_api.core.security import TokenError, decode_token
from task_management_api.db.session import get_session
from task_management_api.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ClockDep = Annotated[Clock, Depends(get_clock)]
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: BearerCredentials,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Not authenticated")

    try:
        payload = decode_token(
            credentials.credentials,
            settings=settings,
            expected_type="access",
            now=clock.now(),
        )
    except TokenError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    user = await session.get(User, uuid.UUID(str(payload["sub"])))
    if user is None:
        raise _unauthorized("Invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
