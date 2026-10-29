import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import FakeClock
from tests.helpers import (
    auth_headers,
    create_task,
    make_admin,
    move_task_to_done,
    register_account,
    transition_task,
)


async def test_create_task_defaults(client: AsyncClient) -> None:
    alice = await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Write specification"},
    )

    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Write specification"
    assert task["description"] is None
    assert task["status"] == "Backlog"
    assert task["priority"] == "Medium"
    assert task["assignee_id"] is None
    assert task["created_by_id"] == alice["id"]
    assert task["due_date"] is None
    assert task["created_at"].endswith("Z")
    assert task["updated_at"].endswith("Z")


async def test_create_task_with_all_fields(client: AsyncClient, clock: FakeClock) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Prepare release",
            "description": "Release notes and checks",
            "priority": "High",
            "assignee_id": bob["id"],
            "due_date": clock.today_value.isoformat(),
        },
    )

    assert response.status_code == 201
    task = response.json()
    assert task["description"] == "Release notes and checks"
    assert task["priority"] == "High"
    assert task["assignee_id"] == bob["id"]
    assert task["due_date"] == clock.today_value.isoformat()


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "Done"},
        {"created_by_id": str(uuid.uuid4())},
        {"id": str(uuid.uuid4())},
        {"created_at": "2026-01-01T00:00:00Z"},
    ],
)
async def test_create_task_rejects_server_managed_fields(
    client: AsyncClient,
    extra: dict,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Task", **extra},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "Task", "description": "x" * 10_001},
        {"title": "Task", "priority": "Urgent"},
    ],
)
async def test_create_task_rejects_invalid_fields(
    client: AsyncClient,
    payload: dict,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.post("/api/v1/tasks", headers=headers, json=payload)

    assert response.status_code == 422


async def test_create_task_deadline_rules(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    today = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Today", "due_date": clock.today_value.isoformat()},
    )
    yesterday = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Yesterday",
            "due_date": (clock.today_value - timedelta(days=1)).isoformat(),
        },
    )
    no_deadline = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "No deadline", "due_date": None},
    )

    assert today.status_code == 201
    assert yesterday.status_code == 422
    assert no_deadline.status_code == 201


async def test_create_task_rejects_unknown_assignee(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Task", "assignee_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Assignee not found"


async def test_create_task_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tasks", json={"title": "Task"})

    assert response.status_code == 401


async def test_task_visibility_is_global(client: AsyncClient) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(client, alice_headers, title="Alice task")

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")

    response = await client.get(f"/api/v1/tasks/{task['id']}", headers=bob_headers)

    assert response.status_code == 200
    assert response.json()["id"] == task["id"]


async def test_get_missing_task_returns_404(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.get(f"/api/v1/tasks/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404


async def test_update_task_fields(client: AsyncClient, clock: FakeClock) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers, due_date=clock.today_value.isoformat())
    original_updated_at = task["updated_at"]

    clock.set_now(clock.now() + timedelta(minutes=1))
    response = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={
            "title": "Updated title",
            "description": "Updated description",
            "priority": "Low",
            "assignee_id": bob["id"],
            "due_date": None,
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Updated title"
    assert updated["description"] == "Updated description"
    assert updated["priority"] == "Low"
    assert updated["assignee_id"] == bob["id"]
    assert updated["due_date"] is None
    assert updated["updated_at"] != original_updated_at


@pytest.mark.parametrize(
    ("setup_status", "expected_status"),
    [
        ("Backlog", 200),
        ("In Progress", 200),
        ("Review", 200),
        ("Done", 409),
        ("Cancelled", 409),
    ],
)
async def test_update_behavior_per_status(
    client: AsyncClient,
    clock: FakeClock,
    setup_status: str,
    expected_status: int,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        headers,
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )

    if setup_status == "In Progress":
        task = await transition_task(client, headers, task["id"], "In Progress")
    elif setup_status == "Review":
        await transition_task(client, headers, task["id"], "In Progress")
        task = await transition_task(client, headers, task["id"], "Review")
    elif setup_status == "Done":
        task = await move_task_to_done(client, headers, task["id"])
    elif setup_status == "Cancelled":
        task = await transition_task(client, headers, task["id"], "Cancelled")

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"title": "Updated title"},
    )

    assert response.status_code == expected_status


async def test_update_rejects_terminal_tasks(client: AsyncClient, clock: FakeClock) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        headers,
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )
    await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "In Progress"},
    )
    await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Review"},
    )
    await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Done"},
    )

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"title": "Nope"},
    )

    assert response.status_code == 409

    cancelled = await create_task(client, headers, title="Cancelled")
    await client.patch(
        f"/api/v1/tasks/{cancelled['id']}/status",
        headers=headers,
        json={"status": "Cancelled"},
    )
    cancelled_update = await client.patch(
        f"/api/v1/tasks/{cancelled['id']}",
        headers=headers,
        json={"title": "Nope"},
    )
    assert cancelled_update.status_code == 409


