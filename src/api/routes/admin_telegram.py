# src/api/routes/admin_telegram.py
"""Менеджер Telegram-канала: композер, дайджесты, расписание, карантин, розыгрыши.

Канал — витрина закрытого архива: пост ведёт в бота, а картинка собирается из наших
превью и размывается (канал не должен ловить блокировку за adult-контент).

Что умеет админка:

* **композер** — выбрать файлы (или подставить свежие/дайджест), поправить подпись,
  посмотреть предпросмотр и опубликовать;
* **дайджест** — подборка «за сутки/за неделю» с подписью по шаблону;
* **расписание** — `scheduled_at` в запросе ставит пост в очередь, её разбирает
  сервис `telegram-publisher`; отложенный пост можно отменить;
* **карантин** — автопост приходит админу в ЛС бота с кнопками «Опубликовать /
  Отклонить / Отложить», в канал ничего не уходит само;
* **розыгрыши** — анонс с кнопкой «Участвовать», выбор победителей и авто-выдача
  премиума, пост-итоги.

Каждая отправка пишется в `telegram_posts` со статусом, id сообщения и текстом ошибки,
чтобы видеть историю и повторять неудачные.

Отдельный файл по аналогии с `admin_feedback.py` и `admin_reports.py`: `admin.py`
уже большой, а здесь своя тема.
"""
from __future__ import annotations

import asyncio
import base64
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, asset_url, visible_thread_clause
from src.api.deps import get_s3, verify_admin
from src.api.schemas import (
    GiveawayIn,
    GiveawayOut,
    TelegramAutopostIn,
    TelegramAutopostOut,
    TelegramCandidateOut,
    TelegramDigestOut,
    TelegramPostIn,
    TelegramPostListOut,
    TelegramPostOut,
    TelegramPreviewOut,
)
from src.core.config import settings
from src.core.db import get_session
from src.core.models import Board, Giveaway, GiveawayEntry, Media, TelegramPost, User
from src.services import telegram_api, telegram_publisher, telegram_service
from src.services.analytics import record_audit
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/admin/telegram", tags=["admin-telegram"])

STATUSES = ("draft", "scheduled", "published", "failed", "deleted", "cancelled", "rejected")
KINDS = ("teaser", "digest", "announce")
IMAGE_MODES = ("mosaic", "single", "none")
MAX_TILES = 4


async def verify_bot_token(request: Request) -> None:
    """Пускает только бота: он подтверждает черновики карантина кнопками в ЛС админа."""
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    sent = (request.headers.get("x-bot-token") or "").strip()
    if not token or sent != token:
        raise HTTPException(status_code=403, detail="Доступно только боту")


def _post_out(post: TelegramPost) -> TelegramPostOut:
    """Запись журнала + ссылка на сообщение в канале (если она есть)."""
    out = TelegramPostOut.model_validate(post)
    out.link = telegram_service.link_for(post)
    return out


# Обратная совместимость внутри модуля: раньше функция называлась `_out`
_out = _post_out



async def _load_media(session: AsyncSession, media_ids: List[int]) -> List[Media]:
    """Файлы для тизера — в порядке выбора, только видимые и уникальные."""
    ordered: List[int] = []
    for media_id in media_ids:
        if media_id not in ordered:
            ordered.append(media_id)
    if not ordered:
        return []

    rows = await session.execute(
        select(Media).where(
            Media.id.in_(ordered[:MAX_TILES]), *VISIBLE_FILTER, visible_thread_clause()
        )
    )
    found = {item.id: item for item in rows.scalars().all()}
    return [found[media_id] for media_id in ordered if media_id in found][:MAX_TILES]


