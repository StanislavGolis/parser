# src/repositories/thread_state_repo.py
from typing import Optional

from sqlalchemy import select

from src.core.models import ThreadState
from src.repositories.base import BaseRepository


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