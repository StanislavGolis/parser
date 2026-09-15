# src/services/pricing.py
"""Тарифы подписки, стартовая акция и выдача премиума по оплате.

Модель «открытый архив»: Free видит открытые разделы (с рекламой), Premium открывает
приватные разделы, скачивание и убирает рекламу. Этот модуль отвечает за «сколько
стоит» и «что человек получает за деньги»:

* `list_plans` / `pricing_view` — витрина: цена и цена со скидкой;
* `promo_state` — активна ли стартовая акция («первые 30 дней или до 50 оплат»);
* `grant_plan` — выдать премиум по тарифу и записать платёж в журнал;
* `register_payment` / `mark_paid` — задел под CryptoBot: счёт создаётся заранее,
  премиум выдаётся один раз по событию «оплачено» (идемпотентно по `external_id`).

Цена хранится в рублях: для крипты сумма пересчитывается по курсу на момент счёта,
а в журнале фиксируется фактически оплаченная сумма.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Payment, Plan, PricingPromo, User
from src.services.premium import grant_premium

# «Навсегда» без отдельного флага: 100 лет доступа — проще для расчёта продлений
FOREVER_DAYS = 36500
PROMO_ID = 1
PAID_STATUSES = ("paid",)


async def get_promo(session: AsyncSession) -> PricingPromo:
    """Настройки акции: строка одна, создаём при первом обращении."""
    promo = await session.get(PricingPromo, PROMO_ID)
    if promo is None:
        promo = PricingPromo(id=PROMO_ID)
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
    return promo


async def paid_count(session: AsyncSession) -> int:
    """Сколько оплат прошло — по этому счётчику работает лимит «первых 50»."""
    total = (
        await session.execute(
            select(func.count()).select_from(Payment).where(Payment.status.in_(PAID_STATUSES))
        )
    ).scalar()
    return int(total or 0)


async def list_plans(session: AsyncSession, *, active_only: bool = True) -> list[Plan]:
    """Тарифы в порядке витрины."""
    query = select(Plan).order_by(Plan.sort_order, Plan.price_rub)
    if active_only:
        query = query.where(Plan.is_active.is_(True))
    return list((await session.execute(query)).scalars().all())


def apply_discount(price_rub: int, percent: int) -> int:
    """Цена со скидкой: суммы у нас «круглые», поэтому обычное округление до рубля."""
    if percent <= 0:
        return price_rub
    return max(1, int(round(price_rub * (100 - min(percent, 95)) / 100)))


async def promo_state(session: AsyncSession) -> dict:
    """Состояние акции: активна ли и почему, сколько осталось по времени и по лимиту.

    Акция живёт, пока включена, не истёк срок **и** не выбран лимит оплат — по
    требованию «первые 30 дней или до первых 50 платящих» достаточно одного из условий.
    """
    promo = await get_promo(session)
    now = datetime.utcnow()
    paid = await paid_count(session)

    reason = ""
    active = True
    if not promo.enabled:
        active, reason = False, "акция выключена"
    elif promo.ends_at and promo.ends_at <= now:
        active, reason = False, "срок акции истёк"
    elif promo.max_paid is not None and paid >= promo.max_paid:
        active, reason = False, "лимит оплат набран"

    days_left = None
    if promo.ends_at:
        days_left = max(0, (promo.ends_at.date() - now.date()).days)
    paid_left = None
    if promo.max_paid is not None:
        paid_left = max(0, promo.max_paid - paid)

    return {
        "active": active,
        "percent": promo.percent if active else 0,
        "reason": reason,
        "ends_at": promo.ends_at,
        "days_left": days_left,
        "paid": paid,
        "max_paid": promo.max_paid,
        "paid_left": paid_left,
        "note": promo.note,
    }


async def pricing_view(session: AsyncSession) -> dict:
    """Готовая витрина: тарифы с ценами, скидкой и состоянием акции.

    Один вызов закрывает и сайт, и бота: не хочется, чтобы бот и страница показывали
    разные цены в момент, когда акция заканчивается.
    """
    promo = await promo_state(session)
    items = []
    for plan in await list_plans(session):
        price_now = apply_discount(plan.price_rub, promo["percent"])
        items.append(
            {
                "code": plan.code,
                "title": plan.title,
                "description": plan.description,
                "days": plan.days,
                "price_rub": plan.price_rub,
                "price_now": price_now,
                "discount_percent": promo["percent"] if price_now != plan.price_rub else 0,
                "badge": plan.badge,
                "is_forever": plan.days >= FOREVER_DAYS,
            }
        )
    return {"plans": items, "promo": promo}


def find_plan(plans: Iterable[Plan], code: str) -> Optional[Plan]:
    """Тариф по коду (или None) — чтобы не ловить исключение в роуте."""
    for plan in plans:
        if plan.code == code:
            return plan
    return None


async def register_payment(
    session: AsyncSession,
    *,
    plan: Plan,
    user: Optional[User] = None,
    provider: str = "manual",
    external_id: Optional[str] = None,
    percent: int = 0,
    note: Optional[str] = None,
) -> Payment:
    """Создаёт счёт: платёж в статусе `pending` (премиум ещё не выдан).

    Так CryptoBot получает счёт заранее, а выдача происходит по факту оплаты —
    и ровно один раз (`mark_paid`).
    """
    payment = Payment(
        user_id=user.id if user else None,
        plan_code=plan.code,
        amount_rub=apply_discount(plan.price_rub, percent),
        discount_percent=percent,
        provider=provider,
        external_id=external_id,
        status="pending",
        days=plan.days,
        note=note,
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


async def mark_paid(
    session: AsyncSession,
    payment: Payment,
    *,
    external_id: Optional[str] = None,
    amount_rub: Optional[int] = None,
) -> Payment:
    """Помечает платёж оплаченным и выдаёт премиум — идемпотентно.

    Повторный вызов (второй вебхук, поллинг, ретрай) не продлевает подписку дважды:
    если платёж уже `paid`, возвращаем его как есть.
    """
    if payment.status in PAID_STATUSES:
        return payment

    plan = await session.get(Plan, payment.plan_code)
    days = payment.days or (plan.days if plan else 0)

    user = await session.get(User, payment.user_id) if payment.user_id else None
    until = None
    if user is not None and days:
        until = grant_premium(user, days)

    payment.status = "paid"
    payment.paid_at = datetime.utcnow()
    payment.premium_until = until
    if external_id:
        payment.external_id = external_id
    if amount_rub is not None:
        payment.amount_rub = amount_rub

    await session.commit()
    await session.refresh(payment)
    return payment


async def grant_plan(
    session: AsyncSession,
    user: User,
    plan: Plan,
    *,
    provider: str = "manual",
    percent: int = 0,
    note: Optional[str] = None,
    external_id: Optional[str] = None,
) -> Payment:
    """Выдаёт тариф сразу (ручная выдача, промо, подарок) и пишет платёж в журнал."""
    payment = await register_payment(
        session,
        plan=plan,
        user=user,
        provider=provider,
        external_id=external_id,
        percent=percent,
        note=note,
    )
    return await mark_paid(session, payment)


async def payments_summary(session: AsyncSession) -> dict:
    """Сводка продаж для админки: сколько оплат и на какую сумму."""
    row = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Payment.amount_rub), 0)).where(
                Payment.status.in_(PAID_STATUSES)
            )
        )
    ).one()
    count, amount = int(row[0] or 0), int(row[1] or 0)
    return {"paid": count, "amount_rub": amount}

