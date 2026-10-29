import hashlib
import uuid
from datetime import datetime, timedelta

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from task_management_api.core.config import Settings
from task_management_api.enums import UserRole

password_hasher = PasswordHash.recommended()


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or of the wrong type."""


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password, password_hash)
    except Exception:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode_token(
    *,
    subject: uuid.UUID,
    token_type: str,
    expires_delta: timedelta,
    settings: Settings,
    now: datetime,
    role: UserRole | None = None,
) -> str:
    payload: dict[str, object] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    if role is not None:
        payload["role"] = role.value
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    *,
    user_id: uuid.UUID,
    role: UserRole,
    settings: Settings,
    now: datetime,
) -> str:
    return _encode_token(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        settings=settings,
        now=now,
        role=role,
    )


def create_refresh_token(
    *,
    user_id: uuid.UUID,
    settings: Settings,
    now: datetime,
) -> tuple[str, datetime]:
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    token = _encode_token(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
        settings=settings,
        now=now,
    )
    return token, expires_at


def decode_token(
    token: str,
    *,
    settings: Settings,
    expected_type: str,
    now: datetime,
) -> dict[str, object]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False, "require": ["exp", "iat", "sub", "type"]},
        )
    except InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Invalid token type")

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int | float) or expires_at <= now.timestamp():
        raise TokenError("Token expired")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise TokenError("Invalid token subject")
    try:
        uuid.UUID(subject)
    except ValueError as exc:
        raise TokenError("Invalid token subject") from exc

    return payload
