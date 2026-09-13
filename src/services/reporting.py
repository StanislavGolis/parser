# src/services/reporting.py
"""Единый отчётный период (сутки по МСК) и суточные агрегаты.

**Отчётные сутки — московские**: с 00:00:00 МСК до 00:00:00 МСК следующего дня.
В БД время хранится в UTC без таймзоны, поэтому границы периода переводятся в
UTC (`MSK_OFFSET = +3`, переходов на летнее время в Москве нет с 2014 года).

Один и тот же период используется всюду, где написано «за сутки», — сводка на
главной (`/api/v1/status`), «+N за сегодня» на карточке раздела
(`/api/v1/boards`), дашборд админки и ежедневное письмо-отчёт. Благодаря этому
цифры на сайте, в админке и в письме всегда совпадают.

Здесь только расчёты: как их показать (сайт, админка, письмо) решают вызывающие.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, visible_thread_clause
from src.core.models import Board, Media, MediaMark, PageHit, ParseRun, User

# Москва: UTC+3 (переходов нет с 2014 года — фиксированное смещение)
MSK_OFFSET = timedelta(hours=3)
MSK_TZ = timezone(MSK_OFFSET)


def now_utc() -> datetime:
    """«Сейчас» в том виде, в котором время лежит в БД: UTC без таймзоны."""
    return datetime.utcnow()


def to_msk(moment: datetime) -> datetime:
    """UTC (naive) → московское время с таймзоной — для подписей в отчётах."""
    return moment.replace(tzinfo=timezone.utc).astimezone(MSK_TZ)


def period_bounds(moment: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """Границы текущих отчётных суток в UTC: [00:00 МСК; 00:00 МСК следующих).

    Возвращает naive-UTC, как в колонках `created_at`: с ними удобно сравнивать
    напрямую (`Media.created_at >= start`).
    """
    msk_now = (moment or now_utc()).replace(tzinfo=timezone.utc).astimezone(MSK_TZ)
    start_msk = msk_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_msk = start_msk + timedelta(days=1)
    to_utc = lambda value: value.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(start_msk), to_utc(end_msk)


def previous_period(moment: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """Границы **прошедших** отчётных суток — то, что попадает в письмо-отчёт."""
    msk_now = (moment or now_utc()).replace(tzinfo=timezone.utc).astimezone(MSK_TZ)
    today_start = msk_now.replace(hour=0, minute=0, second=0, microsecond=0)
    to_utc = lambda value: value.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(today_start - timedelta(days=1)), to_utc(today_start)


def label(moment: datetime, *, with_time: bool = False) -> str:
    """Подпись периода по-московски: «13.09.2026» или «13.09.2026, 00:00 МСК»."""
    value = to_msk(moment)
    return value.strftime("%d.%m.%Y, %H:%M МСК" if with_time else "%d.%m.%Y")


def period_title(start: datetime, end: datetime) -> str:
    """Название отчётного периода: «13.09.2026 (00:00–24:00 МСК)»."""
    return f"{label(start)} (00:00–24:00 МСК)"


def seconds_until_next_period(moment: Optional[datetime] = None) -> float:
    """Сколько секунд до 00:00 МСК — момент, когда прошедшие сутки посчитаны."""
    msk_now = (moment or now_utc()).replace(tzinfo=timezone.utc).astimezone(MSK_TZ)
    next_day = (msk_now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(0.0, (next_day - msk_now).total_seconds())


# ── Расчёты за период ───────────────────────────────────────────────


def _media_clause(start: datetime, end: datetime, *, only_visible: bool, board_ids=None):
    """Условия «файл добавлен в отчётном периоде» (плюс публичные фильтры)."""
    conditions = [
        Media.created_at >= start,
        Media.created_at < end,
        # Дубли-ссылки — не новые файлы: считаем только уникальные
        Media.duplicate_of_id.is_(None),
    ]
    if only_visible:
        conditions.extend([*VISIBLE_FILTER, visible_thread_clause()])
    if board_ids:
        conditions.append(Media.board_id.in_(board_ids))
    return conditions


async def media_today_by_board(
    session: AsyncSession, start: datetime, end: datetime
) -> Dict[int, int]:
    """Сколько файлов прибавилось за период по каждому разделу (карточки каталога)."""
    rows = await session.execute(
        select(Media.board_id, func.count(Media.id))
        .where(*_media_clause(start, end, only_visible=True))
        .group_by(Media.board_id)
    )
    return {int(board_id): int(count) for board_id, count in rows.all()}


async def top_boards(
    session: AsyncSession, start: datetime, end: datetime, *, limit: int = 5
) -> List[Dict[str, Any]]:
    """Разделы с наибольшим приростом файлов за период (для отчёта и админки)."""
    rows = await session.execute(
        select(Board.slug, Board.title, func.count(Media.id).label("files"))
        .join(Media, Media.board_id == Board.id)
        .where(*_media_clause(start, end, only_visible=False))
        .group_by(Board.id, Board.slug, Board.title)
        .order_by(func.count(Media.id).desc())
        .limit(limit)
    )
    return [
        {"slug": slug, "title": title, "files": int(files or 0)}
        for slug, title, files in rows.all()
    ]


async def daily_stats(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    only_visible: bool = False,
) -> Dict[str, Any]:
    """Сводка за отчётные сутки: контент, люди и активность.

    `only_visible` — считать только то, что видно посетителям (публичная сводка
    на сайте); для админки и письма берём всё, включая скрытое и премиум.

    Посетители считаются по `ip_hash` (сам IP не хранится), боты исключаются;
    «новые посетители» — у кого в этом периоде заход «с нуля» (`is_new_visit`),
    а не переход внутри сайта.
    """
    media_where = _media_clause(start, end, only_visible=only_visible)

    totals = (
        await session.execute(
            select(
                func.count(Media.id),
                func.count(func.distinct(Media.thread_id)),
                func.count(func.distinct(Media.board_id)),
                func.coalesce(func.sum(Media.file_size), 0),
                func.count(Media.id).filter(Media.media_type == "image"),
                func.count(Media.id).filter(Media.media_type == "video"),
            )
            .select_from(Media)
            .where(*media_where)
        )
    ).one()

    people = (
        await session.execute(
            select(
                func.count(func.distinct(PageHit.ip_hash)),
                func.count(func.distinct(PageHit.session_id)),
                func.count(PageHit.id),
                func.count(func.distinct(PageHit.ip_hash)).filter(PageHit.is_new_visit.is_(True)),
            ).where(
                PageHit.kind == "page",
                PageHit.is_bot.is_(False),
                PageHit.created_at >= start,
                PageHit.created_at < end,
            )
        )
    ).one()

    activity = (
        await session.execute(
            select(
                select(func.count())
                .select_from(User)
                .where(User.created_at >= start, User.created_at < end)
                .scalar_subquery(),
                select(func.count())
                .select_from(MediaMark)
                .where(MediaMark.created_at >= start, MediaMark.created_at < end)
                .scalar_subquery(),
                select(func.count())
                .select_from(ParseRun)
                .where(
                    ParseRun.started_at >= start,
                    ParseRun.started_at < end,
                    ParseRun.status == "ok",
                )
                .scalar_subquery(),
                select(func.count())
                .select_from(ParseRun)
                .where(
                    ParseRun.started_at >= start,
                    ParseRun.started_at < end,
                    ParseRun.status == "error",
                )
                .scalar_subquery(),
            )
        )
    ).one()

    files_added, threads_touched, boards_touched, bytes_added, images, videos = totals
    visitors, sessions, page_views, first_visits = people
    new_users, marks, runs_ok, runs_error = activity

    return {
        "start": start,
        "end": end,
        "files_added": int(files_added or 0),
        "images_added": int(images or 0),
        "videos_added": int(videos or 0),
        "threads_touched": int(threads_touched or 0),
        "boards_touched": int(boards_touched or 0),
        "bytes_added": int(bytes_added or 0),
        "visitors": int(visitors or 0),
        "sessions": int(sessions or 0),
        "page_views": int(page_views or 0),
        "visitors_new": int(first_visits or 0),
        "page_views_per_visitor": (
            round(int(page_views or 0) / int(visitors), 1) if visitors else 0.0
        ),
        "new_users": int(new_users or 0),
        "marks": int(marks or 0),
        "runs_ok": int(runs_ok or 0),
        "runs_error": int(runs_error or 0),
    }


async def parse_failures(
    session: AsyncSession, start: datetime, end: datetime, *, limit: int = 5
) -> List[Dict[str, Any]]:
    """Сбои прогонов за период — строкой в отчёт, чтобы проблемы не терялись."""
    rows = await session.execute(
        select(ParseRun.started_at, ParseRun.error)
        .where(
            ParseRun.started_at >= start,
            ParseRun.started_at < end,
            ParseRun.status == "error",
        )
        .order_by(ParseRun.started_at.desc())
        .limit(limit)
    )
    return [
        {"at": started_at, "error": (error or "без описания")[:200]}
        for started_at, error in rows.all()
    ]


def human_bytes(size: int) -> str:
    """Размер по-человечески: 3.4 ГБ, 512 МБ, 12 КБ."""
    value = float(size or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{int(value)} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ТБ"

