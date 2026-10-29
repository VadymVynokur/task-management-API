import pytest
from pydantic import ValidationError

from task_management_api.core.config import Settings


def test_settings_validate_timezone() -> None:
    with pytest.raises(ValidationError):
        Settings(timezone="Not/AZone")


def test_settings_validate_worker_interval() -> None:
    with pytest.raises(ValidationError):
        Settings(worker_interval_seconds=0)


def test_settings_reject_short_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key="too-short")


def test_settings_reject_default_page_size_above_maximum() -> None:
    with pytest.raises(ValidationError):
        Settings(page_size_default=101, page_size_max=100)


def test_settings_defaults_match_approved_decisions() -> None:
    settings = Settings()

    assert settings.access_token_expire_minutes == 15
    assert settings.refresh_token_expire_days == 7
    assert settings.worker_interval_seconds == 300
    assert settings.timezone == "Europe/Kyiv"
    assert settings.page_size_default == 20
    assert settings.page_size_max == 100
