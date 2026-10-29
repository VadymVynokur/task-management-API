from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from task_management_api.core.clock import get_clock
from task_management_api.core.config import Settings, get_settings
from task_management_api.db.base import Base
from task_management_api.db.session import get_session
from task_management_api.main import create_app


class FakeClock:
    def __init__(
        self,
        today: date = date(2026, 1, 15),
        now: datetime = datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    ) -> None:
        self.today_value = today
        self.now_value = now

    def today(self, tz: ZoneInfo) -> date:
        return self.today_value

    def now(self) -> datetime:
        return self.now_value

    def set_today(self, value: date) -> None:
        self.today_value = value


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="test-secret-key",
        access_token_expire_minutes=15,
        refresh_token_expire_days=7,
        docs_enabled=True,
        page_size_default=20,
        page_size_max=100,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def client(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_clock] = lambda: clock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client

    app.dependency_overrides.clear()
