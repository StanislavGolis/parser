# src/services/payments_notify.py
"""Сообщение покупателю: «оплата принята — подписка активна».

Зачем отдельный модуль: зачисление приходит из разных мест (вебхук Crypto Pay,
сверка неоплаченных счетов, кнопка «Проверить оплату»), а сообщение покупателю
должно быть одно. Вебхук и сверка легко срабатывают почти одновременно, поэтому
факт отправки запоминаем в Redis (`notify:paid:<payment_id>`, 30 дней).

Отправка не должна мешать зачислению: любые сбои (нет Telegram, нет Redis) только
пишем в лог, а вызывающий код сам решает, отвечать ли покупателю.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import Payment, User
from src.core.redis_client import redis_client
from src.services import pricing, telegram_api

logger = logging.getLogger(__name__)

# Флаг «уже сообщили»: месяца хватает с запасом, дальше запись просто исчезнет
NOTIFY_TTL_SECONDS = 30 * 24 * 3600


def _escape(text: str) -> str:
    """Экранирование для `parse_mode=HTML` (название тарифа правится в админке)."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _first_time(payment_id: int) -> bool:
    """Первый ли это вызов для платежа (`False` — сообщение уже отправляли)."""
    try:
        fresh = await redis_client.set(
            f"notify:paid:{payment_id}", "1", nx=True, ex=NOTIFY_TTL_SECONDS
        )
    except Exception as exc:  # noqa: BLE001
        # Redis недоступен: лучше написать второй раз, чем не написать вовсе
        logger.warning("Флаг уведомления недоступен: %s", exc)
        return True
    return bool(fresh)


async def notify_paid(session: AsyncSession, payment: Payment, *, source: str = "") -> bool:
    """Сообщает покупателю, что оплата принята и премиум начислен.

    `True` — сообщение отправлено (или отправлялось раньше); `False` — отправить не
    получилось (нет `telegram_id`, Telegram недоступен) — тогда вызывающий код может
    ответить покупателю сам, чтобы он не остался без ответа.
    """
    if payment is None or payment.status != "paid" or not payment.user_id:
        return False
    if not await _first_time(payment.id):
        return True

    user = await session.get(User, payment.user_id)
    telegram_id = getattr(user, "telegram_id", None)
    if not telegram_id:
        return False

    plan = await session.get(pricing.Plan, payment.plan_code)
    title = (getattr(plan, "title", "") or "") or payment.plan_code
    days = payment.days or (getattr(plan, "days", 0) or 0)
    until = payment.premium_until.strftime("%d.%m.%Y") if payment.premium_until else "—"

    lines = [
        "✅ <b>Оплата принята — подписка активна</b>",
        "",
        f"Тариф: <b>{_escape(title)}</b>" + (f" ({days} дн.)" if days else ""),
        f"Действует до: <b>{until}</b>",
        "",
        "Открыть сайт можно кнопкой ниже — вход уже привязан к этому чату.",
    ]

    base = (settings.SITE_URL or "").strip().rstrip("/")
    # `buttons` — ряды инлайн-клавиатуры (список списков кнопок)
    buttons = [[{"text": "🔓 Войти на сайт", "url": f"{base}/login"}]] if base else None
    try:
        await telegram_api.send_message(
            chat_id=str(telegram_id), text="\n".join(lines), buttons=buttons
        )
    except Exception as exc:  # noqa: BLE001 — уведомление не должно ломать зачисление
        logger.warning("Не удалось уведомить покупателя %s: %s", telegram_id, exc)
        # Снимаем флаг: следующая сверка попробует отправить сообщение ещё раз
        try:
            await redis_client.delete(f"notify:paid:{payment.id}")
        except Exception:  # noqa: BLE001
            pass
        return False

    logger.info(
        "Покупатель %s уведомлён об оплате (платёж #%s, %s)",
        telegram_id,
        payment.id,
        source or "—",
    )
    return True
