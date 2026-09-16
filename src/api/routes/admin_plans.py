# src/api/routes/admin_plans.py
"""Админка тарифов: цены, сроки, стартовая акция и журнал оплат.

Здесь всё, что нужно менять без деплоя: стоимость и срок каждого тарифа, включение
тарифа, условия акции («−50% первые 30 дней или до 50 оплат») и ручная выдача тарифа
конкретному аккаунту. Журнал оплат показывает, что и когда продано.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import verify_admin
from src.api.schemas import (
    AdminPlanOut,
    AdminPlansOut,
    CryptoWebhookOut,
    PaymentOut,
    PlanIn,
    PromoIn,
    PromoOut,
    WalletCryptoOut,
    WalletJournalOut,
    WalletStarsOut,
    WalletsOut,
)
from src.core.config import settings
from src.core.db import get_session
from src.core.models import Payment, User
from src.services import cryptobot, pricing, telegram_api
from src.services.analytics import record_audit

router = APIRouter(prefix="/api/v1/admin/plans", tags=["admin-plans"])


class GrantIn(BaseModel):
    """Ручная выдача тарифа: кому и, при необходимости, со скидкой."""

    user_id: int
    percent: Optional[int] = None
    note: Optional[str] = None


async def _plans_out(session: AsyncSession) -> AdminPlansOut:
    """Собирает ответ админки: тарифы, акции (с состоянием) и сводку продаж."""
    plans = await pricing.list_plans(session, active_only=False)
    promos = await pricing.list_promos(session)
    paid = await pricing.paid_count(session)
    return AdminPlansOut(
        plans=[AdminPlanOut.model_validate(plan) for plan in plans],
        promos=[PromoOut(**pricing.promo_state(promo, paid)) for promo in promos],
        sales=await pricing.payments_summary(session),
    )


@router.get("", response_model=AdminPlansOut)
async def list_plans(_=Depends(verify_admin), session: AsyncSession = Depends(get_session)):
    """Тарифы, акция и продажи — для вкладки «Тарифы»."""
    return await _plans_out(session)


@router.get("/wallets", response_model=WalletsOut)
async def wallets(_=Depends(verify_admin), session: AsyncSession = Depends(get_session)):
    """Балансы кошельков: звёзды бота (Telegram) и крипта (Crypto Pay) + журнал.

    Деньги лежат не у нас: звёзды — на балансе бота, крипта — в приложении Crypto Pay,
    а в базе только записи `payments`. Поэтому журнал показываем рядом с балансами:
    расхождение означает, что оплата пришла, а выдача не сработала (или наоборот).
    """
    stars = WalletStarsOut(configured=bool((settings.TELEGRAM_BOT_TOKEN or "").strip()))
    if stars.configured:
        try:
            stars.amount = await telegram_api.star_balance()
        except Exception as exc:  # noqa: BLE001
            stars.error = str(exc)

    crypto = WalletCryptoOut(
        configured=cryptobot.configured(),
        asset=(settings.CRYPTOBOT_ASSET or "USDT").strip().upper(),
    )
    if crypto.configured:
        try:
            crypto.balances = await cryptobot.balance()
        except Exception as exc:  # noqa: BLE001
            crypto.error = str(exc)
        # Вебхук: с ним премиум выдаётся сразу после оплаты, без кнопки «Я оплатил».
        # У Crypto Pay нет API для управления вебхуком — показываем адрес для настроек
        # приложения и когда приходило последнее уведомление.
        crypto.webhook = _webhook_out(await cryptobot.last_webhook())

    rows = (
        await session.execute(
            select(
                Payment.provider,
                Payment.status,
                func.count(),
                func.coalesce(func.sum(Payment.amount_rub), 0),
            ).group_by(Payment.provider, Payment.status)
        )
    ).all()

    journal = WalletJournalOut()
    for provider, status, count, rub in rows:
        if status == "paid":
            journal.paid_count += int(count)
            journal.paid_rub += int(rub or 0)
            key = str(provider or "manual")
            journal.by_provider[key] = journal.by_provider.get(key, 0) + int(count)
        elif status == "pending":
            journal.pending_count += int(count)

    return WalletsOut(stars=stars, crypto=crypto, journal=journal)


# ── Вебхук Crypto Pay: премиум выдаётся сразу после оплаты ───────────
#
# Включить вебхук через API нельзя: у Crypto Pay нет `setWebhook`/`getWebhookInfo`,
# адрес задаётся в интерфейсе бота (@CryptoBot → Crypto Pay → My Apps → приложение
# → Webhooks). Поэтому здесь только состояние: адрес для настройки и факт того,
# что уведомление уже приходило.


def _webhook_out(last: Optional[dict], error: Optional[str] = None) -> CryptoWebhookOut:
    """Состояние вебхука: адрес для настроек приложения и последняя доставка."""
    return CryptoWebhookOut(
        configured=cryptobot.configured(),
        url=cryptobot.webhook_url(),
        receiving=bool(last),
        last_received_at=(last or {}).get("at"),
        last_invoice_id=(last or {}).get("invoice_id"),
        error=error,
    )


@router.get("/crypto/webhook", response_model=CryptoWebhookOut)
async def crypto_webhook_status(_=Depends(verify_admin)):
    """Адрес вебхука для настроек Crypto Pay и когда приходило последнее уведомление."""
    if not cryptobot.configured():
        return _webhook_out(None, error="Токен Crypto Pay не задан")
    return _webhook_out(await cryptobot.last_webhook())




@router.get("/promos", response_model=List[PromoOut])
async def list_promos(_=Depends(verify_admin), session: AsyncSession = Depends(get_session)):
    """Все акции с состоянием: включена ли, идёт ли, сколько оплат и дней осталось."""
    promos = await pricing.list_promos(session)
    paid = await pricing.paid_count(session)
    return [PromoOut(**pricing.promo_state(promo, paid)) for promo in promos]


@router.post("/promos", response_model=PromoOut)
async def create_promo(
    payload: PromoIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Создаёт акцию. Включение — отдельным флагом: завести можно заранее.

    Название и описание — то, что увидит покупатель в боте и на витрине; менять их
    можно в любой момент, поэтому акцию удобно готовить под конкретное событие.
    """
    promo = await pricing.create_promo(
        session,
        title=(payload.title or "Акция").strip()[:64],
        description=(payload.description or "").strip()[:200],
        percent=max(0, min(90, payload.percent if payload.percent is not None else 10)),
        is_active=bool(payload.is_active),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        max_paid=payload.max_paid,
        applies_to=payload.applies_to or None,
    )
    await record_audit(
        session,
        action="plans.promo.create",
        target=str(promo.id),
        details=f"{promo.title}: −{promo.percent}%, включена: {promo.is_active}",
    )
    await session.commit()
    paid = await pricing.paid_count(session)
    return PromoOut(**pricing.promo_state(promo, paid))


