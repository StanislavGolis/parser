# src/api/threads_service.py
"""Агрегация тредов доски: метаданные из threads_state + статистика файлов.

Используется публичным API (`/boards/{slug}/threads`) и админкой
(статистика по тредам), чтобы не дублировать логику.
"""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Integer, String, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import sign_media_urls
from src.api.schemas import MediaOut, ThreadOut
from src.core.models import Media, ThreadState
from src.services.s3_storage import S3Storage

UPLOADED_STATUSES = ("uploaded", "verified")
# Сколько последних файлов треда отдавать превью
PREVIEW_SIZE = 8


def thread_work_rank():
    """SQL-выражение «в работе»: парсить важнее, затем «на сайте», затем «по коду»."""
    return (
        cast(ThreadState.parse_enabled, Integer) * 4
        + cast(ThreadState.is_visible, Integer) * 2
        + cast(ThreadState.is_private, Integer)
    )


def _state_filters(state: str):
    """Условия фильтра по состоянию треда (для чипов в админке)."""
    work = or_(
        ThreadState.parse_enabled.is_(True),
        ThreadState.is_visible.is_(True),
        ThreadState.is_private.is_(True),
    )
    if state == "active":
        return [work]
    if state == "parsing":
        return [ThreadState.parse_enabled.is_(True)]
    if state == "visible":
        return [ThreadState.is_visible.is_(True)]
    if state == "private":
        return [ThreadState.is_private.is_(True)]
    if state == "off":
        return [~work]
    return []


async def thread_state_counts(session: AsyncSession, board_id: int) -> Dict[str, int]:
    """Счётчики по состояниям тредов (для чипов фильтра)."""
    work = or_(
        ThreadState.parse_enabled.is_(True),
        ThreadState.is_visible.is_(True),
        ThreadState.is_private.is_(True),
    )
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(work),
                func.count().filter(ThreadState.parse_enabled.is_(True)),
                func.count().filter(ThreadState.is_visible.is_(True)),
                func.count().filter(ThreadState.is_private.is_(True)),
                func.count().filter(~work),
            ).where(ThreadState.board_id == board_id, ThreadState.is_active.is_(True))
        )
    ).one()
    return {
        "all": int(row[0] or 0),
        "active": int(row[1] or 0),
        "parsing": int(row[2] or 0),
        "visible": int(row[3] or 0),
        "private": int(row[4] or 0),
        "off": int(row[5] or 0),
    }


async def list_threads(
    session: AsyncSession,
    board_id: int,
    page: int,
    per_page: int,
    only_visible: bool = False,
    state: str = "all",
    q: Optional[str] = None,
    admin_order: bool = False,
) -> Tuple[List[ThreadState], int]:
    """Треды доски (пагинация).

    only_visible=True — публичный режим: только активные видимые треды с файлами.
    state/q — фильтры админки (состояние, поиск по теме/номеру).
    admin_order=True — «в работе» сверху (для админки).
    """
    filters = [ThreadState.board_id == board_id, ThreadState.is_active.is_(True)]
    if only_visible:
        filters.append(ThreadState.is_visible.is_(True))
        # Публично показываем только треды, в которых есть видимые файлы
        # (иначе получаются «пустые» карточки-мусор после сканирования).
        filters.append(
            exists().where(
                Media.board_id == ThreadState.board_id,
                Media.thread_id == ThreadState.thread_id,
                Media.is_visible.is_(True),
                Media.is_active.is_(True),
                Media.duplicate_of_id.is_(None),
            )
        )
    else:
        filters.extend(_state_filters(state))
        if q:
            like = f"%{q.strip()}%"
            filters.append(
                or_(
                    ThreadState.subject.ilike(like),
                    cast(ThreadState.thread_id, String).like(like),
                )
            )

    total = (
        await session.execute(
            select(func.count()).select_from(ThreadState).where(*filters)
        )
    ).scalar() or 0

    order_by = []
    if admin_order:
        order_by.append(thread_work_rank().desc())
    order_by.append(ThreadState.thread_timestamp.desc().nullslast())
    order_by.append(ThreadState.thread_id.desc())

    result = await session.execute(
        select(ThreadState)
        .where(*filters)
        .order_by(*order_by)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.scalars().all()), int(total)


