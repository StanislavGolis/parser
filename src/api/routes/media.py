# src/api/routes/media.py
import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import (
    VISIBLE_FILTER,
    apply_media_urls,
    apply_user_flags,
    build_media_url,
    media_locked,
    sign_media_urls,
    visible_thread_clause,
)
from src.api.deps import (
    check_rate_limit,
    client_ip,
    get_current_user,
    get_s3,
    ip_hash,
    require_premium,
    require_user,
)
from src.api.schemas import (
    DownloadResult,
    MarkResult,
    MediaDetailOut,
    MediaListOut,
    MediaOut,
    ViewResult,
)
from src.core.config import settings
from src.core.db import get_session
from src.core.models import (
    Board,
    DownloadStat,
    Media,
    MediaMark,
    ThreadState,
    User,
    ViewStat,
)
from src.services.media_cache import MediaCache, get_media_cache
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1", tags=["media"])

# Окно дедупликации статистики по IP (часов)
DEDUP_PERIOD_HOURS = 24


async def _get_visible_media(session: AsyncSession, media_id: int) -> Media:
    result = await session.execute(
        select(Media).where(*VISIBLE_FILTER, Media.id == media_id)
    )
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    return media


async def _check_media_access(
    session: AsyncSession,
    media: Media,
) -> Board:
    """Проверяет видимость доски и треда для файла.

    Скрытая доска/тред = контент «не существует» (404). Премиум-доступ
    проверяется отдельно (`_require_premium`) — он не скрывает файл, а
    ограничивает полный контент и размывает превью.
    """
    board = await session.get(Board, media.board_id)
    if not board or not board.is_visible:
        raise HTTPException(status_code=404, detail="Media not found")

    # Видимость треда — сквозная проверка для файлов
    thread_result = await session.execute(
        select(ThreadState).where(
            ThreadState.board_id == media.board_id,
            ThreadState.thread_id == media.thread_id,
        )
    )
    thread = thread_result.scalar_one_or_none()
    if not thread or not thread.is_active or not thread.is_visible:
        raise HTTPException(status_code=404, detail="Media not found")
    return board


def _require_premium(media: Media, user: Optional[User]) -> None:
    """Полный доступ к премиум-файлу требует активной подписки."""
    if media_locked(media, user):
        raise HTTPException(status_code=403, detail="Требуется премиум-доступ")


