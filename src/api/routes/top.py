# src/api/routes/top.py
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip
from src.api.schemas import MediaOut
from src.core.db import get_session
from src.core.models import Media

router = APIRouter(prefix="/api/v1/top", tags=["top"])

PERIODS = {
    "day": 1,
    "week": 7,
    "month": 30,
}


@router.get("", response_model=list[MediaOut])
async def top_media(
    request: Request,
    type: Optional[str] = Query(None, alias="type", pattern="^(image|video)$"),
    period: str = Query("week", pattern="^(day|week|month)$"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Топ контента по популярности за период."""
    await check_rate_limit(client_ip(request))

    days = PERIODS.get(period, 7)
    cutoff = func.now() - func.make_interval(0, 0, 0, days, 0, 0, 0)

    filters = [
        Media.is_visible.is_(True),
        Media.is_active.is_(True),
        Media.duplicate_of_id.is_(None),
        Media.created_at >= cutoff,
    ]
    if type:
        filters.append(Media.media_type == type)

    query = (
        select(Media)
        .where(*filters)
        .order_by(Media.popularity_score.desc(), Media.views_count.desc())
        .limit(limit)
    )
    result = await session.execute(query)
    items = result.scalars().all()
    return [MediaOut.model_validate(m) for m in items]