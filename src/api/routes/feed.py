# src/api/routes/feed.py
"""Лента «Новинки»: свежие файлы по всем видимым доскам.

Добавлен в рамках этапа 6 (фронтенд): раздел «Новинки» сайта требует
единый пагинируемый поток без выбора конкретной доски.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, sign_media_urls
from src.api.deps import check_rate_limit, client_ip, get_b2
from src.api.schemas import MediaListOut, MediaOut
from src.core.db import get_session
from src.core.models import Board, Media
from src.services.b2_uploader import B2Uploader

router = APIRouter(prefix="/api/v1/feed", tags=["feed"])


@router.get("", response_model=MediaListOut)
async def media_feed(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    media_type: Optional[str] = Query(None, alias="type", pattern="^(image|video)$"),
    session: AsyncSession = Depends(get_session),
    b2: B2Uploader = Depends(get_b2),
):
    """Свежие файлы со всех видимых досок (новинки), с пагинацией."""
    await check_rate_limit(client_ip(request))

    filters = list(VISIBLE_FILTER) + [Board.is_visible.is_(True)]
    if media_type:
        filters.append(Media.media_type == media_type)

    # Подсчёт только видимых записей видимых досок
    count_q = (
        select(func.count())
        .select_from(Media)
        .join(Board, Board.id == Media.board_id)
        .where(*filters)
    )
    total = (await session.execute(count_q)).scalar()

    query = (
        select(Media)
        .join(Board, Board.id == Media.board_id)
        .where(*filters)
        .order_by(Media.created_at.desc(), Media.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await session.execute(query)
    items = result.scalars().all()

    out = [MediaOut.model_validate(m) for m in items]
    sign_media_urls(out, items, b2)
    return MediaListOut(
        items=out,
        page=page,
        per_page=per_page,
        total=int(total or 0),
    )
