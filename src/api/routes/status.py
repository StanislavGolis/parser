# src/api/routes/status.py
"""Публичная сводка архива для главной страницы.

Отдаём только безопасные цифры: сколько файлов и тредов, сколько прибавилось за
сутки и какой раздел обрабатывает парсер. Служебные данные (очередь, промахи,
ошибки каталога) остаются в админке.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, visible_thread_clause
from src.api.deps import check_rate_limit, client_ip
from src.api.schemas import StatusOut
from src.core.db import get_session
from src.core.models import Board, Media, ThreadState
from src.core.redis_client import redis_client

router = APIRouter(prefix="/api/v1/status", tags=["status"])

PARSER_BOARD_KEY = "parser:current_board"
PARSER_ENABLED_KEY = "parser:enabled"


def _text(value) -> str | None:
    """Redis может вернуть bytes — приводим к строке."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return str(value)


@router.get("", response_model=StatusOut)
async def site_status(request: Request, session: AsyncSession = Depends(get_session)):
    """Цифры для сводки на главной: файлы, суточный прирост, треды, разделы, парсер."""
    await check_rate_limit(client_ip(request))

    visible_board = Board.is_visible.is_(True)
    base_filters = [*VISIBLE_FILTER, visible_board, visible_thread_clause()]

    files_total = (
        await session.execute(
            select(func.count())
            .select_from(Media)
            .join(Board, Board.id == Media.board_id)
            .where(*base_filters)
        )
    ).scalar() or 0

    since = datetime.utcnow() - timedelta(hours=24)
    files_24h = (
        await session.execute(
            select(func.count())
            .select_from(Media)
            .join(Board, Board.id == Media.board_id)
            .where(*base_filters, Media.created_at >= since)
        )
    ).scalar() or 0

    threads_active = (
        await session.execute(
            select(func.count())
            .select_from(ThreadState)
            .where(ThreadState.is_active.is_(True))
        )
    ).scalar() or 0

    boards_visible = (
        await session.execute(
            select(func.count()).select_from(Board).where(visible_board)
        )
    ).scalar() or 0

    # Раздел показываем только когда парсинг включён (иначе в Redis остаётся
    # последний обработанный раздел, и сводка врала бы «докачиваем»).
    enabled = await redis_client.get(PARSER_ENABLED_KEY)
    parser_board = _text(await redis_client.get(PARSER_BOARD_KEY)) if enabled else None

    return StatusOut(
        files_total=int(files_total),
        files_24h=int(files_24h),
        threads_active=int(threads_active),
        boards_visible=int(boards_visible),
        parser_board=parser_board,
    )
