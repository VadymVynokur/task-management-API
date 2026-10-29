from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from task_management_api.core.time import ensure_utc


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampedModel(ORMModel):
    @field_serializer("created_at", "updated_at", check_fields=False)
    def serialize_timestamp(self, value: datetime) -> str:
        return ensure_utc(value).isoformat().replace("+00:00", "Z")
