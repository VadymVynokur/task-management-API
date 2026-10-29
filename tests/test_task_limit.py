import uuid

from httpx import AsyncClient

from tests.conftest import FakeClock
from tests.helpers import (
    auth_headers,
    create_task,
    move_task_to_done,
    register_account,
    transition_task,
)


async def _create_ten_active_tasks(
    client: AsyncClient,
    headers: dict[str, str],
    assignee_id: str,
    *,
    due_date: str | None = None,
) -> list[dict]:
    tasks = []
    for index in range(10):
        task = await create_task(
            client,
            headers,
            title=f"Task {index}",
            assignee_id=assignee_id,
            due_date=due_date,
        )
        tasks.append(task)
    return tasks


async def test_eleventh_active_task_is_rejected(client: AsyncClient) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    await _create_ten_active_tasks(client, headers, bob["id"])

    response = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Eleventh", "assignee_id": bob["id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Active task limit exceeded"

    listing = await client.get("/api/v1/tasks", headers=headers)
    assert listing.json()["total"] == 10


async def test_done_and_cancelled_tasks_do_not_count(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    tasks = await _create_ten_active_tasks(
        client,
        headers,
        bob["id"],
        due_date=clock.today_value.isoformat(),
    )

    await move_task_to_done(client, headers, tasks[0]["id"])
    await transition_task(client, headers, tasks[1]["id"], "Cancelled")

    first = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Replacement one", "assignee_id": bob["id"]},
    )
    second = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Replacement two", "assignee_id": bob["id"]},
    )

    assert first.status_code == 201
    assert second.status_code == 201


async def test_same_assignee_update_does_not_double_count(client: AsyncClient) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    tasks = await _create_ten_active_tasks(client, headers, bob["id"])

    response = await client.patch(
        f"/api/v1/tasks/{tasks[0]['id']}",
        headers=headers,
        json={"assignee_id": bob["id"]},
    )

    assert response.status_code == 200


async def test_reassigning_to_full_assignee_is_rejected(client: AsyncClient) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    await _create_ten_active_tasks(client, headers, bob["id"])
    alice_task = await create_task(client, headers, title="Alice task")

    response = await client.patch(
        f"/api/v1/tasks/{alice_task['id']}",
        headers=headers,
        json={"assignee_id": bob["id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Active task limit exceeded"


async def test_reassigning_to_unknown_assignee_is_rejected(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"assignee_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Assignee not found"
