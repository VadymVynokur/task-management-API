import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from task_management_api.core.time import utcnow
from task_management_api.db.base import Base
from task_management_api.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            name="user_role",
            native_enum=False,
            length=10,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=UserRole.user,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
