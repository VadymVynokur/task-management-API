import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from task_management_api.models.task import Task
from tests.conftest import FakeClock
from tests.helpers import (
    auth_headers,
    create_task,
    make_admin,
    move_task_to_done,
    register_account,
    transition_task,
)


async def test_delete_backlog_task_hides_it(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)

    response = await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)

    assert response.status_code == 204
    detail = await client.get(f"/api/v1/tasks/{task['id']}", headers=headers)
    listing = await client.get("/api/v1/tasks", headers=headers)
    assert detail.status_code == 404
    assert listing.json()["total"] == 0


async def test_delete_done_and_cancelled_tasks_allowed(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    done_task = await create_task(
        client,
        headers,
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )
    await move_task_to_done(client, headers, done_task["id"])

    cancelled_task = await create_task(client, headers)
    await transition_task(client, headers, cancelled_task["id"], "Cancelled")

    done_response = await client.delete(f"/api/v1/tasks/{done_task['id']}", headers=headers)
    cancelled_response = await client.delete(
        f"/api/v1/tasks/{cancelled_task['id']}", headers=headers
    )

    assert done_response.status_code == 204
    assert cancelled_response.status_code == 204


async def test_delete_in_progress_and_review_tasks_rejected(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    in_progress = await create_task(client, headers)
    await transition_task(client, headers, in_progress["id"], "In Progress")

    in_review = await create_task(client, headers)
    await transition_task(client, headers, in_review["id"], "In Progress")
    await transition_task(client, headers, in_review["id"], "Review")

    for task in (in_progress, in_review):
        response = await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)
        assert response.status_code == 409
        assert response.json()["detail"] == "Task cannot be deleted in its current status"


async def test_delete_requires_owner_or_admin(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(client, alice_headers)

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")
    forbidden = await client.delete(f"/api/v1/tasks/{task['id']}", headers=bob_headers)
    assert forbidden.status_code == 403

    await make_admin(session_factory, "alice")
    allowed = await client.delete(f"/api/v1/tasks/{task['id']}", headers=alice_headers)
    assert allowed.status_code == 204


async def test_delete_preserves_row_and_updates_timestamp(
    client: AsyncClient,
    clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)

    clock.set_now(clock.now() + timedelta(minutes=10))
    response = await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)
    assert response.status_code == 204

    async with session_factory() as session:
        stored = await session.scalar(select(Task).where(Task.id == uuid.UUID(task["id"])))

    assert stored is not None
    assert stored.deleted_at is not None
    assert stored.updated_at is not None
    assert stored.updated_at > stored.created_at


async def test_deleted_task_cannot_be_updated_or_transitioned(
    client: AsyncClient,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)
    await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)

    update = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"title": "Nope"},
    )
    transition = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "In Progress"},
    )
    delete_again = await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)

    assert update.status_code == 404
    assert transition.status_code == 404
    assert delete_again.status_code == 404


async def test_delete_missing_task_returns_404(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.delete(f"/api/v1/tasks/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404
