import math
import uuid
from datetime import date

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from task_management_api.core.clock import Clock
from task_management_api.core.config import Settings
from task_management_api.core.exceptions import AppError
from task_management_api.enums import (
    ACTIVE_STATUSES,
    ALLOWED_TRANSITIONS,
    MAX_ACTIVE_TASKS,
    PRIORITY_RANK,
    TaskPriority,
    TaskStatus,
    UserRole,
)
from task_management_api.models.task import Task
from task_management_api.models.user import User
from task_management_api.schemas.task import (
    SortOrder,
    TaskCreate,
    TaskSortField,
    TaskUpdate,
)

PRIORITY_RANK_EXPRESSION = case(
    PRIORITY_RANK,
    value=Task.priority,
    else_=99,
)


def _today(settings: Settings, clock: Clock):
    return clock.today(settings.tzinfo)


def _validate_due_date(due_date, settings: Settings, clock: Clock) -> None:
    if due_date is not None and due_date < _today(settings, clock):
        raise AppError(422, "due_date must not be earlier than today")


async def get_task_or_404(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Task:
    statement = select(Task).where(Task.id == task_id, Task.deleted_at.is_(None))
    if for_update:
        statement = statement.with_for_update()
    task = await session.scalar(statement)
    if task is None:
        raise AppError(404, "Task not found")
    return task


def ensure_can_manage(task: Task, user: User) -> None:
    if user.role != UserRole.admin and task.created_by_id != user.id:
        raise AppError(403, "Not enough permissions")


async def _lock_assignee(session: AsyncSession, assignee_id: uuid.UUID) -> None:
    assignee = await session.scalar(select(User.id).where(User.id == assignee_id).with_for_update())
    if assignee is None:
        raise AppError(422, "Assignee not found")


async def _count_active_tasks(
    session: AsyncSession,
    assignee_id: uuid.UUID,
    *,
    exclude_task_id: uuid.UUID | None = None,
) -> int:
    conditions = [
        Task.assignee_id == assignee_id,
        Task.status.in_(ACTIVE_STATUSES),
        Task.deleted_at.is_(None),
    ]
    if exclude_task_id is not None:
        conditions.append(Task.id != exclude_task_id)
    count = await session.scalar(select(func.count(Task.id)).where(*conditions))
    return int(count or 0)


async def _ensure_active_limit(
    session: AsyncSession,
    assignee_id: uuid.UUID,
    *,
    exclude_task_id: uuid.UUID | None = None,
) -> None:
    if await _count_active_tasks(session, assignee_id, exclude_task_id=exclude_task_id) >= (
        MAX_ACTIVE_TASKS
    ):
        raise AppError(409, "Active task limit exceeded")


async def create_task(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    user: User,
    data: TaskCreate,
) -> Task:
    _validate_due_date(data.due_date, settings, clock)

    if data.assignee_id is not None:
        await _lock_assignee(session, data.assignee_id)
        await _ensure_active_limit(session, data.assignee_id)

    now = clock.now()
    task = Task(
        title=data.title,
        description=data.description,
        status=TaskStatus.backlog,
        priority=data.priority,
        assignee_id=data.assignee_id,
        created_by_id=user.id,
        due_date=data.due_date,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def update_task(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    user: User,
    task_id: uuid.UUID,
    data: TaskUpdate,
) -> Task:
    task = await get_task_or_404(session, task_id, for_update=True)
    ensure_can_manage(task, user)

    if task.status in {TaskStatus.done, TaskStatus.cancelled}:
        raise AppError(409, "Task cannot be edited in its current status")

    fields = data.model_fields_set

    if "title" in fields:
        if data.title is None:
            raise AppError(422, "title must not be null")
        task.title = data.title
    if "description" in fields:
        task.description = data.description
    if "priority" in fields:
        if data.priority is None:
            raise AppError(422, "priority must not be null")
        task.priority = data.priority
    if "due_date" in fields:
        _validate_due_date(data.due_date, settings, clock)
        task.due_date = data.due_date
    if "assignee_id" in fields and data.assignee_id != task.assignee_id:
        if task.status == TaskStatus.review:
            raise AppError(409, "Assignee cannot be changed for a task in Review")
        if data.assignee_id is not None:
            await _lock_assignee(session, data.assignee_id)
            await _ensure_active_limit(
                session,
                data.assignee_id,
                exclude_task_id=task.id,
            )
        task.assignee_id = data.assignee_id

    task.updated_at = clock.now()
    await session.commit()
    await session.refresh(task)
    return task


async def change_status(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    user: User,
    task_id: uuid.UUID,
    target_status: TaskStatus,
) -> Task:
    task = await get_task_or_404(session, task_id, for_update=True)
    ensure_can_manage(task, user)

    if target_status not in ALLOWED_TRANSITIONS[task.status]:
        raise AppError(409, "Invalid status transition")

    if target_status == TaskStatus.done:
        if task.assignee_id is None:
            raise AppError(409, "Task cannot be completed without an assignee")
        if task.due_date is not None and task.due_date < _today(settings, clock):
            raise AppError(409, "Task cannot be completed after its deadline")

    task.status = target_status
    task.updated_at = clock.now()
    await session.commit()
    await session.refresh(task)
    return task


async def soft_delete_task(
    session: AsyncSession,
    clock: Clock,
    user: User,
    task_id: uuid.UUID,
) -> None:
    task = await get_task_or_404(session, task_id, for_update=True)
    ensure_can_manage(task, user)

    if task.status in {TaskStatus.in_progress, TaskStatus.review}:
        raise AppError(409, "Task cannot be deleted in its current status")

    now = clock.now()
    task.deleted_at = now
    task.updated_at = now
    await session.commit()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _list_conditions(
    *,
    q: str | None,
    statuses: list[TaskStatus] | None,
    priorities: list[TaskPriority] | None,
    assignee_id: uuid.UUID | None,
    due_from: date | None,
    due_to: date | None,
) -> list:
    conditions = [Task.deleted_at.is_(None)]
    if q:
        pattern = f"%{_escape_like(q)}%"
        conditions.append(
            or_(
                Task.title.ilike(pattern, escape="\\"),
                Task.description.ilike(pattern, escape="\\"),
            )
        )
    if statuses:
        conditions.append(Task.status.in_(statuses))
    if priorities:
        conditions.append(Task.priority.in_(priorities))
    if assignee_id is not None:
        conditions.append(Task.assignee_id == assignee_id)
    if due_from is not None:
        conditions.append(Task.due_date >= due_from)
    if due_to is not None:
        conditions.append(Task.due_date <= due_to)
    return conditions


def _list_order_by(
    sort_by: TaskSortField | None,
    sort_order: SortOrder,
) -> list:
    descending = sort_order == SortOrder.desc
    if sort_by is None:
        return [
            PRIORITY_RANK_EXPRESSION.asc(),
            Task.due_date.asc().nulls_last(),
            Task.id.asc(),
        ]
    if sort_by == TaskSortField.created_at:
        primary = Task.created_at.desc() if descending else Task.created_at.asc()
    elif sort_by == TaskSortField.due_date:
        primary = Task.due_date.desc() if descending else Task.due_date.asc()
        primary = primary.nulls_last()
    else:
        primary = PRIORITY_RANK_EXPRESSION.desc() if descending else PRIORITY_RANK_EXPRESSION.asc()
    return [primary, Task.id.asc()]


async def _paginated_tasks(
    session: AsyncSession,
    conditions: list,
    order_by: list,
    *,
    page: int,
    page_size: int,
) -> tuple[list[Task], int, int]:
    total = await session.scalar(select(func.count(Task.id)).where(*conditions))
    total = int(total or 0)
    statement = (
        select(Task)
        .where(*conditions)
        .order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.scalars(statement)).all())
    pages = math.ceil(total / page_size) if total else 0
    return items, total, pages


async def list_tasks(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    q: str | None = None,
    statuses: list[TaskStatus] | None = None,
    priorities: list[TaskPriority] | None = None,
    assignee_id: uuid.UUID | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    sort_by: TaskSortField | None = None,
    sort_order: SortOrder = SortOrder.asc,
) -> tuple[list[Task], int, int]:
    conditions = _list_conditions(
        q=q,
        statuses=statuses,
        priorities=priorities,
        assignee_id=assignee_id,
        due_from=due_from,
        due_to=due_to,
    )
    order_by = _list_order_by(sort_by, sort_order)
    return await _paginated_tasks(
        session,
        conditions,
        order_by,
        page=page,
        page_size=page_size,
    )


async def overdue_tasks(
    session: AsyncSession,
    settings: Settings,
    clock: Clock,
    *,
    page: int,
    page_size: int,
) -> tuple[list[Task], int, int]:
    today = _today(settings, clock)
    conditions = [
        Task.deleted_at.is_(None),
        Task.due_date.is_not(None),
        Task.due_date < today,
        Task.status.in_(ACTIVE_STATUSES),
    ]
    order_by = [
        PRIORITY_RANK_EXPRESSION.asc(),
        Task.due_date.asc().nulls_last(),
        Task.id.asc(),
    ]
    return await _paginated_tasks(
        session,
        conditions,
        order_by,
        page=page,
        page_size=page_size,
    )
