from datetime import timedelta

from httpx import AsyncClient

from tests.conftest import FakeClock
from tests.helpers import auth_headers, create_task, register_account, transition_task


async def _list(client: AsyncClient, headers: dict[str, str], **params) -> dict:
    response = await client.get("/api/v1/tasks", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_search_is_case_insensitive_in_title_and_description(
    client: AsyncClient,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    await create_task(client, headers, title="Write Documentation")
    await create_task(client, headers, title="Fix bug", description="Important NOTES")
    await create_task(client, headers, title="Unrelated")

    title_match = await _list(client, headers, q="DOC")
    description_match = await _list(client, headers, q="notes")

    assert [item["title"] for item in title_match["items"]] == ["Write Documentation"]
    assert [item["title"] for item in description_match["items"]] == ["Fix bug"]


async def test_search_treats_wildcards_literally(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    await create_task(client, headers, title="100% done")
    await create_task(client, headers, title="Other")

    result = await _list(client, headers, q="%")

    assert result["total"] == 1
    assert result["items"][0]["title"] == "100% done"


async def test_filter_by_status_and_priority(client: AsyncClient, clock: FakeClock) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    backlog = await create_task(client, headers, title="Backlog", priority="High")
    in_progress = await create_task(client, headers, title="In progress")
    await transition_task(client, headers, in_progress["id"], "In Progress")
    done = await create_task(
        client,
        headers,
        title="Done",
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
        priority="Low",
    )
    await transition_task(client, headers, done["id"], "In Progress")
    await transition_task(client, headers, done["id"], "Review")
    await transition_task(client, headers, done["id"], "Done")

    backlog_only = await _list(client, headers, status="Backlog")
    two_statuses = await _list(client, headers, status=["Backlog", "Done"])
    high_priority = await _list(client, headers, priority="High")

    assert [item["id"] for item in backlog_only["items"]] == [backlog["id"]]
    assert {item["id"] for item in two_statuses["items"]} == {backlog["id"], done["id"]}
    assert [item["id"] for item in high_priority["items"]] == [backlog["id"]]


async def test_filter_by_assignee_and_due_date_range(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    today = clock.today_value
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    first = await create_task(
        client,
        headers,
        title="Today",
        assignee_id=bob["id"],
        due_date=today.isoformat(),
    )
    second = await create_task(
        client,
        headers,
        title="Tomorrow",
        assignee_id=bob["id"],
        due_date=tomorrow.isoformat(),
    )
    await create_task(client, headers, title="Day after", due_date=day_after.isoformat())

    by_assignee = await _list(client, headers, assignee_id=bob["id"])
    inclusive = await _list(
        client,
        headers,
        due_from=today.isoformat(),
        due_to=tomorrow.isoformat(),
    )

    assert {item["id"] for item in by_assignee["items"]} == {first["id"], second["id"]}
    assert {item["id"] for item in inclusive["items"]} == {first["id"], second["id"]}


async def test_filters_combine_with_and(client: AsyncClient, clock: FakeClock) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    match = await create_task(
        client,
        headers,
        title="Release checklist",
        description="Important release notes",
        priority="High",
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )
    await create_task(
        client,
        headers,
        title="Release checklist",
        description="Important release notes",
        priority="Low",
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )

    result = await _list(
        client,
        headers,
        q="release",
        status="Backlog",
        priority="High",
        assignee_id=bob["id"],
        due_from=clock.today_value.isoformat(),
        due_to=clock.today_value.isoformat(),
    )

    assert result["total"] == 1
    assert result["items"][0]["id"] == match["id"]


async def test_sort_by_created_at(client: AsyncClient, clock: FakeClock) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    first = await create_task(client, headers, title="First")
    clock.set_now(clock.now() + timedelta(minutes=1))
    second = await create_task(client, headers, title="Second")
    clock.set_now(clock.now() + timedelta(minutes=1))
    third = await create_task(client, headers, title="Third")

    ascending = await _list(client, headers, sort_by="created_at", sort_order="asc")
    descending = await _list(client, headers, sort_by="created_at", sort_order="desc")

    assert [item["id"] for item in ascending["items"]] == [
        first["id"],
        second["id"],
        third["id"],
    ]
    assert [item["id"] for item in descending["items"]] == [
        third["id"],
        second["id"],
        first["id"],
    ]


async def test_sort_by_due_date_keeps_nulls_last(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    today = clock.today_value
    tomorrow = today + timedelta(days=1)

    today_task = await create_task(client, headers, title="Today", due_date=today.isoformat())
    no_deadline = await create_task(client, headers, title="No deadline")
    tomorrow_task = await create_task(
        client,
        headers,
        title="Tomorrow",
        due_date=tomorrow.isoformat(),
    )

    ascending = await _list(client, headers, sort_by="due_date", sort_order="asc")
    descending = await _list(client, headers, sort_by="due_date", sort_order="desc")

    assert [item["id"] for item in ascending["items"]] == [
        today_task["id"],
        tomorrow_task["id"],
        no_deadline["id"],
    ]
    assert [item["id"] for item in descending["items"]] == [
        tomorrow_task["id"],
        today_task["id"],
        no_deadline["id"],
    ]


async def test_sort_by_priority(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    high = await create_task(client, headers, title="High", priority="High")
    medium = await create_task(client, headers, title="Medium", priority="Medium")
    low = await create_task(client, headers, title="Low", priority="Low")

    ascending = await _list(client, headers, sort_by="priority", sort_order="asc")
    descending = await _list(client, headers, sort_by="priority", sort_order="desc")

    assert [item["id"] for item in ascending["items"]] == [
        high["id"],
        medium["id"],
        low["id"],
    ]
    assert [item["id"] for item in descending["items"]] == [
        low["id"],
        medium["id"],
        high["id"],
    ]


async def test_default_ordering_priority_then_deadline(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    today = clock.today_value
    tomorrow = today + timedelta(days=1)

    high_today = await create_task(
        client,
        headers,
        title="High today",
        priority="High",
        due_date=today.isoformat(),
    )
    high_tomorrow = await create_task(
        client,
        headers,
        title="High tomorrow",
        priority="High",
        due_date=tomorrow.isoformat(),
    )
    medium_no_deadline = await create_task(
        client,
        headers,
        title="Medium no deadline",
        priority="Medium",
    )
    low_today = await create_task(
        client,
        headers,
        title="Low today",
        priority="Low",
        due_date=today.isoformat(),
    )

    result = await _list(client, headers)

    assert [item["id"] for item in result["items"]] == [
        high_today["id"],
        high_tomorrow["id"],
        medium_no_deadline["id"],
        low_today["id"],
    ]


async def test_pagination_is_stable_and_has_no_duplicates(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    created = [await create_task(client, headers, title=f"Task {index}") for index in range(5)]

    seen: list[str] = []
    for page in range(1, 4):
        result = await _list(client, headers, page=page, page_size=2)
        seen.extend(item["id"] for item in result["items"])

    assert len(seen) == 5
    assert len(set(seen)) == 5
    assert set(seen) == {task["id"] for task in created}


async def test_pagination_defaults_and_limits(client: AsyncClient) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")

    default = await _list(client, headers)
    too_large = await client.get(
        "/api/v1/tasks",
        headers=headers,
        params={"page_size": 101},
    )
    invalid_sort = await client.get(
        "/api/v1/tasks",
        headers=headers,
        params={"sort_by": "title"},
    )
    invalid_status = await client.get(
        "/api/v1/tasks",
        headers=headers,
        params={"status": "Todo"},
    )

    assert default["page"] == 1
    assert default["page_size"] == 20
    assert too_large.status_code == 422
    assert invalid_sort.status_code == 422
    assert invalid_status.status_code == 422


async def test_due_range_with_lower_bound_after_upper_bound_returns_empty(
    client: AsyncClient,
    clock: FakeClock,
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    today = clock.today_value

    result = await _list(
        client,
        headers,
        due_from=(today + timedelta(days=1)).isoformat(),
        due_to=today.isoformat(),
    )

    assert result["total"] == 0