@router.get("/boards/{slug}/media", response_model=MediaListOut)
async def board_media(
    slug: str,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=300),
    sort: str = Query("new", pattern="^(new|popular|marks)$"),
    media_type: Optional[str] = Query(None, alias="type", pattern="^(image|video)$"),
    thread: Optional[int] = Query(None, description="Показать файлы только этого треда"),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: Optional[User] = Depends(get_current_user),
):
    """Список файлов доски с пагинацией и сортировкой (можно фильтровать по треду).

    Премиум-файлы остаются в списке: превью приходит размытым, полный — по подписке.
    """
    await check_rate_limit(client_ip(request))

    board_result = await session.execute(
        select(Board).where(Board.slug == slug, Board.is_visible.is_(True))
    )
    board = board_result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    filters = list(VISIBLE_FILTER) + [Media.board_id == board.id, visible_thread_clause()]
    if media_type:
        filters.append(Media.media_type == media_type)
    if thread is not None:
        filters.append(Media.thread_id == thread)

    total = (
        await session.execute(select(func.count()).select_from(Media).where(*filters))
    ).scalar()

    query = (
        select(Media)
        .where(*filters)
        .order_by(
            (
                Media.marks_count.desc()
                if sort == "marks"
                else Media.popularity_score.desc()
                if sort == "popular"
                else Media.created_at.desc()
            ),
            Media.id.desc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await session.execute(query)
    items = result.scalars().all()

    out = [MediaOut.model_validate(m) for m in items]
    sign_media_urls(out, items, s3, user)
    await apply_user_flags(session, out, user)
    return MediaListOut(
        items=out,
        page=page,
        per_page=per_page,
        total=int(total or 0),
    )


@router.get("/media/{media_id}", response_model=MediaDetailOut)
async def media_detail(
    media_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: Optional[User] = Depends(get_current_user),
):
    """Информация о файле + URL для просмотра (премиум-файлы помечаются locked)."""
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)

    board = await _check_media_access(session, media)
    data = MediaDetailOut.model_validate(media)
    data.board_slug = board.slug if board else ""
    apply_media_urls(data, media, s3, user)
    await apply_user_flags(session, [data], user)
    return data


def _recalc_popularity(media: Media) -> None:
    """Пересчёт индекса популярности: просмотры, скачивания и метки.

    Метка («отличный контент») — наш аналог лайка, поэтому она тоже влияет
    на «Популярное» (вес 1.5 — сильнее просмотра, слабее скачивания).
    """
    media.popularity_score = (
        media.views_count * 0.3 + media.downloads_count * 0.7 + (media.marks_count or 0) * 1.5
    )


@router.get("/media/{media_id}/view", response_model=ViewResult)
async def media_view(
    media_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    """Отметить просмотр файла (дедупликация по IP за 24 часа).

    Если зритель вошёл, просмотр привязывается к аккаунту — так в админке
    считается статистика по пользователю.
    """
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)
    await _check_media_access(session, media)
    iph = ip_hash(client_ip(request))
    cutoff = datetime.utcnow() - timedelta(hours=DEDUP_PERIOD_HOURS)

    dup_result = await session.execute(
        select(ViewStat).where(
            ViewStat.media_id == media.id,
            ViewStat.ip_hash == iph,
            ViewStat.viewed_at >= cutoff,
        ).limit(1)
    )
    already = dup_result.scalar_one_or_none() is not None

    if not already:
        session.add(
            ViewStat(media_id=media.id, ip_hash=iph, user_id=user.id if user else None)
        )
        media.views_count += 1
        _recalc_popularity(media)
        await session.commit()

    return ViewResult(media_id=media.id, counted=not already)


@router.get("/media/{media_id}/download", response_model=DownloadResult)
async def media_download(
    media_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: User = Depends(require_premium),
):
    """Отметить скачивание и вернуть URL оригинала. Только для премиум-подписки.

    Аноним получает 401, зарегистрированный без подписки — 403
    (скачивание и оригиналы входят в премиум по матрице ролей).
    """
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)
    if not media.s3_key:
        raise HTTPException(status_code=409, detail="File not available")

    await _check_media_access(session, media)
    _require_premium(media, user)
    url = build_media_url(media.id, s3, media.s3_key, download=True)
    if not url:
        raise HTTPException(status_code=503, detail="Storage is not configured")

    iph = ip_hash(client_ip(request))
    cutoff = datetime.utcnow() - timedelta(hours=DEDUP_PERIOD_HOURS)

    dup_result = await session.execute(
        select(DownloadStat).where(
            DownloadStat.media_id == media.id,
            DownloadStat.ip_hash == iph,
            DownloadStat.downloaded_at >= cutoff,
        ).limit(1)
    )
    already = dup_result.scalar_one_or_none() is not None

    if not already:
        session.add(
            DownloadStat(media_id=media.id, ip_hash=iph, user_id=user.id if user else None)
        )
        media.downloads_count += 1
        _recalc_popularity(media)
        await session.commit()

    return DownloadResult(media_id=media.id, counted=not already, url=url)


@router.post("/media/{media_id}/mark", response_model=MarkResult)
async def media_mark(
    media_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    """Поставить/снять метку «отличный контент» (наш аналог лайка).

    Требует аккаунт (аноним → 401). Метка — переключатель: повторный вызов
    снимает её. Счётчик хранится в `media.marks_count`, а личный список
    отмеченного доступен на `GET /api/v1/marks`.
    """
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)
    await _check_media_access(session, media)

    existing = (
        await session.execute(
            select(MediaMark).where(
                MediaMark.user_id == user.id, MediaMark.media_id == media.id
            )
        )
    ).scalar_one_or_none()

    if existing:
        await session.delete(existing)
        media.marks_count = max(0, int(media.marks_count or 0) - 1)
        marked = False
    else:
        session.add(MediaMark(user_id=user.id, media_id=media.id))
        media.marks_count = int(media.marks_count or 0) + 1
        marked = True

    _recalc_popularity(media)
    await session.commit()
    return MarkResult(media_id=media.id, marked=marked, marks_count=int(media.marks_count or 0))


