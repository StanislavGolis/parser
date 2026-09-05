from sqlalchemy import select, and_
from src.core.models import MediaFile
from src.repositories.base import BaseRepository

class MediaRepository(BaseRepository[MediaFile]):
    def __init__(self, session):
        super().__init__(MediaFile, session)
    
    async def get_by_hash(self, file_hash: str) -> Optional[MediaFile]:
        return await self.get_by(file_hash=file_hash)
    
    async def get_recent(self, board_id: int, limit: int = 50):
        query = select(MediaFile).where(
            MediaFile.board_id == board_id
        ).order_by(MediaFile.parsed_at.desc()).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def mark_processed(self, media_id: int):
        await self.session.execute(
            update(MediaFile)
            .where(MediaFile.id == media_id)
            .values(ai_processed=True)
        )