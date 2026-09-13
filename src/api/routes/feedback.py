# src/api/routes/feedback.py
"""Обратная связь: форма для посетителей (`POST /api/v1/feedback`).

Обращение сохраняется в БД (таблица `feedback`) и дублируется письмом админам,
если SMTP настроен. Аноним тоже может написать — тогда контактом служит указанный
им email (если он его оставил). Заявки разбираются в админке
(`/api/v1/admin/feedback`), где ведётся статус и заметка-ответ.
"""
from typing import Optional

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip, get_current_user, ip_hash
from src.api.schemas import FeedbackIn, FeedbackOut
from src.core.config import settings
from src.core.db import get_session
from src.core.models import Feedback, User
from src.services import mailer

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

# Темы обращения: подпись нужна и в письме, и в админке
TOPICS = {
    "bug": "баг",
    "idea": "идея",
    "premium": "премиум-доступ",
    "content": "контент",
    "other": "другое",
}
MIN_MESSAGE = 10
MAX_MESSAGE = 4000


def topic_label(topic: str) -> str:
    """Человеческая подпись темы (для письма и админки)."""
    return TOPICS.get(topic, TOPICS["other"])


@router.post("", response_model=FeedbackOut, status_code=201)
async def send_feedback(
    payload: FeedbackIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    """Принимает обращение: пишет в БД и уведомляет админов письмом.

    Анонимные обращения разрешены (движок сайта открыт), но с контактом: если
    посетитель не вошёл и не оставил email, ответить ему будет некуда — в письме
    админам это видно. Поле `website` — ловушка для ботов: люди его не заполняют.
    """
    ip = client_ip(request)
    await check_rate_limit(ip, limit=max(5, settings.API_RATE_LIMIT // 10), scope="feedback")

    # Бот заполнил скрытое поле — молча «принимаем», но ничего не делаем
    if (payload.website or "").strip():
        raise HTTPException(status_code=202, detail="Спасибо, обращение принято")

    message = (payload.message or "").strip()
    if len(message) < MIN_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"Опишите подробнее, пожалуйста: нужно хотя бы {MIN_MESSAGE} символов",
        )
    if len(message) > MAX_MESSAGE:
        message = message[:MAX_MESSAGE]

    topic = payload.topic if payload.topic in TOPICS else "other"
    email = (payload.email or "").strip() or (user.email if user else None)
    if email and ("@" not in email or len(email) > 255):
        raise HTTPException(status_code=400, detail="Проверьте адрес электронной почты")

    item = Feedback(
        topic=topic,
        message=message,
        email=email,
        user_id=user.id if user else None,
        page_url=(payload.page_url or "")[:255] or None,
        ip_hash=ip_hash(ip),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    # Письмо админам — фоном: отправка через SMTP может занять секунды (или
    # упереться в таймаут), а посетитель не должен ждать почту, чтобы получить
    # подтверждение. Ошибка отправки видна в логе и не влияет на заявку в БД.
    admins = settings.admin_emails
    if admins and mailer.is_configured():
        where = f" (со страницы {item.page_url})" if item.page_url else ""
        who = email or "без контакта (аноним)"
        text = (
            f"Новое обращение №{item.id}\n"
            f"Тема: {topic_label(topic)}\n"
            f"Контакт: {who}\n"
            f"Когда: {item.created_at:%d.%m.%Y %H:%M} UTC{where}\n\n"
            f"{message}\n\n"
            f"— Ответить и разобрать: /admin/feedback\n"
        )
        subject = f"Dredger: обращение #{item.id} — {topic_label(topic)}"
        asyncio.create_task(_notify_admins(admins, subject, text, item.id))
    else:
        print(f"   [mail] Обращение #{item.id} сохранено (письмо не отправлено: SMTP/админы не настроены)")

    return FeedbackOut.model_validate(item)


async def _notify_admins(addresses: list[str], subject: str, text: str, item_id: int) -> None:
    """Рассылает уведомление о заявке (вызывается фоновой задачей)."""
    for address in addresses:
        try:
            await mailer.send_mail(address, subject, text)
        except Exception as exc:  # noqa: BLE001 — уведомление не важнее заявки
            print(f"   [mail] Обращение #{item_id}: не удалось отправить {address} ({exc})")
