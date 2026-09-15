# src/api/routes/plans.py
"""Витрина тарифов: цены для сайта и бота.

Модель «открытый архив»: Free видит только открытые разделы (и получает рекламу),
Premium открывает приватные разделы, скачивание и убирает рекламу. Цены и стартовая
акция отдаются отсюда — страница и бот читают один источник, поэтому не разъезжаются.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import PlansOut
from src.core.db import get_session
from src.services import pricing

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


@router.get("", response_model=PlansOut)
async def list_plans(session: AsyncSession = Depends(get_session)):
    """Тарифы с ценами, скидкой и состоянием акции (без авторизации)."""
    return await pricing.pricing_view(session)
