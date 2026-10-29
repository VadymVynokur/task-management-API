import uuid
from datetime import datetime

from task_management_api.enums import UserRole
from task_management_api.schemas.base import TimestampedModel


class UserResponse(TimestampedModel):
    id: uuid.UUID
    username: str
    role: UserRole
    created_at: datetime
