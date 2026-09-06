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
import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import hash_access_code
from src.api.deps import verify_admin
from src.api.schemas import (
    AdminBoardOut,
    AdminOverview,
    BoardCreate,
    BoardUpdate,
    ForumBoardOut,
    SystemTotals,
    ThreadListOut,
    ToggleResult,
)
from src.api.stats_service import collect_board_stats
from src.api.threads_service import build_thread_outs, list_threads
from src.core.db import get_session
from src.core.models import Board, Media

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
        has_access_code=bool(board.access_code_hash),
        media_total=int(m.get("media_total", 0)),
        media_downloaded=int(m.get("media_downloaded", 0)),
        media_in_b2=int(m.get("media_in_b2", 0)),
        media_missing=int(m.get("media_missing", 0)),
        threads_active=int(m.get("threads_active", 0)),
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
    """Все доски (включая скрытые) с флагами и статистикой."""
    boards_result = await session.execute(
        select(Board).order_by(Board.slug)
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
        totals.media_in_b2 += b.media_in_b2
        totals.media_downloaded += b.media_downloaded
        totals.media_missing += b.media_missing
        totals.threads_active += b.threads_active
        totals.files_in_catalog += b.files_in_catalog
        totals.views_total += b.views_total
        totals.downloads_total += b.downloads_total

    return AdminOverview(generated_at=datetime.utcnow(), totals=totals, boards=boards)


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
            media_in_b2=int(s.get("media_in_b2", 0)),
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

    board = Board(slug=slug, title=slug, parse_enabled=False, is_visible=False)
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


