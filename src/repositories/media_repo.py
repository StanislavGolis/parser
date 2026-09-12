# src/repositories/media_repo.py
from typing import Optional

from sqlalchemy import select

from src.core.models import Media
from src.repositories.base import BaseRepository


class MediaRepository(BaseRepository[Media]):
    def __init__(self, session):
        super().__init__(Media, session)

    async def _first_canonical(self, query) -> Optional[Media]:
        """Первая «каноническая» запись: оригинал раньше дублей.

        Исторические данные могут содержать несколько строк с одним md5/s3_key
        (дубли-ссылки в том же треде из-за старых повторных проходов), поэтому
        `.scalar_one_or_none()` использовать нельзя — он падал бы с
        «Multiple rows were found when one or none was required».
        """
        query = query.order_by(Media.duplicate_of_id.isnot(None), Media.id).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_md5(self, source_md5: str) -> Optional[Media]:
        """Поиск по md5 из API (каноническая запись; дубли-ссылки не в счёт)."""
        return await self._first_canonical(select(Media).where(Media.source_md5 == source_md5))

    async def get_by_hash(self, file_hash: str) -> Optional[Media]:
        """Поиск по SHA-256 (каноническая запись)."""
        return await self._first_canonical(select(Media).where(Media.file_hash == file_hash))

    async def get_by_s3_key(self, s3_key: str) -> Optional[Media]:
        """Поиск по ключу в S3 (каноническая запись: дубли делят один объект)."""
        return await self._first_canonical(select(Media).where(Media.s3_key == s3_key))

    async def get_by_board_thread_md5(
        self, board_id: int, thread_id: int, source_md5: str
    ) -> Optional[Media]:
        """Запись этого же файла в этом же треде.

        Нужна для идемпотентности повторных проходов: если файл уже сохранён в
        треде, новая запись не создаётся (иначе статистика и галерея удваиваются
        на каждом сканировании).
        """
        return await self._first_canonical(
            select(Media).where(
                Media.board_id == board_id,
                Media.thread_id == thread_id,
                Media.source_md5 == source_md5,
            )
        )

    async def get_downloaded_local(self, board_id: int, limit: int = 200):
        """Записи со статусом downloaded — кандидаты на перезаливку в S3."""
        query = select(Media).where(Media.download_status == "downloaded")
        if board_id:
            query = query.where(Media.board_id == board_id)
        query = query.limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()