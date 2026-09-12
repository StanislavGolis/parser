# src/api/routes/admin.py
"""Админ-эндпоинты (защищены ADMIN_TOKEN): центр управления контентом.

- GET  /admin/overview              — сводка по всем доскам + общие цифры (для polling)
- GET  /admin/forum                 — все доски форума (index.json) + сопоставление с БД
- GET  /admin/boards                — наши доски с флагами и статистикой
- POST /admin/boards                — создать доску по slug
- PATCH /admin/boards/{slug}        — обновить флаги и код доступа
- GET  /admin/boards/{slug}/threads — треды доски со статистикой
- POST /admin/boards/{slug}/toggle  — скрыть/показать доску
- POST /admin/media/{id}/toggle     — скрыть/показать файл
"""
import asyncio
import json
import logging
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_s3, verify_admin
from src.api.schemas import (
    AdminBoardOut,
    AdminOverview,
    BoardCreate,
    BoardReorder,
    BoardUpdate,
    ForumBoardOut,
    ResetResult,
    SystemTotals,
    ThreadBulkUpdate,
    ThreadListOut,
    ThreadOut,
    ThreadUpdate,
    ToggleResult,
)
from src.api.stats_service import collect_board_stats
from src.api.threads_service import (
    build_thread_outs,
    list_threads,
    thread_catalog_totals,
    thread_state_counts,
)
from src.core.db import async_session_factory, get_session
from src.core.models import Board, Media, ThreadState
from src.core.redis_client import redis_client
from src.services.catalog_health import catalog_errors, mark_catalog_error, mark_catalog_ok
from src.services.s3_storage import S3Storage
from src.services.derivatives import generate_and_upload
from src.services.premium import (
    sync_board_media_premium,
    sync_thread_media_premium,
    sync_threads_media_premium,
)
from src.services.thread_discovery import ThreadDiscovery, scan_key

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

logger = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9]{1,32}$")

# Полный список досок форума
FORUM_INDEX_URL = "https://2ch.hk/index.json"
FORUM_CATALOG_URL = "https://2ch.hk/{slug}/catalog.json"
FORUM_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FORUM_CACHE_TTL = 300  # 5 минут
_forum_cache: Dict[str, object] = {}


def _admin_out(
    board: Board,
    m: Optional[dict] = None,
    catalog_error: Optional[str] = None,
) -> AdminBoardOut:
    m = m or {}
    return AdminBoardOut(
        id=board.id,
        slug=board.slug,
        title=board.title,
        description=board.description,
        media_count=int(m.get("media_visible", 0)),
        is_visible=board.is_visible,
        is_premium=board.is_premium,
        parse_enabled=board.parse_enabled,
        parse_mode=board.parse_mode,
        sort_order=board.sort_order,
        media_total=int(m.get("media_total", 0)),
        media_downloaded=int(m.get("media_downloaded", 0)),
        media_in_s3=int(m.get("media_in_s3", 0)),
        media_missing=int(m.get("media_missing", 0)),
        threads_active=int(m.get("threads_active", 0)),
        threads_parsing=int(m.get("threads_parsing", 0)),
        files_in_catalog=int(m.get("files_in_catalog", 0)),
        threads_posts_total=int(m.get("threads_posts_total", 0)),
        threads_views_total=int(m.get("threads_views_total", 0)),
        last_scan=m.get("last_scan"),
        views_total=int(m.get("views_total", 0)),
        downloads_total=int(m.get("downloads_total", 0)),
        catalog_error=catalog_error,
    )


async def _load_board(session: AsyncSession, slug: str) -> Board:
    result = await session.execute(select(Board).where(Board.slug == slug))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


