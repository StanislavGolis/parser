# src/repositories/media_repo.py
from typing import Optional

from sqlalchemy import select

from src.core.models import Media
from src.repositories.base import BaseRepository


class MediaRepository(BaseRepository[Media]):
    def __init__(self, session):
        super().__init__(Media, session)

    async def get_by_md5(self, source_md5: str) -> Optional[Media]:
        """Поиск дубликата по md5 из API (до скачивания)."""
        query = select(Media).where(Media.source_md5 == source_md5)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_hash(self, file_hash: str) -> Optional[Media]:
        """Поиск по SHA-256 (контроль целостности)."""
        query = select(Media).where(Media.file_hash == file_hash)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_s3_key(self, s3_key: str) -> Optional[Media]:
        query = select(Media).where(Media.s3_key == s3_key)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_downloaded_local(self, board_id: int, limit: int = 200):
        """Записи со статусом downloaded — кандидаты на перезаливку в S3."""
        query = select(Media).where(Media.download_status == "downloaded")
        if board_id:
            query = query.where(Media.board_id == board_id)
        query = query.limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()