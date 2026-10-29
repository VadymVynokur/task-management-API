from fastapi import APIRouter

from task_management_api.api.routes import auth, comments, health, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(tasks.router)
api_router.include_router(comments.router)
api_router.include_router(health.router)