async def _tile_bytes(s3: S3Storage, items: List[Media], limit: int) -> List[bytes]:
    """Байты превью выбранных файлов: `thumb`, иначе размытый вариант.

    У видео `thumb` — это постер, поэтому отдельная ветка не нужна. Файлы качаем
    во временный каталог и читаем в память: дальше с ними работает PIL.
    """
    picked = [item for item in items if item.s3_key][:limit]
    if not picked:
        return []

    payloads: List[bytes] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, item in enumerate(picked):
            variants = item.variants or {}
            key = variants.get("thumb") or variants.get("thumb_blur")
            if not key:
                continue
            path = Path(tmp) / f"tile_{index}"
            try:
                if await s3.download_to_file(key, path):
                    payloads.append(path.read_bytes())
            except Exception:  # noqa: BLE001 — один битый дериватив не ломает пост
                continue
            finally:
                path.unlink(missing_ok=True)
    return payloads


async def _latest_items(session: AsyncSession, limit: int = MAX_TILES) -> List[Media]:
    """Четыре самых свежих файла архива — когда админ ничего не выбрал вручную.

    Предпросмотр и публикация используют один и тот же подбор, иначе админ видел бы
    в предпросмотре мозаику, а в канал уходил текстовый пост.
    """
    rows = await session.execute(
        select(Media)
        .where(
            *VISIBLE_FILTER,
            visible_thread_clause(),
            Media.is_premium.is_(False),
        )
        .order_by(Media.created_at.desc(), Media.id.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def _board_slugs(session: AsyncSession, items: List[Media]) -> List[str]:
    """Слаги разделов выбранных файлов — в подписи постов перечисляем разделы."""
    board_ids = sorted({item.board_id for item in items})
    if not board_ids:
        return []
    rows = await session.execute(
        select(Board.slug).where(Board.id.in_(board_ids)).order_by(Board.slug)
    )
    return [slug for (slug,) in rows.all()]


def _mode(payload: TelegramPostIn) -> str:
    return payload.image_mode if payload.image_mode in IMAGE_MODES else "mosaic"


def _caption(payload: TelegramPostIn, boards: List[str], total: int) -> str:
    return telegram_publisher.build_caption(
        payload.kind,
        boards=boards,
        media_total=total,
        text=payload.text,
        bot_username=settings.TELEGRAM_BOT_USERNAME,
    )


def _button(payload: TelegramPostIn) -> tuple[str, str]:
    """Кнопка под постом: по умолчанию ведёт в бота (сайт закрытый)."""
    label = (payload.button_text or "").strip()
    if not label and settings.TELEGRAM_BOT_USERNAME:
        label = "Открыть в боте"
    url = (payload.button_url or "").strip() or telegram_publisher.bot_url(
        settings.TELEGRAM_BOT_USERNAME
    )
    return label, url


async def _render_image(
    s3: S3Storage,
    items: List[Media],
    mode: str,
    blur: int,
) -> Optional[bytes]:
    """Картинка тизера: мозаика 2×2, одиночный кадр или без картинки."""
    if mode == "none":
        return None
    tiles = await _tile_bytes(s3, items, 1 if mode == "single" else MAX_TILES)
    if not tiles:
        return None
    return await asyncio.to_thread(telegram_publisher.build_teaser_image, tiles, blur=blur)


@router.get("/status")
async def telegram_status(_=Depends(verify_admin)):
    """Настройки публикации: задан ли токен бота и канал (для композера)."""
    return {
        "configured": telegram_api.is_configured(),
        "channel": (settings.TELEGRAM_CHANNEL or "").lstrip("@") or None,
        "bot": settings.TELEGRAM_BOT_USERNAME or None,
        "chat": telegram_api.channel_chat_id() if telegram_api.is_configured() else None,
        "kinds": list(KINDS),
        "image_modes": list(IMAGE_MODES),
        "default_blur": telegram_publisher.DEFAULT_BLUR,
    }


@router.get("/posts", response_model=TelegramPostListOut)
async def list_posts(
    status: str = Query("all", pattern="^(all|draft|scheduled|published|failed|deleted|cancelled|rejected)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Журнал постов: свежие сверху + счётчики по статусам для фильтров."""
    conditions = [] if status == "all" else [TelegramPost.status == status]

    total = (
        await session.execute(
            select(func.count()).select_from(TelegramPost).where(*conditions)
        )
    ).scalar() or 0

    rows = await session.execute(
        select(TelegramPost)
        .where(*conditions)
        .order_by(TelegramPost.created_at.desc(), TelegramPost.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = [_out(post) for post in rows.scalars().all()]

    counters = await session.execute(
        select(TelegramPost.status, func.count()).group_by(TelegramPost.status)
    )
    counts = {name: int(count) for name, count in counters.all()}
    counts["all"] = sum(counts.values())
    return TelegramPostListOut(items=items, total=int(total), counts=counts)


@router.get("/candidates", response_model=List[TelegramCandidateOut])
async def candidates(
    board: Optional[str] = Query(None, description="Слаг раздела (пусто — все разделы)"),
    limit: int = Query(24, ge=4, le=96),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Свежие файлы архива — галерея выбора для тизера.

    Премиум-файлы не предлагаем: они доступны только подписчикам, а канал должен
    показывать то, что человек увидит после входа.
    """
    query = (
        select(Media.id, Media.media_type, Media.variants, Board.slug)
        .join(Board, Board.id == Media.board_id)
        .where(
            *VISIBLE_FILTER,
            visible_thread_clause(),
            Media.is_premium.is_(False),
            Board.is_visible.is_(True),
        )
        .order_by(Media.created_at.desc(), Media.id.desc())
        .limit(limit)
    )
    if board:
        query = query.where(Board.slug == board)

    rows = await session.execute(query)
    items: List[TelegramCandidateOut] = []
    for media_id, media_type, variants, slug in rows.all():
        variants = variants or {}
        thumb = variants.get("thumb") or variants.get("thumb_blur")
        kind = "thumb" if variants.get("thumb") else "thumb_blur"
        items.append(
            TelegramCandidateOut(
                id=media_id,
                media_type=media_type or "image",
                thumb_url=asset_url(media_id, kind, thumb) if thumb else None,
                board_slug=slug,
            )
        )
    return items


@router.post("/preview", response_model=TelegramPreviewOut)
async def preview_post(
    payload: TelegramPostIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Предпросмотр тизера: текст и картинка — без публикации.

    Если файлы не выбраны, берём четыре самых свежих: админ сразу видит, как будет
    выглядеть пост, и может просто нажать «Опубликовать».
    """
    items = await telegram_service.load_media(session, payload.media_ids)
    if not items:
        items = await telegram_service.latest_media(session)

    boards = await telegram_service.board_slugs(session, items)
    caption = telegram_service.caption_for(
        kind=payload.kind, boards=boards, total=len(items), text=payload.text, period=payload.period
    )
    mode = payload.image_mode if payload.image_mode in IMAGE_MODES else "mosaic"
    image = await telegram_service.render_image(
        s3, items, mode, max(0, min(24, payload.blur))
    )

    configured = telegram_api.is_configured()
    return TelegramPreviewOut(
        caption=caption,
        image_data_url=("data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")) if image else None,
        chat=telegram_api.channel_chat_id() if configured else None,
        configured=configured,
        warning=None if configured else "Публикация недоступна: проверьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHANNEL",
    )


async def _publish(
    session: AsyncSession,
    s3: S3Storage,
    payload: TelegramPostIn,
    *,
    actor: str,
) -> TelegramPostOut:
    """Публикация в канал: сборка тизера, отправка и запись в журнал.

    Ошибка Telegram не «выбрасывается» молча: она остаётся в журнале (status=failed,
    текст ошибки) — админ видит причину и может повторить отправку.
    """
    items = await _load_media(session, payload.media_ids)
    if not items:
        items = await _latest_items(session)
    boards = await _board_slugs(session, items)
    caption = _caption(payload, boards, len(items))
    mode = _mode(payload)
    label, url = _button(payload)

    post = TelegramPost(
        kind=payload.kind if payload.kind in KINDS else "teaser",
        caption=caption,
        media_ids=[item.id for item in items] or None,
        image_mode=mode,
        button_text=label or None,
        button_url=url or None,
        channel=(settings.TELEGRAM_CHANNEL or "").lstrip("@") or None,
        created_by=actor,
    )
    session.add(post)

    if not telegram_api.is_configured():
        post.status = "failed"
        post.error = "Публикация не настроена: нет токена бота или канала"
        await record_audit(session, action="telegram.post", target="—", details="не настроено")
        await session.commit()
        await session.refresh(post)
        return _out(post)

    try:
        image = await _render_image(s3, items, mode, max(0, min(24, payload.blur)))
        if image:
            result = await telegram_api.send_photo(
                photo=image, caption=caption, button_text=label, button_url=url
            )
        else:
            result = await telegram_api.send_message(
                text=caption, button_text=label, button_url=url
            )
        post.status = "published"
        post.published_at = datetime.utcnow()
        post.message_id = result.get("message_id")
        details = f"{post.kind}: опубликовано (файлов: {len(items)})"
    except Exception as exc:  # noqa: BLE001 — текст ошибки нужен в админке
        post.status = "failed"
        post.error = str(exc)[:500]
        details = f"{post.kind}: ошибка — {post.error}"

    await record_audit(
        session, action="telegram.post", target=str(post.message_id or "—"), details=details
    )
    await session.commit()
    await session.refresh(post)
    return _out(post)


@router.get("/digest", response_model=TelegramDigestOut)
async def digest_preview(
    period: str = Query("day", pattern="^(day|week)$"),
    board: Optional[str] = Query(None, description="Слаг раздела (пусто — все)"),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Подборка для дайджеста: файлы за сутки или неделю и готовая подпись.

    Композер подставляет это в форму — админ смотрит предпросмотр и публикует.
    """
    items = await telegram_service.digest_media(session, period=period, board=board)
    boards = await telegram_service.board_slugs(session, items)
    caption = telegram_service.caption_for(
        kind="digest", boards=boards, total=len(items), period=period
    )
    return TelegramDigestOut(
        media_ids=[item.id for item in items], boards=boards, caption=caption, period=period
    )


@router.get("/autopost", response_model=TelegramAutopostOut)
async def get_autopost(_=Depends(verify_admin), session: AsyncSession = Depends(get_session)):
    """Настройки автопостинга + подсказка, можно ли запускать сейчас."""
    row = await telegram_service.get_autopost(session)
    allowed, reason = await telegram_service.autopost_allowed(session, row)
    out = TelegramAutopostOut.model_validate(row)
    out.published_last_day = await telegram_service.published_last_day(session)
    out.allowed = allowed
    out.reason = reason or None
    return out


@router.patch("/autopost", response_model=TelegramAutopostOut)
async def update_autopost(
    payload: TelegramAutopostIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Меняет настройки автопостинга: лимит, окна тишины, карантин, разделы."""
    row = await telegram_service.get_autopost(session)

    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.posts_per_day is not None:
        row.posts_per_day = max(1, min(10, payload.posts_per_day))
    if payload.quiet_from is not None:
        row.quiet_from = max(0, min(23, payload.quiet_from))
    if payload.quiet_to is not None:
        row.quiet_to = max(0, min(23, payload.quiet_to))
    if payload.require_approval is not None:
        row.require_approval = payload.require_approval
    if payload.boards is not None:
        row.boards = [item.strip().lstrip("/") for item in payload.boards if item.strip()] or None
    if payload.period is not None:
        row.period = "week" if payload.period == "week" else "day"
    if payload.blur is not None:
        row.blur = max(0, min(24, payload.blur))

    await record_audit(
        session,
        action="telegram.autopost",
        target="settings",
        details=f"включён: {row.enabled}, карантин: {row.require_approval}, лимит: {row.posts_per_day}",
    )
    await session.commit()
    await session.refresh(row)

    allowed, reason = await telegram_service.autopost_allowed(session, row)
    out = TelegramAutopostOut.model_validate(row)
    out.published_last_day = await telegram_service.published_last_day(session)
    out.allowed = allowed
    out.reason = reason or None
    return out

@router.post("/post", response_model=TelegramPostOut)
async def publish_post(
    payload: TelegramPostIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Публикует пост в канал — кнопка «Опубликовать» в композере.

    Если в запросе есть `scheduled_at`, пост не уходит сразу, а встаёт в очередь:
    планировщик отправит его в назначенное время.
    """
    if payload.scheduled_at:
        post = await telegram_service.schedule_post(
            session,
            scheduled_at=payload.scheduled_at,
            kind=payload.kind,
            media_ids=payload.media_ids,
            image_mode=payload.image_mode,
            text=payload.text,
            period=payload.period,
            button_text=payload.button_text,
            button_url=payload.button_url,
        )
        return _post_out(post)

    post = await telegram_service.publish_now(
        session,
        s3,
        kind=payload.kind,
        media_ids=payload.media_ids,
        image_mode=payload.image_mode,
        blur=payload.blur,
        text=payload.text,
        period=payload.period,
        button_text=payload.button_text,
        button_url=payload.button_url,
    )
    return _post_out(post)


@router.post("/posts/{post_id}/retry", response_model=TelegramPostOut)
async def retry_post(
    post_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Повторяет публикацию из журнала.

    Текст берём сохранённый (`caption`), картинку пересобираем из тех же файлов:
    «повторить» не меняет пост, который админ уже видел перед отправкой.
    """
    post = (
        await session.execute(select(TelegramPost).where(TelegramPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Пост не найден")

    items = await _load_media(session, list(post.media_ids or []))
    label, url = post.button_text or "", post.button_url or ""

    if not telegram_api.is_configured():
        post.status = "failed"
        post.error = "Публикация не настроена: нет токена бота или канала"
        await session.commit()
        await session.refresh(post)
        return _out(post)

    try:
        image = await _render_image(
            s3, items, post.image_mode or "mosaic", telegram_publisher.DEFAULT_BLUR
        )
        if image:
            result = await telegram_api.send_photo(
                photo=image, caption=post.caption, button_text=label, button_url=url
            )
        else:
            result = await telegram_api.send_message(
                text=post.caption, button_text=label, button_url=url
            )
        post.status = "published"
        post.published_at = datetime.utcnow()
        post.message_id = result.get("message_id")
        post.error = None
        details = f"повтор #{post.id}: опубликовано"
    except Exception as exc:  # noqa: BLE001
        post.status = "failed"
        post.error = str(exc)[:500]
        details = f"повтор #{post.id}: ошибка — {post.error}"

    await record_audit(
        session, action="telegram.retry", target=str(post.message_id or post.id), details=details
    )
    await session.commit()
    await session.refresh(post)
    return _out(post)


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Убирает пост: отменяет запланированный или удаляет сообщение из канала.

    Нужно для отката: заметили опечатку в уже опубликованном посте — удаляем
    сообщение, правим текст и публикуем заново. Отложенный пост просто отменяем,
    в канал он не уйдёт.
    """
    post = await _post_or_404(session, post_id)

    if post.status == "scheduled":
        post.status = "cancelled"
        await record_audit(
            session, action="telegram.cancel", target=str(post.id), details="отложенный пост отменён"
        )
        await session.commit()
        await session.refresh(post)
        return _post_out(post)

    if post.message_id and telegram_api.is_configured():
        try:
            await telegram_api.delete_message(int(post.message_id))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"Telegram не удалил сообщение: {exc}"
            ) from exc

    post.status = "deleted"
    await record_audit(
        session, action="telegram.delete", target=str(post.message_id or post.id)
    )
    await session.commit()
    await session.refresh(post)
    return _post_out(post)


@router.post("/autopost/run", response_model=TelegramPostOut)
async def run_autopost(
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Собирает автопост прямо сейчас: при карантине — черновик в ЛС админам.

    Кнопка «Собрать сейчас» в админке: удобно проверить, что карантин доходит,
    и не ждать, пока планировщик решит, что пора.
    """
    row = await telegram_service.get_autopost(session)

    if row.require_approval:
        post = await telegram_service.make_draft(
            session, s3, period=row.period, board=(row.boards or [None])[0]
        )
        return _post_out(post)

    post = await telegram_service.publish_now(
        session,
        s3,
        kind="digest",
        media_ids=[],
        image_mode="mosaic",
        blur=row.blur,
        period=row.period,
        actor="autopost",
    )
    row.last_post_at = datetime.utcnow()
    await session.commit()
    return _post_out(post)


async def _post_or_404(session: AsyncSession, post_id: int) -> TelegramPost:
    post = (
        await session.execute(select(TelegramPost).where(TelegramPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Пост не найден")
    return post


@router.post("/posts/{post_id}/approve", response_model=TelegramPostOut)
async def approve_post(
    post_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
    _=Depends(verify_bot_token),
):
    """Карантин: админ подтвердил черновик кнопкой в ЛС бота — отправляем в канал."""
    post = await _post_or_404(session, post_id)
    if post.status != "draft":
        return _post_out(post)

    items = await telegram_service.load_media(session, list(post.media_ids or []))
    if not items:
        items = await telegram_service.latest_media(session)
    await telegram_service._deliver(
        session, s3, post, items, label=post.button_text or "", url=post.button_url or ""
    )
    await session.commit()
    await session.refresh(post)
    return _post_out(post)


@router.post("/posts/{post_id}/reject", response_model=TelegramPostOut)
async def reject_post(
    post_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _=Depends(verify_bot_token),
):
    """Карантин: админ отклонил черновик — в канал он не уйдёт."""
    post = await _post_or_404(session, post_id)
    if post.status == "draft":
        post.status = "rejected"
        await record_audit(
            session, action="telegram.reject", target=str(post.id), details="карантин отклонён"
        )
        await session.commit()
        await session.refresh(post)
    return _post_out(post)


@router.post("/posts/{post_id}/later", response_model=TelegramPostOut)
async def later_post(
    post_id: int,
    request: Request,
    hours: int = Query(2, ge=1, le=48),
    session: AsyncSession = Depends(get_session),
    _=Depends(verify_bot_token),
):
    """Карантин: «отложить» — ставим черновик в очередь через N часов."""
    post = await _post_or_404(session, post_id)
    if post.status != "draft":
        return _post_out(post)

    post.status = "scheduled"
    post.scheduled_at = datetime.utcnow() + timedelta(hours=hours)
    await record_audit(
        session, action="telegram.later", target=str(post.id), details=f"отложено на {hours} ч"
    )
    await session.commit()
    await session.refresh(post)
    return _post_out(post)


# ── Розыгрыши ────────────────────────────────────────────────────────

async def _giveaway_or_404(session: AsyncSession, giveaway_id: int) -> Giveaway:
    item = (
        await session.execute(select(Giveaway).where(Giveaway.id == giveaway_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    return item


async def _giveaway_entries(session: AsyncSession, giveaway_id: int) -> int:
    total = (
        await session.execute(
            select(func.count())
            .select_from(GiveawayEntry)
            .where(GiveawayEntry.giveaway_id == giveaway_id)
        )
    ).scalar()
    return int(total or 0)


def _giveaway_out(item: Giveaway, entries: int) -> GiveawayOut:
    """Розыгрыш для админки: число участников и ссылка на пост-анонс."""
    out = GiveawayOut.model_validate(item)
    out.entries = entries
    channel = (settings.TELEGRAM_CHANNEL or "").lstrip("@")
    if channel and item.announce_message_id and not channel.startswith("-"):
        out.link = f"https://t.me/{channel}/{item.announce_message_id}"
    return out


@router.get("/giveaways", response_model=List[GiveawayOut])
async def list_giveaways(
    limit: int = Query(20, ge=1, le=100),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Последние розыгрыши с числом участников — для панели админки."""
    rows = await session.execute(
        select(Giveaway).order_by(Giveaway.created_at.desc()).limit(limit)
    )
    items = list(rows.scalars().all())
    return [_giveaway_out(item, await _giveaway_entries(session, item.id)) for item in items]


@router.post("/giveaways", response_model=GiveawayOut)
async def create_giveaway(
    payload: GiveawayIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Создаёт розыгрыш: пока черновик, анонс публикуется отдельной кнопкой."""
    item = await telegram_service.create_giveaway(
        session,
        kind=payload.kind,
        prize_days=payload.prize_days,
        title=payload.title or "",
        hours=payload.hours,
    )
    return _giveaway_out(item, 0)


@router.post("/giveaways/{giveaway_id}/announce", response_model=GiveawayOut)
async def announce_giveaway(
    giveaway_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Публикует пост-анонс в канале с кнопкой «Участвовать» (deep-link в бота)."""
    item = await _giveaway_or_404(session, giveaway_id)
    if not telegram_api.is_configured():
        raise HTTPException(
            status_code=409, detail="Публикация не настроена: нет токена бота или канала"
        )
    await telegram_service.announce_giveaway(session, item)
    return _giveaway_out(item, await _giveaway_entries(session, item.id))


@router.post("/giveaways/{giveaway_id}/draw", response_model=GiveawayOut)
async def draw_giveaway(
    giveaway_id: int,
    count: int = Query(1, ge=1, le=10),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Разыгрывает приз: выбирает победителей и сразу выдаёт им премиум."""
    item = await _giveaway_or_404(session, giveaway_id)
    await telegram_service.draw_winners(session, item, count=count)
    return _giveaway_out(item, await _giveaway_entries(session, item.id))


@router.post("/giveaways/{giveaway_id}/results", response_model=GiveawayOut)
async def giveaway_results(
    giveaway_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Публикует в канале итоги розыгрыша (победители и выданный приз)."""
    item = await _giveaway_or_404(session, giveaway_id)
    if not telegram_api.is_configured():
        raise HTTPException(
            status_code=409, detail="Публикация не настроена: нет токена бота или канала"
        )
    await telegram_service.publish_giveaway_results(session, item)
    return _giveaway_out(item, await _giveaway_entries(session, item.id))


@router.post("/giveaways/join")
async def join_giveaway(
    request: Request,
    telegram_id: int = Query(..., description="Участник (передаёт бот после проверки подписки)"),
    session: AsyncSession = Depends(get_session),
    _=Depends(verify_bot_token),
):
    """Участие в активном розыгрыше: бот передаёт telegram_id, мы находим аккаунт.

    Условие «быть подписанным на канал» проверяет бот (`getChatMember`) — сюда
    приходит уже подтверждённый участник. Один аккаунт — одно участие.
    """
    user = (
        await session.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if user is None:
        return {
            "status": "unknown",
            "detail": "Аккаунт не привязан: откройте архив по ссылке из бота и вернитесь",
        }

    giveaway, already = await telegram_service.join_giveaway(session, user)
    if giveaway is None:
        return {"status": "none", "detail": "Активных розыгрышей нет"}

    return {
        "status": "already" if already else "joined",
        "giveaway_id": giveaway.id,
        "title": giveaway.title,
        "prize_days": giveaway.prize_days,
        "ends_at": giveaway.ends_at.isoformat(),
    }

