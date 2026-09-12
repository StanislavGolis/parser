# src/api/routes/boards.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip, get_current_user, get_s3
from src.api.schemas import BoardOut, ThreadListOut
from src.api.threads_service import build_thread_outs, list_threads
from src.core.db import get_session
from src.core.models import Board, Media, User
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/boards", tags=["boards"])


@router.get("", response_model=list[BoardOut])
async def list_boards(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Список видимых досок с числом видимых файлов.

    Премиум-доски видны в списке: их контент открывается по подписке.
    """
    await check_rate_limit(client_ip(request))

    subq = (
        select(
            Media.board_id.label("board_id"),
            func.count(Media.id).label("cnt"),
        )
        .where(
            Media.is_visible.is_(True),
            Media.is_active.is_(True),
            # Дубли-ссылки не файлы: в каталоге считаем только уникальные
            Media.duplicate_of_id.is_(None),
        )
        .group_by(Media.board_id)
        .subquery()
    )

    query = (
        select(Board, func.coalesce(subq.c.cnt, 0))
        .outerjoin(subq, subq.c.board_id == Board.id)
        .where(Board.is_visible.is_(True))
        .order_by(Board.slug)
    )
    result = await session.execute(query)

    boards = []
    for board, cnt in result.all():
        boards.append(BoardOut(
            id=board.id,
            slug=board.slug,
            title=board.title,
            description=board.description,
            media_count=int(cnt or 0),
            is_premium=board.is_premium,
        ))
    return boards


@router.get("/{slug}/threads", response_model=ThreadListOut)
async def board_threads(
    slug: str,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: Optional[User] = Depends(get_current_user),
):
    """Треды доски (активные) с метаданными и статистикой файлов.

    Превью премиум-тредов приходят размытыми; полный контент — по подписке.
    """
    await check_rate_limit(client_ip(request))

    result = await session.execute(
        select(Board).where(Board.slug == slug, Board.is_visible.is_(True))
    )
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    threads, total = await list_threads(session, board.id, page, per_page, only_visible=True)
    items = await build_thread_outs(
        session, board.id, threads, s3=s3, with_preview=True, user=user
    )
    return ThreadListOut(items=items, page=page, per_page=per_page, total=total)
