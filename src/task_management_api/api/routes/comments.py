import uuid

from fastapi import APIRouter, Response, status

from task_management_api.api.deps import ClockDep, CurrentUser, SessionDep
from task_management_api.schemas.comment import (
    CommentCreate,
    CommentResponse,
    CommentUpdate,
)
from task_management_api.services.comments import (
    create_comment,
    delete_comment,
    list_comments,
    update_comment,
)

router = APIRouter(tags=["comments"])


@router.get("/tasks/{task_id}/comments", response_model=list[CommentResponse])
async def list_comments_route(
    task_id: uuid.UUID,
    _user: CurrentUser,
    session: SessionDep,
) -> list[CommentResponse]:
    comments = await list_comments(session, task_id)
    return [CommentResponse.model_validate(comment) for comment in comments]


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment_route(
    task_id: uuid.UUID,
    payload: CommentCreate,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
) -> CommentResponse:
    comment = await create_comment(session, clock, user, task_id, payload)
    return CommentResponse.model_validate(comment)


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment_route(
    comment_id: uuid.UUID,
    payload: CommentUpdate,
    user: CurrentUser,
    session: SessionDep,
    clock: ClockDep,
) -> CommentResponse:
    comment = await update_comment(session, clock, user, comment_id, payload)
    return CommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment_route(
    comment_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    await delete_comment(session, user, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
