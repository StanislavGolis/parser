# src/api/routes/search.py
"""Поиск по файлам: имя файла / MD5 / SHA-256."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, sign_media_urls, visible_thread_clause
from src.api.deps import check_rate_limit, client_ip, get_current_user, get_s3
from src.api.schemas import MediaListOut, MediaOut
from src.core.db import get_session
from src.core.models import Board, Media, User
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("", response_model=MediaListOut)
async def search_media(
    request: Request,
    q: str = Query(..., min_length=2, max_length=120),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    media_type: Optional[str] = Query(None, alias="type", pattern="^(image|video)$"),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: Optional[User] = Depends(get_current_user),
):
    """Поиск по имени файла, md5 или sha-256 (премиум-файлы — с размытым превью)."""
    await check_rate_limit(client_ip(request))

    query_text = q.strip()
    if len(query_text) < 2:
        raise HTTPException(status_code=400, detail="Слишком короткий запрос (мин. 2 символа)")

    pattern = f"%{query_text}%"
    filters = list(VISIBLE_FILTER) + [
        Board.is_visible.is_(True),
        visible_thread_clause(),
        or_(
            Media.original_name.ilike(pattern),
            Media.source_md5.ilike(pattern),
            Media.file_hash.ilike(pattern),
        ),
    ]
    if media_type:
        filters.append(Media.media_type == media_type)

    total = (
        await session.execute(
            select(func.count())
            .select_from(Media)
            .join(Board, Board.id == Media.board_id)
            .where(*filters)
        )
    ).scalar()

    result = await session.execute(
        select(Media)
        .join(Board, Board.id == Media.board_id)
        .where(*filters)
        .order_by(Media.created_at.desc(), Media.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = result.scalars().all()

    out = [MediaOut.model_validate(m) for m in items]
    sign_media_urls(out, items, s3, user)
    return MediaListOut(
        items=out,
        page=page,
        per_page=per_page,
        total=int(total or 0),
    )
