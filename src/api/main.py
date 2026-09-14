# src/api/main.py
"""Точка входа FastAPI-приложения (бэкенд сайта).

Запуск:
  uvicorn src.api.main:app --reload
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from src.api.routes import (
    admin,
    admin_auth,
    admin_feedback,
    admin_stats,
    admin_users,
    auth,
    boards,
    feed,
    feedback,
    marks,
    media,
    resume,
    search,
    sitemap,
    status,
    threads,
    top,
    track,
)
from src.api.services import recalc_popularity
from src.core.config import settings
from src.core.db import async_session_factory
from src.core.models import User, UserSession
from src.core.redis_client import redis_client
from src.services import auth as auth_service
from src.services import reporting
from src.services.analytics import cleanup_analytics

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


async def _analytics_worker() -> None:
    """Фоновая задача: ретеншн аналитики — чистим старые посещения, аудит и сессии."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            async with async_session_factory() as session:
                removed = await cleanup_analytics(session)
            logger.info("Ретеншн аналитики: %s", removed)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Ошибка ретеншна аналитики")


async def _daily_report_worker() -> None:
    """Фоновая задача: ежедневный отчёт на почту после закрытия отчётных суток.

    Отчётные сутки — по МСК (00:00–24:00). Просыпаемся через
    `DAILY_REPORT_DELAY_MINUTES` после 00:00 МСК, считаем прошедшие сутки и
    отправляем письмо адресатам (`DAILY_REPORT_EMAILS`, иначе — админам).

    Задержка нужна, чтобы парсер успел дописать прогон: иначе итоги ночной
    докачки попадут в следующий отчёт.
    """
    if not settings.DAILY_REPORT:
        logger.info("Ежедневный отчёт выключен (DAILY_REPORT=false)")
        return

    from src.services import daily_report

    if not daily_report.recipients():
        logger.info("Ежедневный отчёт: получатели не заданы (ADMIN_EMAILS пуст) — выключен")
        return
    if not daily_report.mailer.is_configured():
        logger.info("Ежедневный отчёт: SMTP не настроен — письма не будет (доступен предпросмотр в админке)")

    logger.info("Ежедневный отчёт: ждём 00:%02d МСК", settings.DAILY_REPORT_DELAY_MINUTES)
    while True:
        try:
            delay = reporting.seconds_until_next_period() + settings.DAILY_REPORT_DELAY_MINUTES * 60
            await asyncio.sleep(max(30.0, delay))
            start, end = reporting.previous_period()
            async with async_session_factory() as session:
                report = await daily_report.build_report(session, start, end)
            sent = await daily_report.send_report(report["text"], report["subject"])
            logger.info(
                "Ежедневный отчёт за %s отправлен: %s",
                report["period_label"],
                ", ".join(sent) or "нет получателей/почта не настроена",
            )
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Ошибка ежедневного отчёта")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    tasks = [
        asyncio.create_task(_popularity_worker()),
        asyncio.create_task(_analytics_worker()),
        asyncio.create_task(_daily_report_worker()),
    ]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
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
app.include_router(threads.router)
app.include_router(sitemap.router)
app.include_router(media.router)
app.include_router(auth.router)
app.include_router(marks.router)
app.include_router(resume.router)
app.include_router(top.router)
app.include_router(feed.router)
app.include_router(status.router)
app.include_router(search.router)
app.include_router(feedback.router)
app.include_router(admin.router)
app.include_router(admin_auth.router)
app.include_router(admin_feedback.router)
app.include_router(admin_stats.router)
app.include_router(admin_users.router)
app.include_router(track.router)


@app.middleware("http")
async def count_api_errors(request: Request, call_next):
    """Считает ошибки API по дням (Redis-хеш `err:<дата>`) для вкладки «Статистика».

    Храним только счётчики по коду ответа — ни путей, ни адресов, ни тел ответов.
    """
    response = await call_next(request)
    if response.status_code >= 400 and request.url.path.startswith("/api/"):
        try:
            key = f"err:{datetime.utcnow().date().isoformat()}"
            pipe = redis_client.pipeline()
            pipe.hincrby(key, str(response.status_code), 1)
            pipe.expire(key, settings.ANALYTICS_ERROR_COUNTER_DAYS * 86400)
            await pipe.execute()
        except Exception:  # noqa: BLE001 — счётчик не должен ломать ответ
            logger.debug("Счётчик ошибок API не записан", exc_info=True)
    return response


# ── Закрытый режим (Dredger 2.0): контент только для вошедших ─────────────────
# Сайт закрыт целиком, поэтому недостаточно прятать страницы: файлы, превью и
# списки отдаёт API. Требуем действующую сессию для всех контентных ручек, а
# открытыми оставляем вход, healthz и админку (у неё своя защита токеном).
CLOSED_MODE_OPEN_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/admin/",
    "/docs",
    "/openapi.json",
)
# Кэш проверок сессии: middleware вызывается на каждый запрос, а валидность токена
# меняется редко. 30 секунд — компромисс между нагрузкой на БД и скоростью отзыва.
SESSION_CACHE_TTL = 30.0
SESSION_CACHE_MAX = 500
_session_cache: dict[str, tuple[float, bool]] = {}


async def _session_is_valid(token: str) -> bool:
    """Есть ли действующая сессия с таким токеном (один запрос, с кэшем)."""
    token_hash = auth_service.token_hash(token)
    now = time.monotonic()
    cached = _session_cache.get(token_hash)
    if cached and cached[0] > now:
        return cached[1]

    async with async_session_factory() as session:
        result = await session.execute(
            select(UserSession.id)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.expires_at > datetime.utcnow(),
                User.is_active.is_(True),
            )
            .limit(1)
        )
        valid = result.scalar_one_or_none() is not None

    if len(_session_cache) >= SESSION_CACHE_MAX:
        _session_cache.clear()
    _session_cache[token_hash] = (now + SESSION_CACHE_TTL, valid)
    return valid


@app.middleware("http")
async def guard_closed_mode(request: Request, call_next):
    """В закрытом режиме контентные ручки API требуют вход.

    Аноним получает 401 (на этом основании web уводит на `/login`), вошедший —
    обычный ответ. Результат проверки кэшируется на 30 секунд.
    """
    path = request.url.path
    if settings.site_closed and path.startswith("/api/"):
        if not path.startswith(CLOSED_MODE_OPEN_PREFIXES):
            token = request.cookies.get(auth_service.COOKIE_NAME)
            if not token or not await _session_is_valid(token):
                return JSONResponse({"detail": "Требуется вход"}, status_code=401)
    return await call_next(request)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}