# ─────────────── Анонимная отдача файлов (прокси S3) ───────────────

# Размер чанка потоковой отдачи (256 КБ)
STREAM_CHUNK_SIZE = 256 * 1024

# Публичные варианты деривативов (оригинал — /raw)
ASSET_KINDS = ("thumb", "thumb_blur", "web", "video")


def _content_disposition(filename: str) -> str:
    """Content-Disposition с поддержкой не-ASCII имён (RFC 5987)."""
    fallback = re.sub(r"[^\w.\-]+", "_", filename) or "file"
    quoted = urllib.parse.quote(filename, safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quoted}'


async def _iter_body(body):
    """Потоковое чтение тела объекта из S3."""
    try:
        while True:
            chunk = await asyncio.to_thread(body.read, STREAM_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(body.close)


def _parse_range(header: Optional[str], size: int) -> Optional[tuple]:
    """Разбирает `Range: bytes=start-end` → (start, end) включительно.

    Поддерживает обычные (`bytes=100-200`) и суффиксные (`bytes=-500`) диапазоны.
    None — заголовка нет, он множественный или некорректный (тогда отдаём всё).
    """
    if not header or not header.startswith("bytes=") or size <= 0:
        return None
    spec = header[len("bytes="):].strip()
    if "," in spec:
        return None
    start_part, _, end_part = spec.partition("-")
    try:
        if start_part:
            start = int(start_part)
            end = int(end_part) if end_part else size - 1
        elif end_part:
            length = int(end_part)
            if length <= 0:
                return None
            start = max(0, size - length)
            end = size - 1
        else:
            return None
    except ValueError:
        return None
    if start >= size or start > end:
        return None
    return start, min(end, size - 1)


def _iter_file(path: Path, start: int = 0, end: Optional[int] = None):
    """Читает локальный файл (Starlette выполняет такой генератор в пуле потоков)."""
    remaining = None if end is None else end - start + 1
    with path.open("rb") as handle:
        if start:
            handle.seek(start)
        while True:
            chunk_size = (
                STREAM_CHUNK_SIZE if remaining is None else min(STREAM_CHUNK_SIZE, remaining)
            )
            if chunk_size <= 0:
                break
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            if remaining is not None:
                remaining -= len(chunk)
            yield chunk


def _local_file_response(
    *,
    media: Media,
    path: Path,
    request: Request,
    media_type: str,
    cache_control: str,
    download: bool,
):
    """Отдаёт файл из локального кэша (с поддержкой Range-запросов)."""
    stat = path.stat()
    size = stat.st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": cache_control,
        "X-Cache": "HIT",
        "ETag": f'"{int(stat.st_mtime)}-{size}"',
    }
    if download:
        headers["Content-Disposition"] = _content_disposition(media.original_name)

    span = _parse_range(request.headers.get("range"), size)
    if span is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            _iter_file(path),
            status_code=200,
            media_type=media_type,
            headers=headers,
        )

    start, end = span
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


