from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query

from task_management_api.api.deps import SettingsDep


@dataclass(frozen=True)
class Pagination:
    page: int
    page_size: int
    offset: int
    limit: int


def get_pagination(
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(ge=1)] = None,
) -> Pagination:
    resolved_page_size = page_size or settings.page_size_default
    if resolved_page_size > settings.page_size_max:
        raise HTTPException(
            status_code=422,
            detail=f"page_size must not exceed {settings.page_size_max}",
        )
    return Pagination(
        page=page,
        page_size=resolved_page_size,
        offset=(page - 1) * resolved_page_size,
        limit=resolved_page_size,
    )


PaginationDep = Annotated[Pagination, Depends(get_pagination)]
