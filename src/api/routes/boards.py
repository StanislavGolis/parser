# src/api/routes/boards.py
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip
from src.api.schemas import BoardOut
from src.core.db import get_session
from src.core.models import Board, Media

router = APIRouter(prefix="/api/v1/boards", tags=["boards"])


@router.get("", response_model=list[BoardOut])
async def list_boards(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Список видимых досок с количеством видимых активных файлов."""
    await check_rate_limit(client_ip(request))

    subq = (
        select(
            Media.board_id.label("board_id"),
            func.count(Media.id).label("cnt"),
        )
        .where(Media.is_visible.is_(True), Media.is_active.is_(True))
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
        ))
    return boards