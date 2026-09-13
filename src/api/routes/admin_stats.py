# src/api/routes/admin_stats.py
"""Статистика посещаемости и поведения для админки (вкладка «Статистика»).

Всё считается по своей таблице `page_hits` (плюс уже существующие просмотры,
скачивания и метки). Боты исключаются: они пишутся, но в отчёты не попадают.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import verify_admin
from src.core.db import get_session
from src.core.models import Board, DownloadStat, Media, MediaMark, PageHit, ViewStat
from src.core.redis_client import redis_client

router = APIRouter(prefix="/api/v1/admin/stats", tags=["admin-stats"])

# Статусы, которые считает middleware API (429 — лимиты, 5xx — сбои).
HEALTH_STATUSES = ("429", "500", "502", "503", "504")


def _window(days: int) -> tuple[datetime, datetime]:
    """Окно отчёта: (начало, конец)."""
    now = datetime.utcnow()
    return now - timedelta(days=max(1, days)), now


def _human():
    """Только люди: боты в отчёты не попадают."""
    return PageHit.is_bot.is_(False)


def _totals_query(start: datetime, end: datetime):
    """Базовые метрики за интервал: посетители, визиты, просмотры, события."""
    return select(
        func.count(func.distinct(PageHit.session_id)).label("visitors"),
        func.count().filter(PageHit.is_new_visit.is_(True)).label("visits"),
        func.count().filter(PageHit.kind == "page").label("pageviews"),
        func.count().filter(PageHit.kind == "event").label("events"),
        func.count(func.distinct(PageHit.user_id)).label("registered"),
    ).where(_human(), PageHit.created_at >= start, PageHit.created_at < end)


def _as_dict(row) -> dict:
    return {
        "visitors": int(row.visitors or 0),
        "visits": int(row.visits or 0),
        "pageviews": int(row.pageviews or 0),
        "events": int(row.events or 0),
        "registered": int(row.registered or 0),
    }


@router.get("/overview")
async def stats_overview(
    days: int = Query(30, ge=1, le=365),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Сводка за период + сравнение с предыдущим таким же периодом."""
    since, now = _window(days)
    prev_since = since - timedelta(days=days)

    current = _as_dict((await session.execute(_totals_query(since, now))).one())
    previous = _as_dict((await session.execute(_totals_query(prev_since, since))).one())

    # Новые посетители: их самый первый хит вообще — внутри периода.
    first_seen = (
        select(
            PageHit.session_id.label("sid"),
            func.min(PageHit.created_at).label("first_at"),
        )
        .where(_human(), PageHit.session_id.isnot(None), PageHit.created_at >= prev_since)
        .group_by(PageHit.session_id)
        .subquery()
    )
    new_visitors = (
        await session.execute(
            select(func.count()).select_from(first_seen).where(first_seen.c.first_at >= since)
        )
    ).scalar() or 0

    def delta(key: str) -> Optional[float]:
        base = previous.get(key) or 0
        if not base:
            return None
        return round((current[key] - base) / base * 100, 1)

    visits = current["visits"] or 0
    return {
        "days": days,
        "generated_at": now.isoformat(),
        **current,
        "previous": previous,
        "delta": {k: delta(k) for k in ("visitors", "visits", "pageviews")},
        "new_visitors": int(new_visitors),
        "returning_visitors": max(0, current["visitors"] - int(new_visitors)),
        "pages_per_visit": round(current["pageviews"] / visits, 2) if visits else 0,
    }