@router.patch("/promos/{promo_id}", response_model=PromoOut)
async def update_promo(
    promo_id: int,
    payload: PromoIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Меняет акцию: название, описание, процент, срок, лимит, тарифы, включение."""
    promo = await session.get(pricing.Promo, promo_id)
    if promo is None:
        raise HTTPException(status_code=404, detail="Акция не найдена")

    if payload.title is not None:
        promo.title = payload.title.strip()[:64] or promo.title
    if payload.description is not None:
        promo.description = payload.description.strip()[:200]
    if payload.percent is not None:
        promo.percent = max(0, min(90, payload.percent))
    if payload.is_active is not None:
        promo.is_active = payload.is_active
    if payload.starts_at is not None:
        promo.starts_at = payload.starts_at
    if payload.ends_at is not None:
        promo.ends_at = payload.ends_at
    if payload.max_paid is not None:
        promo.max_paid = max(0, payload.max_paid)
    if payload.applies_to is not None:
        promo.applies_to = payload.applies_to or None

    await record_audit(
        session,
        action="plans.promo.update",
        target=str(promo.id),
        details=f"{promo.title}: −{promo.percent}%, включена: {promo.is_active}",
    )
    await session.commit()
    await session.refresh(promo)
    paid = await pricing.paid_count(session)
    return PromoOut(**pricing.promo_state(promo, paid))


@router.delete("/promos/{promo_id}")
async def delete_promo(
    promo_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Удаляет акцию (например, отменённое событие)."""
    promo = await session.get(pricing.Promo, promo_id)
    if promo is None:
        raise HTTPException(status_code=404, detail="Акция не найдена")
    title = promo.title
    await pricing.delete_promo(session, promo)
    await record_audit(
        session, action="plans.promo.delete", target=str(promo_id), details=title
    )
    await session.commit()
    return {"ok": True}


@router.get("/payments", response_model=List[PaymentOut])
async def list_payments(
    limit: int = 50,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Журнал оплат: ручные выдачи, крипта (позже) и статусы."""
    rows = await session.execute(
        select(Payment).order_by(Payment.created_at.desc()).limit(max(1, min(limit, 200)))
    )
    return [PaymentOut.model_validate(item) for item in rows.scalars().all()]


@router.patch("/{code}", response_model=AdminPlanOut)
async def update_plan(
    code: str,
    payload: PlanIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Правка тарифа: цена, срок, название, включение."""
    plan = await session.get(pricing.Plan, code)
    if plan is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    if payload.title is not None:
        plan.title = payload.title.strip()[:64] or plan.title
    if payload.description is not None:
        plan.description = payload.description.strip()[:200]
    if payload.days is not None:
        plan.days = max(1, min(36500, payload.days))
    if payload.price_rub is not None:
        plan.price_rub = max(0, min(1_000_000, payload.price_rub))
    if payload.price_stars is not None:
        # Звёзды задаются вручную (вариант A): 0 или пусто — оплата звёздами выключена
        plan.price_stars = max(0, min(100_000, payload.price_stars)) or None
    if payload.price_usdt_cents is not None:
        # Крипта: сумма в центах USDT (150 = 1.50 USDT); 0 или пусто — крипта выключена
        plan.price_usdt_cents = max(0, min(10_000_000, payload.price_usdt_cents)) or None
    if payload.is_active is not None:
        plan.is_active = payload.is_active
    if payload.sort_order is not None:
        plan.sort_order = payload.sort_order
    if payload.badge is not None:
        plan.badge = payload.badge.strip()[:32] or None

    await record_audit(
        session,
        action="plans.update",
        target=plan.code,
        details=f"{plan.title}: {plan.price_rub} ₽ / {plan.days} дн., активен: {plan.is_active}",
    )
    await session.commit()
    await session.refresh(plan)
    return AdminPlanOut.model_validate(plan)


@router.post("/{code}/grant", response_model=PaymentOut)
async def grant_plan(
    code: str,
    payload: GrantIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Выдаёт тариф аккаунту вручную (подарок, оплата вне бота, компенсация).

    Премиум продлевается от текущего срока — как при обычной оплате, и в журнал
    попадает строка со скидкой (если выдали со скидкой) и пометкой.
    """
    plan = await session.get(pricing.Plan, code)
    if plan is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    percent = payload.percent if payload.percent is not None else 0
    payment = await pricing.grant_plan(
        session,
        user,
        plan,
        provider="manual",
        percent=percent,
        note=payload.note or "ручная выдача из админки",
    )
    await record_audit(
        session,
        action="plans.grant",
        target=f"user:{user.id}",
        details=f"{plan.code} на {plan.days} дн., скидка {percent}%",
        user_id=user.id,
    )
    await session.commit()
    return PaymentOut.model_validate(payment)
