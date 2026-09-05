from sqlalchemy import select
from src.core.models import Thread
from src.repositories.base import BaseRepository

class ThreadRepository(BaseRepository[Thread]):
    def __init__(self, session):
        super().__init__(Thread, session)
    
    async def get_by_thread_id(self, board_id: int, thread_id: int):
        query = select(Thread).where(
            Thread.board_id == board_id,
            Thread.thread_id == thread_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()