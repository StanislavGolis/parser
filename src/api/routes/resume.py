# src/api/routes/resume.py
"""Точки возврата «продолжить просмотр» — синхронизация для аккаунта.

Аноним продолжает просмотр по localStorage браузера, авторизованный — по этой
таблице: точка не теряется при смене устройства. Данные приватные (видны только
владельцу), поэтому все эндпоинты требуют аккаунт: аноним получает 401.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip, require_user
from src.api.schemas import ResumeListOut, ResumePointIn, ResumePointOut
from src.core.db import get_session
from src.core.models import Media, User, UserResumePoint

router = APIRouter(prefix="/api/v1/resume", tags=["resume"])

# Сколько точек держим на пользователя: хватает на все активные треды, а запись
# остаётся маленькой (лишние вытесняются по времени просмотра).
MAX_POINTS = 500


@router.get("", response_model=ResumeListOut)
async def list_resume(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    """Точки возврата текущего пользователя — свежие сверху."""
    await check_rate_limit(client_ip(request))

    rows = (
        await session.execute(
            select(UserResumePoint)
            .where(UserResumePoint.user_id == user.id)
            .order_by(UserResumePoint.updated_at.desc())
            .limit(MAX_POINTS)
        )
    ).scalars().all()

    return ResumeListOut(
        items=[
            ResumePointOut(
                thread_id=row.thread_id,
                media_id=row.media_id,
                index=row.position,
                total=row.total,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
    )


@router.post("", response_model=ResumePointOut)
async def save_resume(
    payload: ResumePointIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    """Запомнить точку возврата (upsert по паре «пользователь + тред»).

    Проверяем, что файл действительно лежит в этом треде: без проверки клиент мог
    бы записать произвольные числа, и «продолжить» вело бы в никуда.
    """
    await check_rate_limit(client_ip(request))

    in_thread = (
        await session.execute(
            select(Media.id).where(
                Media.id == payload.media_id, Media.thread_id == payload.thread_id
            )
        )
    ).scalar_one_or_none()
    if in_thread is None:
        raise HTTPException(status_code=404, detail="Файл не найден в этом треде")

    stamp = datetime.utcnow()
    row = (
        await session.execute(
            select(UserResumePoint).where(
                UserResumePoint.user_id == user.id,
                UserResumePoint.thread_id == payload.thread_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        session.add(
            UserResumePoint(
                user_id=user.id,
                thread_id=payload.thread_id,
                media_id=payload.media_id,
                position=payload.index,
                total=payload.total,
                updated_at=stamp,
            )
        )
    else:
        row.media_id = payload.media_id
        row.position = payload.index
        row.total = payload.total
        row.updated_at = stamp
    await session.commit()

    # Вытеснение: держим MAX_POINTS самых свежих точек пользователя
    extra = (
        await session.execute(
            select(UserResumePoint.id)
            .where(UserResumePoint.user_id == user.id)
            .order_by(UserResumePoint.updated_at.desc())
            .offset(MAX_POINTS)
        )
    ).scalars().all()
    if extra:
        await session.execute(delete(UserResumePoint).where(UserResumePoint.id.in_(extra)))
        await session.commit()

    return ResumePointOut(
        thread_id=payload.thread_id,
        media_id=payload.media_id,
        index=payload.index,
        total=payload.total,
        updated_at=stamp,
    )


@router.delete("/{thread_id}")
async def forget_resume(
    thread_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    """Забыть точку возврата треда («начать сначала»)."""
    await check_rate_limit(client_ip(request))

    await session.execute(
        delete(UserResumePoint).where(
            UserResumePoint.user_id == user.id, UserResumePoint.thread_id == thread_id
        )
    )
    await session.commit()
    return {"thread_id": thread_id, "removed": True}
