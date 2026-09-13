# src/api/routes/auth.py
"""Аутентификация: регистрация/вход/выход, профиль и премиум-доступ.

Оригиналы и полные версии премиум-файлов (`/media/{id}/raw|download|asset/web`)
доступны только вошедшим; премиум-контент дополнительно требует подписки.
Размытые превью (`/asset/thumb_blur`) и деривативы обычных файлов публичны.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip, ip_hash, require_user
from src.api.schemas import AuthCredentials, UserOut
from src.core.config import settings
from src.core.db import get_session
from src.core.models import MediaMark, User, UserSession
from src.services import admin_auth
from src.services import auth as auth_service
from src.services.premium import PROMO_PREMIUM_DAYS, grant_premium, premium_active

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_COOKIE_MAX_AGE = int(auth_service.SESSION_TTL.total_seconds())


def user_out(user: User) -> UserOut:
    """Схема пользователя с актуальным премиум-статусом."""
    return UserOut(
        id=user.id,
        email=user.email,
        premium_until=user.premium_until,
        is_premium=premium_active(user),
    )


async def user_out_with_counts(session: AsyncSession, user: User) -> UserOut:
    """Схема пользователя + счётчик его меток (для профиля)."""
    marks = (
        await session.execute(
            select(func.count()).select_from(MediaMark).where(MediaMark.user_id == user.id)
        )
    ).scalar()
    data = user_out(user)
    data.marks_count = int(marks or 0)
    return data


async def _issue_session(
    session: AsyncSession,
    response: Response,
    user: User,
    request: Optional[Request] = None,
) -> None:
    """Создаёт сессию и ставит httpOnly-cookie.

    Из запроса сохраняем след для админки: хеш IP (не сам IP) и User-Agent.
    """
    token = auth_service.new_token()
    agent = request.headers.get("user-agent") if request else None
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=auth_service.token_hash(token),
            expires_at=datetime.utcnow() + auth_service.SESSION_TTL,
            ip_hash=ip_hash(client_ip(request)) if request else None,
            user_agent=agent[:255] if agent else None,
            last_seen_at=datetime.utcnow(),
        )
    )
    await session.commit()
    response.set_cookie(
        key=auth_service.COOKIE_NAME,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # В проде за HTTPS включаем SESSION_COOKIE_SECURE=1 (см. .env.prod.example)
        secure=settings.SESSION_COOKIE_SECURE,
        path="/",
    )


@router.post("/register", response_model=UserOut)
async def register(
    payload: AuthCredentials,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Регистрация нового пользователя (доступ к оригиналам)."""
    await check_rate_limit(client_ip(request))

    email = payload.email.strip().lower()
    if "@" not in email or len(email) > 255:
        raise HTTPException(status_code=400, detail="Некорректный email")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Пароль короче 6 символов")

    exists = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Email уже зарегистрирован")

    user = User(email=email, password_hash=auth_service.hash_password(payload.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)

    await _issue_session(session, response, user, request)
    return await user_out_with_counts(session, user)


@router.post("/login", response_model=UserOut)
async def login(
    payload: AuthCredentials,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Вход по email и паролю."""
    await check_rate_limit(client_ip(request))

    email = payload.email.strip().lower()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if (
        not user
        or not user.is_active
        or not auth_service.verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    await _issue_session(session, response, user, request)
    return await user_out_with_counts(session, user)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Выход: удаляет сессию и cookie."""
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if token:
        await session.execute(
            delete(UserSession).where(UserSession.token_hash == auth_service.token_hash(token))
        )
        await session.commit()
    response.delete_cookie(auth_service.COOKIE_NAME, path="/")
    return {"ok": True}


class PasswordResetIn(BaseModel):
    """Смена пароля по одноразовой ссылке, которую выдал админ."""

    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=6, max_length=200)


@router.post("/reset")
async def reset_password(
    payload: PasswordResetIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Смена пароля посетителя по ссылке из админки.

    Права админа при этом не выдаются (`promote_admin=False`): ссылка выдаётся
    обычному аккаунту. Все прежние сессии аккаунта удаляются.
    """
    await check_rate_limit(client_ip(request))
    try:
        user = await admin_auth.consume_reset_token(
            session,
            payload.token,
            payload.password,
            promote_admin=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "email": user.email}


@router.get("/me", response_model=UserOut)
async def me(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    """Текущий пользователь + счётчик меток (401, если не вошёл)."""
    return await user_out_with_counts(session, user)


@router.post("/premium/activate", response_model=UserOut)
async def activate_premium(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_user),
):
    """Промо-активация премиума на PROMO_PREMIUM_DAYS дней.

    Пока платёжной системы нет — кнопка в профиле выдаёт премиум бесплатно;
    повторная активация продлевает срок от текущего (накопление).
    """
    await check_rate_limit(client_ip(request))

    grant_premium(user, PROMO_PREMIUM_DAYS)
    await session.commit()
    await session.refresh(user)
    return await user_out_with_counts(session, user)
