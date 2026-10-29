from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from task_management_api.enums import UserRole
from task_management_api.models.user import User

DEFAULT_PASSWORD = "password123"


async def register_account(
    client: AsyncClient,
    username: str = "alice",
    password: str = DEFAULT_PASSWORD,
) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login_account(
    client: AsyncClient,
    username: str = "alice",
    password: str = DEFAULT_PASSWORD,
) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def auth_headers(
    client: AsyncClient,
    username: str = "alice",
    password: str = DEFAULT_PASSWORD,
) -> dict[str, str]:
    tokens = await login_account(client, username, password)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def make_admin(
    session_factory: async_sessionmaker[AsyncSession],
    username: str = "alice",
) -> None:
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.username == username))
        assert user is not None
        user.role = UserRole.admin
        await session.commit()


async def create_task(
    client: AsyncClient,
    headers: dict[str, str],
    **overrides,
) -> dict:
    payload = {"title": "Task"}
    payload.update(overrides)
    response = await client.post("/api/v1/tasks", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def transition_task(
    client: AsyncClient,
    headers: dict[str, str],
    task_id: str,
    target_status: str,
) -> dict:
    response = await client.patch(
        f"/api/v1/tasks/{task_id}/status",
        headers=headers,
        json={"status": target_status},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def move_task_to_done(
    client: AsyncClient,
    headers: dict[str, str],
    task_id: str,
) -> dict:
    await transition_task(client, headers, task_id, "In Progress")
    await transition_task(client, headers, task_id, "Review")
    return await transition_task(client, headers, task_id, "Done")