async def test_update_review_task_allows_non_assignee_fields(
    client: AsyncClient,
) -> None:
    bob = await register_account(client, "bob")
    carol = await register_account(client, "carol")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers, assignee_id=bob["id"])
    for status in ("In Progress", "Review"):
        await client.patch(
            f"/api/v1/tasks/{task['id']}/status",
            headers=headers,
            json={"status": status},
        )

    assignee_change = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"assignee_id": carol["id"]},
    )
    title_change = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"title": "Still editable"},
    )
    same_assignee = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"assignee_id": bob["id"]},
    )

    assert assignee_change.status_code == 409
    assert title_change.status_code == 200
    assert same_assignee.status_code == 200


async def test_update_can_clear_due_date(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers, due_date=clock.today_value.isoformat())

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"due_date": None},
    )

    assert response.status_code == 200
    assert response.json()["due_date"] is None


async def test_update_rejects_past_due_date(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"due_date": (clock.today_value - timedelta(days=1)).isoformat()},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "Done"},
        {"created_by_id": str(uuid.uuid4())},
        {"created_at": "2026-01-01T00:00:00Z"},
    ],
)
async def test_update_rejects_server_managed_fields(
    client: AsyncClient,
    extra: dict,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=headers,
        json={"title": "Updated", **extra},
    )

    assert response.status_code == 422


async def test_update_requires_owner_or_admin(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(client, alice_headers)

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")
    forbidden = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=bob_headers,
        json={"title": "Bob edit"},
    )
    assert forbidden.status_code == 403

    await make_admin(session_factory, "alice")
    allowed = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        headers=alice_headers,
        json={"title": "Admin edit"},
    )
    assert allowed.status_code == 200


async def test_update_missing_task_returns_404(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.patch(
        f"/api/v1/tasks/{uuid.uuid4()}",
        headers=headers,
        json={"title": "Nope"},
    )

    assert response.status_code == 404


async def test_list_tasks_is_paginated_and_excludes_deleted(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    first = await create_task(client, headers, title="First")
    await create_task(client, headers, title="Second")
    await create_task(client, headers, title="Third")
    await client.delete(f"/api/v1/tasks/{first['id']}", headers=headers)

    page_one = await client.get(
        "/api/v1/tasks",
        headers=headers,
        params={"page": 1, "page_size": 2},
    )
    page_two = await client.get(
        "/api/v1/tasks",
        headers=headers,
        params={"page": 2, "page_size": 2},
    )

    assert page_one.status_code == 200
    assert page_one.json()["total"] == 2
    assert page_one.json()["pages"] == 1
    assert len(page_one.json()["items"]) == 2
    assert page_two.status_code == 200
    assert page_two.json()["items"] == []


async def test_list_tasks_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks")

    assert response.status_code == 401


async def test_list_rejects_page_size_above_maximum(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.get(
        "/api/v1/tasks",
        headers=headers,
        params={"page_size": 101},
    )

    assert response.status_code == 422
