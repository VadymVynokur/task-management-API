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


async def _overdue(client: AsyncClient, headers: dict[str, str], **params) -> dict:
    response = await client.get("/api/v1/tasks/overdue", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_overdue_criteria_and_statuses(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    due_today = clock.today_value.isoformat()

    backlog = await create_task(client, headers, title="Backlog", due_date=due_today)
    in_progress = await create_task(client, headers, title="In progress", due_date=due_today)
    await transition_task(client, headers, in_progress["id"], "In Progress")
    in_review = await create_task(client, headers, title="In review", due_date=due_today)
    await transition_task(client, headers, in_review["id"], "In Progress")
    await transition_task(client, headers, in_review["id"], "Review")
    done = await create_task(
        client,
        headers,
        title="Done",
        assignee_id=bob["id"],
        due_date=due_today,
    )
    await move_task_to_done(client, headers, done["id"])
    cancelled = await create_task(client, headers, title="Cancelled", due_date=due_today)
    await transition_task(client, headers, cancelled["id"], "Cancelled")
    no_deadline = await create_task(client, headers, title="No deadline")

    before = await _overdue(client, headers)
    clock.set_today(clock.today_value + timedelta(days=1))
    after = await _overdue(client, headers)

    assert before["total"] == 0
    assert {item["id"] for item in after["items"]} == {
        backlog["id"],
        in_progress["id"],
        in_review["id"],
    }
    assert no_deadline["id"] not in {item["id"] for item in after["items"]}


async def test_due_today_is_not_overdue(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    await create_task(client, headers, title="Today", due_date=clock.today_value.isoformat())

    result = await _overdue(client, headers)

    assert result["total"] == 0


async def test_overdue_is_global_scope(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        alice_headers,
        title="Alice task",
        due_date=clock.today_value.isoformat(),
    )

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")
    clock.set_today(clock.today_value + timedelta(days=1))

    result = await _overdue(client, bob_headers)

    assert [item["id"] for item in result["items"]] == [task["id"]]


async def test_soft_deleted_tasks_are_not_overdue(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        headers,
        title="Deleted",
        due_date=clock.today_value.isoformat(),
    )
    await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)

    clock.set_today(clock.today_value + timedelta(days=1))
    result = await _overdue(client, headers)

    assert result["total"] == 0


async def test_overdue_pagination_and_ordering(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    due_today = clock.today_value.isoformat()
    high = await create_task(
        client,
        headers,
        title="High",
        priority="High",
        due_date=due_today,
    )
    medium = await create_task(
        client,
        headers,
        title="Medium",
        priority="Medium",
        due_date=due_today,
    )
    low = await create_task(
        client,
        headers,
        title="Low",
        priority="Low",
        due_date=due_today,
    )

    clock.set_today(clock.today_value + timedelta(days=1))
    first_page = await _overdue(client, headers, page=1, page_size=2)
    second_page = await _overdue(client, headers, page=2, page_size=2)

    assert [item["id"] for item in first_page["items"]] == [high["id"], medium["id"]]
    assert [item["id"] for item in second_page["items"]] == [low["id"]]
    assert first_page["pages"] == 2


async def test_overdue_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/overdue")

    assert response.status_code == 401
