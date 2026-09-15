# src/api/routes/admin.py
"""Админ-эндпоинты (защищены ADMIN_TOKEN): центр управления контентом.

- GET  /admin/overview              — сводка по всем доскам + общие цифры (для polling)
- GET  /admin/sources/{code}/catalog — разделы, которые предлагает источник (аналог «досок форума»)
- GET  /admin/boards                — наши доски с флагами и статистикой
- POST /admin/boards                — создать доску по slug
- PATCH /admin/boards/{slug}        — обновить флаги и код доступа
- GET  /admin/boards/{slug}/threads — треды доски со статистикой
- POST /admin/boards/{slug}/scan    — прочитать каталог раздела («треды» без файлов)
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
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, asset_url, visible_thread_clause
from src.api.deps import get_s3, verify_admin
from src.api.schemas import (
    AdminBoardOut,
    AdminOverview,
    BoardCoverCandidate,
    BoardCreate,
    BoardReorder,
    BoardUpdate,
    ResetResult,
    SourceBoardOut,
    SourceUpdate,
    SystemTotals,
    ThreadBulkUpdate,
    ThreadDeleteRequest,
    ThreadDeleteResult,
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
from src.core.config import settings
from src.core.models import Board, Media, Source, ThreadState
from src.core.redis_client import redis_client
from src.parsers import build_adapter
from src.services.analytics import record_audit
from src.services.catalog_health import catalog_errors, mark_catalog_error, mark_catalog_ok
from src.services import daily_report, reporting
from src.services.media_cache import get_media_cache
from src.services.media_validator import MediaValidator
from src.services.s3_storage import S3Storage
from src.services import sources as sources_service
from src.services.derivatives import generate_and_upload
from src.services.premium import (
    sync_board_media_premium,
    sync_thread_media_premium,
    sync_threads_media_premium,
)
from src.services.scan_planner import ScanPlanner
from src.services.thread_discovery import scan_key

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

logger = logging.getLogger(__name__)

# Слаг раздела: латиница/цифры и дефис (у сайтов разделы — короткие категории)
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")

# Проверка каталога доски 2ch при добавлении раздела вручную
FORUM_CATALOG_URL = "https://2ch.hk/{slug}/catalog.json"
FORUM_LABEL = "2ch"
FORUM_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


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
        source_id=board.source_id,
        cover_media_ids=list(board.cover_media_ids or []),
        media_total=int(m.get("media_total", 0)),
        media_downloaded=int(m.get("media_downloaded", 0)),
        media_in_s3=int(m.get("media_in_s3", 0)),
        media_missing=int(m.get("media_missing", 0)),
        threads_active=int(m.get("threads_active", 0)),
        threads_parsing=int(m.get("threads_parsing", 0)),
        threads_pending=int(m.get("threads_pending", 0)),
        threads_dead=int(m.get("threads_dead", 0)),
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


# Сколько плиток в мозаике карточки раздела (как COVER_THUMBS в каталоге)
COVER_LIMIT = 4


async def _resolve_cover_ids(
    session: AsyncSession,
    board: Board,
    media_ids: List[int],
) -> Optional[list]:
    """Проверяет ручные превью раздела и возвращает id для хранения.

    Файлы должны существовать и принадлежать этому же разделу; плиток — не
    больше четырёх. Пустой список означает «вернуть автоматический выбор» (NULL).
    """
    ids: List[int] = []
    for mid in media_ids:
        if mid not in ids:
            ids.append(mid)
    if len(ids) > COVER_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Превью раздела: не больше {COVER_LIMIT} файлов",
        )
    if ids:
        rows = await session.execute(
            select(Media.id).where(Media.id.in_(ids), Media.board_id == board.id)
        )
        found = {row[0] for row in rows.all()}
        missing = [mid for mid in ids if mid not in found]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Превью раздела: файлы не из /{board.slug}: {missing}",
            )
    return ids or None


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
        totals.threads_pending += b.threads_pending
        totals.threads_dead += b.threads_dead
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


async def _dvach_board_slugs() -> set:
    """Слаги досок 2ch из `index.json` (через адаптер — один источник правды).

    Нужны, чтобы отличить «доска есть в списке форума, но закрыта» от «такой
    доски на форуме нет» при добавлении раздела вручную.
    """
    adapter = build_adapter(sources_service.DEFAULT_SOURCE_CODE)
    try:
        async with adapter:
            nodes = await adapter.fetch_boards()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось получить index.json двача: %s", exc)
        return set()
    return {node.slug for node in (nodes or [])}


async def _probe_board_catalog(slug: str) -> tuple:
    """Проверяет, что каталог раздела читается (раздел не удалён с 2ch).

    Возвращает `(ok, reason, in_index)`: `in_index` — есть ли слаг в `index.json`.
    2ch отдаёт `500 Not found` для разделов, которые сам же перечисляет в
    `index.json`: это удалённые доски и «взрослые» разделы, закрытые без pass
    (`/h`, `/ho`, `/hc`, `/e`, `/hg`) — парсить их нельзя, но причина разная,
    поэтому в тексте ошибки это различаем.
    """
    url = FORUM_CATALOG_URL.format(slug=slug)
    in_index = slug in await _dvach_board_slugs()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": FORUM_UA})
    except Exception as exc:  # noqa: BLE001
        return False, f"не удалось проверить каталог: {exc}", in_index

    if resp.status_code == 200:
        try:
            threads = (resp.json() or {}).get("threads") or []
        except Exception:  # noqa: BLE001
            return False, "форум вернул не JSON", in_index
        if not threads:
            return False, "в каталоге раздела нет тредов", in_index
        return True, "", in_index

    if resp.status_code == 404:
        reason = "раздел не найден на форуме (404)"
    elif resp.status_code >= 500:
        reason = (
            "форум ответил 500 «Not found»: раздел закрыт (взрослый раздел без pass) "
            "или удалён"
            if in_index
            else "форум ответил 500 — раздела нет на форуме"
        )
    else:
        reason = f"форум ответил {resp.status_code}"
    return False, reason, in_index


def _scan_error_text(slug: str, exc: Exception, source_label: str = FORUM_LABEL) -> str:
    """Человеческий текст ошибки сканирования вместо сырого текста aiohttp."""
    if isinstance(exc, aiohttp.ClientResponseError):
        if exc.status == 404:
            return f"Раздел /{slug} не найден на источнике «{source_label}» (404)"
        if exc.status >= 500:
            return (
                f"Источник «{source_label}» ответил {exc.status} на каталог /{slug}: "
                f"раздел удалён или недоступен (проверьте slug)"
            )
        return f"Источник «{source_label}» ответил {exc.status} на каталог /{slug}"
    if isinstance(exc, asyncio.TimeoutError):
        return f"Источник «{source_label}» не ответил вовремя (таймаут) — попробуйте ещё раз"
    if isinstance(exc, aiohttp.ClientError):
        return f"Не удалось связаться с источником «{source_label}»: {exc}"
    return str(exc) or exc.__class__.__name__


@router.get("/sources/{code}/catalog", response_model=List[SourceBoardOut])
async def source_catalog(
    code: str,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Разделы, которые предлагает источник, — «Доски форума» для любого источника.

    Список читает адаптер источника: у 2ch это `index.json`, у сайтов — своё меню
    категорий. Админка показывает те разделы, которых ещё нет в системе, и
    добавляет выбранные (`POST /admin/boards`): дальше раздел ведёт себя как
    обычный — «Парсить» / «published» / «премиум», а внутри появляются «треды»
    (у сайтов — записи), их тоже можно включать поштучно.
    """
    source = await _require_source(session, code)
    adapter = sources_service.build_source_adapter(source)
    try:
        async with adapter:
            nodes = await adapter.fetch_boards()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Источник %s не отдал список разделов: %s", code, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Источник «{code}» не отдал список разделов: {exc}",
        )
    if nodes is None:
        raise HTTPException(
            status_code=502,
            detail=f"Источник «{code}» не отдал список разделов (сайт недоступен)",
        )

    db_boards = {
        b.slug: b
        for b in (
            await session.execute(select(Board).where(Board.source_id == source.id))
        )
        .scalars()
        .all()
    }
    stats, _ = await collect_board_stats(session)

    out: List[SourceBoardOut] = []
    for node in nodes:
        board = db_boards.get(node.slug)
        s = stats.get(board.id, {}) if board else {}
        out.append(
            SourceBoardOut(
                slug=node.slug,
                name=node.title,
                group=node.group,
                hint=int(node.hint or 0),
                in_db=board is not None,
                parse_enabled=board.parse_enabled if board else False,
                parse_mode=board.parse_mode if board else None,
                is_visible=board.is_visible if board else False,
                is_premium=board.is_premium if board else False,
                media_total=int(s.get("media_total", 0)),
                media_in_s3=int(s.get("media_in_s3", 0)),
                threads_active=int(s.get("threads_active", 0)),
            )
        )
    return out


