# src/api/main.py
"""Точка входа FastAPI-приложения (бэкенд сайта).

Запуск:
  uvicorn src.api.main:app --reload
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import admin, boards, feed, media, top
from src.api.services import recalc_popularity
from src.core.config import settings
from src.core.db import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _popularity_worker() -> None:
    """Фоновая задача: периодический пересчёт индекса популярности."""
    if settings.POPULARITY_RECALC_MINUTES <= 0:
        logger.info("Пересчёт популярности выключен (POPULARITY_RECALC_MINUTES<=0)")
        return
    logger.info("Запуск фонового пересчёта популярности (каждые %s мин)",
                settings.POPULARITY_RECALC_MINUTES)
    while True:
        try:
            await asyncio.sleep(settings.POPULARITY_RECALC_MINUTES * 60)
            async with async_session_factory() as session:
                updated = await recalc_popularity(session)
            if updated:
                logger.info("Пересчитана популярность: %s записей", updated)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Ошибка пересчёта популярности")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_popularity_worker())
    yield
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


app = FastAPI(
    title="Media Site API",
    description="API сайта галереи: доски, медиа, топ, администрирование",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
origins = [o.strip() for o in settings.API_CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роуты
app.include_router(boards.router)
app.include_router(media.router)
app.include_router(top.router)
app.include_router(feed.router)
app.include_router(admin.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}