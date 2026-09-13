# src/api/routes/feed.py
"""Лента «Новинки»: свежие файлы по всем видимым доскам.

Добавлен в рамках этапа 6 (фронтенд): раздел «Новинки» сайта требует
единый пагинируемый поток без выбора конкретной доски.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import (
    VISIBLE_FILTER,
    apply_user_flags,
    sign_media_urls,
    visible_thread_clause,
)
from src.api.deps import check_rate_limit, client_ip, get_current_user, get_s3
from src.api.schemas import MediaListOut, MediaOut
from src.core.db import get_session
from src.core.models import Board, Media, User
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/feed", tags=["feed"])


def _as_naive_utc(value: datetime) -> datetime:
    """Приводит пришедшую с клиента дату к naive-UTC (так хранится в БД)."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def encode_cursor(created_at: datetime, media_id: int) -> str:
    """Курсор догрузки: `<created_at ISO>|<id>` — позиция последней карточки."""
    return f"{created_at.isoformat()}|{media_id}"


def decode_cursor(raw: str) -> Optional[tuple[datetime, int]]:
    """Разбирает курсор. `None` — мусор (выдаём первую страницу, не падаем)."""
    try:
        moment, raw_id = raw.split("|", 1)
        return datetime.fromisoformat(moment), int(raw_id)
    except (ValueError, TypeError):
        return None


@router.get("", response_model=MediaListOut)
async def media_feed(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    media_type: Optional[str] = Query(None, alias="type", pattern="^(image|video)$"),
    free_only: bool = Query(
        False, alias="free", description="Только файлы без премиум-подписки"
    ),
    since: Optional[datetime] = Query(
        None,
        description=(
            "Только файлы новее указанного момента (ISO 8601, UTC) — "
            "блок «новое с прошлого визита»"
        ),
    ),
    cursor: Optional[str] = Query(
        None,
        description=(
            "Курсор догрузки ленты (`<created_at>|<id>` из `next_cursor`): "
            "берём то, что **старее** курсора. Пока ленту листают, парсер добавляет "
            "файлы сверху — с курсором выдача не сдвигается и ничего не теряется."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    user: Optional[User] = Depends(get_current_user),
):
    """Свежие файлы со всех видимых досок (новинки), с пагинацией.

    Премиум-файлы тоже попадают в ленту, но с размытым превью (locked).
    `free=1` оставляет только файлы без подписки (чип «без подписки» на главной),
    `since=<ISO>` — только то, что появилось после указанного момента.

    Догрузка — по курсору (`cursor`), а не по offset: лента «живая», и без курсора
    новые файлы сдвигали бы страницы (часть карточек дублировалась, часть терялась).
    """
    await check_rate_limit(client_ip(request))

    filters = list(VISIBLE_FILTER) + [
        Board.is_visible.is_(True),
        visible_thread_clause(),
    ]
    if media_type:
        filters.append(Media.media_type == media_type)
    if free_only:
        filters.append(Media.is_premium.is_(False))
    if since:
        filters.append(Media.created_at > _as_naive_utc(since))

    # Курсор: всё, что строго старее последней показанной карточки
    anchor = decode_cursor(cursor) if cursor else None
    if anchor:
        anchor_ts, anchor_id = anchor
        filters.append(
            tuple_(Media.created_at, Media.id) < tuple_(anchor_ts, anchor_id)
        )
        # При курсорной догрузке страница всегда «первая»: позицию задаёт курсор
        offset = 0
    else:
        offset = (page - 1) * per_page

    # Подсчёт только видимых записей видимых досок
    count_q = (
        select(func.count())
        .select_from(Media)
        .join(Board, Board.id == Media.board_id)
        .where(*filters)
    )
    total = (await session.execute(count_q)).scalar()

    query = (
        select(Media)
        .join(Board, Board.id == Media.board_id)
        .where(*filters)
        .order_by(Media.created_at.desc(), Media.id.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await session.execute(query)
    items = result.scalars().all()

    out = [MediaOut.model_validate(m) for m in items]
    sign_media_urls(out, items, s3, user)
    # Метка текущего пользователя: без этого «лайк» на карточке гас после
    # перезагрузки страницы (в ленте marked всегда приходил false).
    await apply_user_flags(session, out, user)

    # Курсор следующей порции: берём позицию последней карточки этой страницы
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if len(items) == per_page else None
    )
    return MediaListOut(
        items=out,
        page=page,
        per_page=per_page,
        total=int(total or 0),
        next_cursor=next_cursor,
        has_more=bool(next_cursor),
    )
