import uuid

from fastapi import APIRouter, Response, status

from task_management_api.api.deps import ClockDep, CurrentUser, SessionDep, SettingsDep
from task_management_api.api.pagination import PaginationDep
from task_management_api.schemas.task import (
    TaskCreate,
    TaskPage,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
)
from task_management_api.services.tasks import (
    change_status,
    create_task,
    get_task_or_404,
    list_tasks,
    soft_delete_task,
    update_task,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskPage)
async def list_tasks_route(
    _user: CurrentUser,
    session: SessionDep,
    pagination: PaginationDep,
) -> TaskPage:
    items, total, pages = await list_tasks(
        session,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return TaskPage(
        items=[TaskResponse.model_validate(task) for task in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        pages=pages,
    )


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task_route(
    payload: TaskCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> TaskResponse:
    task = await create_task(session, settings, clock, user, payload)
    return TaskResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_route(
    task_id: uuid.UUID,
    _user: CurrentUser,
    session: SessionDep,
) -> TaskResponse:
    task = await get_task_or_404(session, task_id)
    return TaskResponse.model_validate(task)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task_route(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> TaskResponse:
    task = await update_task(session, settings, clock, user, task_id, payload)
    return TaskResponse.model_validate(task)


@router.patch("/{task_id}/status", response_model=TaskResponse)
async def change_status_route(
    task_id: uuid.UUID,
    payload: TaskStatusUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> TaskResponse:
    task = await change_status(
        session,
        settings,
        clock,
        user,
        task_id,
        payload.status,
    )
    return TaskResponse.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_route(
    task_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
) -> Response:
    await soft_delete_task(session, clock, user, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
