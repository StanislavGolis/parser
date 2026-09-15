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
from src.services import pricing
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
        raise HTTPException(
            status_code=404,
            detail="Аккаунт не привязан: сначала откройте сайт по ссылке из бота (/link)",
        )

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
        external_id=payload.charge_id,
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
