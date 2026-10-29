import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from task_management_api.schemas.base import TimestampedModel


class CommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def body_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("body must not be blank")
        return stripped


class CommentCreate(CommentBody):
    pass


class CommentUpdate(CommentBody):
    pass


class CommentResponse(TimestampedModel):
    id: uuid.UUID
    task_id: uuid.UUID
    author_id: uuid.UUID
    body: str
    created_at: datetime
    updated_at: datetime
