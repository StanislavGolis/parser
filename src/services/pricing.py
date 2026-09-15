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
from typing import Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Payment, Plan, Promo, User
from src.services.premium import grant_premium

# «Навсегда» без отдельного флага: 100 лет доступа — проще для расчёта продлений
FOREVER_DAYS = 36500
PAID_STATUSES = ("paid",)


async def paid_count(session: AsyncSession) -> int:
    """Сколько оплат прошло — по этому счётчику работают лимиты акций."""
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


def apply_discount(price: int, percent: int) -> int:
    """Цена со скидкой: суммы «круглые», поэтому обычное округление до целого."""
    if percent <= 0:
        return price
    return max(1, int(round(price * (100 - min(percent, 95)) / 100)))


# ── Акции ────────────────────────────────────────────────────────────

def promo_running(promo: Promo, now: Optional[datetime] = None) -> bool:
    """Идёт ли акция по времени (включение проверяем отдельно)."""
    moment = now or datetime.utcnow()
    if promo.starts_at and promo.starts_at > moment:
        return False
    if promo.ends_at and promo.ends_at <= moment:
        return False
    return True


def promo_applies_to(promo: Promo, plan_code: str) -> bool:
    """Действует ли акция на тариф: пустой список = на все."""
    codes = promo.applies_to or []
    return not codes or plan_code in codes


async def list_promos(session: AsyncSession, *, only_active: bool = False) -> list[Promo]:
    """Акции: все (для админки) или только включённые и идущие (для витрины).

    Лимит оплат проверяем тем же счётчиком, что и выдача: как только оплат стало
    больше, чем допускает акция, она перестаёт показываться.
    """
    query = select(Promo).order_by(Promo.is_active.desc(), Promo.id.desc())
    promos = list((await session.execute(query)).scalars().all())
    if not only_active:
        return promos

    paid = await paid_count(session)
    now = datetime.utcnow()
    return [
        promo
        for promo in promos
        if promo.is_active
        and promo_running(promo, now)
        and (promo.max_paid is None or paid < promo.max_paid)
    ]


def best_promo(promos: Sequence[Promo], plan_code: str) -> Optional[Promo]:
    """Самая выгодная из подходящих акций (при равном проценте — ранее созданная)."""
    candidates = [promo for promo in promos if promo_applies_to(promo, plan_code)]
    if not candidates:
        return None
    return max(candidates, key=lambda promo: promo.percent)


def promo_state(promo: Promo, paid: int, now: Optional[datetime] = None) -> dict:
    """Состояние акции для админки: идёт ли, сколько осталось по времени и оплатам."""
    moment = now or datetime.utcnow()
    running = promo_running(promo, moment)
    limit_hit = promo.max_paid is not None and paid >= promo.max_paid
    active = bool(promo.is_active and running and not limit_hit)

    reason = ""
    if not promo.is_active:
        reason = "выключена"
    elif not running:
        reason = "вне срока"
    elif limit_hit:
        reason = "лимит оплат набран"

    return {
        "id": promo.id,
        "title": promo.title,
        "description": promo.description,
        "percent": promo.percent,
        "is_active": promo.is_active,
        "active": active,
        "reason": reason,
        "starts_at": promo.starts_at,
        "ends_at": promo.ends_at,
        "days_left": max(0, (promo.ends_at.date() - moment.date()).days) if promo.ends_at else None,
        "max_paid": promo.max_paid,
        "paid_left": max(0, promo.max_paid - paid) if promo.max_paid is not None else None,
        "applies_to": promo.applies_to or [],
    }


async def create_promo(session: AsyncSession, **fields) -> Promo:
    """Создаёт акцию (включение — отдельным флагом, по умолчанию выключена)."""
    promo = Promo(**fields)
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


async def delete_promo(session: AsyncSession, promo: Promo) -> None:
    await session.delete(promo)
    await session.commit()


async def active_promo_details(session: AsyncSession, promos: Optional[list[Promo]] = None) -> list[dict]:
    """Активные акции в виде, удобном для витрины (сайт, бот, админка)."""
    current = promos if promos is not None else await list_promos(session, only_active=True)
    paid = await paid_count(session)
    return [promo_state(promo, paid) for promo in current]



async def pricing_view(session: AsyncSession) -> dict:
    """Готовая витрина: тарифы с ценами в рублях и звёздах + активные акции.

    Один вызов закрывает и сайт, и бота: не хочется, чтобы бот и страница показывали
    разные цены в момент, когда акция включается или заканчивается.
    """
    promos = await list_promos(session, only_active=True)
    paid = await paid_count(session)

    items = []
    for plan in await list_plans(session):
        promo = best_promo(promos, plan.code)
        percent = promo.percent if promo else 0

        price_now = apply_discount(plan.price_rub, percent)
        stars_now = (
            apply_discount(plan.price_stars, percent) if plan.price_stars else None
        )
        changed = price_now != plan.price_rub or (
            plan.price_stars is not None and stars_now != plan.price_stars
        )
        items.append(
            {
                "code": plan.code,
                "title": plan.title,
                "description": plan.description,
                "days": plan.days,
                "price_rub": plan.price_rub,
                "price_now": price_now,
                # Цена в звёздах задаётся вручную (вариант A): None — оплата звёздами
                # для тарифа выключена
                "price_stars": plan.price_stars,
                "stars_now": stars_now,
                "discount_percent": percent if changed else 0,
                "promo_id": promo.id if promo else None,
                "promo_title": promo.title if promo else None,
                "promo_description": promo.description if promo else None,
                "badge": plan.badge,
                "is_forever": plan.days >= FOREVER_DAYS,
            }
        )

    return {"plans": items, "promos": [promo_state(promo, paid) for promo in promos]}


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

