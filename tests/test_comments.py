import uuid
from datetime import timedelta

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


async def _comment(
    client: AsyncClient,
    headers: dict[str, str],
    task_id: str,
    body: str = "Looks good",
) -> dict:
    response = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        headers=headers,
        json={"body": body},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_list_comments(client: AsyncClient) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(client, alice_headers)

    bob = await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")
    created = await _comment(client, bob_headers, task["id"], "First comment")

    response = await client.get(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=alice_headers,
    )

    assert response.status_code == 200
    comments = response.json()
    assert len(comments) == 1
    assert comments[0]["id"] == created["id"]
    assert comments[0]["author_id"] == bob["id"]
    assert comments[0]["body"] == "First comment"
    assert comments[0]["created_at"].endswith("Z")


async def test_comment_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/tasks/{uuid.uuid4()}/comments")

    assert response.status_code == 401


async def test_comment_rejects_client_supplied_author(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)

    response = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=headers,
        json={"body": "Comment", "author_id": str(uuid.uuid4())},
    )

    assert response.status_code == 422


async def test_comment_body_validation(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)

    blank = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=headers,
        json={"body": "   "},
    )
    too_long = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=headers,
        json={"body": "x" * 2001},
    )
    maximum = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=headers,
        json={"body": "x" * 2000},
    )

    assert blank.status_code == 422
    assert too_long.status_code == 422
    assert maximum.status_code == 201


async def test_comments_allowed_on_terminal_tasks(
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

    done_comment = await client.post(
        f"/api/v1/tasks/{done_task['id']}/comments",
        headers=headers,
        json={"body": "Done comment"},
    )
    cancelled_comment = await client.post(
        f"/api/v1/tasks/{cancelled_task['id']}/comments",
        headers=headers,
        json={"body": "Cancelled comment"},
    )

    assert done_comment.status_code == 201
    assert cancelled_comment.status_code == 201


async def test_comment_on_missing_task_returns_404(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.post(
        f"/api/v1/tasks/{uuid.uuid4()}/comments",
        headers=headers,
        json={"body": "Comment"},
    )

    assert response.status_code == 404


async def test_edit_own_comment(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)
    comment = await _comment(client, headers, task["id"], "Original")

    clock.set_now(clock.now() + timedelta(minutes=2))
    response = await client.patch(
        f"/api/v1/comments/{comment['id']}",
        headers=headers,
        json={"body": "Edited"},
    )

    assert response.status_code == 200
    assert response.json()["body"] == "Edited"
    assert response.json()["updated_at"] != comment["updated_at"]


async def test_edit_other_comment_is_forbidden(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(client, alice_headers)
    comment = await _comment(client, alice_headers, task["id"])

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")
    forbidden = await client.patch(
        f"/api/v1/comments/{comment['id']}",
        headers=bob_headers,
        json={"body": "Bob edit"},
    )
    assert forbidden.status_code == 403

    await make_admin(session_factory, "bob")
    admin_forbidden = await client.patch(
        f"/api/v1/comments/{comment['id']}",
        headers=bob_headers,
        json={"body": "Admin edit"},
    )
    assert admin_forbidden.status_code == 403


async def test_delete_own_comment(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)
    comment = await _comment(client, headers, task["id"])

    response = await client.delete(
        f"/api/v1/comments/{comment['id']}",
        headers=headers,
    )
    listing = await client.get(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=headers,
    )

    assert response.status_code == 204
    assert listing.json() == []


async def test_delete_other_comment_is_forbidden(client: AsyncClient) -> None:
    await register_account(client, "alice")
    alice_headers = await auth_headers(client, "alice")
    task = await create_task(client, alice_headers)
    comment = await _comment(client, alice_headers, task["id"])

    await register_account(client, "bob")
    bob_headers = await auth_headers(client, "bob")

    response = await client.delete(
        f"/api/v1/comments/{comment['id']}",
        headers=bob_headers,
    )

    assert response.status_code == 403


async def test_comments_of_deleted_task_are_inaccessible(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(client, headers)
    comment = await _comment(client, headers, task["id"])
    await client.delete(f"/api/v1/tasks/{task['id']}", headers=headers)

    listing = await client.get(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=headers,
    )
    creation = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        headers=headers,
        json={"body": "Nope"},
    )
    editing = await client.patch(
        f"/api/v1/comments/{comment['id']}",
        headers=headers,
        json={"body": "Nope"},
    )
    deletion = await client.delete(
        f"/api/v1/comments/{comment['id']}",
        headers=headers,
    )

    assert listing.status_code == 404
    assert creation.status_code == 404
    assert editing.status_code == 404
    assert deletion.status_code == 404


async def test_comment_missing_returns_404(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    response = await client.patch(
        f"/api/v1/comments/{uuid.uuid4()}",
        headers=headers,
        json={"body": "Nope"},
    )

    assert response.status_code == 404
