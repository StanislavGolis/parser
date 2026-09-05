from sqlalchemy.ext.asyncio import AsyncSession
from typing import TypeVar, Generic, Type, Optional

T = TypeVar('T', bound=Base)

class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T], session: AsyncSession):
        self.model = model
        self.session = session
    
    async def create(self, **kwargs) -> T:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance
    
    async def get_by(self, **filters) -> Optional[T]:
        query = await self.session.execute(
            select(self.model).filter_by(**filters)
        )
        return query.scalar_one_or_none()
    
    async def get_or_create(self, defaults=None, **filters) -> tuple[T, bool]:
        instance = await self.get_by(**filters)
        if instance:
            return instance, False
        instance = self.model(**filters, **(defaults or {}))
        self.session.add(instance)
        await self.session.flush()
        return instance, True