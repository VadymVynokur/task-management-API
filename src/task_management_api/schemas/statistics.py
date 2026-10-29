from pydantic import BaseModel

from task_management_api.enums import TaskPriority, TaskStatus


class StatisticsResponse(BaseModel):
    total: int
    by_status: dict[TaskStatus, int]
    by_priority: dict[TaskPriority, int]
    overdue: int
    active: int
