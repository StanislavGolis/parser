from sqlalchemy import select
from src.core.models import Board
from src.repositories.base import BaseRepository

class BoardRepository(BaseRepository[Board]):
    def __init__(self, session):
        super().__init__(Board, session)
    
    async def get_parsable_slugs(self):
        """Слаги досок, помеченных к парсингу (parse_enabled) в БД."""
        query = select(Board.slug).where(Board.parse_enabled.is_(True)).order_by(Board.slug)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_slug(self, slug: str):
        query = select(Board).where(Board.slug == slug)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()