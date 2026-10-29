from fastapi import APIRouter

from task_management_api.api.routes import health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
