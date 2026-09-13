# src/api/threads_service.py
"""Агрегация тредов доски: метаданные из threads_state + статистика файлов.

Используется публичным API (`/boards/{slug}/threads`) и админкой
(статистика по тредам), чтобы не дублировать логику.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Integer, String, and_, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import apply_user_flags, is_locked, sign_media_urls
from src.api.schemas import MediaOut, ThreadOut
from src.core.config import settings
from src.core.models import Media, ThreadState, User
from src.services import reporting
from src.services.s3_storage import S3Storage

UPLOADED_STATUSES = ("uploaded", "verified")
# Сколько последних файлов треда отдавать превью
PREVIEW_SIZE = 8


def thread_work_rank():
    """SQL-выражение «в работе»: парсить важнее, затем «на сайте», затем «премиум»."""
    return (
        cast(ThreadState.parse_enabled, Integer) * 4
        + cast(ThreadState.is_visible, Integer) * 2
        + cast(ThreadState.is_premium, Integer)
    )


def stale_before() -> datetime:
    """Порог «просроченного» треда: сканировался раньше этого времени."""
    return datetime.utcnow() - timedelta(hours=settings.STALE_SCAN_HOURS)


def stale_clause():
    """Условие «просрочен»: парсить включено, но тред давно не сканировался.

    Нужно потому, что обход идёт по каталогу и тред без изменений в каталоге
    может не перепроверяться бесконечно долго — такие треды важно видеть.
    """
    return and_(
        ThreadState.is_active.is_(True),
        ThreadState.parse_enabled.is_(True),
        or_(
            ThreadState.last_scanned_at.is_(None),
            ThreadState.last_scanned_at < stale_before(),
        ),
    )


def lagging_clause():
    """«Недокачано»: на форуме файлов больше, чем записей у нас по треду.

    `files_detected` — число файлов из `res/{id}.json` (обновляется при каждом
    скане и в режиме «считать файлы»), а `media` — то, что реально сохранено
    (учитывая дубли-ссылки: они тоже строки треда). Разница — файлы, которых у
    нас нет: битые/недоступные или не дошедшие из-за сбоя.

    Считаем только треды «в работе» (`parse_enabled`): у выключенных тредов
    разница ожидаема и не требует действий.
    """
    seen = (
        select(func.count())
        .select_from(Media)
        .where(
            Media.board_id == ThreadState.board_id,
            Media.thread_id == ThreadState.thread_id,
        )
        .scalar_subquery()
    )
    return and_(
        ThreadState.is_active.is_(True),
        ThreadState.parse_enabled.is_(True),
        ThreadState.files_detected > seen,
    )


def _state_filters(state: str):
    """Условия фильтра по состоянию треда (для чипов в админке)."""
    work = or_(
        ThreadState.parse_enabled.is_(True),
        ThreadState.is_visible.is_(True),
        ThreadState.is_premium.is_(True),
    )
    if state == "active":
        return [work]
    if state == "parsing":
        return [ThreadState.parse_enabled.is_(True)]
    if state == "visible":
        return [ThreadState.is_visible.is_(True)]
    if state == "premium":
        return [ThreadState.is_premium.is_(True)]
    if state == "off":
        return [~work]
    if state == "dead":
        # Выпали из каталога доски (is_active=False): не теряем их из вида
        return [ThreadState.is_active.is_(False)]
    if state == "stale":
        return [stale_clause()]
    if state == "queued":
        # Стоят в очереди на докачку (фаза B двухфазного цикла)
        return [ThreadState.pending_scan.is_(True)]
    if state == "lagging":
        # Недокачано: на форуме файлов больше, чем сохранено у нас
        return [lagging_clause()]
    return []


async def thread_state_counts(session: AsyncSession, board_id: int) -> Dict[str, int]:
    """Счётчики по состояниям тредов (для чипов фильтра).

    Считаем **все** треды доски, включая выпавшие из каталога (`dead`):
    иначе «забытые» треды не видны в админке вообще.
    """
    work = or_(
        ThreadState.parse_enabled.is_(True),
        ThreadState.is_visible.is_(True),
        ThreadState.is_premium.is_(True),
    )
    active = ThreadState.is_active.is_(True)
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(and_(active, work)),
                func.count().filter(and_(active, ThreadState.parse_enabled.is_(True))),
                func.count().filter(and_(active, ThreadState.is_visible.is_(True))),
                func.count().filter(and_(active, ThreadState.is_premium.is_(True))),
                func.count().filter(and_(active, ~work)),
                func.count().filter(ThreadState.is_active.is_(False)),
                func.count().filter(stale_clause()),
                func.count().filter(and_(active, ThreadState.pending_scan.is_(True))),
                func.count().filter(lagging_clause()),
            ).where(ThreadState.board_id == board_id)
        )
    ).one()
    return {
        "all": int(row[0] or 0),        # все треды доски, включая мёртвые
        "active": int(row[1] or 0),
        "parsing": int(row[2] or 0),
        "visible": int(row[3] or 0),
        "premium": int(row[4] or 0),
        "off": int(row[5] or 0),
        "dead": int(row[6] or 0),       # нет в каталоге доски
        "stale": int(row[7] or 0),      # давно не сканировались
        "pending": int(row[8] or 0),    # стоят в очереди на докачку
        "lagging": int(row[9] or 0),    # недокачано (файлов на форуме больше)
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
    sort: str = "new",
) -> Tuple[List[ThreadState], int]:
    """Треды доски (пагинация).

    only_visible=True — публичный режим: только активные видимые треды с файлами.
    state/q — фильтры админки (состояние, поиск по теме/номеру).
    admin_order=True — «в работе» сверху (для админки).
    sort — порядок выдачи: `new` (свежие треды), `files` (больше файлов в архиве),
    `posts` (больше постов), `views` (больше просмотров).
    """
    filters = [ThreadState.board_id == board_id]
    if only_visible:
        # Публично — только активные треды (выпавшие из каталога форума скрыты)
        filters.append(ThreadState.is_active.is_(True))
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
        # «Мёртвые» (выпавшие из каталога доски) — отдельный фильтр. Остальные
        # состояния показываем только по активным тредам.
        if state != "dead":
            filters.append(ThreadState.is_active.is_(True))
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

    # Сортировка публичного списка. «По файлам» считаем по фактически видимым
    # файлам треда (дубли-ссылки не в счёт) — это то, что зритель увидит на
    # карточке, а не число файлов из каталога источника.
    query = select(ThreadState).where(*filters)
    if sort == "files":
        counts = (
            select(
                Media.board_id.label("board_id"),
                Media.thread_id.label("thread_id"),
                func.count(Media.id).label("files_cnt"),
            )
            .where(
                Media.is_visible.is_(True),
                Media.is_active.is_(True),
                Media.duplicate_of_id.is_(None),
            )
            .group_by(Media.board_id, Media.thread_id)
            .subquery()
        )
        query = query.outerjoin(
            counts,
            and_(
                counts.c.board_id == ThreadState.board_id,
                counts.c.thread_id == ThreadState.thread_id,
            ),
        )
        order_by.append(func.coalesce(counts.c.files_cnt, 0).desc())
    elif sort == "posts":
        order_by.append(ThreadState.posts_count.desc())
    elif sort == "views":
        order_by.append(ThreadState.views_count.desc())

    order_by.append(ThreadState.thread_timestamp.desc().nullslast())
    order_by.append(ThreadState.thread_id.desc())

    result = await session.execute(
        query.order_by(*order_by).offset((page - 1) * per_page).limit(per_page)
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
            select(func.count(Media.id)).where(
                Media.board_id == board_id, Media.duplicate_of_id.is_(None)
            )
        )
    ).scalar() or 0
    return {
        "posts_total": int(row[0] or 0),
        "views_total": int(row[1] or 0),
        "files_detected_total": int(row[2] or 0),
        "files_downloaded_total": int(downloaded),
    }


async def _media_stats(session: AsyncSession, board_id: int) -> Dict[int, dict]:
    """Статистика файлов по тредам доски: {thread_id: {поля}}.

    Дубли-ссылки (`duplicate_of_id`) не считаем: это тот же файл, повторно
    встреченный в другом треде/доске — иначе счётчики удваиваются.

    `media_today` — сколько видимых файлов треда добавлено с начала текущих
    отчётных суток (00:00 МСК): тот же период, что у счётчика на карточке раздела
    и в сводке на главной, поэтому «+N за сутки» в разделе и в тредах сходится.
    """
    start, end = reporting.period_bounds()
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
            func.count()
            .filter(
                Media.is_visible.is_(True),
                Media.created_at >= start,
                Media.created_at < end,
            )
            .label("media_today"),
        )
        .where(Media.board_id == board_id, Media.duplicate_of_id.is_(None))
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
            "media_today": int(r.media_today or 0),
        }
    return stats


async def _previews(
    session: AsyncSession,
    board_id: int,
    thread_ids: List[int],
) -> Dict[int, List[Media]]:
    """Первые PREVIEW_SIZE видимых файлов треда (с S3-ключом).

    Показываем **начало** треда: просмотр в лайтбоксе тоже идёт с начала (файлы
    упорядочены по `source_order`), поэтому превью совпадает с тем, что зритель
    увидит, кликнув по нему. Раньше здесь были последние файлы, и клик по
    картинке открывал совсем другое место треда.
    """
    if not thread_ids:
        return {}
    order = (Media.source_order.asc().nullslast(), Media.id.asc())
    rn = func.row_number().over(partition_by=Media.thread_id, order_by=order).label("rn")
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
        .order_by(*order)
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
    user: Optional[User] = None,
    board_premium: bool = False,
) -> List[ThreadOut]:
    """Собирает ThreadOut для списка тредов (+ статистика и превью).

    Превью премиум-файлов отдаются размытыми (thumb_blur) для пользователей
    без активной подписки. `is_premium` учитывает премиум доски (доска
    закрывает все свои треды), `locked` — премиум без подписки у зрителя.
    """
    if not threads:
        return []

    stats = await _media_stats(session, board_id)
    thread_ids = [t.thread_id for t in threads]
    previews = await _previews(session, board_id, thread_ids) if with_preview else {}

    out = []
    stale_at = stale_before()
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
            misses=int(t.misses or 0),
            missing_since=t.missing_since,
            pending_scan=bool(t.pending_scan),
            pending_reason=t.pending_reason,
            last_scan_attempt_at=t.last_scan_attempt_at,
            last_post_num=t.last_post_num,
            last_scan_errors=int(t.last_scan_errors or 0),
            last_scan_note=t.last_scan_note,
            # «Просрочен» считаем только для тредов в работе: остальные не парсим
            is_stale=bool(
                t.is_active
                and t.parse_enabled
                and (t.last_scanned_at is None or t.last_scanned_at < stale_at)
            ),
            parse_enabled=t.parse_enabled,
            is_visible=t.is_visible,
            is_premium=bool(t.is_premium or board_premium),
            locked=is_locked(t.is_premium or board_premium, user),
            media_total=s.get("media_total", 0),
            media_downloaded=s.get("media_downloaded", 0),
            media_in_s3=s.get("media_in_s3", 0),
            media_missing=s.get("media_missing", 0),
            media_visible=s.get("media_visible", 0),
            media_today=s.get("media_today", 0),
            preview=[],
        )

        if with_preview:
            media_items = previews.get(t.thread_id, [])
            if media_items:
                preview_out = [MediaOut.model_validate(m) for m in media_items]
                if s3 is not None:
                    sign_media_urls(preview_out, media_items, s3, user)
                if user is not None:
                    # Отметки зрителя видны и на превью в списке тредов.
                    await apply_user_flags(session, preview_out, user)
                item.preview = preview_out
        out.append(item)

    return out