async def _all_boards_with_stats(session: AsyncSession) -> List[AdminBoardOut]:
    """Все доски (включая скрытые) с флагами и статистикой, в порядке очереди.

    Дополнительно отдаём `catalog_error` — причину, по которой каталог доски не
    читается (2ch отдаёт 500 «Not found» у удалённых разделов, а index.json их
    всё ещё перечисляет). Карточка доски показывает это бейджем.
    """
    boards_result = await session.execute(
        select(Board).order_by(Board.sort_order, Board.slug)
    )
    boards = boards_result.scalars().all()
    stats, _totals = await collect_board_stats(session)
    errors = await catalog_errors([b.slug for b in boards])
    return [_admin_out(b, stats.get(b.id), errors.get(b.slug)) for b in boards]


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Сводка по всем доскам + итоги системы (клиент опрашивает polling'ом)."""
    boards = await _all_boards_with_stats(session)

    totals = SystemTotals(boards_total=len(boards))
    totals.boards_parsed = sum(1 for b in boards if b.parse_enabled)
    for b in boards:
        totals.media_total += b.media_total
        totals.media_in_s3 += b.media_in_s3
        totals.media_downloaded += b.media_downloaded
        totals.media_missing += b.media_missing
        totals.threads_active += b.threads_active
        totals.files_in_catalog += b.files_in_catalog
        totals.views_total += b.views_total
        totals.downloads_total += b.downloads_total

    # Статус парсера (демон пишет heartbeat в Redis; включение — кнопка в админке)
    parser_up = bool(await redis_client.exists("parser:up"))
    parser_enabled = (await redis_client.get("parser:enabled")) == "1"
    parser_current: Optional[str] = await redis_client.get("parser:current_board")
    parser_alive = bool(await redis_client.exists("parser:alive"))

    return AdminOverview(
        generated_at=datetime.utcnow(),
        totals=totals,
        boards=boards,
        parser_up=parser_up,
        parser_enabled=parser_enabled,
        parser_alive=parser_alive,
        parser_current_board=parser_current,
    )


@router.post("/parser/start")
async def parser_start(
    _=Depends(verify_admin),
):
    """Запускает парсинг: демон парсера подхватит флаг в течение ~5 секунд."""
    await redis_client.set("parser:enabled", "1")
    return {"ok": True, "enabled": True}


@router.post("/parser/stop")
async def parser_stop(
    _=Depends(verify_admin),
):
    """Останавливает парсинг (демон остаётся запущенным и ждёт команды)."""
    await redis_client.delete("parser:enabled")
    await redis_client.delete("parser:alive")
    await redis_client.delete("parser:current_board")
    return {"ok": True, "enabled": False}


async def _fetch_forum_boards() -> List[dict]:
    """Список досок форума из 2ch index.json (с 5-минутным кэшем)."""
    now = time.time()
    cached = _forum_cache.get("boards")
    if cached and now - float(_forum_cache.get("ts", 0)) < FORUM_CACHE_TTL:
        return cached  # type: ignore[return-value]

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            FORUM_INDEX_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ParserBot/1.0)"},
        )
        resp.raise_for_status()
        data = resp.json()

    boards = [b for b in (data.get("boards") or []) if b.get("id")]
    _forum_cache["boards"] = boards
    _forum_cache["ts"] = now
    return boards


async def _probe_board_catalog(slug: str) -> tuple[bool, str]:
    """Проверяет, что каталог раздела читается (раздел не удалён с 2ch).

    2ch отдаёт `500 Not found` для удалённых разделов, хотя `index.json` их ещё
    перечисляет (хентай-доски `/h`, `/ho`, `/hc`), поэтому проверяем именно
    каталог и возвращаем человеческую причину.
    """
    url = FORUM_CATALOG_URL.format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": FORUM_UA})
    except Exception as exc:  # noqa: BLE001
        return False, f"не удалось проверить каталог: {exc}"

    if resp.status_code == 200:
        try:
            threads = (resp.json() or {}).get("threads") or []
        except Exception:  # noqa: BLE001
            return False, "форум вернул не JSON"
        if not threads:
            return False, "каталог раздела пуст"
        return True, ""
    if resp.status_code == 404:
        return False, "раздел не найден на форуме (404)"
    if resp.status_code >= 500:
        return False, f"форум ответил {resp.status_code} — раздел удалён или недоступен"
    return False, f"форум ответил {resp.status_code}"


def _scan_error_text(slug: str, exc: Exception) -> str:
    """Человеческий текст ошибки сканирования вместо сырого текста aiohttp."""
    if isinstance(exc, aiohttp.ClientResponseError):
        if exc.status == 404:
            return f"Раздел /{slug} не найден на 2ch (404)"
        if exc.status >= 500:
            return (
                f"2ch ответил {exc.status} на каталог /{slug}: раздел удалён или "
                f"недоступен (проверьте slug)"
            )
        return f"2ch ответил {exc.status} на каталог /{slug}"
    if isinstance(exc, asyncio.TimeoutError):
        return "2ch не ответил вовремя (таймаут) — попробуйте ещё раз"
    if isinstance(exc, aiohttp.ClientError):
        return f"Не удалось связаться с 2ch: {exc}"
    return str(exc) or exc.__class__.__name__


