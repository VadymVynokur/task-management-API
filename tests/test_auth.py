from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from task_management_api.core.time import ensure_utc
from task_management_api.models.refresh_token import RefreshToken
from tests.conftest import FakeClock
from tests.helpers import DEFAULT_PASSWORD, auth_headers, login_account, register_account


async def test_register_creates_user_with_default_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": DEFAULT_PASSWORD},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["role"] == "user"
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_rejects_duplicate_username(client: AsyncClient) -> None:
    await register_account(client)

    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": DEFAULT_PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Username already registered"


async def test_register_rejects_invalid_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "a", "password": "short"},
    )

    assert response.status_code == 422


async def test_register_ignores_client_supplied_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": DEFAULT_PASSWORD, "role": "admin"},
    )

    assert response.status_code == 422


async def test_login_returns_access_and_refresh_tokens(client: AsyncClient) -> None:
    await register_account(client)

    tokens = await login_account(client)

    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60
    assert tokens["access_token"]
    assert tokens["refresh_token"]


async def test_refresh_token_records_creation_time(
    client: AsyncClient,
    clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client)
    await login_account(client)

    async with session_factory() as session:
        stored_token = await session.scalar(select(RefreshToken))

    assert stored_token is not None
    assert ensure_utc(stored_token.created_at) == clock.now()


async def test_login_rejects_invalid_credentials(client: AsyncClient) -> None:
    await register_account(client)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


async def test_login_rejects_unknown_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": DEFAULT_PASSWORD},
    )

    assert response.status_code == 401


async def test_protected_route_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": "anything"})

    assert response.status_code == 401


async def test_protected_route_rejects_invalid_access_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer not-a-token"},
        json={"refresh_token": "anything"},
    )

    assert response.status_code == 401


async def test_refresh_rotates_and_revokes_old_token(client: AsyncClient) -> None:
    await register_account(client)
    tokens = await login_account(client)

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    replay = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401

    next_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert next_refresh.status_code == 200


async def test_refresh_rejects_access_token(client: AsyncClient) -> None:
    await register_account(client)
    tokens = await login_account(client)

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["access_token"]},
    )

    assert response.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    await register_account(client)
    tokens = await login_account(client)

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 204

    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_response.status_code == 401


async def test_logout_requires_matching_user(client: AsyncClient) -> None:
    await register_account(client, "alice")
    await register_account(client, "bob")
    alice_tokens = await login_account(client, "alice")
    bob_tokens = await login_account(client, "bob")

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {alice_tokens['access_token']}"},
        json={"refresh_token": bob_tokens["refresh_token"]},
    )

    assert response.status_code == 401


async def test_access_token_expires(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client)
    tokens = await login_account(client)

    clock.set_now(clock.now() + timedelta(minutes=16))

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 401


async def test_refresh_token_expires(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client)
    tokens = await login_account(client)

    clock.set_now(clock.now() + timedelta(days=8))

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 401


async def test_auth_headers_helper_works(client: AsyncClient) -> None:
    await register_account(client)

    headers = await auth_headers(client)

    response = await client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": "invalid"},
    )
    assert response.status_code == 401
