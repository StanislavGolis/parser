# src/api/routes/billing.py
"""Приём оплат звёздами Telegram (Bot Payments, валюта XTR).

Бот продаёт доступ через `sendInvoice` с валютой XTR, а сюда приходит подтверждение
успешного платежа. Платёжный провайдер для звёзд не нужен, поэтому всё, что требуется —
токен бота: он же защищает ручку (`X-Bot-Token`), иначе оплату можно было бы «нарисовать»
снаружи.

Идемпотентность: ключ — `telegram_payment_charge_id`. Повторный вызов (ретрай бота,
повторная доставка апдейта) вернёт ту же запись и не продлит подписку второй раз.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import PaymentOut
from src.core.config import settings
from src.core.db import get_session
from src.core.models import Payment, User
from src.services import cryptobot, magic_link, payments_notify, pricing
from src.services.analytics import record_audit

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

logger = logging.getLogger(__name__)

# Сверка неоплаченных счетов: сколько проверяем за проход и насколько свежие счета
SCAN_LIMIT = 20
SCAN_HOURS = 24


class StarsPaymentIn(BaseModel):
    """Оплата звёздами: кто заплатил, за какой тариф, сколько и с каким charge_id."""

    telegram_id: int
    plan_code: str
    stars: int
    charge_id: str
    promo_id: Optional[int] = None


async def verify_bot_token(request: Request) -> None:
    """Пускает только нашего бота: он передаёт подтверждение оплаты звёздами."""
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    sent = (request.headers.get("x-bot-token") or "").strip()
    if not token or sent != token:
        raise HTTPException(status_code=403, detail="Доступно только боту")


@router.post("/stars", response_model=PaymentOut)
async def stars_paid(
    payload: StarsPaymentIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(verify_bot_token),
):
    """Зачисляет оплату звёздами: пишет платёж и выдаёт премиум (один раз).

    Скидку берём из акции, если бот передал её `promo_id` и акция действует на тариф:
    так покупатель получает ровно ту цену, которую видел в счёте.
    """
    plan = await session.get(pricing.Plan, payload.plan_code)
    if plan is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    existing = (
        await session.execute(select(Payment).where(Payment.external_id == payload.charge_id))
    ).scalar_one_or_none()
    if existing is not None:
        return PaymentOut.model_validate(existing)

    user = (
        await session.execute(select(User).where(User.telegram_id == payload.telegram_id))
    ).scalar_one_or_none()
    if user is None:
        # Человек оплатил, ещё не заходя на сайт: заводим аккаунт сразу, чтобы оплата
        # не потерялась — доступ всё равно выдаётся тому же telegram_id, а на сайте
        # он войдёт по ссылке из бота.
        user = await magic_link.get_or_create_telegram_user(session, payload.telegram_id)

    percent = 0
    if payload.promo_id:
        promo = await session.get(pricing.Promo, payload.promo_id)
        if promo is not None and pricing.promo_applies_to(promo, plan.code):
            percent = promo.percent

    payment = await pricing.register_payment(
        session,
        plan=plan,
        user=user,
        provider="stars",
        # `telegram_payment_charge_id` бывает длинным: держим запас, обрезая до 255
        external_id=(payload.charge_id or "").strip()[:255] or None,
        percent=percent,
        note=f"Telegram Stars: {payload.stars} ⭐",
    )
    payment = await pricing.mark_paid(session, payment)

    await record_audit(
        session,
        action="billing.stars",
        target=f"user:{user.id}",
        details=f"{plan.code}: {payload.stars} ⭐, премиум до {payment.premium_until}",
        user_id=user.id,
    )
    await session.commit()
    await session.refresh(payment)
    return PaymentOut.model_validate(payment)


# ─────────────────────────── Крипта (Crypto Pay) ───────────────────────────


class CryptoInvoiceIn(BaseModel):
    """Запрос счёта в крипте: кому, за какой тариф и с какой акцией."""

    telegram_id: int
    plan_code: str
    promo_id: Optional[int] = None


class CryptoCheckIn(BaseModel):
    """Проверка счёта: `invoice_id` из Crypto Pay."""

    invoice_id: int


async def _promo_percent(
    session: AsyncSession, plan: pricing.Plan, promo_id: Optional[int]
) -> int:
    """Процент акции, если она передана и действует на этот тариф."""
    if not promo_id:
        return 0
    promo = await session.get(pricing.Promo, promo_id)
    if promo is not None and pricing.promo_applies_to(promo, plan.code):
        return promo.percent
    return 0


@router.post("/crypto")
async def crypto_invoice(
    payload: CryptoInvoiceIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(verify_bot_token),
):
    """Создаёт счёт в Crypto Pay и записывает его в журнал как `pending`.

    Премиум здесь не выдаётся: счёт может остаться неоплаченным. Если у человека уже
    есть живой счёт по этому тарифу — возвращаем его же, чтобы не плодить ссылки.
    """
    plan = await session.get(pricing.Plan, payload.plan_code)
    if plan is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    if not cryptobot.configured():
        raise HTTPException(status_code=503, detail="Приём крипты не настроен")
    if not plan.price_usdt_cents:
        raise HTTPException(status_code=400, detail="Тариф недоступен для оплаты криптой")

    user = (
        await session.execute(select(User).where(User.telegram_id == payload.telegram_id))
    ).scalar_one_or_none()
    if user is None:
        # Ещё не заходил на сайт — заводим аккаунт, чтобы оплата не потерялась
        user = await magic_link.get_or_create_telegram_user(session, payload.telegram_id)

    # Живой счёт по этому тарифу переиспользуем: у нас одна ссылка на тариф
    pending = (
        await session.execute(
            select(Payment)
            .where(
                Payment.user_id == user.id,
                Payment.provider == "crypto",
                Payment.plan_code == plan.code,
                Payment.status == "pending",
            )
            .order_by(Payment.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if pending is not None and pending.external_id:
        invoice = await cryptobot.get_invoice(int(pending.external_id))
        if invoice and invoice.get("status") == "paid":
            # Оплатили, а бот не успел проверить — зачисляем прямо сейчас
            pending = await pricing.mark_paid(session, pending)
            await record_audit(
                session,
                action="billing.crypto",
                target=f"user:{user.id}",
                details=(
                    f"{plan.code}: счёт {pending.external_id}, "
                    f"премиум до {pending.premium_until}"
                ),
                user_id=user.id,
            )
            await session.commit()
            return {"paid": True, "status": "paid", "premium_until": pending.premium_until}
        if invoice and invoice.get("status") == "active":
            return {
                "paid": False,
                "status": "active",
                "invoice_id": invoice["invoice_id"],
                "pay_url": invoice.get("bot_invoice_url") or invoice.get("mini_app_invoice_url"),
                "amount": invoice.get("amount"),
                "asset": invoice.get("asset"),
            }

    percent = await _promo_percent(session, plan, payload.promo_id)
    amount_cents = pricing.apply_discount(plan.price_usdt_cents, percent)
    invoice = await cryptobot.create_invoice(
        amount_cents=amount_cents,
        title=f"Dredger — {plan.title}",
        description=plan.description or f"Доступ на {plan.days} дн.",
        payload=f"{plan.code}:{user.id}",
    )
    if not invoice:
        raise HTTPException(status_code=502, detail="Crypto Pay не выдал счёт")

    await pricing.register_payment(
        session,
        plan=plan,
        user=user,
        provider="crypto",
        external_id=str(invoice["invoice_id"]),
        percent=percent,
        note=f"Crypto Pay: {invoice['amount']} {invoice['asset']}",
    )
    return {
        "paid": False,
        "status": invoice.get("status"),
        "invoice_id": invoice["invoice_id"],
        "pay_url": invoice["pay_url"],
        "amount": invoice["amount"],
        "asset": invoice["asset"],
    }


@router.post("/crypto/webhook")
async def crypto_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Вебхук Crypto Pay: счёт оплачен → сразу выдаём премиум.

    До этого оплата зачислялась только по кнопке «Я оплатил» (бот опрашивал статус).
    Теперь Crypto Pay сам стучится сюда, и выдача происходит за секунды, без действий
    покупателя. Опрос остаётся запасным путём: если уведомление не дошло (домен
    недоступен, сбой), бот всё равно выяснит статус по кнопке.

    Защита — подпись уведомления: заголовок `crypto-pay-api-signature`, HMAC-SHA256
    от сырого тела запроса с ключом SHA256(токен приложения). Сверх подписи статус
    счёта перепроверяется в `getInvoices`: выдаём только когда Crypto Pay
    действительно подтверждает `paid`, поэтому даже валидная по подписи, но чужая
    «оплата» ничего не даёт. Идемпотентность обеспечивает `mark_paid`.

    Отвечаем 200 и на «не наше» уведомление: повторять его бессмысленно, а ретраи
    Crypto Pay нам не нужны.
    """
    raw = await request.body()
    if not cryptobot.verify_webhook_signature(
        raw, request.headers.get("crypto-pay-api-signature")
    ):
        raise HTTPException(status_code=403, detail="Неверная подпись вебхука")

    try:
        update = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 — мусор от сканеров не должен ронять ручку
        raise HTTPException(status_code=400, detail="Ожидается JSON") from None
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="Ожидается JSON-объект")

    payload = update.get("payload") if isinstance(update.get("payload"), dict) else {}
    invoice_id = payload.get("invoice_id")
    if not invoice_id:
        return {"ok": True, "ignored": "в уведомлении нет счёта"}

    payment = (
        await session.execute(
            select(Payment).where(
                Payment.external_id == str(invoice_id),
                Payment.provider == "crypto",
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        await cryptobot.remember_webhook(int(invoice_id), False)
        return {"ok": True, "ignored": "счёт не найден в журнале"}
    if payment.status == "paid":
        await cryptobot.remember_webhook(int(invoice_id), True)
        return {"ok": True, "paid": True, "status": "paid", "already": True}

    # Подтверждение — только статус счёта у Crypto Pay (а не тело уведомления)
    invoice = await cryptobot.get_invoice(int(invoice_id))
    if invoice is None:
        raise HTTPException(status_code=502, detail="Crypto Pay недоступен")
    if invoice.get("status") != "paid":
        await cryptobot.remember_webhook(int(invoice_id), False)
        return {"ok": True, "paid": False, "status": invoice.get("status")}

    payment = await pricing.mark_paid(session, payment)
    await record_audit(
        session,
        action="billing.crypto",
        target=f"user:{payment.user_id}",
        details=(
            f"{payment.plan_code}: счёт {payment.external_id} (вебхук), "
            f"премиум до {payment.premium_until}"
        ),
        user_id=payment.user_id,
    )
    await session.commit()
    await session.refresh(payment)
    await cryptobot.remember_webhook(int(invoice_id), True)
    # Покупателю сразу пишем в Telegram: подписка включилась, ждать ничего не нужно
    await payments_notify.notify_paid(session, payment, source="вебхук")
    return {"ok": True, "paid": True, "status": "paid", "premium_until": payment.premium_until}


@router.post("/crypto/check")
async def crypto_check(
    payload: CryptoCheckIn,
    session: AsyncSession = Depends(get_session),
    _=Depends(verify_bot_token),
):
    """Проверяет счёт в Crypto Pay и выдаёт премиум ровно один раз.

    Опрос вместо вебхука: наш домен не обязан быть доступен для Crypto Pay, а бот
    спрашивает статус, когда человек нажал «Я оплатил», и повторно — при следующем
    обращении. Идемпотентность даёт `mark_paid` (ключ — `payments.external_id`).
    """
    payment = (
        await session.execute(
            select(Payment).where(
                Payment.external_id == str(payload.invoice_id),
                Payment.provider == "crypto",
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Счёт не найден в журнале")
    if payment.status == "paid":
        return {"paid": True, "status": "paid", "premium_until": payment.premium_until}

    invoice = await cryptobot.get_invoice(payload.invoice_id)
    if invoice is None:
        raise HTTPException(status_code=502, detail="Crypto Pay недоступен")
    status = invoice.get("status")
    if status != "paid":
        return {"paid": False, "status": status, "premium_until": None}

    payment = await pricing.mark_paid(session, payment)
    await record_audit(
        session,
        action="billing.crypto",
        target=f"user:{payment.user_id}",
        details=(
            f"{payment.plan_code}: счёт {payment.external_id}, "
            f"премиум до {payment.premium_until}"
        ),
        user_id=payment.user_id,
    )
    await session.commit()
    await session.refresh(payment)
    # Уведомление покупателю: бот по флагу `notified` поймёт, отвечать ли самому
    notified = await payments_notify.notify_paid(session, payment, source="проверка счёта")
    return {
        "paid": True,
        "status": "paid",
        "premium_until": payment.premium_until,
        "notified": notified,
    }


@router.post("/crypto/scan")
async def crypto_scan(
    session: AsyncSession = Depends(get_session),
    _=Depends(verify_bot_token),
):
    """Сверяет неоплаченные счета с Crypto Pay и зачисляет оплаченные.

    Зачем: вебхук включается руками в интерфейсе @CryptoBot, а оплата должна
    зачисляться сама. Бот раз в минуту просит API сделать эту сверку — подписка
    включается без кнопки «Я оплатил», покупателю сразу уходит уведомление.

    Ограничения: у Crypto Pay нет пакетного метода, поэтому за проход спрашиваем не
    больше `SCAN_LIMIT` свежих счетов. Сверка идемпотентна — зачисление держит
    `mark_paid`, а уведомление — флаг в Redis.
    """
    since = datetime.utcnow() - timedelta(hours=SCAN_HOURS)
    payments = (
        (
            await session.execute(
                select(Payment)
                .where(
                    Payment.provider == "crypto",
                    Payment.status == "pending",
                    Payment.created_at >= since,
                )
                .order_by(Payment.id.desc())
                .limit(SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    checked = 0
    paid = 0
    notified = 0
    for payment in payments:
        if not (payment.external_id or "").isdigit():
            continue
        checked += 1
        invoice = await cryptobot.get_invoice(int(payment.external_id))
        if not invoice or invoice.get("status") != "paid":
            continue

        payment = await pricing.mark_paid(session, payment)
        await record_audit(
            session,
            action="billing.crypto",
            target=f"user:{payment.user_id}",
            details=(
                f"{payment.plan_code}: счёт {payment.external_id} (сверка), "
                f"премиум до {payment.premium_until}"
            ),
            user_id=payment.user_id,
        )
        paid += 1
        if await payments_notify.notify_paid(session, payment, source="сверка"):
            notified += 1

    if paid:
        await session.commit()
    if checked:
        logger.info("Сверка счетов: проверено %s, зачислено %s", checked, paid)
    return {"checked": checked, "paid": paid, "notified": notified}
