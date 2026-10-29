from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from task_management_api.core.clock import Clock
from task_management_api.core.config import Settings
from task_management_api.enums import ACTIVE_STATUSES, TaskPriority, TaskStatus
from task_management_api.models.task import Task
from task_management_api.schemas.statistics import StatisticsResponse


async def get_statistics(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
) -> StatisticsResponse:
    not_deleted = Task.deleted_at.is_(None)

    total = int(await session.scalar(select(func.count(Task.id)).where(not_deleted)) or 0)

    status_rows = await session.execute(
        select(Task.status, func.count(Task.id)).where(not_deleted).group_by(Task.status)
    )
    by_status = {status: 0 for status in TaskStatus}
    by_status.update({status: int(count) for status, count in status_rows.all()})

    priority_rows = await session.execute(
        select(Task.priority, func.count(Task.id)).where(not_deleted).group_by(Task.priority)
    )
    by_priority = {priority: 0 for priority in TaskPriority}
    by_priority.update({priority: int(count) for priority, count in priority_rows.all()})

    today = clock.today(settings.tzinfo)
    overdue = int(
        await session.scalar(
            select(func.count(Task.id)).where(
                not_deleted,
                Task.due_date.is_not(None),
                Task.due_date < today,
                Task.status.in_(ACTIVE_STATUSES),
            )
        )
        or 0
    )
    active = int(
        await session.scalar(
            select(func.count(Task.id)).where(
                not_deleted,
                Task.status.in_(ACTIVE_STATUSES),
            )
        )
        or 0
    )

    return StatisticsResponse(
        total=total,
        by_status=by_status,
        by_priority=by_priority,
        overdue=overdue,
        active=active,
    )