async def _iter_body_tee(body, temp: Path, cache: MediaCache, key: str, total: Optional[int] = None):
    """Читает объект из S3 и попутно складывает его в локальный кэш.

    Первый запрос не ждёт отдельной загрузки: клиент получает данные сразу, а файл
    остаётся на диске для следующих запросов (трафик S3 не удваивается).

    Клиент может закрыть соединение сразу после получения последнего байта — тогда
    генератор не успевает дойти до конца. Если записан весь объект (`total` из
    Content-Length совпал), всё равно коммитим файл: иначе мелкие ассеты никогда
    не попадали бы в кэш.
    """
    completed = False
    written = 0
    handle = None
    try:
        handle = await asyncio.to_thread(temp.open, "wb")
        while True:
            chunk = await asyncio.to_thread(body.read, STREAM_CHUNK_SIZE)
            if not chunk:
                break
            await asyncio.to_thread(handle.write, chunk)
            written += len(chunk)
            yield chunk
        completed = True
    finally:
        # ВАЖНО: в finally нельзя делать await — при обрыве клиента задача
        # отменяется, и первый же await падает с CancelledError, из-за чего файл
        # не попадал в кэш. Закрываем и коммитим синхронно (это быстрые операции).
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass
        if completed or (total is not None and written == total):
            cache.commit_part(key, temp)
            try:
                asyncio.get_running_loop().create_task(asyncio.to_thread(cache.sweep))
            except Exception:  # noqa: BLE001
                pass
        else:
            cache.drop_part(temp)


# Ключи, которые прямо сейчас догружаются в кэш (чтобы не дублировать работу)
_WARMING: set = set()
_WARM_SEMAPHORE: Optional[asyncio.Semaphore] = None


async def _warm_object(key: str, s3: S3Storage, cache: MediaCache) -> None:
    """Фоновая загрузка объекта целиком (нужна после Range-запросов к видео)."""
    global _WARM_SEMAPHORE
    if _WARM_SEMAPHORE is None:
        _WARM_SEMAPHORE = asyncio.Semaphore(max(1, settings.MEDIA_CACHE_WARM_WORKERS))
    try:
        async with _WARM_SEMAPHORE:
            if cache.has(key):
                return
            temp = cache.path_for_part(key)
            if await s3.download_to_file(key, temp):
                cache.commit_part(key, temp)
                await asyncio.to_thread(cache.sweep)
            else:
                cache.drop_part(temp)
    except Exception as exc:  # noqa: BLE001
        print(f"   [cache] прогрев {key} не удался: {exc}")
    finally:
        _WARMING.discard(key)


def _schedule_warm(key: str, s3: S3Storage, cache: MediaCache) -> None:
    """Ставит объект в фоновый прогрев, не задерживая ответ клиенту."""
    if not cache.enabled or key in _WARMING:
        return
    _WARMING.add(key)
    asyncio.create_task(_warm_object(key, s3, cache))


async def _stream_object(
    *,
    media: Media,
    key: str,
    request: Request,
    s3: S3Storage,
    cache: Optional[MediaCache] = None,
    download: bool = False,
    content_type: Optional[str] = None,
    cache_control: str = "public, max-age=3600",
):
    """Отдаёт объект: сначала локальный кэш, при промахе — S3 (с записью в кэш).

    Локальный диск (замер: 500+ МБ/с) на порядки быстрее S3 у провайдера
    (~3 МБ/с), поэтому повторные запросы — включая премиум-оригиналы, которые
    нельзя класть в общий кэш nginx, — обслуживаются прямо с диска.
    """
    media_type = content_type or media.mime_type

    if cache is not None and cache.enabled:
        cached = cache.get(key)
        if cached is not None:
            return _local_file_response(
                media=media,
                path=cached,
                request=request,
                media_type=media_type,
                cache_control=cache_control,
                download=download,
            )

    if not s3.is_configured:
        raise HTTPException(status_code=503, detail="Storage is not configured")

    range_header = request.headers.get("range")
    obj = await s3.open_object_stream(key, range_header=range_header)
    if obj is None or obj.get("body") is None:
        raise HTTPException(status_code=404, detail="File not found in storage")

    headers = {"Accept-Ranges": obj.get("accept_ranges") or "bytes", "X-Cache": "MISS"}
    if obj.get("content_length") is not None:
        headers["Content-Length"] = str(obj["content_length"])
    if obj.get("content_range"):
        headers["Content-Range"] = obj["content_range"]
    if obj.get("etag"):
        headers["ETag"] = obj["etag"]
    if download:
        headers["Content-Disposition"] = _content_disposition(media.original_name)
    headers["Cache-Control"] = cache_control

    body_iter = _iter_body(obj["body"])
    if cache is not None and cache.enabled:
        if not range_header:
            # Объект целиком: пишем в кэш «по пути», клиент ничего не ждёт
            try:
                body_iter = _iter_body_tee(
                    obj["body"],
                    cache.path_for_part(key),
                    cache,
                    key,
                    total=obj.get("content_length"),
                )
            except OSError as exc:
                print(f"   [cache] не удалось начать запись {key}: {exc}")
                body_iter = _iter_body(obj["body"])
        else:
            # Диапазон (перемотка видео): объект нужен целиком → греем в фоне
            _schedule_warm(key, s3, cache)

    return StreamingResponse(
        body_iter,
        status_code=206 if obj.get("content_range") else 200,
        media_type=media_type,
        headers=headers,
    )


