# src/core/db.py
"""Общий движок и фабрика async-сессий для парсера и API."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session():
    """FastAPI dependency: асинхронная сессия БД."""
    async with async_session_factory() as session:
        yield session