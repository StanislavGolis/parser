from sqlalchemy import select
from src.core.models import Board
from src.repositories.base import BaseRepository
from src.services import sources as sources_service

class BoardRepository(BaseRepository[Board]):
    def __init__(self, session):
        super().__init__(Board, session)
        self._default_source_id = None

    async def default_source_id(self) -> int:
        """id источника по умолчанию (2ch) — для вызовов без явного источника.

        Исторический код (парсер 2ch, старые админ-ручки) создаёт доски, не зная
        про источники: такие доски привязываются к источнику `dvach`.
        """
        if self._default_source_id is None:
            source = await sources_service.ensure_source(
                self.session,
                sources_service.DEFAULT_SOURCE_CODE,
                title="2ch.hk",
                kind="json",
                base_url="https://2ch.hk",
                is_enabled=True,
                rate_limit_rps=0.5,
            )
            self._default_source_id = source.id
        return self._default_source_id

    async def get_or_create(self, defaults=None, **filters):
        """Как базовый, но гарантирует привязку доски к источнику."""
        merged = dict(defaults or {})
        merged.setdefault("source_id", await self.default_source_id())
        return await super().get_or_create(defaults=merged, **filters)

    async def get_parsable_slugs(self, source_id: int | None = None):
        """Слаги досок, помеченных к парсингу, в порядке очереди.

        `source_id` ограничивает выборку досками одного источника: прогоны
        разных источников независимы и не забирают доски друг друга.
        """
        query = (
            select(Board.slug)
            .where(Board.parse_enabled.is_(True))
            .order_by(Board.sort_order, Board.slug)
        )
        if source_id is not None:
            query = query.where(Board.source_id == source_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_slug(self, slug: str):
        query = select(Board).where(Board.slug == slug)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()