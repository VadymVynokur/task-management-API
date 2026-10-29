import logging
import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from task_management_api.core.config import Settings
from task_management_api.enums import TaskStatus
from task_management_api.models.comment import Comment
from task_management_api.models.task import Task
from task_management_api.workers.deadline import cancel_overdue_tasks, run_check, run_worker
from tests.conftest import FakeClock
from tests.helpers import (
    auth_headers,
    create_task,
    move_task_to_done,
    register_account,
    transition_task,
)


async def _stored_task(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: str,
) -> Task:
    async with session_factory() as session:
        task = await session.scalar(select(Task).where(Task.id == uuid.UUID(task_id)))
    assert task is not None
    return task


async def _run_check(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    clock: FakeClock,
) -> int:
    async with session_factory() as session:
        return await cancel_overdue_tasks(session, settings, clock)


async def test_worker_cancels_only_eligible_overdue_tasks(
    client: AsyncClient,
    settings: Settings,
    clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
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
    deleted = await create_task(client, headers, title="Deleted", due_date=due_today)
    await client.delete(f"/api/v1/tasks/{deleted['id']}", headers=headers)

    before = await _stored_task(session_factory, backlog["id"])
    clock.set_today(clock.today_value + timedelta(days=1))
    clock.set_now(clock.now() + timedelta(days=1))

    count = await _run_check(session_factory, settings, clock)

    assert count == 3
    for task in (backlog, in_progress, in_review):
        stored = await _stored_task(session_factory, task["id"])
        assert stored.status == TaskStatus.cancelled
        assert stored.updated_at > before.updated_at
    assert (await _stored_task(session_factory, done["id"])).status == TaskStatus.done
    assert (await _stored_task(session_factory, cancelled["id"])).status == TaskStatus.cancelled
    assert (await _stored_task(session_factory, no_deadline["id"])).status == TaskStatus.backlog
    deleted_stored = await _stored_task(session_factory, deleted["id"])
    assert deleted_stored.status == TaskStatus.backlog
    assert deleted_stored.deleted_at is not None

    async with session_factory() as session:
        comment_count = await session.scalar(select(func.count(Comment.id)))
    assert comment_count == 0


async def test_worker_is_idempotent(
    client: AsyncClient,
    settings: Settings,
    clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        headers,
        title="Overdue",
        due_date=clock.today_value.isoformat(),
    )
    clock.set_today(clock.today_value + timedelta(days=1))
    clock.set_now(clock.now() + timedelta(days=1))

    first = await _run_check(session_factory, settings, clock)
    after_first = await _stored_task(session_factory, task["id"])
    second = await _run_check(session_factory, settings, clock)
    after_second = await _stored_task(session_factory, task["id"])

    assert first == 1
    assert second == 0
    assert after_first.status == TaskStatus.cancelled
    assert after_second.status == TaskStatus.cancelled
    assert after_second.updated_at == after_first.updated_at


async def test_worker_does_not_overwrite_done_task(
    client: AsyncClient,
    settings: Settings,
    clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bob = await register_account(client, "bob")
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        headers,
        title="Done task",
        assignee_id=bob["id"],
        due_date=clock.today_value.isoformat(),
    )
    await move_task_to_done(client, headers, task["id"])

    clock.set_today(clock.today_value + timedelta(days=1))
    clock.set_now(clock.now() + timedelta(days=1))
    count = await _run_check(session_factory, settings, clock)

    stored = await _stored_task(session_factory, task["id"])
    assert count == 0
    assert stored.status == TaskStatus.done


async def test_worker_runs_startup_check_then_sleeps_for_interval(
    client: AsyncClient,
    settings: Settings,
    clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        headers,
        title="Overdue",
        due_date=clock.today_value.isoformat(),
    )
    clock.set_today(clock.today_value + timedelta(days=1))
    clock.set_now(clock.now() + timedelta(days=1))

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    await run_worker(
        session_factory=session_factory,
        settings=settings,
        clock=clock,
        sleep=fake_sleep,
        max_iterations=2,
    )

    stored = await _stored_task(session_factory, task["id"])
    assert stored.status == TaskStatus.cancelled
    assert sleeps == [settings.worker_interval_seconds]


async def test_worker_logging_omits_sensitive_error_details(
    settings: Settings,
    caplog,
) -> None:
    class FailingFactory:
        def __call__(self):
            raise RuntimeError("database password=secret")

    with caplog.at_level(logging.INFO, logger="task_management_api.workers.deadline"):
        count = await run_check(FailingFactory(), settings, FakeClock())

    assert count == 0
    assert "Deadline check started" in caplog.text
    assert "Deadline check failed" in caplog.text
    assert "password=secret" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_worker_continues_after_transient_error(
    client: AsyncClient,
    settings: Settings,
    clock: FakeClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_account(client, "alice")
    headers = await auth_headers(client, "alice")
    task = await create_task(
        client,
        headers,
        title="Overdue",
        due_date=clock.today_value.isoformat(),
    )
    clock.set_today(clock.today_value + timedelta(days=1))
    clock.set_now(clock.now() + timedelta(days=1))

    class FailingOnceFactory:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database temporarily unavailable")
            return session_factory()

    failing_factory = FailingOnceFactory()

    async def fake_sleep(_: float) -> None:
        return None

    await run_worker(
        session_factory=failing_factory,
        settings=settings,
        clock=clock,
        sleep=fake_sleep,
        max_iterations=2,
    )

    stored = await _stored_task(session_factory, task["id"])
    assert failing_factory.calls == 2
    assert stored.status == TaskStatus.cancelled
