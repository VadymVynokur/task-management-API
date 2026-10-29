import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from task_management_api.core.clock import Clock, system_clock
from task_management_api.core.config import Settings, get_settings
from task_management_api.db.session import get_session_factory
from task_management_api.enums import ACTIVE_STATUSES, TaskStatus
from task_management_api.models.task import Task

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


async def cancel_overdue_tasks(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
) -> int:
    """Atomically cancel active tasks whose deadline has passed in the configured timezone."""
    today = clock.today(settings.tzinfo)
    now = clock.now()
    statement = (
        update(Task)
        .where(
            Task.due_date.is_not(None),
            Task.due_date < today,
            Task.status.in_(ACTIVE_STATUSES),
            Task.deleted_at.is_(None),
        )
        .values(status=TaskStatus.cancelled, updated_at=now)
    )
    result = await session.execute(statement)
    await session.commit()
    return int(result.rowcount or 0)


async def run_check(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    clock: Clock,
) -> int:
    try:
        async with session_factory() as session:
            cancelled = await cancel_overdue_tasks(session, settings, clock)
    except Exception:
        logger.exception("Deadline check failed; the next scheduled check will retry")
        return 0

    logger.info("Deadline check completed: cancelled %s overdue task(s)", cancelled)
    return cancelled


async def run_worker(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    settings: Settings | None = None,
    clock: Clock | None = None,
    sleep: Sleep = asyncio.sleep,
    max_iterations: int | None = None,
) -> None:
    resolved_settings = settings or get_settings()
    resolved_clock = clock or system_clock
    factory = session_factory or get_session_factory(resolved_settings)

    logger.info(
        "Deadline worker started (interval=%s seconds, timezone=%s)",
        resolved_settings.worker_interval_seconds,
        resolved_settings.timezone,
    )

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        await run_check(factory, resolved_settings, resolved_clock)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        await sleep(resolved_settings.worker_interval_seconds)

    logger.info("Deadline worker stopped")


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    try:
        asyncio.run(run_worker(settings=settings))
    except KeyboardInterrupt:
        logger.info("Deadline worker interrupted")


if __name__ == "__main__":
    main()
