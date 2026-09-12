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
import time
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import hash_access_code
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
from src.api.threads_service import build_thread_outs, list_threads
from src.core.db import async_session_factory, get_session
from src.core.models import Board, Media, ThreadState
from src.core.redis_client import redis_client
from src.services.s3_storage import S3Storage
from src.services.thread_discovery import ThreadDiscovery, scan_key

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

logger = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9]{1,32}$")

# Полный список досок форума
FORUM_INDEX_URL = "https://2ch.hk/index.json"
FORUM_CACHE_TTL = 300  # 5 минут
_forum_cache: Dict[str, object] = {}


def _admin_out(board: Board, m: Optional[dict] = None) -> AdminBoardOut:
    m = m or {}
    return AdminBoardOut(
        id=board.id,
        slug=board.slug,
        title=board.title,
        description=board.description,
        media_count=int(m.get("media_visible", 0)),
        is_visible=board.is_visible,
        is_private=board.is_private,
        parse_enabled=board.parse_enabled,
        parse_mode=board.parse_mode,
        has_access_code=bool(board.access_code_hash),
        sort_order=board.sort_order,
        media_total=int(m.get("media_total", 0)),
        media_downloaded=int(m.get("media_downloaded", 0)),
        media_in_s3=int(m.get("media_in_s3", 0)),
        media_missing=int(m.get("media_missing", 0)),
        threads_active=int(m.get("threads_active", 0)),
        threads_parsing=int(m.get("threads_parsing", 0)),
        files_in_catalog=int(m.get("files_in_catalog", 0)),
        last_scan=m.get("last_scan"),
        views_total=int(m.get("views_total", 0)),
        downloads_total=int(m.get("downloads_total", 0)),
    )


async def _load_board(session: AsyncSession, slug: str) -> Board:
    result = await session.execute(select(Board).where(Board.slug == slug))
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


async def _all_boards_with_stats(session: AsyncSession) -> List[AdminBoardOut]:
    """Все доски (включая скрытые) с флагами и статистикой, в порядке очереди."""
    boards_result = await session.execute(
        select(Board).order_by(Board.sort_order, Board.slug)
    )
    boards = boards_result.scalars().all()
    stats, _totals = await collect_board_stats(session)
    return [_admin_out(b, stats.get(b.id)) for b in boards]


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
            is_private=board.is_private if board else False,
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
    """Обновляет флаги доски и/или код доступа.

    access_code: непустая строка — установить/сменить код;
    пустая строка — сбросить код (закроет приватный доступ).
    """
    board = await _load_board(session, slug)

    if payload.parse_enabled is not None:
        board.parse_enabled = payload.parse_enabled
    if payload.is_visible is not None:
        board.is_visible = payload.is_visible
    if payload.is_private is not None:
        board.is_private = payload.is_private
    if payload.parse_mode is not None:
        mode = payload.parse_mode.strip().lower()
        if mode not in ("all", "selected"):
            raise HTTPException(status_code=400, detail="parse_mode: ожидается all или selected")
        board.parse_mode = mode
    if payload.title is not None:
        title = payload.title.strip()
        board.title = title[:100] if title else board.slug

    if payload.access_code is not None:
        code = payload.access_code.strip()
        if code:
            board.access_code_hash = hash_access_code(code)
        else:
            board.access_code_hash = None  # явный сброс кода

    if board.is_private and not board.access_code_hash:
        raise HTTPException(
            status_code=400,
            detail="Для приватной доски нужно задать код доступа",
        )

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
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Треды доски со статистикой файлов (для drill-down в админке)."""
    board = await _load_board(session, slug)
    threads, total = await list_threads(session, board.id, page, per_page)
    items = await build_thread_outs(session, board.id, threads, with_preview=False)
    return ThreadListOut(items=items, page=page, per_page=per_page, total=total)


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
    """Обновляет флаги треда и/или код доступа к приватному треду.

    access_code: непустая строка — установить/сменить код; пустая строка — сбросить.
    """
    board = await _load_board(session, slug)
    thread = await _load_thread(session, board, thread_id)

    if payload.parse_enabled is not None:
        thread.parse_enabled = payload.parse_enabled
    if payload.is_visible is not None:
        thread.is_visible = payload.is_visible
    if payload.is_private is not None:
        thread.is_private = payload.is_private
    if payload.access_code is not None:
        code = payload.access_code.strip()
        thread.access_code_hash = hash_access_code(code) if code else None

    if thread.is_private and not thread.access_code_hash:
        raise HTTPException(
            status_code=400,
            detail="Для приватного треда нужно задать код доступа",
        )

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
    """Массово меняет флаги выбранных тредов доски (Парсить/Показывать/По коду)."""
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
        if payload.is_private is not None:
            thread.is_private = payload.is_private
    await session.commit()
    return {"ok": True, "updated": len(threads)}


# ───────────── Сканирование каталога доски («Загрузить треды») ─────────────


async def _run_board_scan(slug: str) -> None:
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

            async def on_progress(done: int, total: int) -> None:
                await redis_client.set(
                    key,
                    json.dumps({"status": "running", "total": total, "done": done}),
                    ex=600,
                )

            result = await ThreadDiscovery(session).discover(board, on_progress=on_progress)

        await redis_client.set(
            key,
            json.dumps(
                {
                    "status": "done",
                    "total": result["total"],
                    "done": result["total"],
                    "created": result["created"],
                    "updated": result["updated"],
                }
            ),
            ex=600,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("scan failed for /%s", slug)
        await redis_client.set(key, json.dumps({"status": "error", "error": str(e)}), ex=600)


@router.post("/boards/{slug}/scan")
async def scan_board(slug: str, _=Depends(verify_admin)):
    """Запускает сканирование каталога доски (создание/обновление тредов)."""
    current = await redis_client.get(scan_key(slug))
    if current:
        data = json.loads(current)
        if data.get("status") == "running":
            return data

    await redis_client.set(
        scan_key(slug), json.dumps({"status": "running", "total": 0, "done": 0}), ex=600
    )
    asyncio.create_task(_run_board_scan(slug))
    return {"status": "running", "total": 0, "done": 0}


@router.get("/boards/{slug}/scan/status")
async def scan_board_status(slug: str, _=Depends(verify_admin)):
    """Текущий прогресс сканирования каталога доски."""
    current = await redis_client.get(scan_key(slug))
    if not current:
        return {"status": "idle", "total": 0, "done": 0}
    return json.loads(current)


