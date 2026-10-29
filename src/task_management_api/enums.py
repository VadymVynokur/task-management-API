from enum import StrEnum


class UserRole(StrEnum):
    user = "user"
    admin = "admin"


class TaskStatus(StrEnum):
    backlog = "Backlog"
    in_progress = "In Progress"
    review = "Review"
    done = "Done"
    cancelled = "Cancelled"


class TaskPriority(StrEnum):
    high = "High"
    medium = "Medium"
    low = "Low"


ACTIVE_STATUSES: tuple[TaskStatus, ...] = (
    TaskStatus.backlog,
    TaskStatus.in_progress,
    TaskStatus.review,
)

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.backlog: frozenset({TaskStatus.in_progress, TaskStatus.cancelled}),
    TaskStatus.in_progress: frozenset({TaskStatus.review, TaskStatus.cancelled}),
    TaskStatus.review: frozenset({TaskStatus.done}),
    TaskStatus.done: frozenset(),
    TaskStatus.cancelled: frozenset(),
}

PRIORITY_RANK: dict[TaskPriority, int] = {
    TaskPriority.high: 1,
    TaskPriority.medium: 2,
    TaskPriority.low: 3,
}

MAX_ACTIVE_TASKS = 10