@router.get("/timeseries")
async def stats_timeseries(
    days: int = Query(30, ge=1, le=365),
    group: str = Query("day", pattern="^(day|hour)$"),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Ряд для графика: по дням или по часам (часы — для суток-двух)."""
    since, now = _window(days)
    bucket = func.date_trunc(group, PageHit.created_at).label("bucket")
    rows = (
        await session.execute(
            select(
                bucket,
                func.count(func.distinct(PageHit.session_id)).label("visitors"),
                func.count().filter(PageHit.is_new_visit.is_(True)).label("visits"),
                func.count().filter(PageHit.kind == "page").label("pageviews"),
            )
            .where(_human(), PageHit.created_at >= since, PageHit.created_at < now)
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()
    return {
        "group": group,
        "days": days,
        "points": [
            {
                "t": row.bucket.isoformat(),
                "visitors": int(row.visitors or 0),
                "visits": int(row.visits or 0),
                "pageviews": int(row.pageviews or 0),
            }
            for row in rows
        ],
    }


@router.get("/pages")
async def stats_pages(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Топ страниц: просмотры и уникальные посетители."""
    since, now = _window(days)
    rows = (
        await session.execute(
            select(
                PageHit.path,
                func.count().label("views"),
                func.count(func.distinct(PageHit.session_id)).label("visitors"),
            )
            .where(_human(), PageHit.kind == "page", PageHit.created_at >= since)
            .group_by(PageHit.path)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return {
        "days": days,
        "items": [
            {"path": r.path, "views": int(r.views or 0), "visitors": int(r.visitors or 0)}
            for r in rows
        ],
    }


@router.get("/sources")
async def stats_sources(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Источники: внешние сайты (рефереры) и метки UTM."""
    since, now = _window(days)
    refs = (
        await session.execute(
            select(
                PageHit.referrer_host,
                func.count().label("visits"),
                func.count(func.distinct(PageHit.session_id)).label("visitors"),
            )
            .where(_human(), PageHit.is_new_visit.is_(True), PageHit.created_at >= since)
            .group_by(PageHit.referrer_host)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    utm = (
        await session.execute(
            select(PageHit.utm_source, func.count().label("visits"))
            .where(
                _human(),
                PageHit.is_new_visit.is_(True),
                PageHit.utm_source.isnot(None),
                PageHit.created_at >= since,
            )
            .group_by(PageHit.utm_source)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return {
        "days": days,
        "referrers": [
            {
                "host": r.referrer_host or "прямые заходы",
                "visits": int(r.visits or 0),
                "visitors": int(r.visitors or 0),
            }
            for r in refs
        ],
        "utm": [{"source": u.utm_source, "visits": int(u.visits or 0)} for u in utm],
    }


@router.get("/devices")
async def stats_devices(
    days: int = Query(30, ge=1, le=365),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Устройства, браузеры и ОС посетителей."""
    since, now = _window(days)

    async def breakdown(column):
        rows = (
            await session.execute(
                select(
                    column,
                    func.count().label("hits"),
                    func.count(func.distinct(PageHit.session_id)).label("visitors"),
                )
                .where(_human(), PageHit.created_at >= since)
                .group_by(column)
                .order_by(func.count().desc())
                .limit(12)
            )
        ).all()
        return [
            {
                "name": str(r[0] or "неизвестно"),
                "hits": int(r.hits or 0),
                "visitors": int(r.visitors or 0),
            }
            for r in rows
        ]

    return {
        "days": days,
        "devices": await breakdown(PageHit.device),
        "browsers": await breakdown(PageHit.browser),
        "os": await breakdown(PageHit.os),
    }


@router.get("/events")
async def stats_events(
    days: int = Query(30, ge=1, le=365),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """События интерфейса: открытия просмотра, фильтры, скачивания и т.п."""
    since, now = _window(days)
    rows = (
        await session.execute(
            select(
                PageHit.event,
                func.count().label("hits"),
                func.count(func.distinct(PageHit.session_id)).label("visitors"),
            )
            .where(_human(), PageHit.kind == "event", PageHit.created_at >= since)
            .group_by(PageHit.event)
            .order_by(func.count().desc())
            .limit(30)
        )
    ).all()
    return {
        "days": days,
        "items": [
            {
                "event": r.event,
                "hits": int(r.hits or 0),
                "visitors": int(r.visitors or 0),
            }
            for r in rows
        ],
    }


@router.get("/content")
async def stats_content(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(15, ge=1, le=50),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Что смотрят: топ файлов по просмотрам, скачиваниям и меткам + по разделам."""
    since, _now = _window(days)

    async def top_media(model, time_column):
        rows = (
            await session.execute(
                select(
                    Media.id,
                    Media.original_name,
                    Board.slug,
                    func.count().label("cnt"),
                )
                .join(Media, Media.id == model.media_id)
                .join(Board, Board.id == Media.board_id)
                .where(time_column >= since)
                .group_by(Media.id, Media.original_name, Board.slug)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": int(r.id),
                "name": r.original_name,
                "board": r.slug,
                "count": int(r.cnt or 0),
            }
            for r in rows
        ]

    boards = (
        await session.execute(
            select(Board.slug, func.count().label("views"))
            .join(Media, Media.board_id == Board.id)
            .join(ViewStat, ViewStat.media_id == Media.id)
            .where(ViewStat.viewed_at >= since)
            .group_by(Board.slug)
            .order_by(func.count().desc())
            .limit(12)
        )
    ).all()

    return {
        "days": days,
        "views": await top_media(ViewStat, ViewStat.viewed_at),
        "downloads": await top_media(DownloadStat, DownloadStat.downloaded_at),
        "marks": await top_media(MediaMark, MediaMark.created_at),
        "boards": [{"board": r.slug, "views": int(r.views or 0)} for r in boards],
    }


@router.get("/health")
async def stats_health(
    days: int = Query(7, ge=1, le=30),
    _=Depends(verify_admin),
):
    """Здоровье API: счётчики ошибок по дням (429 — лимиты, 5xx — сбои).

    Счётчики пишет middleware API в Redis-хеш `err:<дата>`; сами ответы не
    логируем, чтобы не хранить лишнего.
    """
    today = datetime.utcnow().date()
    items = []
    for offset in range(days):
        date = today - timedelta(days=offset)
        raw = await redis_client.hgetall(f"err:{date.isoformat()}")
        counters = {
            (k.decode() if isinstance(k, bytes) else str(k)): int(v)
            for k, v in (raw or {}).items()
        }
        items.append(
            {
                "date": date.isoformat(),
                "counters": counters,
                "total": sum(counters.values()),
            }
        )
    return {"days": days, "statuses": list(HEALTH_STATUSES), "items": items}
