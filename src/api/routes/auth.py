# src/api/routes/auth.py
"""Аутентификация: регистрация/вход/выход, профиль и премиум-доступ.

Оригиналы и полные версии премиум-файлов (`/media/{id}/raw|download|asset/web`)
доступны только вошедшим; премиум-контент дополнительно требует подписки.
Размытые превью (`/asset/thumb_blur`) и деривативы обычных файлов публичны.
"""
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.common import display_name
from src.api.deps import check_rate_limit, client_ip, ip_hash, require_user
from src.api.schemas import (
    AuthCredentials,
    MagicConsumeOut,
    MagicIssueIn,
    MagicLinkOut,
    TelegramStatusOut,
    UserOut,
)
from src.core.config import settings
from src.core.db import get_session
from src.core.models import MediaMark, User, UserSession
from src.services import admin_auth
from src.services import auth as auth_service
from src.services import magic_link
from src.services.premium import PROMO_PREMIUM_DAYS, grant_premium, premium_active

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_COOKIE_MAX_AGE = int(auth_service.SESSION_TTL.total_seconds())


def site_base() -> str:
    """Публичный адрес сайта для ссылок (magic link): SITE_URL или база писем."""
    base = (settings.SITE_URL or settings.PUBLIC_BASE_URL or "https://dredg.ru").strip()
    return base.rstrip("/")


def user_out(user: User) -> UserOut:
    """Схема пользователя с актуальным премиум-статусом."""
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=display_name(user),
        telegram_id=user.telegram_id,
        telegram_username=user.telegram_username,
        premium_until=user.premium_until,
        is_premium=premium_active(user),
        created_at=user.created_at,
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
    """Регистрация нового пользователя (доступ к оригиналам).

    В закрытом режиме (Dredger 2.0) регистрация выключена: аккаунт появляется
    только через Telegram-бота (`/link`), а вход — по magic link.
    """
    if settings.site_closed:
        raise HTTPException(status_code=403, detail="Регистрация закрыта")
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


# ── Magic link: вход без пароля (модель Dredger 2.0) ──────────────────────────

def _bot_token_ok(provided: Optional[str]) -> bool:
    """Проверяет токен бота из заголовка (сравнение постоянного времени)."""
    expected = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not expected:
        return False
    return bool(provided) and secrets.compare_digest(provided, expected)


@router.post("/magic/issue", response_model=MagicLinkOut)
async def magic_issue(
    payload: MagicIssueIn,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_bot_token: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
):
    """Выпускает одноразовую ссылку входа для Telegram-бота.

    Доступ только по токену бота (`X-Bot-Token` или `Authorization: Bot <token>`):
    ручка создаёт/находит аккаунт по Telegram ID и возвращает ссылку, которую бот
    присылает человеку. Если токен бота не настроен — 503 (бот ещё не подключён).
    """
    token = x_bot_token
    if not token and authorization and authorization.lower().startswith("bot "):
        token = authorization.split(" ", 1)[1].strip()
    if not (settings.TELEGRAM_BOT_TOKEN or "").strip():
        raise HTTPException(status_code=503, detail="Telegram-бот не настроен")
    if not _bot_token_ok(token):
        raise HTTPException(status_code=403, detail="Неверный токен бота")

    await check_rate_limit(client_ip(request))

    user = await magic_link.get_or_create_telegram_user(
        session, payload.telegram_id, payload.username
    )
    link_token, expires_at = await magic_link.issue(
        session, user, settings.MAGIC_LINK_TTL_MINUTES, ip_hash(client_ip(request))
    )
    return MagicLinkOut(
        url=magic_link.login_url(link_token),
        expires_at=expires_at,
        telegram_id=user.telegram_id,
        user_id=user.id,
    )


@router.get("/telegram/status", response_model=TelegramStatusOut)
async def telegram_status(
    telegram_id: int = Query(..., gt=0),
    authorization: Optional[str] = Header(None),
    x_bot_token: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
):
    """Статус доступа по Telegram ID — для команды `/status` в боте.

    Доступ только по токену бота. Если аккаунта ещё нет, он не создаётся: бот
    покажет «нет подписки» (аккаунт появится при `/link`).
    """
    token = x_bot_token
    if not token and authorization and authorization.lower().startswith("bot "):
        token = authorization.split(" ", 1)[1].strip()
    if not (settings.TELEGRAM_BOT_TOKEN or "").strip():
        raise HTTPException(status_code=503, detail="Telegram-бот не настроен")
    if not _bot_token_ok(token):
        raise HTTPException(status_code=403, detail="Неверный токен бота")

    user = (
        await session.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")

    marks = (
        await session.execute(
            select(func.count(MediaMark.id)).where(MediaMark.user_id == user.id)
        )
    ).scalar_one()
    return TelegramStatusOut(
        user_id=user.id,
        telegram_id=telegram_id,
        is_active=bool(user.is_active),
        premium_active=premium_active(user),
        premium_until=user.premium_until,
        marks_count=int(marks or 0),
    )


@router.get("/magic", response_model=MagicConsumeOut)
async def magic_consume(
    request: Request,
    response: Response,
    token: str = Query(..., min_length=10, max_length=200),
    session: AsyncSession = Depends(get_session),
):
    """Вход по одноразовой ссылке: гасит ссылку и ставит cookie сессии.

    Ссылка одноразовая и живёт `MAGIC_LINK_TTL_MINUTES`; повторный переход по ней
    вернёт 401. Вызывается из web-роута `/auth/magic`, который переносит cookie
    браузеру и уводит на главную.
    """
    user = await magic_link.consume(session, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Ссылка недействительна")

    await _issue_session(session, response, user, request)
    return MagicConsumeOut(ok=True, redirect="/")
