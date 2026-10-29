import logging

from httpx import ASGITransport, AsyncClient

from task_management_api.core.config import Settings
from task_management_api.main import create_app
from tests.helpers import register_account


async def test_validation_errors_do_not_echo_credentials(client: AsyncClient) -> None:
    await register_account(client)
    secret = "s" * 129

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": secret},
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert "input" not in response.text


async def test_unhandled_error_returns_generic_response_without_sensitive_logs(
    settings: Settings,
    caplog,
) -> None:
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password=secret")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="task_management_api.main"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "password=secret" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
