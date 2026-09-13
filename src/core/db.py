# src/core/db.py
"""Общий движок и фабрика async-сессий для парсера и API."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings

# Пул параметризован (см. DB_POOL_* в config): под нагрузкой дефолтных 5+10
# соединений не хватало — запросы ждали по 30 с и падали с
# `QueuePool limit ... connection timed out`, а API отдавал 500.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    # Проверяем соединение перед выдачей: после рестарта Postgres пул не «залипает»
    pool_pre_ping=True,
)
async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session():
    """FastAPI dependency: асинхронная сессия БД."""
    async with async_session_factory() as session:
        yield session