async def thread_catalog_totals(session: AsyncSession, board_id: int) -> dict:
    """Суммы по доске для описания страницы сканирования.

    посты/просмотры/файлы-на-форуме — из данных 2ch (каталог и res/{id}.json,
    т.е. доступны ещё до скачивания медиа); скачано — фактически в БД.
    """
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(ThreadState.posts_count), 0),
                func.coalesce(func.sum(ThreadState.views_count), 0),
                func.coalesce(func.sum(ThreadState.files_detected), 0),
            ).where(ThreadState.board_id == board_id, ThreadState.is_active.is_(True))
        )
    ).one()
    downloaded = (
        await session.execute(
            select(func.count(Media.id)).where(Media.board_id == board_id)
        )
    ).scalar() or 0
    return {
        "posts_total": int(row[0] or 0),
        "views_total": int(row[1] or 0),
        "files_detected_total": int(row[2] or 0),
        "files_downloaded_total": int(downloaded),
    }


async def _media_stats(session: AsyncSession, board_id: int) -> Dict[int, dict]:
    """Статистика файлов по тредам доски: {thread_id: {поля}}."""
    rows = await session.execute(
        select(
            Media.thread_id.label("thread_id"),
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
        )
        .where(Media.board_id == board_id)
        .group_by(Media.thread_id)
    )
    stats = {}
    for r in rows:
        stats[r.thread_id] = {
            "media_total": int(r.media_total or 0),
            "media_in_s3": int(r.media_in_s3 or 0),
            "media_downloaded": int(r.media_downloaded or 0),
            "media_missing": int(r.media_missing or 0),
            "media_visible": int(r.media_visible or 0),
        }
    return stats


async def _previews(
    session: AsyncSession,
    board_id: int,
    thread_ids: List[int],
) -> Dict[int, List[Media]]:
    """Последние PREVIEW_SIZE видимых файлов (с S3-ключом) по каждому треду."""
    if not thread_ids:
        return {}
    rn = func.row_number().over(
        partition_by=Media.thread_id,
        order_by=(Media.created_at.desc(), Media.id.desc()),
    ).label("rn")
    sub = (
        select(Media.id.label("mid"), Media.thread_id.label("thread_id"), rn)
        .where(
            Media.board_id == board_id,
            Media.is_visible.is_(True),
            Media.s3_key.isnot(None),
        )
        .subquery()
    )
    rows = await session.execute(
        select(Media)
        .join(sub, sub.c.mid == Media.id)
        .where(sub.c.rn <= PREVIEW_SIZE, sub.c.thread_id.in_(thread_ids))
        .order_by(Media.created_at.desc(), Media.id.desc())
    )
    result: Dict[int, List[Media]] = defaultdict(list)
    for media in rows.scalars().all():
        if len(result[media.thread_id]) < PREVIEW_SIZE:
            result[media.thread_id].append(media)
    return dict(result)


async def build_thread_outs(
    session: AsyncSession,
    board_id: int,
    threads: List[ThreadState],
    *,
    s3: Optional[S3Storage] = None,
    with_preview: bool = True,
    allowed_private_ids: Optional[set] = None,
) -> List[ThreadOut]:
    """Собирает ThreadOut для списка тредов (+ статистика и превью)."""
    if not threads:
        return []

    allowed = allowed_private_ids or set()
    stats = await _media_stats(session, board_id)
    thread_ids = [t.thread_id for t in threads]
    previews = await _previews(session, board_id, thread_ids) if with_preview else {}

    out = []
    for t in threads:
        s = stats.get(t.thread_id, {})
        item = ThreadOut(
            board_id=board_id,
            thread_id=t.thread_id,
            subject=t.subject,
            comment=t.comment,
            posts_count=t.posts_count,
            files_count=t.files_count,
            files_detected=t.files_detected,
            views_count=t.views_count,
            thread_timestamp=t.thread_timestamp,
            last_scanned_at=t.last_scanned_at,
            is_active=t.is_active,
            parse_enabled=t.parse_enabled,
            is_visible=t.is_visible,
            is_private=t.is_private,
            has_access_code=bool(t.access_code_hash),
            media_total=s.get("media_total", 0),
            media_downloaded=s.get("media_downloaded", 0),
            media_in_s3=s.get("media_in_s3", 0),
            media_missing=s.get("media_missing", 0),
            media_visible=s.get("media_visible", 0),
            preview=[],
        )

        # Превью приватного треда отдаём только при подтверждённом доступе
        can_preview = (not t.is_private) or (t.thread_id in allowed)
        if with_preview and can_preview:
            media_items = previews.get(t.thread_id, [])
            if media_items:
                preview_out = [MediaOut.model_validate(m) for m in media_items]
                if s3 is not None:
                    sign_media_urls(preview_out, media_items, s3)
                item.preview = preview_out
        out.append(item)

    return out
