# src/api/routes/admin_feedback.py
"""Админ-приёмная обратной связи: список заявок, статусы, заметки-ответы.

Отдельный файл, потому что `admin.py` уже большой, а здесь своя маленькая тема:
`GET/PATCH/DELETE /api/v1/admin/feedback`. Статусы: new → in_progress → answered →
closed; при переводе в `answered` проставляем время ответа.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import verify_admin
from src.api.routes.feedback import TOPICS, topic_label
from src.api.schemas import FeedbackListOut, FeedbackOut, FeedbackUpdate
from src.core.db import get_session
from src.core.models import Feedback
from src.services.analytics import record_audit

router = APIRouter(prefix="/api/v1/admin", tags=["admin-feedback"])

STATUSES = ("new", "in_progress", "answered", "closed")


def _out(item: Feedback) -> FeedbackOut:
    """Схема + человеческая подпись темы (в БД её хранить не нужно)."""
    out = FeedbackOut.model_validate(item)
    out.topic_label = topic_label(item.topic)
    return out


@router.get("/feedback", response_model=FeedbackListOut)
async def list_feedback(
    status: str = Query("all", pattern="^(all|new|in_progress|answered|closed)$"),
    q: Optional[str] = Query(None, description="Поиск по тексту, email или адресу страницы"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Заявки обратной связи: свежие сверху + счётчики по статусам для фильтров."""
    conditions = []
    if status != "all":
        conditions.append(Feedback.status == status)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                Feedback.message.ilike(pattern),
                Feedback.email.ilike(pattern),
                Feedback.page_url.ilike(pattern),
            )
        )

    total = (
        await session.execute(select(func.count()).select_from(Feedback).where(*conditions))
    ).scalar() or 0

    rows = await session.execute(
        select(Feedback)
        .where(*conditions)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = [_out(item) for item in rows.scalars().all()]

    # Счётчики по статусам считаем по всей таблице (на чипах всегда полная картина)
    counter_rows = await session.execute(
        select(Feedback.status, func.count()).group_by(Feedback.status)
    )
    counts = {name: int(count) for name, count in counter_rows.all()}
    counts["all"] = sum(counts.values())

    return FeedbackListOut(items=items, total=int(total), counts=counts)


@router.patch("/feedback/{item_id}", response_model=FeedbackOut)
async def update_feedback(
    item_id: int,
    payload: FeedbackUpdate,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Меняет статус и заметку обращения (ответ администратора)."""
    item = (
        await session.execute(select(Feedback).where(Feedback.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")

    if payload.status is not None:
        if payload.status not in STATUSES:
            raise HTTPException(status_code=400, detail="Неизвестный статус обращения")
        item.status = payload.status
        item.answered_at = datetime.utcnow() if payload.status == "answered" else item.answered_at
    if payload.admin_note is not None:
        item.admin_note = payload.admin_note.strip() or None

    await record_audit(
        session,
        action="feedback.update",
        target=str(item.id),
        details=f"статус: {item.status}",
    )
    await session.commit()
    await session.refresh(item)
    return _out(item)


@router.delete("/feedback/{item_id}")
async def delete_feedback(
    item_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Удаляет обращение (спам или разобранная заявка, которая больше не нужна)."""
    item = (
        await session.execute(select(Feedback).where(Feedback.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    await session.delete(item)
    await record_audit(session, action="feedback.delete", target=str(item_id))
    await session.commit()
    return {"ok": True, "deleted": item_id}


@router.get("/feedback/topics")
async def feedback_topics(_=Depends(verify_admin)):
    """Темы обращений (для фильтров в админке)."""
    return [{"value": value, "label": label} for value, label in TOPICS.items()]
