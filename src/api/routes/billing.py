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

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import PaymentOut
from src.core.config import settings
from src.core.db import get_session
from src.core.models import Payment, User
from src.services import cryptobot, magic_link, pricing
from src.services.analytics import record_audit

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


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

    Защита — заголовок `crypto-pay-api-token`: им Crypto Pay подписывает уведомление.
    Сверх этого статус счёта перепроверяется в `getInvoices`: выдаём только когда
    Crypto Pay действительно подтверждает `paid`, поэтому подделка уведомления
    ничего не даёт. Идемпотентность даёт `mark_paid` (ключ — `external_id`).

    Отвечаем 200 и на «не наше» уведомление: повторять его бессмысленно, а ретраи
    Crypto Pay нам не нужны.
    """
    if not cryptobot.webhook_token_ok(request.headers.get("crypto-pay-api-token")):
        raise HTTPException(status_code=403, detail="Неверная подпись вебхука")

    try:
        update = await request.json()
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
        return {"ok": True, "ignored": "счёт не найден в журнале"}
    if payment.status == "paid":
        return {"ok": True, "paid": True, "status": "paid", "already": True}

    # Подтверждение — только статус счёта у Crypto Pay (а не тело уведомления)
    invoice = await cryptobot.get_invoice(int(invoice_id))
    if invoice is None:
        raise HTTPException(status_code=502, detail="Crypto Pay недоступен")
    if invoice.get("status") != "paid":
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
    return {"paid": True, "status": "paid", "premium_until": payment.premium_until}
