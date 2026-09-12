# src/api/routes/favorites.py
"""Избранное пользователя — личная подборка файлов (требует аккаунт)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import (
    VISIBLE_FILTER,
    apply_user_flags,
    sign_media_urls,
    visible_thread_clause,
)
from src.api.deps import check_rate_limit, client_ip, get_s3, require_user
from src.api.schemas import MediaListOut, MediaOut
from src.core.db import get_session
from src.core.models import Board, Favorite, Media, User
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])


@router.get("", response_model=MediaListOut)
async def my_favorites(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    media_type: Optional[str] = Query(None, alias="type", pattern="^(image|video)$"),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: User = Depends(require_user),
):
    """Файлы из избранного текущего пользователя (свежие добавления сверху).

    Учитываются только видимые файлы видимых досок/тредов: если файл скрыли
    в админке, он пропадает и из избранного (но отметка в БД остаётся).
    """
    await check_rate_limit(client_ip(request))

    filters = list(VISIBLE_FILTER) + [
        Board.is_visible.is_(True),
        visible_thread_clause(),
        Favorite.user_id == user.id,
    ]
    if media_type:
        filters.append(Media.media_type == media_type)

    total = (
        await session.execute(
            select(func.count())
            .select_from(Media)
            .join(Favorite, Favorite.media_id == Media.id)
            .join(Board, Board.id == Media.board_id)
            .where(*filters)
        )
    ).scalar()

    items = (
        (
            await session.execute(
                select(Media)
                .join(Favorite, Favorite.media_id == Media.id)
                .join(Board, Board.id == Media.board_id)
                .where(*filters)
                .order_by(Favorite.created_at.desc(), Media.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )

    out = [MediaOut.model_validate(m) for m in items]
    sign_media_urls(out, items, s3, user)
    await apply_user_flags(session, out, user)
    for item in out:  # по определению списка всё уже в избранном
        item.favorited = True

    return MediaListOut(items=out, page=page, per_page=per_page, total=int(total or 0))
