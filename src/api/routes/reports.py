# src/api/routes/reports.py
"""Жалобы на файлы: кнопка «Пожаловаться» в лайтбоксе и на странице файла.

Жалоба — часть модерации: контент должен скрываться за минуты, а не «когда-нибудь».
Поэтому жалоба с причиной `csam` закрывает доступ **сразу**: файл и его тред
скрываются, хеш уходит в блок-лист (чтобы файл не вернулся пересканированием или
архивным импортом), и админам уходит письмо. Остальные причины попадают в очередь
админки (`/admin/reports`), где модератор решает: скрыть файл, скрыть тред,
удалить файл или отклонить жалобу.

Жалобу может отправить только вошедший зритель (сайт закрытый), а открытая жалоба
у пары (пользователь, файл) одна: повторная отправка обновляет причину и текст.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import VISIBLE_FILTER, asset_url
from src.api.deps import check_rate_limit, client_ip, ip_hash, require_user
from src.api.schemas import MediaReportIn, MediaReportOut
from src.core.config import settings
from src.core.db import get_session
from src.core.models import BlockedHash, Media, MediaReport, ThreadState, User
from src.services import mailer
from src.services.analytics import record_audit

router = APIRouter(prefix="/api/v1/media", tags=["reports"])

# Причины жалобы: подпись нужна в письме админам и в админке
REASONS = {
    "csam": "детская безопасность",
    "copyright": "авторские права",
    "illegal": "запрещённый контент",
    "spam": "спам или реклама",
    "other": "другое",
}
MAX_COMMENT = 2000


def reason_label(reason: str) -> str:
    """Человеческая подпись причины (для письма и админки)."""
    return REASONS.get(reason, REASONS["other"])


async def _notify_admins(subject: str, text: str) -> None:
    """Письмо админам о жалобе: фоном, ошибка почты не мешает приёму жалобы."""
    for address in settings.admin_emails:
        try:
            await mailer.send_mail(address, subject, text)
        except Exception as exc:  # noqa: BLE001 — жалоба важнее письма
            print(f"   [mail] Жалоба: не удалось отправить {address} ({exc})")


async def hide_media_and_thread(
    session: AsyncSession,
    media: Media,
    *,
    reason: str,
    actor: str,
    block_hash: bool = True,
) -> None:
    """Скрывает файл и весь его тред, при необходимости ставит хеш в блок-лист.

    Такой порядок важен: пока модератор открывает очередь, контент уже недоступен
    на сайте и в лентах, а через блок-лист он не вернётся ни при пересканировании,
    ни при повторном импорте из архива.
    """
    media.is_visible = False

    thread = (
        await session.execute(
            select(ThreadState).where(
                ThreadState.board_id == media.board_id,
                ThreadState.thread_id == media.thread_id,
            )
        )
    ).scalar_one_or_none()
    if thread is not None:
        thread.is_visible = False

    # Скрываем все файлы треда: тред не должен «просвечивать» через соседей
    siblings = (
        await session.execute(
            select(Media).where(
                Media.board_id == media.board_id, Media.thread_id == media.thread_id
            )
        )
    ).scalars().all()
    for item in siblings:
        item.is_visible = False

    if block_hash and media.file_hash:
        exists = (
            await session.execute(
                select(BlockedHash).where(BlockedHash.sha256 == media.file_hash)
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                BlockedHash(
                    sha256=media.file_hash,
                    reason="csam" if reason == "csam" else "other",
                    note=f"автоскрытие по жалобе на файл #{media.id}",
                    created_by=actor,
                )
            )

    await record_audit(
        session,
        action="report.autohide",
        target=str(media.id),
        details=f"причина: {reason}; файл и тред скрыты автоматически",
    )


@router.post("/{media_id}/report", response_model=MediaReportOut)
async def report_media(
    media_id: int,
    payload: MediaReportIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
) -> MediaReportOut:
    """Принимает жалобу на файл: пишет её в очередь модерации.

    Повторная жалоба того же зрителя на тот же файл не плодит записи, а уточняет
    причину и комментарий (в ответе — 200 вместо 201). Причина `csam` закрывает
    доступ немедленно, письмо админам уходит в любом случае.
    """
    ip = client_ip(request)
    await check_rate_limit(ip, limit=max(3, settings.API_RATE_LIMIT // 20), scope="report")

    media = (
        await session.execute(select(Media).where(Media.id == media_id, *VISIBLE_FILTER))
    ).scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=404, detail="Файл не найден")

    reason = payload.reason if payload.reason in REASONS else "other"
    comment = (payload.comment or "").strip()[:MAX_COMMENT] or None

    existing = (
        await session.execute(
            select(MediaReport).where(
                MediaReport.media_id == media_id,
                MediaReport.user_id == user.id,
                MediaReport.status == "open",
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.reason = reason
        existing.comment = comment
        item = existing
        response.status_code = 200
    else:
        item = MediaReport(
            media_id=media_id,
            user_id=user.id,
            reason=reason,
            comment=comment,
            ip_hash=ip_hash(ip),
        )
        session.add(item)

    # Опасные причины закрываем сразу: контент не ждёт модератора
    if reason == "csam":
        await hide_media_and_thread(
            session, media, reason=reason, actor=f"user:{user.id}"
        )

    await session.commit()
    await session.refresh(item)

    if settings.admin_emails and mailer.is_configured():
        who = (
            user.email
            or (f"@{user.telegram_username}" if user.telegram_username else f"аккаунт #{user.id}")
        )
        text = (
            f"{'СРОЧНО: ' if reason == 'csam' else ''}Жалоба на файл #{media_id}\n"
            f"Причина: {reason_label(reason)}\n"
            f"От: {who}\n"
            f"Когда: {item.created_at:%d.%m.%Y %H:%M} UTC\n"
            f"Файл: {media.original_name} (раздел #{media.board_id}, тред #{media.thread_id})\n\n"
            f"{comment or '(без комментария)'}\n\n"
            f"— Разобрать: /admin/reports\n"
        )
        subject = f"Dredger: жалоба #{item.id} — {reason_label(reason)}"
        asyncio.create_task(_notify_admins(subject, text))

    out = MediaReportOut.model_validate(item)
    out.reason_label = reason_label(item.reason)
    out.media_name = media.original_name
    out.thread_id = media.thread_id
    out.media_type = media.media_type
    out.media_visible = media.is_visible
    variants = media.variants or {}
    thumb = variants.get("thumb") or variants.get("thumb_blur")
    out.thumb_url = asset_url(media.id, "thumb", thumb) if thumb else None
    out.reporter = (
        user.email
        or (f"@{user.telegram_username}" if user.telegram_username else None)
    )
    return out
