# src/api/stats_service.py
"""Агрегация статистики по доскам для админ-панели (overview + polling).

Всё считается по БД — без запросов к форуму.
"""
from typing import Dict, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Board, Media, ThreadState

UPLOADED_STATUSES = ("uploaded", "verified")


async def media_stats_by_board(session: AsyncSession) -> Dict[int, dict]:
    """Статистика медиа по доскам."""
    rows = await session.execute(
        select(
            Media.board_id.label("board_id"),
            func.count(Media.id).label("media_total"),
            func.count()
            .filter(Media.download_status.in_(UPLOADED_STATUSES))
            .label("media_in_s3"),
            func.count()
            .filter(Media.download_status == "downloaded")
            .label("media_downloaded"),
            func.count()
            .filter(Media.download_status == "missing")
            .label("media_missing"),
            func.count().filter(Media.is_visible.is_(True)).label("media_visible"),
            func.coalesce(func.sum(Media.views_count), 0).label("views_total"),
            func.coalesce(func.sum(Media.downloads_count), 0).label("downloads_total"),
        )
        .group_by(Media.board_id)
    )
    stats = {}
    for r in rows:
        stats[r.board_id] = {
            "media_total": int(r.media_total or 0),
            "media_in_s3": int(r.media_in_s3 or 0),
            "media_downloaded": int(r.media_downloaded or 0),
            "media_missing": int(r.media_missing or 0),
            "media_visible": int(r.media_visible or 0),
            "views_total": int(r.views_total or 0),
            "downloads_total": int(r.downloads_total or 0),
        }
    return stats


async def thread_stats_by_board(session: AsyncSession) -> Dict[int, dict]:
    """Статистика threads_state по доскам."""
    rows = await session.execute(
        select(
            ThreadState.board_id.label("board_id"),
            func.count().filter(ThreadState.is_active.is_(True)).label("threads_active"),
            func.coalesce(
                func.sum(ThreadState.files_count).filter(ThreadState.is_active.is_(True)),
                0,
            ).label("files_in_catalog"),
            func.max(ThreadState.last_scanned_at).label("last_scan"),
        )
        .group_by(ThreadState.board_id)
    )
    stats = {}
    for r in rows:
        stats[r.board_id] = {
            "threads_active": int(r.threads_active or 0),
            "files_in_catalog": int(r.files_in_catalog or 0),
            "last_scan": r.last_scan,
        }
    return stats


async def collect_board_stats(
    session: AsyncSession,
) -> Tuple[Dict[int, dict], dict]:
    """Сводная статистика по каждой доске + итоговые цифры системы."""
    media = await media_stats_by_board(session)
    threads = await thread_stats_by_board(session)

    boards: Dict[int, dict] = {}
    totals = {
        "media_total": 0,
        "media_in_s3": 0,
        "media_downloaded": 0,
        "media_missing": 0,
        "media_visible": 0,
        "threads_active": 0,
        "files_in_catalog": 0,
        "views_total": 0,
        "downloads_total": 0,
    }
    for board_id in set(media) | set(threads):
        m = media.get(board_id, {})
        t = threads.get(board_id, {})
        combined = {**m, **t}
        boards[board_id] = combined
        for key in totals:
            totals[key] += int(combined.get(key, 0) or 0)

    return boards, totals
