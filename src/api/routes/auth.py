# src/api/routes/auth.py
"""Аутентификация: регистрация/вход/выход, профиль и премиум-доступ.

Оригиналы и полные версии премиум-файлов (`/media/{id}/raw|download|asset/web`)
доступны только вошедшим; премиум-контент дополнительно требует подписки.
Размытые превью (`/asset/thumb_blur`) и деривативы обычных файлов публичны.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip, require_user
from src.api.schemas import AuthCredentials, UserOut
from src.core.db import get_session
from src.core.models import User, UserSession
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


async def _issue_session(session: AsyncSession, response: Response, user: User) -> None:
    """Создаёт сессию и ставит httpOnly-cookie."""
    token = auth_service.new_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=auth_service.token_hash(token),
            expires_at=datetime.utcnow() + auth_service.SESSION_TTL,
        )
    )
    await session.commit()
    response.set_cookie(
        key=auth_service.COOKIE_NAME,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
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

    await _issue_session(session, response, user)
    return user_out(user)


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

    await _issue_session(session, response, user)
    return user_out(user)


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


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_user)):
    """Текущий пользователь (401, если не вошёл)."""
    return user_out(user)


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
    return user_out(user)
