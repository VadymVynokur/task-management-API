import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from task_management_api.api.router import api_router
from task_management_api.core.config import Settings, get_settings
from task_management_api.core.exceptions import AppError
from task_management_api.db.session import dispose_engine

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    logging.basicConfig(level=resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await dispose_engine()

    docs_url = "/docs" if resolved_settings.docs_enabled else None
    redoc_url = "/redoc" if resolved_settings.docs_enabled else None
    openapi_url = "/openapi.json" if resolved_settings.docs_enabled else None

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(api_router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("task_management_api.main:app", host="0.0.0.0", port=8000)
