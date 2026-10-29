from datetime import timedelta

from httpx import AsyncClient

from tests.conftest import FakeClock
from tests.helpers import (
    auth_headers,
    create_task,
    move_task_to_done,
    register_account,
    transition_task,
)


async def _stats(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/api/v1/tasks/statistics", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_empty_statistics_include_zero_categories(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    stats = await _stats(client, headers)

    assert stats["total"] == 0
    assert stats["active"] == 0
    assert stats["overdue"] == 0
    assert stats["by_status"] == {
        "Backlog": 0,
        "In Progress": 0,
        "Review": 0,
        "Done": 0,
        "Cancelled": 0,
    }
    assert stats["by_priority"] == {"High": 0, "Medium": 0, "Low": 0}


async def test_statistics_counts_statuses_priorities_and_active(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    due_today = clock.today_value.isoformat()

    backlog_high = await create_task(client, headers, title="Backlog high", priority="High")
    backlog_high_two = await create_task(client, headers, title="Backlog high two", priority="High")
    in_progress = await create_task(client, headers, title="In progress", priority="Medium")
    await transition_task(client, headers, in_progress["id"], "In Progress")
    review = await create_task(client, headers, title="Review", priority="Low")
    await transition_task(client, headers, review["id"], "In Progress")
    await transition_task(client, headers, review["id"], "Review")
    done = await create_task(
        client,
        headers,
        title="Done",
        priority="High",
        assignee_id=bob["id"],
        due_date=due_today,
    )
    await move_task_to_done(client, headers, done["id"])
    cancelled = await create_task(client, headers, title="Cancelled", priority="Medium")
    await transition_task(client, headers, cancelled["id"], "Cancelled")
    deleted = await create_task(client, headers, title="Deleted", priority="High")
    await client.delete(f"/api/v1/tasks/{deleted['id']}", headers=headers)

    stats = await _stats(client, headers)

    assert stats["total"] == 6
    assert stats["by_status"] == {
        "Backlog": 2,
        "In Progress": 1,
        "Review": 1,
        "Done": 1,
        "Cancelled": 1,
    }
    assert stats["by_priority"] == {"High": 3, "Medium": 2, "Low": 1}
    assert stats["active"] == 4
    assert stats["overdue"] == 0
    assert backlog_high["id"] != backlog_high_two["id"]


async def test_statistics_are_global(client: AsyncClient) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    await create_task(client, alice_headers, title="Alice task")

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")

    stats = await _stats(client, bob_headers)

    assert stats["total"] == 1
    assert stats["by_status"]["Backlog"] == 1


async def test_statistics_overdue_count(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    await create_task(
        client,
        headers,
        title="Overdue",
        due_date=clock.today_value.isoformat(),
    )
    await create_task(
        client,
        headers,
        title="Future",
        due_date=(clock.today_value + timedelta(days=1)).isoformat(),
    )
    await create_task(client, headers, title="No deadline")

    clock.set_today(clock.today_value + timedelta(days=1))
    stats = await _stats(client, headers)

    assert stats["total"] == 3
    assert stats["overdue"] == 1
    assert stats["active"] == 3


async def test_statistics_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/statistics")

    assert response.status_code == 401
