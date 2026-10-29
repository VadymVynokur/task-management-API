import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from task_management_api.core.clock import Clock
from task_management_api.core.exceptions import AppError
from task_management_api.models.comment import Comment
from task_management_api.models.task import Task
from task_management_api.models.user import User
from task_management_api.schemas.comment import CommentCreate, CommentUpdate
from task_management_api.services.tasks import get_task_or_404


async def list_comments(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> list[Comment]:
    await get_task_or_404(session, task_id)
    statement = (
        select(Comment)
        .where(Comment.task_id == task_id)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
    )
    return list((await session.scalars(statement)).all())


async def create_comment(
    session: AsyncSession,
    clock: Clock,
    user: User,
    task_id: uuid.UUID,
    data: CommentCreate,
) -> Comment:
    await get_task_or_404(session, task_id)
    now = clock.now()
    comment = Comment(
        task_id=task_id,
        author_id=user.id,
        body=data.body,
        created_at=now,
        updated_at=now,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


async def _get_comment_or_404(
    session: AsyncSession,
    comment_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Comment:
    statement = (
        select(Comment)
        .join(Task, Comment.task_id == Task.id)
        .where(Comment.id == comment_id, Task.deleted_at.is_(None))
    )
    if for_update:
        statement = statement.with_for_update()
    comment = await session.scalar(statement)
    if comment is None:
        raise AppError(404, "Comment not found")
    return comment


async def update_comment(
    session: AsyncSession,
    clock: Clock,
    user: User,
    comment_id: uuid.UUID,
    data: CommentUpdate,
) -> Comment:
    comment = await _get_comment_or_404(session, comment_id, for_update=True)
    if comment.author_id != user.id:
        raise AppError(403, "Not enough permissions")

    comment.body = data.body
    comment.updated_at = clock.now()
    await session.commit()
    await session.refresh(comment)
    return comment


async def delete_comment(
    session: AsyncSession,
    user: User,
    comment_id: uuid.UUID,
) -> None:
    comment = await _get_comment_or_404(session, comment_id, for_update=True)
    if comment.author_id != user.id:
        raise AppError(403, "Not enough permissions")

    await session.delete(comment)
    await session.commit()
