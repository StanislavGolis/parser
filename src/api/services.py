# src/api/services.py
"""Сервисные функции API: пересчёт популярности, кэширование."""
import logging
from datetime import datetime

from sqlalchemy import cast, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Numeric

from src.core.models import Media

logger = logging.getLogger(__name__)


async def recalc_popularity(session: AsyncSession) -> int:
    """Пересчитывает popularity_score по формуле ТЗ: views*0.3 + downloads*0.7."""
    result = await session.execute(
        update(Media)
        .values(
            # В PostgreSQL нет round(double precision, int): кастуем выражение в NUMERIC.
            popularity_score=func.round(
                cast(Media.views_count * 0.3 + Media.downloads_count * 0.7, Numeric(12, 4)),
                2,
            ),
            updated_at=datetime.utcnow(),
        )
    )
    await session.commit()
    updated = result.rowcount or 0
    if updated:
        logger.info("popularity_score пересчитан для %s записей", updated)
    return updated