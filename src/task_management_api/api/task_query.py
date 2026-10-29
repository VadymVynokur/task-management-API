import uuid
from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Query

from task_management_api.api.deps import SettingsDep
from task_management_api.enums import TaskPriority, TaskStatus
from task_management_api.schemas.task import SortOrder, TaskSortField


class TaskListQuery:
    def __init__(
        self,
        settings: SettingsDep,
        q: Annotated[str | None, Query(max_length=200)] = None,
        status: Annotated[list[TaskStatus] | None, Query()] = None,
        priority: Annotated[list[TaskPriority] | None, Query()] = None,
        assignee_id: Annotated[uuid.UUID | None, Query()] = None,
        due_from: Annotated[date | None, Query()] = None,
        due_to: Annotated[date | None, Query()] = None,
        sort_by: Annotated[TaskSortField | None, Query()] = None,
        sort_order: Annotated[SortOrder, Query()] = SortOrder.asc,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int | None, Query(ge=1)] = None,
    ) -> None:
        resolved_page_size = page_size or settings.page_size_default
        if resolved_page_size > settings.page_size_max:
            raise HTTPException(
                status_code=422,
                detail=f"page_size must not exceed {settings.page_size_max}",
            )
        self.q = q
        self.statuses = status
        self.priorities = priority
        self.assignee_id = assignee_id
        self.due_from = due_from
        self.due_to = due_to
        self.sort_by = sort_by
        self.sort_order = sort_order
        self.page = page
        self.page_size = resolved_page_size
        self.offset = (page - 1) * resolved_page_size
        self.limit = resolved_page_size


TaskListQueryDep = Annotated[TaskListQuery, Depends(TaskListQuery)]
