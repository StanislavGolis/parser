# src/repositories/thread_state_repo.py
from typing import List, Optional, Tuple

from sqlalchemy import case, func, select

from src.core.models import Board, ThreadState
from src.repositories.base import BaseRepository

# Причины очереди, которые считаются «свежими» (новые файлы уже на форуме):
# они уходят в начало очереди, плановый догон («просрочен», «не скачивался») — после.
FRESH_REASONS = ("новый", "изменения", "файлы", "вручную")


class ThreadStateRepository(BaseRepository[ThreadState]):
    """Репозиторий состояния тредов для инкрементального парсинга."""

    def __init__(self, session):
        super().__init__(ThreadState, session)

    async def get_by_board_thread(self, board_id: int, thread_id: int) -> Optional[ThreadState]:
        query = select(ThreadState).where(
            ThreadState.board_id == board_id,
            ThreadState.thread_id == thread_id,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_active_by_board(self, board_id: int):
        query = select(ThreadState).where(
            ThreadState.board_id == board_id,
            ThreadState.is_active.is_(True),
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_all_by_board(self, board_id: int):
        """Все треды доски, включая выпавшие из каталога (is_active=False).

        Нужно для гигиены обхода: считаем «промахи» и по уже отключённым
        тредам, чтобы их не потерять окончательно.
        """
        query = select(ThreadState).where(ThreadState.board_id == board_id)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_scan_queue(self, limit: Optional[int] = None) -> List[Tuple[str, int, str]]:
        """Очередь докачки (фаза B): треды, помеченные фазой A (`pending_scan`).

        Порядок:
        1) свежие изменения/новые («новый», «изменения», «файлы») — вперёд;
        2) плановый догон («просрочен», «не скачивался»);
        3) внутри каждой группы — по «давности» сканирования (LRU, NULL первыми),
           поэтому «забытых» тредов не остаётся: очередь всегда разбирается до конца.

        Доски без `parse_enabled` в очередь не попадают: парсер по ним не ходит.
        """
        fresh = case(
            (ThreadState.pending_reason.in_(FRESH_REASONS), 0),
            else_=1,
        )
        query = (
            select(Board.slug, ThreadState.thread_id, ThreadState.pending_reason)
            .join(Board, Board.id == ThreadState.board_id)
            .where(
                Board.parse_enabled.is_(True),
                ThreadState.is_active.is_(True),
                ThreadState.parse_enabled.is_(True),
                ThreadState.pending_scan.is_(True),
            )
            .order_by(
                fresh,
                ThreadState.last_scanned_at.asc().nullsfirst(),
                ThreadState.thread_id.asc(),
            )
        )
        if limit is not None:
            query = query.limit(limit)
        rows = await self.session.execute(query)
        return [(row[0], int(row[1]), row[2] or "") for row in rows.all()]

    async def scan_queue_size(self) -> int:
        """Сколько тредов сейчас в очереди (для сводки в логе/админке)."""
        query = (
            select(func.count())
            .select_from(ThreadState)
            .join(Board, Board.id == ThreadState.board_id)
            .where(
                Board.parse_enabled.is_(True),
                ThreadState.is_active.is_(True),
                ThreadState.parse_enabled.is_(True),
                ThreadState.pending_scan.is_(True),
            )
        )
        return int((await self.session.execute(query)).scalar() or 0)