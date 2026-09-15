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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import verify_admin
from src.api.schemas import AdminPlanOut, AdminPlansOut, PaymentOut, PlanIn, PromoIn, PromoOut
from src.core.db import get_session
from src.core.models import Payment, User
from src.services import pricing
from src.services.analytics import record_audit

router = APIRouter(prefix="/api/v1/admin/plans", tags=["admin-plans"])


class GrantIn(BaseModel):
    """Ручная выдача тарифа: кому и, при необходимости, со скидкой."""

    user_id: int
    percent: Optional[int] = None
    note: Optional[str] = None


async def _plans_out(session: AsyncSession) -> AdminPlansOut:
    """Собирает ответ админки: тарифы, состояние акции и сводку продаж."""
    plans = await pricing.list_plans(session, active_only=False)
    return AdminPlansOut(
        plans=[AdminPlanOut.model_validate(plan) for plan in plans],
        promo=PromoOut(**await pricing.promo_state(session)),
        sales=await pricing.payments_summary(session),
    )


@router.get("", response_model=AdminPlansOut)
async def list_plans(_=Depends(verify_admin), session: AsyncSession = Depends(get_session)):
    """Тарифы, акция и продажи — для вкладки «Тарифы»."""
    return await _plans_out(session)


@router.patch("/promo", response_model=PromoOut)
async def update_promo(
    payload: PromoIn,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Меняет условия акции: включение, процент, срок, лимит оплат."""
    promo = await pricing.get_promo(session)
    if payload.enabled is not None:
        promo.enabled = payload.enabled
    if payload.percent is not None:
        promo.percent = max(0, min(90, payload.percent))
    if payload.ends_at is not None:
        promo.ends_at = payload.ends_at
    if payload.max_paid is not None:
        promo.max_paid = max(0, payload.max_paid)
    if payload.note is not None:
        promo.note = payload.note.strip()[:200] or None

    await record_audit(
        session,
        action="plans.promo",
        target="promo",
        details=f"включена: {promo.enabled}, −{promo.percent}%, лимит: {promo.max_paid}",
    )
    await session.commit()
    await session.refresh(promo)
    return PromoOut(**await pricing.promo_state(session))


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
