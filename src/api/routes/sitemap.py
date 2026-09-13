# src/api/routes/sitemap.py
"""Выдача для карт сайта: файлы, видео и треды постранично.

Отдельные эндпоинты, а не пользовательские списки: картам нужны большие страницы
(до 5000 записей) и минимум полей, а `feed`/`boards` отдают полные карточки с
превью и метками — для карты это лишняя нагрузка.

Премиум-контент из карт не исчезает: страница файла остаётся индексируемой, но
превью (размытое) в `<image:image>`/`<video:thumbnail_loc>` не отдаётся — робот
увидел бы «дефект» вместо кадра. Видео-карта включает только открытые файлы с
готовым mp4 и известной длительностью.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, is_locked
from src.api.deps import check_rate_limit, client_ip, get_current_user
from src.api.schemas import (
    SitemapMediaListOut,
    SitemapMediaOut,
    SitemapVideoListOut,
    SitemapVideoOut,
    ThreadRefListOut,
    ThreadRefOut,
)
from src.core.db import get_session
from src.core.models import Board, Media, ThreadState, User

router = APIRouter(prefix="/api/v1/sitemap", tags=["sitemap"])

# Сколько записей отдаём за раз: 5000 адресов — безопасный размер карты
# (лимит протокола — 50 000 URL и 50 МБ на файл, но меньшие карты обходятся быстрее)
MAX_PAGE = 5000


def _visible_base(model):
    """Базовый JOIN «файл → видимая доска → живой видимый тред»."""
    return (
        select(model)
        .join(Board, Board.id == Media.board_id)
        .join(
            ThreadState,
            (ThreadState.board_id == Media.board_id)
            & (ThreadState.thread_id == Media.thread_id),
        )
        .where(
            *VISIBLE_FILTER,
            Board.is_visible.is_(True),
            ThreadState.is_active.is_(True),
            ThreadState.is_visible.is_(True),
        )
    )


async def _total(session: AsyncSession, base) -> int:
    value = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    return int(value or 0)


@router.get("/media", response_model=SitemapMediaListOut)
async def sitemap_media(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(MAX_PAGE, ge=1, le=MAX_PAGE),
    session: AsyncSession = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    """Файлы для карты сайта: свежие сверху, только публично видимые.

    `locked` отдаём, чтобы web не ставил в `<image:image>` размытое превью
    премиум-файла.
    """
    await check_rate_limit(client_ip(request))

    base = _visible_base(Media)
    total = await _total(session, base)
    rows = (
        await session.execute(
            base.order_by(Media.created_at.desc(), Media.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    items = [
        SitemapMediaOut(
            id=media.id,
            created_at=media.created_at,
            media_type=media.media_type,
            locked=is_locked(media.is_premium, user),
        )
        for media in rows
    ]
    return SitemapMediaListOut(items=items, page=page, per_page=per_page, total=total)


@router.get("/videos", response_model=SitemapVideoListOut)
async def sitemap_videos(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(MAX_PAGE, ge=1, le=MAX_PAGE),
    session: AsyncSession = Depends(get_session),
):
    """Видео с готовым mp4 и длительностью — для `<video:video>` в карте.

    Премиум-видео исключены: робот получил бы 403 на поток, а `VideoObject` без
    `content_loc` бесполезен.
    """
    await check_rate_limit(client_ip(request))

    base = (
        _visible_base(Media)
        .where(
            Media.media_type == "video",
            Media.is_premium.is_(False),
            Media.duration_seconds.isnot(None),
        )
        # mp4-дериватив: без него видео нечего отдавать роботу
        .where(Media.variants["video"].astext.isnot(None))
    )
    total = await _total(session, base)
    rows = (
        await session.execute(
            base.order_by(Media.created_at.desc(), Media.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    items = [
        SitemapVideoOut(
            id=media.id,
            created_at=media.created_at,
            duration_seconds=media.duration_seconds,
            file_size=media.file_size,
        )
        for media in rows
    ]
    return SitemapVideoListOut(items=items, page=page, per_page=per_page, total=total)


@router.get("/threads", response_model=ThreadRefListOut)
async def sitemap_threads(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(MAX_PAGE, ge=1, le=MAX_PAGE),
    session: AsyncSession = Depends(get_session),
):
    """Треды для карты сайта: видимые и непустые, свежие сверху."""
    await check_rate_limit(client_ip(request))

    last_media_at = func.max(Media.created_at)
    base = (
        select(
            ThreadState.thread_id,
            Board.slug,
            ThreadState.subject,
            func.count(Media.id).label("media_total"),
            last_media_at.label("last_media_at"),
        )
        .join(Board, Board.id == ThreadState.board_id)
        .join(
            Media,
            (Media.board_id == ThreadState.board_id)
            & (Media.thread_id == ThreadState.thread_id),
        )
        .where(
            ThreadState.is_active.is_(True),
            ThreadState.is_visible.is_(True),
            Board.is_visible.is_(True),
            *VISIBLE_FILTER,
        )
        .group_by(ThreadState.thread_id, Board.slug, ThreadState.subject)
    )

    total = await _total(session, base)
    rows = (
        await session.execute(
            base.order_by(last_media_at.desc().nullslast())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()

    items = [
        ThreadRefOut(
            thread_id=int(row.thread_id),
            board_slug=row.slug,
            subject=row.subject,
            media_total=int(row.media_total or 0),
            last_media_at=row.last_media_at,
        )
        for row in rows
    ]
    return ThreadRefListOut(items=items, page=page, per_page=per_page, total=total)
