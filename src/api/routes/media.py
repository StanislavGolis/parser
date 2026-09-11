# src/api/routes/media.py
import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, board_access_granted, build_media_url, sign_media_urls
from src.api.deps import check_rate_limit, client_ip, get_s3, ip_hash
from src.api.schemas import DownloadResult, MediaDetailOut, MediaListOut, MediaOut, ViewResult
from src.core.db import get_session
from src.core.models import Board, DownloadStat, Media, ViewStat
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


async def _check_media_board_access(
    request: Request,
    session: AsyncSession,
    media: Media,
) -> Board:
    """Проверяет видимость доски и доступ к приватной доске.

    Скрытая доска = контент «не существует» (404).
    Приватная доска без валидного cookie доступа — 403.
    """
    board = await session.get(Board, media.board_id)
    if not board or not board.is_visible:
        raise HTTPException(status_code=404, detail="Media not found")
    if board.is_private and not board_access_granted(request, board):
        raise HTTPException(status_code=403, detail="Access denied")
    return board


@router.get("/boards/{slug}/media", response_model=MediaListOut)
async def board_media(
    slug: str,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=300),
    sort: str = Query("new", pattern="^(new|popular)$"),
    media_type: Optional[str] = Query(None, alias="type", pattern="^(image|video)$"),
    thread: Optional[int] = Query(None, description="Показать файлы только этого треда"),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Список файлов доски с пагинацией и сортировкой (можно фильтровать по треду)."""
    await check_rate_limit(client_ip(request))

    board_result = await session.execute(
        select(Board).where(Board.slug == slug, Board.is_visible.is_(True))
    )
    board = board_result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    # Приватная доска: контент только по коду доступа (cookie).
    if board.is_private and not board_access_granted(request, board):
        raise HTTPException(status_code=403, detail="Access denied")

    filters = list(VISIBLE_FILTER) + [Media.board_id == board.id]
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
            Media.popularity_score.desc() if sort == "popular" else Media.created_at.desc(),
            Media.id.desc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await session.execute(query)
    items = result.scalars().all()

    out = [MediaOut.model_validate(m) for m in items]
    sign_media_urls(out, items, s3)
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
):
    """Информация о файле + URL для просмотра."""
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)

    board = await _check_media_board_access(request, session, media)
    data = MediaDetailOut.model_validate(media)
    data.board_slug = board.slug if board else ""
    data.url = build_media_url(media.id, s3, media.s3_key)
    return data


@router.get("/media/{media_id}/view", response_model=ViewResult)
async def media_view(
    media_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Отметить просмотр файла (дедупликация по IP за 24 часа)."""
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)
    await _check_media_board_access(request, session, media)
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
        session.add(ViewStat(media_id=media.id, ip_hash=iph))
        media.views_count += 1
        media.popularity_score = media.views_count * 0.3 + media.downloads_count * 0.7
        await session.commit()

    return ViewResult(media_id=media.id, counted=not already)


@router.get("/media/{media_id}/download", response_model=DownloadResult)
async def media_download(
    media_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Отметить скачивание и вернуть URL файла."""
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)
    if not media.s3_key:
        raise HTTPException(status_code=409, detail="File not available")

    await _check_media_board_access(request, session, media)
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
        session.add(DownloadStat(media_id=media.id, ip_hash=iph))
        media.downloads_count += 1
        media.popularity_score = media.views_count * 0.3 + media.downloads_count * 0.7
        await session.commit()

    return DownloadResult(media_id=media.id, counted=not already, url=url)


# ─────────────── Анонимная отдача файлов (прокси S3) ───────────────

# Размер чанка потоковой отдачи (256 КБ)
STREAM_CHUNK_SIZE = 256 * 1024


def _content_disposition(filename: str) -> str:
    """Content-Disposition с поддержкой не-ASCII имён (RFC 5987)."""
    fallback = re.sub(r"[^\w.\-]+", "_", filename) or "file"
    quoted = urllib.parse.quote(filename, safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quoted}'


@router.get("/media/{media_id}/raw")
async def media_raw(
    media_id: int,
    request: Request,
    download: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Отдаёт содержимое файла через наш API (S3-бакет клиенту не раскрывается).

    Поддерживает Range (видео, докачка) и Content-Disposition при `?download=1`.
    """
    await check_rate_limit(client_ip(request))

    media = await _get_visible_media(session, media_id)
    if not media.s3_key:
        raise HTTPException(status_code=404, detail="File not available")

    board = await _check_media_board_access(request, session, media)

    if not s3.is_configured:
        raise HTTPException(status_code=503, detail="Storage is not configured")

    obj = await s3.open_object_stream(media.s3_key, range_header=request.headers.get("range"))
    if obj is None or obj.get("body") is None:
        raise HTTPException(status_code=404, detail="File not found in storage")

    headers = {"Accept-Ranges": obj.get("accept_ranges") or "bytes"}
    if obj.get("content_length") is not None:
        headers["Content-Length"] = str(obj["content_length"])
    if obj.get("content_range"):
        headers["Content-Range"] = obj["content_range"]
    if obj.get("etag"):
        headers["ETag"] = obj["etag"]
    if download:
        headers["Content-Disposition"] = _content_disposition(media.original_name)
    headers["Cache-Control"] = (
        "private, max-age=3600" if board.is_private else "public, max-age=3600"
    )

    status_code = 206 if obj.get("content_range") else 200

    async def _stream():
        body = obj["body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    return StreamingResponse(
        _stream(),
        status_code=status_code,
        media_type=obj.get("content_type") or media.mime_type,
        headers=headers,
    )
