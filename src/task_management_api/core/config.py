from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Task Management API"
    app_env: str = "development"
    database_url: str = (
        "postgresql+asyncpg://task_user:task_password@localhost:5432/task_management"
    )
    jwt_secret_key: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)
    worker_interval_seconds: int = Field(default=300, ge=1)
    timezone: str = "Europe/Kyiv"
    docs_enabled: bool = True
    log_level: str = "INFO"
    page_size_default: int = Field(default=20, ge=1)
    page_size_max: int = Field(default=100, ge=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:  # pragma: no cover - exact exception type varies
            raise ValueError(f"Unknown timezone: {value}") from exc
        return value

    @field_validator("page_size_max")
    @classmethod
    def validate_page_size_max(cls, value: int) -> int:
        if value < 1:
            raise ValueError("page_size_max must be at least 1")
        return value

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
