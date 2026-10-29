from datetime import timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import FakeClock
from tests.helpers import (
    auth_headers,
    create_task,
    make_admin,
    move_task_to_done,
    register_account,
    transition_task,
)


async def _create_in_progress(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:
    task = await create_task(client, headers, **overrides)
    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "In Progress"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_in_review(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:
    task = await _create_in_progress(client, headers, **overrides)
    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Review"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("setup_status", "target_status"),
    [
        ("Backlog", "In Progress"),
        ("Backlog", "Cancelled"),
        ("In Progress", "Review"),
        ("In Progress", "Cancelled"),
    ],
)
async def test_valid_status_transitions(
    client: AsyncClient,
    setup_status: str,
    target_status: str,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    if setup_status == "Backlog":
        task = await create_task(client, headers)
    else:
        task = await _create_in_progress(client, headers)

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": target_status},
    )

    assert response.status_code == 200
    assert response.json()["status"] == target_status


async def test_review_to_done_succeeds(client: AsyncClient, clock: FakeClock) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await _create_in_review(
        client,
        headers,
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Done"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "Done"


@pytest.mark.parametrize(
    ("setup_status", "target_status"),
    [
        ("Backlog", "Review"),
        ("Backlog", "Done"),
        ("Backlog", "Backlog"),
        ("In Progress", "Done"),
        ("In Progress", "Backlog"),
        ("In Progress", "In Progress"),
        ("Review", "Cancelled"),
        ("Review", "In Progress"),
        ("Review", "Backlog"),
        ("Review", "Review"),
        ("Done", "Backlog"),
        ("Done", "In Progress"),
        ("Done", "Review"),
        ("Done", "Done"),
        ("Done", "Cancelled"),
        ("Cancelled", "Backlog"),
        ("Cancelled", "In Progress"),
        ("Cancelled", "Review"),
        ("Cancelled", "Done"),
        ("Cancelled", "Cancelled"),
    ],
)
async def test_invalid_status_transitions(
    client: AsyncClient,
    clock: FakeClock,
    setup_status: str,
    target_status: str,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    if setup_status == "Backlog":
        task = await create_task(
            client,
            headers,
            assignee_id=bob["id"],
            due_date=clock.today_value.isoformat(),
        )
    elif setup_status == "In Progress":
        task = await _create_in_progress(
            client,
            headers,
            assignee_id=bob["id"],
            due_date=clock.today_value.isoformat(),
        )
    elif setup_status == "Review":
        task = await _create_in_review(
            client,
            headers,
            assignee_id=bob["id"],
            due_date=clock.today_value.isoformat(),
        )
    elif setup_status == "Done":
        task = await create_task(
            client,
            headers,
            assignee_id=bob["id"],
            due_date=clock.today_value.isoformat(),
        )
        task = await move_task_to_done(client, headers, task["id"])
    else:
        task = await create_task(client, headers)
        task = await transition_task(client, headers, task["id"], "Cancelled")

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": target_status},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Invalid status transition"


async def test_done_requires_assignee(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await _create_in_review(client, headers)

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Done"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Task cannot be completed without an assignee"


async def test_done_without_deadline_is_allowed(client: AsyncClient) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await _create_in_review(client, headers, assignee_id=bob["id"])

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Done"},
    )

    assert response.status_code == 200


async def test_done_with_today_deadline_is_allowed(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await _create_in_review(
        client,
        headers,
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Done"},
    )

    assert response.status_code == 200


async def test_done_after_deadline_is_rejected(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await _create_in_review(
        client,
        headers,
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )

    clock.set_today(clock.today_value + timedelta(days=1))

    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "Done"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Task cannot be completed after its deadline"


async def test_terminal_tasks_cannot_transition(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    done_task = await _create_in_review(
        client,
        headers,
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )
    await client.patch(
        f"/api/v1/tasks/{done_task['id']}/status",
        headers=headers,
        json={"status": "Done"},
    )

    cancelled_task = await create_task(client, headers)
    await client.patch(
        f"/api/v1/tasks/{cancelled_task['id']}/status",
        headers=headers,
        json={"status": "Cancelled"},
    )

    for task, target in ((done_task, "Cancelled"), (cancelled_task, "Backlog")):
        response = await client.patch(
            f"/api/v1/tasks/{task['id']}/status",
            headers=headers,
            json={"status": target},
        )
        assert response.status_code == 409


async def test_status_change_updates_updated_at(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)
    original_updated_at = task["updated_at"]

    clock.set_now(clock.now() + timedelta(minutes=5))
    response = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=headers,
        json={"status": "In Progress"},
    )

    assert response.status_code == 200
    assert response.json()["updated_at"] != original_updated_at


async def test_status_change_requires_owner_or_admin(
    client: AsyncClient,
    session_factory,
) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(client, alice_headers)

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")
    forbidden = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=bob_headers,
        json={"status": "In Progress"},
    )
    assert forbidden.status_code == 403

    await make_admin(session_factory, "alice")
    allowed = await client.patch(
        f"/api/v1/tasks/{task['id']}/status",
        headers=alice_headers,
        json={"status": "In Progress"},
    )
    assert allowed.status_code == 200
