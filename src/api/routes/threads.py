# src/api/routes/threads.py
"""Публичные страницы тредов: метаданные и список для карты сайта.

Тред — единственный носитель текста в архиве (тема и описание записи у сайтов,
тема треда у 2ch), поэтому у него есть отдельный адрес `/t/{thread_id}`:
это посадочная страница под поисковый запрос, а не только лента внутри раздела.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, is_locked
from src.api.deps import check_rate_limit, client_ip, get_current_user
from src.api.schemas import ThreadDetailOut, ThreadRefListOut, ThreadRefOut
from src.core.db import get_session
from src.core.models import Board, Media, ThreadState, User

router = APIRouter(prefix="/api/v1", tags=["threads"])


async def _find_thread(
    session: AsyncSession, thread_id: int
) -> tuple[ThreadState, Board]:
    """Тред по публичному номеру: доска и тред должны быть видимы.

    `thread_id` уникален в паре с доской, но у источников нумерация независимая —
    на всякий случай берём первый по id (в проде коллизий нет) и не раскрываем
    скрытое: невидимая доска/тред = 404.
    """
    result = await session.execute(
        select(ThreadState, Board)
        .join(Board, Board.id == ThreadState.board_id)
        .where(
            ThreadState.thread_id == thread_id,
            ThreadState.is_active.is_(True),
            ThreadState.is_visible.is_(True),
            Board.is_visible.is_(True),
        )
        .order_by(ThreadState.id.asc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return row[0], row[1]


@router.get("/threads/{thread_id}", response_model=ThreadDetailOut)
async def thread_detail(
    thread_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    """Метаданные треда для страницы `/t/{thread_id}`.

    `locked` считается с учётом премиума доски: страница сама решает, показывать
    ли размытые превью (полные файлы всё равно закрыты премиум-гейтом).
    """
    await check_rate_limit(client_ip(request))

    thread, board = await _find_thread(session, thread_id)

    stats = (
        await session.execute(
            select(
                func.count(Media.id),
                func.max(Media.created_at),
            ).where(
                *VISIBLE_FILTER,
                Media.board_id == board.id,
                Media.thread_id == thread_id,
            )
        )
    ).one()
    media_total = int(stats[0] or 0)
    last_media_at = stats[1]

    is_premium = bool(thread.is_premium or board.is_premium)
    return ThreadDetailOut(
        thread_id=thread_id,
        board_id=board.id,
        board_slug=board.slug,
        board_title=board.title,
        subject=thread.subject,
        comment=thread.comment,
        posts_count=int(thread.posts_count or 0),
        files_count=int(thread.files_count or 0),
        views_count=int(thread.views_count or 0),
        media_total=media_total,
        thread_timestamp=thread.thread_timestamp,
        last_media_at=last_media_at,
        is_premium=is_premium,
        locked=is_locked(is_premium, user),
    )


@router.get("/threads", response_model=ThreadRefListOut)
async def thread_list(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    """Треды для карты сайта: только видимые, где уже есть файлы.

    Отдаём минимум полей (адрес, тема, дата последнего файла) — это вход для
    `sitemap.xml`, а не пользовательский список.
    """
    await check_rate_limit(client_ip(request))

    files_count = func.count(Media.id)
    last_media_at = func.max(Media.created_at)

    filters = (
        ThreadState.is_active.is_(True),
        ThreadState.is_visible.is_(True),
        Board.is_visible.is_(True),
        *VISIBLE_FILTER,
    )
    base = (
        select(
            ThreadState.thread_id,
            Board.slug,
            ThreadState.subject,
            files_count.label("media_total"),
            last_media_at.label("last_media_at"),
        )
        .join(Board, Board.id == ThreadState.board_id)
        .join(
            Media,
            (Media.board_id == ThreadState.board_id)
            & (Media.thread_id == ThreadState.thread_id),
        )
        .where(*filters)
        .group_by(ThreadState.thread_id, Board.slug, ThreadState.subject)
    )

    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

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
    return ThreadRefListOut(items=items, page=page, per_page=per_page, total=int(total or 0))