async def _source_for_board(session: AsyncSession, board: Board) -> Source:
    """Источник раздела: по `board.source_id`, а для старых досок — 2ch."""
    if board.source_id:
        source = (
            await session.execute(select(Source).where(Source.id == board.source_id))
        ).scalar_one_or_none()
        if source is not None:
            return source
    source = await sources_service.get_source(session, sources_service.DEFAULT_SOURCE_CODE)
    if source is None:
        raise RuntimeError(
            "Реестр источников пуст: нет даже источника "
            f"«{sources_service.DEFAULT_SOURCE_CODE}»"
        )
    return source


@router.get("/boards", response_model=list[AdminBoardOut])
async def list_admin_boards(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Наши доски (включая скрытые) с флагами и статистикой."""
    return await _all_boards_with_stats(session)


def _normalize_slug(raw: str) -> str:
    """Приводит ввод пользователя к слагу: `/hc`, ` hc `, `https://2ch.su/hc/` → `hc`."""
    value = (raw or "").strip().lower()
    if value.startswith("http://") or value.startswith("https://"):
        # Берём первый сегмент пути после домена
        value = value.split("//", 1)[-1]
        value = value.split("/", 1)[1] if "/" in value else ""
    return value.strip().strip("/").strip()


@router.post("/boards", response_model=AdminBoardOut)
async def create_board(
    payload: BoardCreate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Создаёт доску по слагу (которой ещё нет в нашей системе).

    По умолчанию раздел должен реально читаться на форуме: `index.json`
    перечисляет и удалённые/закрытые разделы (у них каталог отдаёт 500), а
    парсить их нельзя. Если каталог недоступен, но раздел нужен в списке —
    панель предлагает добавить его принудительно (`force=true`): доска
    появится с бейджем «каталог недоступен» и не будет парситься, пока 2ch
    её не откроет.
    """
    slug = _normalize_slug(payload.slug)
    if not SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Некорректный slug: допустимы латиница/цифры и `-`, до 32 символов",
                "can_force": False,
            },
        )

    existing = await session.execute(select(Board).where(Board.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"message": f"Раздел /{slug} уже добавлен", "can_force": False},
        )

    # Источник раздела: у 2ch проверяем каталог на форуме, у остальных источников
    # разделы создаёт их собственный парсер (он знает свою структуру).
    is_dvach = payload.source == sources_service.DEFAULT_SOURCE_CODE
    source = await sources_service.get_source(session, payload.source)
    if source is None:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Неизвестный источник «{payload.source}»", "can_force": False},
        )

    if is_dvach and not payload.force:
        ok, reason, in_index = await _probe_board_catalog(slug)
        if not ok:
            if in_index:
                message = (
                    f"Раздел /{slug} есть в списке 2ch, но каталог не читается: {reason}. "
                    f"Парсить его нельзя, пока форум не откроет доступ."
                )
            else:
                message = f"Раздел /{slug} недоступен на 2ch: {reason}."
            raise HTTPException(
                status_code=400,
                detail={"message": message, "can_force": True},
            )
    elif is_dvach:
        # Добавляем принудительно, но состояние каталога всё равно проверяем и
        # помечаем причину — в списке разделов сразу виден бейдж «каталог недоступен».
        ok, reason, _in_index = await _probe_board_catalog(slug)
        if not ok:
            await mark_catalog_error(slug, f"раздел не читается: {reason}")
        print(f"[admin] раздел /{slug} добавлен принудительно (каталог: {'ок' if ok else reason})")
    else:
        # Остальные источники: раздел должен быть в списке, который предлагает
        # сам источник (у сайтов это категории). Список не пришёл — не мешаем.
        known = None
        try:
            async with sources_service.build_source_adapter(source) as adapter:
                known = await adapter.fetch_boards()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Источник %s не отдал разделы при добавлении /%s: %s", source.code, slug, exc
            )
        if known and slug not in {node.slug for node in known} and not payload.force:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        f"У источника «{source.code}» нет раздела «{slug}» — "
                        f"обновите список разделов и выберите из него"
                    ),
                    "can_force": True,
                },
            )

    max_order = (await session.execute(select(func.max(Board.sort_order)))).scalar() or 0
    name = (payload.name or "").strip()
    board = Board(
        slug=slug,
        title=name[:100] or slug,
        parse_enabled=False,
        is_visible=False,
        sort_order=int(max_order) + 1,
        source_id=source.id,
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

    # Превью карточки раздела: выбранные админом файлы (пустой список — авто)
    if payload.cover_media_ids is not None:
        board.cover_media_ids = await _resolve_cover_ids(
            session, board, payload.cover_media_ids
        )

    if payload.is_premium is not None and payload.is_premium != board.is_premium:
        board.is_premium = payload.is_premium
        await sync_board_media_premium(session, board)

    await session.commit()

    stats, _ = await collect_board_stats(session)
    return _admin_out(board, stats.get(board.id))


@router.get("/boards/{slug}/cover-candidates", response_model=List[BoardCoverCandidate])
async def board_cover_candidates(
    slug: str,
    limit: int = Query(60, ge=4, le=200),
    ids: Optional[str] = Query(
        None, description="Дополнительно вернуть эти id (уже выбранные превью)"
    ),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Свежие файлы раздела — галерея выбора превью для карточки каталога.

    Миниатюры отдаём настоящие (без премиум-размытия): админ выбирает по картинке.
    Через `ids` можно до-запросить уже сохранённые превью, если файл старый и в
    свежую выборку не попал (иначе плитка осталась бы без картинки).
    """
    board = await _load_board(session, slug)
    extra_ids = []
    for chunk in (ids or "").split(","):
        chunk = chunk.strip()
        if chunk.isdigit() and int(chunk) not in extra_ids:
            extra_ids.append(int(chunk))

    fresh = await session.execute(
        select(Media.id, Media.media_type, Media.variants)
        .where(Media.board_id == board.id, *VISIBLE_FILTER, visible_thread_clause())
        .order_by(Media.created_at.desc(), Media.id.desc())
        .limit(limit)
    )
    rows = list(fresh.all())
    seen = {row[0] for row in rows}
    if extra_ids:
        picked = await session.execute(
            select(Media.id, Media.media_type, Media.variants).where(
                Media.id.in_([mid for mid in extra_ids if mid not in seen])
            )
        )
        rows.extend(picked.all())

    items: List[BoardCoverCandidate] = []
    for media_id, media_type, variants in rows:
        variants = variants or {}
        thumb = variants.get("thumb")
        blur = variants.get("thumb_blur")
        kind = "thumb" if thumb else "thumb_blur"
        items.append(
            BoardCoverCandidate(
                id=media_id,
                media_type=media_type or "image",
                thumb_url=asset_url(media_id, kind, thumb or blur) if (thumb or blur) else None,
            )
        )
    return items


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


# ── Локальный кэш медиа (диск сервера) ────────────────────────────
# S3 у провайдера отдаёт ~3 МБ/с, локальный SSD — 500+ МБ/с. Всё, что уже
# прочитано или скачано парсером, лежит в кэше: повторные запросы (включая
# премиум-оригиналы, которым закрыт общий кэш nginx) идут с диска.

WARM_STATUS_KEY = "media_cache:warm"
# Если прогрева нет дольше этого времени — считаем его прерванным (рестарт API)
WARM_STALE_SECONDS = 120
_warm_task: Optional[asyncio.Task] = None


async def _warm_status() -> Dict[str, object]:
    """Прогресс прогрева кэша (хранится в Redis, переживает рестарт API).

    Если процесс упал во время прогрева, статус остался бы «running» навсегда —
    поэтому по «протухшему» отметке времени считаем прогрев прерванным.
    """
    raw = await redis_client.get(WARM_STATUS_KEY)
    if raw:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            state = json.loads(raw)
            if state.get("status") == "running":
                heartbeat = float(state.get("ts") or 0)
                if time.time() - heartbeat > WARM_STALE_SECONDS:
                    state["status"] = "interrupted"
            return state
        except (TypeError, ValueError):
            pass
    return {"status": "idle", "done": 0, "total": 0, "failed": 0}


async def _cache_keys(session: AsyncSession) -> List[str]:
    """Все ключи объектов S3 из БД: оригиналы + деривативы."""
    result = await session.execute(
        select(Media.s3_key, Media.variants).where(Media.s3_key.isnot(None))
    )
    keys: List[str] = []
    for s3_key, variants in result.all():
        if s3_key:
            keys.append(s3_key)
        for value in (variants or {}).values():
            if value:
                keys.append(value)
    return keys


async def _warm_cache(keys: List[str]) -> None:
    """Фоновый прогрев: тянет объекты из S3 в локальный кэш (пачками, с лимитом)."""
    s3 = get_s3()
    cache = get_media_cache()
    total = len(keys)
    state: Dict[str, object] = {
        "status": "running",
        "done": 0,
        "total": total,
        "failed": 0,
        "ts": time.time(),
    }
    await redis_client.set(WARM_STATUS_KEY, json.dumps(state), ex=86400)
    semaphore = asyncio.Semaphore(max(1, settings.MEDIA_CACHE_WARM_WORKERS))
    lock = asyncio.Lock()

    async def fetch(key: str) -> None:
        ok = True
        if not cache.has(key):
            async with semaphore:
                temp = cache.path_for_part(key)
                ok = await s3.download_to_file(key, temp)
                if ok:
                    cache.commit_part(key, temp)
                else:
                    cache.drop_part(temp)
        async with lock:
            state["done"] = int(state["done"]) + 1
            if not ok:
                state["failed"] = int(state["failed"]) + 1
            if int(state["done"]) % 5 == 0 or int(state["done"]) == total:
                state["ts"] = time.time()
                await redis_client.set(WARM_STATUS_KEY, json.dumps(state), ex=86400)
                await asyncio.to_thread(cache.sweep)

    # Пачками, чтобы не плодить десятки тысяч задач сразу
    for start in range(0, total, 200):
        await asyncio.gather(*(fetch(key) for key in keys[start:start + 200]))

    state["status"] = "done"
    await redis_client.set(WARM_STATUS_KEY, json.dumps(state), ex=86400)
    await asyncio.to_thread(cache.sweep)
    print(f"[cache] прогрев завершён: {state['done']} объектов, ошибок {state['failed']}")


@router.get("/media-cache")
async def media_cache_state(_=Depends(verify_admin)):
    """Состояние локального кэша: файлы, объём, лимит, место на диске, прогрев."""
    cache = get_media_cache()
    stats = await asyncio.to_thread(cache.stats)
    stats["warm"] = await _warm_status()
    return stats


@router.post("/media-cache/sweep")
async def media_cache_sweep(_=Depends(verify_admin)):
    """Принудительная LRU-чистка кэша (удаляются самые старые файлы)."""
    cache = get_media_cache()
    freed = await asyncio.to_thread(cache.sweep, True)
    stats = await asyncio.to_thread(cache.stats)
    return {"freed_bytes": freed, **stats}


@router.post("/media-cache/clear")
async def media_cache_clear(_=Depends(verify_admin)):
    """Полная очистка кэша: файлы остаются в S3, скачаются заново при запросе."""
    cache = get_media_cache()
    removed = await asyncio.to_thread(cache.clear)
    stats = await asyncio.to_thread(cache.stats)
    return {"removed_files": removed, **stats}


@router.post("/media-cache/warm")
async def media_cache_warm(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Запускает фоновый прогрев кэша: все объекты из БД тянутся из S3 на диск."""
    global _warm_task
    current = await _warm_status()
    if current.get("status") == "running":
        return current
    keys = await _cache_keys(session)
    _warm_task = asyncio.create_task(_warm_cache(keys))
    return {"status": "running", "done": 0, "total": len(keys), "failed": 0}


@router.get("/media-cache/warm")
async def media_cache_warm_status(_=Depends(verify_admin)):
    """Прогресс прогрева кэша (опрашивается админкой)."""
    return await _warm_status()


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


@router.post("/boards/{slug}/threads/delete", response_model=ThreadDeleteResult)
async def delete_threads(
    slug: str,
    payload: ThreadDeleteRequest,
    dry_run: bool = Query(False, description="Только посчитать объём удаления, ничего не менять"),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Удаляет треды раздела: файлы из БД и хранилища + тред из выдачи.

    Парсинг треда выключается, а строка треда остаётся «надгробием»: иначе
    сканирование каталога вернуло бы тред, и парсер скачал бы всё заново.
    Объекты, на которые ссылаются файлы других тредов (тот же файл в перекрёстном
    дубле) не удаляем — они попадают в `kept_objects`.
    `?dry_run=true` — прикидка без изменений (сколько тредов/файлов/объектов).
    """
    board = await _load_board(session, slug)
    ids = [int(t) for t in (payload.thread_ids or [])]
    if not ids:
        return ThreadDeleteResult()

    media_rows = (
        await session.execute(
            select(Media.id, Media.s3_key, Media.variants).where(
                Media.board_id == board.id, Media.thread_id.in_(ids)
            )
        )
    ).all()
    media_ids = [row[0] for row in media_rows]

    own_keys: set = set()
    for _mid, key, variants in media_rows:
        if key:
            own_keys.add(key)
        for value in (variants or {}).values():
            if value:
                own_keys.add(value)

    # Что нельзя трогать: ключи файлов этого же раздела вне удаляемых тредов
    # (дубли ссылаются на тот же объект в S3).
    keep: set = set()
    if own_keys:
        foreign = (
            await session.execute(
                select(Media.s3_key, Media.variants).where(
                    Media.board_id == board.id, Media.thread_id.notin_(ids)
                )
            )
        ).all()
        for key, variants in foreign:
            if key:
                keep.add(key)
            for value in (variants or {}).values():
                if value:
                    keep.add(value)

    removable = sorted(own_keys - keep)

    threads = (
        await session.execute(
            select(ThreadState).where(
                ThreadState.board_id == board.id, ThreadState.thread_id.in_(ids)
            )
        )
    ).scalars().all()

    if not dry_run:
        if removable:
            await s3.delete_keys(removable)
            # Заодно выкидываем локальный кэш этих файлов (иначе он держит
            # удалённый контент до следующего прогона LRU).
            cache = get_media_cache()
            for key in removable:
                try:
                    cache.path_for(key).unlink(missing_ok=True)
                except OSError:
                    pass

        if media_ids:
            # Метки/просмотры/скачивания уходят каскадом (ON DELETE CASCADE).
            await session.execute(delete(Media).where(Media.id.in_(media_ids)))

        for thread in threads:
            # «Надгробие»: тред не парсится и не виден, но каталог вернёт его
            # строку — повторной закачки файлов не будет.
            thread.parse_enabled = False
            thread.is_visible = False
            thread.pending_scan = False
            thread.pending_reason = None
            thread.files_count = 0
            thread.files_detected = 0
            thread.last_scan_note = "файлы удалены вручную"

        await session.commit()

    logger.info(
        "threads %s: /%s ids=%s media=%s objects=%s kept=%s",
        "counted" if dry_run else "deleted",
        slug,
        ids,
        len(media_ids),
        len(removable),
        len(own_keys & keep),
    )
    return ThreadDeleteResult(
        deleted_threads=len(threads),
        deleted_media=len(media_ids),
        deleted_objects=len(removable),
        kept_objects=len(own_keys & keep),
        dry_run=dry_run,
    )


# ───────────── Сканирование каталога доски («Загрузить треды») ─────────────


async def _run_board_scan(slug: str, deep: bool = False) -> None:
    """Фоновое чтение каталога раздела: «треды» появляются до скачивания файлов.

    Работает через адаптер источника, поэтому одинаково устроено для 2ch
    (`catalog.json`) и для сайтов (страницы категории). Новые «треды» включаются
    только у раздела с `parse_mode=all`: по умолчанию админ выбирает их вручную
    (`selected`) — это и есть инструмент отбора записей/тредов.

    `deep=true` дополнительно читает каждый «тред» и считает файлы, которые прошли
    бы фильтры; медиа при этом **не скачивается**.
    """
    key = scan_key(slug)
    source_label = FORUM_LABEL
    try:
        async with async_session_factory() as session:
            board = (
                await session.execute(select(Board).where(Board.slug == slug))
            ).scalar_one_or_none()
            if not board:
                await redis_client.set(
                    key, json.dumps({"status": "error", "error": "Раздел не найден"}), ex=600
                )
                return

            source = await _source_for_board(session, board)
            source_label = source.title or source.code
            adapter = sources_service.build_source_adapter(source)
            planner = ScanPlanner(session, adapter, source.code, source.id)
            repo = planner.thread_state_repo

            files_total = 0
            async with adapter:
                before = len(await repo.get_all_by_board(board.id))
                total = await planner.sync_board_catalog(slug)
                if total is None:
                    raise RuntimeError(f"каталог раздела /{slug} недоступен")

                states = await repo.get_all_by_board(board.id)
                created = max(0, len(states) - before)

                if deep:
                    await redis_client.set(
                        key,
                        json.dumps(
                            {"status": "running", "phase": "files", "total": len(states), "done": 0}
                        ),
                        ex=600,
                    )
                    for i, state in enumerate(states, start=1):
                        try:
                            files = await adapter.fetch_thread_files(slug, state.external_id)
                        except Exception as e:  # noqa: BLE001
                            files = None
                            print(f"   [warn] не удалось посчитать файлы «{state.external_id}»: {e}")
                        if files is not None:
                            count = sum(
                                1
                                for f in files
                                if MediaValidator.is_allowed(
                                    f.filename, f.size_bytes, f.media_type, f.width, f.height
                                )[0]
                            )
                            state.files_detected = count
                            files_total += count
                        if i % 25 == 0:
                            await session.commit()
                            await redis_client.set(
                                key,
                                json.dumps(
                                    {
                                        "status": "running",
                                        "phase": "files",
                                        "total": len(states),
                                        "done": i,
                                    }
                                ),
                                ex=600,
                            )
                        await asyncio.sleep(settings.REQUEST_DELAY * 0.5)
                    await session.commit()

        await mark_catalog_ok(slug)
        await redis_client.set(
            key,
            json.dumps(
                {
                    "status": "done",
                    "phase": "files" if deep else "catalog",
                    "total": total,
                    "done": total,
                    "created": created,
                    "updated": max(0, int(total) - created),
                    "files_total": files_total,
                }
            ),
            ex=600,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("scan failed for /%s", slug)
        text = _scan_error_text(slug, e, source_label)
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


# ── Источники: реестр и независимые прогоны ─────────────────────────
# У каждого источника свои флаги в Redis (`parser:{code}:…`), свой прогресс и
# своя история прогонов. Старые ручки `/parser/*` остаются как «источник по
# умолчанию» (2ch) — чтобы админку можно было переключать постепенно.


async def _source_totals(session: AsyncSession, source_id: int) -> tuple[int, int]:
    """Сколько у источника досок и уникальных файлов (для вкладки источника)."""
    boards_count = await session.scalar(
        select(func.count()).select_from(Board).where(Board.source_id == source_id)
    )
    media_count = await session.scalar(
        select(func.count())
        .select_from(Media)
        .where(Media.source_id == source_id, Media.duplicate_of_id.is_(None))
    )
    return int(boards_count or 0), int(media_count or 0)


async def _require_source(session: AsyncSession, code: str):
    source = await sources_service.get_source(session, code)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Источник «{code}» не найден")
    return source


def _run_out(run) -> dict:
    return {
        "id": run.id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "phase": run.phase,
        "stats": run.stats or {},
        "error": run.error,
    }


@router.get("/sources")
async def admin_sources(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Реестр источников: настройки, состояние прогона, объёмы, история.

    Из этого списка админка строит вкладки по источникам — новый источник
    появляется в интерфейсе без правок фронтенда.
    """
    items = []
    for source in await sources_service.list_sources(session):
        boards_total, media_total = await _source_totals(session, source.id)
        items.append(
            {
                "id": source.id,
                "code": source.code,
                "title": source.title,
                "kind": source.kind,
                "base_url": source.base_url,
                "is_enabled": source.is_enabled,
                "schedule_minutes": source.schedule_minutes,
                "rate_limit_rps": source.rate_limit_rps,
                "budget_minutes": source.budget_minutes,
                "sort_order": source.sort_order,
                "config": source.config or {},
                "boards_total": boards_total,
                "media_total": media_total,
                "status": await sources_service.read_status(source.code),
                "runs": [
                    _run_out(run) for run in await sources_service.last_runs(session, source.id, limit=3)
                ],
            }
        )
    return {"items": items}


@router.get("/sources/{code}/status")
async def source_status(code: str, _=Depends(verify_admin)):
    """Лёгкий статус прогона источника (частый опрос из его вкладки)."""
    return await sources_service.read_status(code)


@router.post("/sources/{code}/start")
async def source_start(
    code: str,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Запускает прогон источника: его контейнер подхватит флаг за ~5 секунд."""
    source = await _require_source(session, code)
    await sources_service.set_enabled(source.code, True)
    return {"ok": True, "code": source.code, "enabled": True}


@router.post("/sources/{code}/stop")
async def source_stop(
    code: str,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Останавливает прогон источника (остальные источники продолжают работу)."""
    source = await _require_source(session, code)
    await sources_service.set_enabled(source.code, False)
    return {"ok": True, "code": source.code, "enabled": False}


@router.patch("/sources/{code}")
async def source_update(
    code: str,
    payload: SourceUpdate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Правка источника в реестре: включение, адрес, расписание, лимиты, конфиг.

    Меняются только переданные поля. `is_enabled` — «источник может работать»,
    это отдельный тумблер от флага прогона (`parser:{code}:enabled`, кнопка
    «Запустить»): выключенный в реестре источник не запустится даже кнопкой.
    """
    source = await _require_source(session, code)

    changed: dict = {}
    if payload.title is not None:
        source.title = payload.title.strip()[:100]
        changed["title"] = source.title
    if payload.base_url is not None:
        source.base_url = payload.base_url.strip()[:255]
        changed["base_url"] = source.base_url
    if payload.is_enabled is not None:
        source.is_enabled = payload.is_enabled
        changed["is_enabled"] = payload.is_enabled
    if payload.schedule_minutes is not None:
        source.schedule_minutes = max(1, int(payload.schedule_minutes))
        changed["schedule_minutes"] = source.schedule_minutes
    if payload.rate_limit_rps is not None:
        source.rate_limit_rps = max(0.1, float(payload.rate_limit_rps))
        changed["rate_limit_rps"] = source.rate_limit_rps
    if payload.budget_minutes is not None:
        source.budget_minutes = max(0, int(payload.budget_minutes))
        changed["budget_minutes"] = source.budget_minutes
    if payload.sort_order is not None:
        source.sort_order = int(payload.sort_order)
        changed["sort_order"] = source.sort_order
    if payload.config is not None:
        source.config = payload.config
        changed["config"] = sorted(payload.config.keys())

    # Выключили источник — снимаем и флаг прогона, иначе контейнер остался бы «жив»
    if payload.is_enabled is False:
        await sources_service.set_enabled(source.code, False)

    if changed:
        await record_audit(
            session,
            action="source.update",
            target=source.code,
            details=json.dumps(changed, ensure_ascii=False)[:500],
        )
    await session.commit()
    return {"ok": True, "code": source.code, "changed": sorted(changed.keys())}


@router.get("/sources/{code}/runs")
async def source_runs(
    code: str,
    limit: int = Query(20, ge=1, le=200),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """История прогонов источника (журнал `parse_runs`) — для вкладки «Источники»."""
    source = await _require_source(session, code)
    runs = await sources_service.last_runs(session, source.id, limit=limit)
    return {"code": source.code, "items": [_run_out(run) for run in runs]}


# ─────────── Ежедневный отчёт: предпросмотр и ручная отправка ───────────


@router.get("/reports/daily")
async def daily_report_preview(
    period: str = Query("today", pattern="^(today|yesterday)$"),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Текст ежедневного отчёта без отправки — видно, что попадёт в письмо.

    Период — отчётные сутки по МСК (00:00–24:00): `today` — текущие (ещё идут),
    `yesterday` — прошедшие (это же уходит письмом в 00:05 МСК).
    """
    if period == "yesterday":
        start, end = reporting.previous_period()
    else:
        start, end = reporting.period_bounds()
    return await daily_report.build_report(session, start, end)


@router.post("/reports/daily/send")
async def daily_report_send(
    period: str = Query("yesterday", pattern="^(today|yesterday)$"),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Отправляет отчёт сейчас (то же письмо, что уходит автоматически в 00:05 МСК)."""
    if period == "yesterday":
        start, end = reporting.previous_period()
    else:
        start, end = reporting.period_bounds()
    report = await daily_report.build_report(session, start, end)
    sent = await daily_report.send_report(report["text"], report["subject"])
    return {
        "period_label": report["period_label"],
        "subject": report["subject"],
        "sent": sent,
        "mail_configured": report["mail_configured"],
        "recipients": report["recipients"],
    }


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


