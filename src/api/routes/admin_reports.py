# src/api/routes/admin_reports.py
"""Модерация: очередь жалоб и блок-лист хешей (админка, фаза 5).

Очередь показывает не только текст жалобы, но и сам файл (миниатюра, раздел, тред,
видимость) — модератор решает по картинке, не открывая сайт. Действия: скрыть
файл, скрыть тред, удалить файл вместе с объектами в S3 или отклонить жалобу;
каждое пишется в `admin_audit`.

Блок-лист хешей — для запрещённого контента (в первую очередь CSAM): файл с таким
SHA-256 не публикуется. При добавлении хеша существующие файлы скрываются сразу,
а новые пайплайн сохраняет скрытыми (`src/services/pipeline.py`).

Отдельный файл, потому что `admin.py` уже большой, а здесь своя тема — как
`admin_feedback.py` для обращений.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import asset_url
from src.api.deps import get_s3, verify_admin
from src.api.routes.reports import REASONS, hide_media_and_thread, reason_label
from src.api.schemas import (
    BlockedHashIn,
    BlockedHashOut,
    MediaReportListOut,
    MediaReportOut,
    MediaReportUpdate,
)
from src.core.db import get_session
from src.core.models import BlockedHash, Board, Media, MediaReport, ThreadState, User
from src.services.analytics import record_audit
from src.services.s3_storage import S3Storage

router = APIRouter(prefix="/api/v1/admin", tags=["admin-reports"])

STATUSES = ("open", "hidden", "thread_hidden", "removed", "rejected")
ACTIONS = ("hide_media", "hide_thread", "remove_media", "reject")
HASH_REASONS = ("csam", "copyright", "other")


def _out(
    report: MediaReport,
    media: Optional[Media] = None,
    board_slug: Optional[str] = None,
    email: Optional[str] = None,
    telegram: Optional[str] = None,
) -> MediaReportOut:
    """Жалоба + контекст файла и автора (без второго запроса на каждую строку)."""
    out = MediaReportOut.model_validate(report)
    out.reason_label = reason_label(report.reason)
    if media is not None:
        out.media_name = media.original_name
        out.board_slug = board_slug
        out.thread_id = media.thread_id
        out.media_type = media.media_type
        out.media_visible = media.is_visible
        variants = media.variants or {}
        thumb = variants.get("thumb") or variants.get("thumb_blur")
        out.thumb_url = asset_url(media.id, "thumb", thumb) if thumb else None
    out.reporter = email or (f"@{telegram}" if telegram else None)
    return out


async def _media_of(session: AsyncSession, media_id: int) -> Media:
    """Файл жалобы (нужен и для действий, и для контекста в ответе)."""
    media = (
        await session.execute(select(Media).where(Media.id == media_id))
    ).scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=404, detail="Файл жалобы не найден")
    return media


@router.get("/reports", response_model=MediaReportListOut)
async def list_reports(
    status: str = Query("open", pattern="^(all|open|hidden|thread_hidden|removed|rejected)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Очередь жалоб: свежие сверху + счётчики по статусам для фильтров."""
    conditions = [] if status == "all" else [MediaReport.status == status]

    total = (
        await session.execute(
            select(func.count()).select_from(MediaReport).where(*conditions)
        )
    ).scalar() or 0

    rows = await session.execute(
        select(MediaReport, Media, Board.slug, User.email, User.telegram_username)
        .join(Media, Media.id == MediaReport.media_id)
        .outerjoin(Board, Board.id == Media.board_id)
        .outerjoin(User, User.id == MediaReport.user_id)
        .where(*conditions)
        .order_by(MediaReport.created_at.desc(), MediaReport.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = [
        _out(report, media, board_slug, email, telegram)
        for report, media, board_slug, email, telegram in rows.all()
    ]

    # Счётчики по всей таблице: на чипах всегда полная картина
    counter_rows = await session.execute(
        select(MediaReport.status, func.count()).group_by(MediaReport.status)
    )
    counts = {name: int(count) for name, count in counter_rows.all()}
    counts["all"] = sum(counts.values())

    return MediaReportListOut(items=items, total=int(total), counts=counts)


@router.get("/reports/count")
async def reports_open_count(_=Depends(verify_admin), session: AsyncSession = Depends(get_session)):
    """Сколько жалоб ждёт разбора — для бейджа во вкладке админки."""
    open_count = (
        await session.execute(
            select(func.count()).select_from(MediaReport).where(MediaReport.status == "open")
        )
    ).scalar() or 0
    return {"open": int(open_count)}


@router.get("/reports/reasons")
async def report_reasons(_=Depends(verify_admin)):
    """Причины жалоб для фильтров и подписей в админке."""
    return [{"value": value, "label": label} for value, label in REASONS.items()]


@router.patch("/reports/{report_id}", response_model=MediaReportOut)
async def resolve_report(
    report_id: int,
    payload: MediaReportUpdate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
    s3: S3Storage = Depends(get_s3),
):
    """Разбор жалобы: скрыть файл, скрыть тред, удалить файл или отклонить.

    «Удалить файл» уносит и объекты в хранилище (оригинал + деривативы): требование
    правообладателя должно выполняться, а не откладываться. Остальные открытые
    жалобы на удалённый файл автоматически отклоняются — иначе очередь копила бы
    заявки на контент, которого уже нет.
    """
    if payload.action not in ACTIONS:
        raise HTTPException(
            status_code=400, detail=f"Ожидается действие: {', '.join(ACTIONS)}"
        )

    report = (
        await session.execute(select(MediaReport).where(MediaReport.id == report_id))
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Жалоба не найдена")

    media = await _media_of(session, report.media_id)
    keep_media = True

    if payload.action == "hide_media":
        media.is_visible = False
        report.status = "hidden"
        details = "файл скрыт"
    elif payload.action == "hide_thread":
        await hide_media_and_thread(
            session, media, reason=report.reason, actor="admin-token", block_hash=False
        )
        report.status = "thread_hidden"
        details = "тред скрыт (файлы треда тоже)"
    elif payload.action == "remove_media":
        keys = [media.s3_key, *(media.variants or {}).values()]
        keys = [key for key in keys if key]
        if keys:
            await s3.delete_keys(keys)
        await session.execute(
            update(MediaReport)
            .where(
                MediaReport.media_id == media.id,
                MediaReport.status == "open",
                MediaReport.id != report.id,
            )
            .values(
                status="rejected",
                resolved_at=datetime.utcnow(),
                resolution_note="файл удалён по другой жалобе",
            )
        )
        report.status = "removed"
        details = f"файл удалён, объектов в S3: {len(keys)}"
        await session.delete(media)
        keep_media = False
    else:  # reject
        report.status = "rejected"
        details = "жалоба отклонена"

    report.resolved_at = datetime.utcnow()
    if payload.note is not None:
        report.resolution_note = payload.note.strip() or None

    await record_audit(
        session, action=f"report.{payload.action}", target=str(report.id), details=details
    )
    await session.commit()
    await session.refresh(report)
    return _out(report, media if keep_media else None)


@router.get("/blocked-hashes", response_model=List[BlockedHashOut])
async def list_blocked_hashes(
    _=Depends(verify_admin), session: AsyncSession = Depends(get_session)
):
    """Блок-лист хешей: свежие сверху, с числом файлов архива на каждый хеш."""
    rows = (
        await session.execute(
            select(BlockedHash).order_by(BlockedHash.created_at.desc()).limit(500)
        )
    ).scalars().all()

    counts: dict[str, int] = {}
    if rows:
        counter_rows = await session.execute(
            select(Media.file_hash, func.count())
            .where(Media.file_hash.in_([item.sha256 for item in rows]))
            .group_by(Media.file_hash)
        )
        counts = {value: int(count) for value, count in counter_rows.all()}

    out: List[BlockedHashOut] = []
    for item in rows:
        entry = BlockedHashOut.model_validate(item)
        entry.media_count = counts.get(item.sha256, 0)
        out.append(entry)
    return out


@router.post("/blocked-hashes", response_model=BlockedHashOut, status_code=201)
async def add_blocked_hash(
    payload: BlockedHashIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Добавляет хеш в блок-лист и сразу скрывает файлы архива с этим хешем.

    Пайплайн тоже проверяет блок-лист при приёме новых файлов, поэтому хеш закрывает
    контент и «на будущее»: повторное скачивание или импорт из архива не вернёт файл
    на сайт.
    """
    sha = (payload.sha256 or "").strip().lower()
    if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
        raise HTTPException(status_code=400, detail="Ожидается SHA-256 в hex (64 символа)")

    exists = (
        await session.execute(select(BlockedHash).where(BlockedHash.sha256 == sha))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=400, detail="Такой хеш уже в блок-листе")

    reason = payload.reason if payload.reason in HASH_REASONS else "other"
    item = BlockedHash(
        sha256=sha,
        reason=reason,
        note=(payload.note or "").strip() or None,
        created_by="admin-token",
    )
    session.add(item)

    # Скрываем всё, что уже лежит в архиве с этим хешем, включая их треды
    media_rows = (
        await session.execute(select(Media).where(Media.file_hash == sha))
    ).scalars().all()
    threads = {(row.board_id, row.thread_id) for row in media_rows}
    for row in media_rows:
        row.is_visible = False
    for board_id, thread_id in threads:
        await session.execute(
            update(ThreadState)
            .where(ThreadState.board_id == board_id, ThreadState.thread_id == thread_id)
            .values(is_visible=False)
        )

    await record_audit(
        session,
        action="blocked_hash.add",
        target=sha[:16],
        details=f"причина: {reason}; скрыто файлов: {len(media_rows)}",
    )
    await session.commit()
    await session.refresh(item)

    out = BlockedHashOut.model_validate(item)
    out.media_count = len(media_rows)
    return out


@router.delete("/blocked-hashes/{hash_id}")
async def delete_blocked_hash(
    hash_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Убирает хеш из блок-листа.

    Уже скрытые файлы остаются скрытыми: видимость им возвращает модератор вручную
    (вкладка «Контент»), иначе снятие хеша мгновенно вернуло бы контент в ленты.
    """
    item = (
        await session.execute(select(BlockedHash).where(BlockedHash.id == hash_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Хеш не найден")

    target = item.sha256[:16]
    await session.delete(item)
    await record_audit(session, action="blocked_hash.delete", target=target)
    await session.commit()
    return {"ok": True, "deleted": hash_id}