@router.get("/media/{media_id}/raw")
async def media_raw(
    media_id: int,
    request: Request,
    download: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    cache: MediaCache = Depends(get_media_cache),
    user: User = Depends(require_premium),
):
    """Отдаёт ОРИГИНАЛ файла через наш API (только премиум-подписка).

    Публично доступны только деривативы (`/asset/thumb|thumb_blur|web|video`),
    причём `thumb_blur` — публичное размытое превью премиум-контента.
    Аноним получает 401, зарегистрированный без подписки — 403.
    Поддерживает Range и Content-Disposition при `?download=1`.
    """
    await check_rate_limit(client_ip(request), limit=settings.MEDIA_RATE_LIMIT, scope="media")

    media = await _get_visible_media(session, media_id)
    if not media.s3_key:
        raise HTTPException(status_code=404, detail="File not available")

    await _check_media_access(session, media)
    _require_premium(media, user)
    return await _stream_object(
        media=media,
        key=media.s3_key,
        request=request,
        s3=s3,
        cache=cache,
        download=download,
        cache_control=(
            "private, no-store" if media.is_premium else "public, max-age=3600"
        ),
    )


@router.get("/media/{media_id}/asset/{kind}")
async def media_asset(
    media_id: int,
    kind: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    cache: MediaCache = Depends(get_media_cache),
    user: Optional[User] = Depends(get_current_user),
):
    """Отдаёт дериватив: `thumb` (превью), `thumb_blur` (размытое превью), `web`, `video`.

    - `thumb_blur` публичен и кэшируется надолго: используется для премиум-контента.
    - `thumb`/`web`/`video` для премиум-файлов требуют подписку и не кэшируются
      (Cache-Control: private, no-store), чтобы вариант не «утёк» из кэша nginx.
    """
    if kind not in ASSET_KINDS:
        raise HTTPException(status_code=404, detail="Unknown asset kind")

    await check_rate_limit(client_ip(request), limit=settings.MEDIA_RATE_LIMIT, scope="media")

    media = await _get_visible_media(session, media_id)
    await _check_media_access(session, media)

    variants = media.variants or {}

    if kind == "thumb_blur":
        # Публичный размытый превью премиум-контента. Пока блюр не сгенерирован
        # (бэкфилл не проходил), отдаём обычное превью — карточка не «ломается»,
        # визуально его прячет клиентский блюр.
        key = variants.get("thumb_blur") or variants.get("thumb")
        if not key:
            raise HTTPException(status_code=404, detail="Asset not available")
        return await _stream_object(
            media=media,
            key=key,
            request=request,
            s3=s3,
            cache=cache,
            cache_control="public, max-age=31536000, immutable",
        )

    _require_premium(media, user)
    key = variants.get(kind)
    if not key:
        raise HTTPException(status_code=404, detail="Asset not available")

    content_type = "video/mp4" if (kind == "video") else None
    # ВАЖНО: имя не `cache` — иначе локальная переменная перекрывает объект кэша,
    # пришедший из Depends(get_media_cache), и _stream_object получает строку.
    cache_control = (
        "private, no-store"
        if media.is_premium
        else "public, max-age=31536000, immutable"
    )
    return await _stream_object(
        media=media,
        key=key,
        request=request,
        s3=s3,
        cache=cache,
        content_type=content_type,
        cache_control=cache_control,
    )