@router.get("/forum", response_model=list[ForumBoardOut])
async def admin_forum_boards(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Все доски форума (из index.json двача) с признаком «есть в нашей системе»."""
    try:
        forum_boards = await _fetch_forum_boards()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось получить index.json двача: %s", exc)
        raise HTTPException(status_code=502, detail="Не удалось получить список досок форума")

    db_result = await session.execute(select(Board))
    db_boards = {b.slug: b for b in db_result.scalars().all()}
    stats, _ = await collect_board_stats(session)

    out = []
    for fb in forum_boards:
        slug = str(fb["id"])
        board = db_boards.get(slug)
        s = stats.get(board.id, {}) if board else {}
        out.append(ForumBoardOut(
            slug=slug,
            name=fb.get("name"),
            category=fb.get("category"),
            threads_on_forum=int(fb.get("threads") or 0),
            in_db=board is not None,
            parse_enabled=board.parse_enabled if board else False,
            is_visible=board.is_visible if board else False,
            is_premium=board.is_premium if board else False,
            media_total=int(s.get("media_total", 0)),
            media_in_s3=int(s.get("media_in_s3", 0)),
            threads_active=int(s.get("threads_active", 0)),
        ))
    return out


@router.get("/boards", response_model=list[AdminBoardOut])
async def list_admin_boards(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Наши доски (включая скрытые) с флагами и статистикой."""
    return await _all_boards_with_stats(session)


@router.post("/boards", response_model=AdminBoardOut)
async def create_board(
    payload: BoardCreate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Создаёт доску по слагу (которой ещё нет в нашей системе)."""
    slug = (payload.slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug (a-z0-9, до 32 символов)")

    existing = await session.execute(select(Board).where(Board.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Board already exists")

    # Раздел должен реально существовать на форуме: index.json перечисляет и
    # удалённые доски (у них каталог отдаёт 500), а парсить их нельзя.
    ok, reason = await _probe_board_catalog(slug)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Раздел /{slug} недоступен на 2ch: {reason}",
        )

    max_order = (await session.execute(select(func.max(Board.sort_order)))).scalar() or 0
    name = (payload.name or "").strip()
    board = Board(
        slug=slug,
        title=name[:100] or slug,
        parse_enabled=False,
        is_visible=False,
        sort_order=int(max_order) + 1,
    )
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return _admin_out(board)


@router.patch("/boards/{slug}", response_model=AdminBoardOut)
async def update_board(
    slug: str,
    payload: BoardUpdate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Обновляет флаги доски (в т.ч. премиум-доступ) и название.

    Включение is_premium закрывает весь контент доски: всем её файлам
    проставляется премиум-признак (media.is_premium).
    """
    board = await _load_board(session, slug)

    if payload.parse_enabled is not None:
        board.parse_enabled = payload.parse_enabled
    if payload.is_visible is not None:
        board.is_visible = payload.is_visible
    if payload.parse_mode is not None:
        mode = payload.parse_mode.strip().lower()
        if mode not in ("all", "selected"):
            raise HTTPException(status_code=400, detail="parse_mode: ожидается all или selected")
        board.parse_mode = mode
    if payload.title is not None:
        title = payload.title.strip()
        board.title = title[:100] if title else board.slug

    if payload.is_premium is not None and payload.is_premium != board.is_premium:
        board.is_premium = payload.is_premium
        await sync_board_media_premium(session, board)

    await session.commit()

    stats, _ = await collect_board_stats(session)
    return _admin_out(board, stats.get(board.id))


@router.post("/boards/reorder")
async def reorder_boards(
    payload: BoardReorder,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Задаёт порядок очереди парсинга (sort_order по порядку slugs)."""
    result = await session.execute(select(Board))
    boards = {b.slug: b for b in result.scalars().all()}

    # Доски из списка — в заданном порядке, остальные — в конец (по алфавиту)
    extra = sorted(set(boards) - set(payload.slugs))
    ordered_slugs = payload.slugs + extra
    for idx, slug in enumerate(ordered_slugs):
        board = boards.get(slug)
        if board is not None:
            board.sort_order = idx
    await session.commit()
    return {"ok": True, "count": len(ordered_slugs)}


@router.delete("/boards/{slug}", response_model=ResetResult)
async def delete_board(
    slug: str,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Удаляет раздел: записи БД + все его объекты в S3."""
    board = await _load_board(session, slug)

    # 1) Все ключи раздела: из БД (точный список media.s3_key) + по префиксу
    #    (осиротевшие объекты, которые могли остаться от сбоев).
    db_keys = [
        k
        for k in (
            await session.execute(
                select(Media.s3_key).where(
                    Media.board_id == board.id, Media.s3_key.isnot(None)
                )
            )
        ).scalars().all()
        if k
    ]
    prefix = f"board_{board.id}/"
    prefixed = await s3.list_keys(prefix) or []
    keys = list(dict.fromkeys(db_keys + list(prefixed)))

    deleted_objects = 0
    if keys:
        await s3.delete_keys(keys)
        deleted_objects = len(keys)

    # 2) Записи БД (каскад по ON DELETE CASCADE)
    await session.delete(board)
    await session.commit()
    return ResetResult(deleted_boards=1, deleted_objects=deleted_objects)


@router.post("/cleanup-storage")
async def cleanup_storage_orphans(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Удаляет из S3 объекты, которых нет в БД (мусор после сбоев/прерываний)."""
    keys = await s3.list_keys("")
    if not keys:
        return {"total": 0, "orphans": 0, "deleted": 0}

    known = {
        k
        for k in (
            await session.execute(select(Media.s3_key).where(Media.s3_key.isnot(None)))
        ).scalars().all()
        if k
    }
    orphans = [k for k in keys if k not in known]
    if orphans:
        await s3.delete_keys(orphans)
    return {"total": len(keys), "orphans": len(orphans), "deleted": len(orphans)}


@router.delete("/reset", response_model=ResetResult)
async def reset_all(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Полный сброс: удаляет все доски/медиа из БД и все объекты из S3."""
    # 0) Сначала останавливаем парсер (прервётся на границе текущего треда),
    #    иначе TRUNCATE будет ждать его транзакции.
    await redis_client.delete("parser:enabled")
    await redis_client.delete("parser:alive")
    await redis_client.delete("parser:current_board")

    # 1) Объекты S3
    deleted_objects = 0
    keys = await s3.list_keys("")
    if keys:
        await s3.delete_keys(keys)
        deleted_objects = len(keys)

    # 2) Данные БД (каскадно: media/threads/stats)
    await session.execute(text("TRUNCATE TABLE download_stats, view_stats, media, threads_state, boards RESTART IDENTITY CASCADE"))
    await session.commit()
    return ResetResult(deleted_objects=deleted_objects)


@router.get("/boards/{slug}/threads", response_model=ThreadListOut)
async def admin_board_threads(
    slug: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    state: str = Query("all", pattern="^(all|active|parsing|visible|premium|off|dead|stale|queued|lagging)$"),
    q: Optional[str] = Query(None, max_length=120),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Треды доски со статистикой; «в работе» — сверху, с фильтром и поиском."""
    board = await _load_board(session, slug)
    threads, total = await list_threads(
        session, board.id, page, per_page, state=state, q=q, admin_order=True
    )
    items = await build_thread_outs(session, board.id, threads, with_preview=False)
    totals = await thread_catalog_totals(session, board.id)
    counts = await thread_state_counts(session, board.id)
    return ThreadListOut(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        counts=counts,
        **totals,
    )


@router.post("/boards/{slug}/toggle", response_model=ToggleResult)
async def toggle_board(
    slug: str,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Скрыть/показать доску (обратная совместимость)."""
    board = await _load_board(session, slug)
    board.is_visible = not board.is_visible
    await session.commit()
    return ToggleResult(id=board.id, is_visible=board.is_visible)


@router.post("/media/{media_id}/toggle", response_model=ToggleResult)
async def toggle_media(
    media_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Скрыть/показать файл."""
    media = await session.get(Media, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    media.is_visible = not media.is_visible
    await session.commit()
    return ToggleResult(id=media.id, is_visible=media.is_visible)


async def _load_thread(session: AsyncSession, board: Board, thread_id: int) -> ThreadState:
    result = await session.execute(
        select(ThreadState).where(
            ThreadState.board_id == board.id,
            ThreadState.thread_id == thread_id,
        )
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.patch("/boards/{slug}/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(
    slug: str,
    thread_id: int,
    payload: ThreadUpdate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Обновляет флаги треда: парсинг, публикация, премиум-доступ.

    Премиум треда синхронизируется с файлами (media.is_premium); если
    премиум включён на доске, тред остаётся премиальным при любом значении.
    """
    board = await _load_board(session, slug)
    thread = await _load_thread(session, board, thread_id)

    if payload.parse_enabled is not None:
        thread.parse_enabled = payload.parse_enabled
    if payload.is_visible is not None:
        thread.is_visible = payload.is_visible
    if payload.is_premium is not None and payload.is_premium != thread.is_premium:
        thread.is_premium = payload.is_premium
        await sync_thread_media_premium(session, board, thread)
    if payload.restore:
        # «Вернуть в обход»: тред выпал из каталога доски — возвращаем в работу
        # и сбрасываем промахи (тред снова попадает в публичные списки; до
        # следующего отключения пройдёт DEAD_THREAD_AFTER_MISSES проходов).
        thread.is_active = True
        thread.misses = 0
        thread.missing_since = None
    if payload.requeue:
        # «В очередь»: ручная постановка на докачку (приоритет — как у свежих).
        # Сработает, если у треда включён «Парсить» — иначе парсер в тред не пойдёт.
        thread.pending_scan = True
        thread.pending_reason = "вручную"

    await session.commit()
    items = await build_thread_outs(session, board.id, [thread], with_preview=False)
    return items[0]


@router.post("/boards/{slug}/threads/bulk")
async def bulk_update_threads(
    slug: str,
    payload: ThreadBulkUpdate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Массово меняет флаги выбранных тредов доски (Парсить/На сайте/Премиум)."""
    board = await _load_board(session, slug)
    if not payload.thread_ids:
        return {"ok": True, "updated": 0}

    result = await session.execute(
        select(ThreadState).where(
            ThreadState.board_id == board.id,
            ThreadState.thread_id.in_(payload.thread_ids),
        )
    )
    threads = result.scalars().all()
    for thread in threads:
        if payload.parse_enabled is not None:
            thread.parse_enabled = payload.parse_enabled
        if payload.is_visible is not None:
            thread.is_visible = payload.is_visible
        if payload.is_premium is not None:
            thread.is_premium = payload.is_premium
        if payload.restore:
            thread.is_active = True
            thread.misses = 0
            thread.missing_since = None
        if payload.requeue:
            thread.pending_scan = True
            thread.pending_reason = "вручную"
    if payload.is_premium is not None:
        await sync_threads_media_premium(session, board, payload.thread_ids)
    await session.commit()
    return {"ok": True, "updated": len(threads)}


# ───────────── Сканирование каталога доски («Загрузить треды») ─────────────


async def _run_board_scan(slug: str, deep: bool = False) -> None:
    """Фоновое сканирование каталога доски с записью прогресса в Redis."""
    key = scan_key(slug)
    try:
        async with async_session_factory() as session:
            board = (
                await session.execute(select(Board).where(Board.slug == slug))
            ).scalar_one_or_none()
            if not board:
                await redis_client.set(
                    key, json.dumps({"status": "error", "error": "Board not found"}), ex=600
                )
                return

            async def on_progress(phase: str, done: int, total: int) -> None:
                await redis_client.set(
                    key,
                    json.dumps({"status": "running", "phase": phase, "total": total, "done": done}),
                    ex=600,
                )

            result = await ThreadDiscovery(session).discover(
                board, on_progress=on_progress, deep=deep
            )
        await mark_catalog_ok(slug)

        await redis_client.set(
            key,
            json.dumps(
                {
                    "status": "done",
                    "phase": "files" if deep else "catalog",
                    "total": result["total"],
                    "done": result["total"],
                    "created": result["created"],
                    "updated": result["updated"],
                    "files_total": result.get("files_total", 0),
                }
            ),
            ex=600,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("scan failed for /%s", slug)
        text = _scan_error_text(slug, e)
        await mark_catalog_error(slug, text)
        await redis_client.set(key, json.dumps({"status": "error", "error": text}), ex=600)


@router.post("/boards/{slug}/scan")
async def scan_board(slug: str, deep: bool = Query(False), _=Depends(verify_admin)):
    """Запускает сканирование каталога доски (создание/обновление тредов).

    `deep=true` — дополнительно читает res/{id}.json каждого треда и считает
    число файлов (медиа НЕ скачивается): «файлов: N» видно до парсинга.
    """
    current = await redis_client.get(scan_key(slug))
    if current:
        data = json.loads(current)
        if data.get("status") == "running":
            return data

    await redis_client.set(
        scan_key(slug),
        json.dumps({"status": "running", "phase": "catalog", "total": 0, "done": 0}),
        ex=600,
    )
    asyncio.create_task(_run_board_scan(slug, deep))
    return {"status": "running", "phase": "catalog", "total": 0, "done": 0}


@router.get("/boards/{slug}/scan/status")
async def scan_board_status(slug: str, _=Depends(verify_admin)):
    """Текущий прогресс сканирования каталога доски."""
    current = await redis_client.get(scan_key(slug))
    if not current:
        return {"status": "idle", "total": 0, "done": 0}
    return json.loads(current)


# ─────────── Бэкфилл деривативов (оптимизация уже скачанных файлов) ───────────

BACKFILL_KEY = "backfill:variants"
# Размер пачки по умолчанию: сколько файлов проходим между записями прогресса
BACKFILL_BATCH_DEFAULT = 200
# Предохранитель: максимум пачек за один прогон (антибесконечный цикл)
BACKFILL_MAX_BATCHES = 500


def _variant_candidates_clause():
    """«Файл в S3, но нет размытого превью» — кто нужен бэкфиллу."""
    return and_(
        Media.s3_key.isnot(None),
        or_(Media.variants.is_(None), Media.variants["thumb_blur"].is_(None)),
    )


async def _count_variant_candidates(session: AsyncSession) -> int:
    """Сколько файлов ещё ждут оптимизации (очередь бэкфилла)."""
    total = (
        await session.execute(
            select(func.count()).select_from(Media).where(_variant_candidates_clause())
        )
    ).scalar()
    return int(total or 0)


async def _backfill_progress(payload: dict, *, ex: int = 7200) -> None:
    """Пишет статус бэкфилла в Redis (его читает админка при опросе)."""
    await redis_client.set(BACKFILL_KEY, json.dumps(payload), ex=ex)


async def _run_variants_backfill(batch_size: int) -> None:
    """Проходит очередь оптимизации целиком, пачками по `batch_size` файлов.

    Идёт курсором по возрастанию `id` (файл обрабатывается один раз за прогон),
    поэтому «застрявшие» (битый файл, ошибка S3) не зацикливают процесс: они
    остаются кандидатами и видны в `remaining`.
    """
    s3 = S3Storage()
    if not s3.is_configured:
        await _backfill_progress({"status": "error", "error": "Storage is not configured"}, ex=600)
        return

    processed = errors = done = 0
    try:
        async with async_session_factory() as session:
            total = await _count_variant_candidates(session)
            if total == 0:
                await _backfill_progress(
                    {
                        "status": "done",
                        "total": 0,
                        "done": 0,
                        "remaining": 0,
                        "processed": 0,
                        "errors": 0,
                        "batch_size": batch_size,
                    },
                    ex=600,
                )
                return

            def progress(done_count: int, remaining: int, status: str = "running") -> dict:
                return {
                    "status": status,
                    "total": total,
                    "done": done_count,
                    "remaining": remaining,
                    "processed": processed,
                    "errors": errors,
                    "batch_size": batch_size,
                }

            await _backfill_progress(progress(0, total))

            cursor = 0
            batches = 0
            with tempfile.TemporaryDirectory() as tmp:
                while batches < BACKFILL_MAX_BATCHES:
                    rows = (
                        await session.execute(
                            select(Media)
                            .where(_variant_candidates_clause(), Media.id > cursor)
                            .order_by(Media.id)
                            .limit(batch_size)
                        )
                    ).scalars().all()
                    if not rows:
                        break

                    batches += 1
                    cursor = rows[-1].id
                    for media in rows:
                        try:
                            orig = Path(tmp) / f"orig_{media.id}"
                            if await s3.download_to_file(media.s3_key, orig):
                                prefix = (media.file_hash or "")[:12] or str(media.id)
                                base = f"board_{media.board_id}/thread_{media.thread_id}/{prefix}"
                                variants, duration = await generate_and_upload(
                                    s3,
                                    base_key=base,
                                    media_type=media.media_type,
                                    local_path=orig,
                                )
                                if variants:
                                    media.variants = variants
                                    if duration:
                                        media.duration_seconds = duration
                                    processed += 1
                                else:
                                    errors += 1
                            else:
                                errors += 1
                            orig.unlink(missing_ok=True)
                        except Exception:  # noqa: BLE001
                            errors += 1

                        done += 1
                        if done % 5 == 0:
                            await session.commit()
                            # Внутри пачки остаток оцениваем линейно (точный пересчёт — раз в пачку)
                            await _backfill_progress(progress(done, max(total - done, 0)))

                    await session.commit()
                    # Точный остаток после пачки: часть файлов могла не поддаться
                    remaining = await _count_variant_candidates(session)
                    await _backfill_progress(progress(done, remaining))
                    if len(rows) < batch_size:
                        break

            remaining = await _count_variant_candidates(session)

        await _backfill_progress(
            {
                "status": "done",
                "total": max(total, done),
                "done": done,
                "remaining": remaining,
                "processed": processed,
                "errors": errors,
                "batch_size": batch_size,
            },
            ex=600,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("variants backfill failed")
        await _backfill_progress({"status": "error", "error": str(e)}, ex=600)


@router.post("/backfill-variants")
async def backfill_variants(
    limit: int = Query(BACKFILL_BATCH_DEFAULT, ge=1, le=5000), _=Depends(verify_admin)
):
    """Оптимизация уже скачанных файлов: один запуск проходит всю очередь.

    `limit` — размер пачки (сколько файлов проходим между записями прогресса),
    а не общий объём работы: бэкенд идёт по очереди пачками, пока не кончатся
    кандидаты. Пока прогон идёт, повторный вызов возвращает текущий прогресс.
    """
    current = await redis_client.get(BACKFILL_KEY)
    if current and json.loads(current).get("status") == "running":
        return json.loads(current)

    async with async_session_factory() as session:
        total = await _count_variant_candidates(session)

    payload = {
        "status": "running",
        "total": total,
        "done": 0,
        "remaining": total,
        "processed": 0,
        "errors": 0,
        "batch_size": limit,
    }
    await _backfill_progress(payload)
    asyncio.create_task(_run_variants_backfill(limit))
    return payload


@router.get("/backfill-variants/status")
async def backfill_variants_status(_=Depends(verify_admin)):
    """Прогресс бэкфилла: сколько обработано из очереди и сколько осталось."""
    current = await redis_client.get(BACKFILL_KEY)
    if not current:
        return {
            "status": "idle",
            "total": 0,
            "done": 0,
            "remaining": 0,
            "processed": 0,
            "errors": 0,
            "batch_size": 0,
        }
    return json.loads(current)


# ───────────── Статус парсера (частый опрос: живость + прогресс) ─────────────


@router.get("/parser/status")
async def parser_status(_=Depends(verify_admin)):
    """Лёгкий статус парсера: живость и прогресс по текущему треду.

    Рассчитан на частый опрос (раз в секунду) из админки.
    """
    up = (await redis_client.get("parser:up")) == "1"
    enabled = (await redis_client.get("parser:enabled")) == "1"
    alive = (await redis_client.get("parser:alive")) == "1"
    current_board = await redis_client.get("parser:current_board")

    progress = None
    stall_seconds = None
    raw = await redis_client.get("parser:progress")
    if raw:
        try:
            progress = json.loads(raw)
        except Exception:
            progress = None
    if progress and progress.get("updated_at"):
        try:
            updated = datetime.fromisoformat(progress["updated_at"])
            stall_seconds = max(0, int((datetime.utcnow() - updated).total_seconds()))
        except Exception:
            stall_seconds = None

    return {
        "up": up,
        "enabled": enabled,
        "alive": alive,
        "current_board": current_board,
        "progress": progress,
        "stall_seconds": stall_seconds,
    }


