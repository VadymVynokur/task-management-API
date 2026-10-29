from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    """Injectable clock used by deadline-sensitive business rules."""

    def now(self) -> datetime:
        """Return the current instant in UTC."""

    def today(self, tz: ZoneInfo) -> date:
        """Return the current calendar date in the requested timezone."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self, tz: ZoneInfo) -> date:
        return datetime.now(tz).date()


system_clock = SystemClock()


def get_clock() -> Clock:
    return system_clock
