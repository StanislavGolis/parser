# src/api/routes/status.py
"""Публичная сводка архива для главной страницы.

Отдаём только цифры о контенте: сколько файлов и тредов, сколько прибавилось за
сутки, сколько разделов. Никакой служебной телеметрии (состояние парсера, очередь,
ошибки) наружу не выводим — она остаётся в админке.
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
from src.services import reporting

router = APIRouter(prefix="/api/v1/status", tags=["status"])


@router.get("", response_model=StatusOut)
async def site_status(request: Request, session: AsyncSession = Depends(get_session)):
    """Цифры для сводки на главной: файлы, прирост за отчётные сутки, треды, разделы.

    Прирост считается за **отчётные сутки по МСК** (00:00–24:00) — тем же
    периодом считают админка, карточки разделов и письмо-отчёт.
    """
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

    # Единый отчётный период: сутки по МСК (00:00 → 00:00)
    start, end = reporting.period_bounds()
    today = await reporting.daily_stats(session, start, end, only_visible=True)

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

    return StatusOut(
        files_total=int(files_total),
        files_today=int(today["files_added"]),
        threads_active=int(threads_active),
        boards_visible=int(boards_visible),
        period_start=start,
        period_end=end,
        period_label=reporting.period_title(start, end),
    )
