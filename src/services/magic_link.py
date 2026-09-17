# src/services/magic_link.py
"""Одноразовые ссылки входа (magic link) — вход на сайт без пароля.

Модель Dredger 2.0: аккаунт сайта = Telegram ID, доступ выдаёт бот. Ссылку можно
выпустить двумя путями — из бота (`POST /api/v1/auth/magic/issue` с токеном бота)
или из админки (карточка пользователя). В БД лежит только sha256 токена, срок
жизни — `MAGIC_LINK_TTL_MINUTES`, после использования ссылка гаснет.
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import AuthMagicLink, User
from src.services import auth as auth_service


def login_url(token: str) -> str:
    """Готовая ссылка входа: `{сайт}/auth/magic?token=…`.

    Единственная точка формирования адреса: так ссылка из бота, из уведомления об
    оплате и из админки ведёт в одно место — страницу, которая сразу гасит токен и
    ставит сессию (а не на `/login`, где пришлось бы идти в бота за новой ссылкой).
    """
    base = (settings.SITE_URL or settings.PUBLIC_BASE_URL or "https://dredg.ru").strip()
    return f"{base.rstrip('/')}/auth/magic?token={token}"


def new_token() -> str:
    """Случайный токен ссылки: в ссылке — открытым, в БД — только хеш."""
    return secrets.token_urlsafe(32)


async def issue(
    session: AsyncSession,
    user: User,
    ttl_minutes: int,
    ip: Optional[str] = None,
) -> Tuple[str, datetime]:
    """Выпускает одноразовую ссылку. Возвращает (токен, срок действия)."""
    token = new_token()
    expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
    session.add(
        AuthMagicLink(
            token_hash=auth_service.token_hash(token),
            user_id=user.id,
            expires_at=expires_at,
            created_ip=ip,
        )
    )
    await session.commit()
    return token, expires_at


async def consume(session: AsyncSession, token: str) -> Optional[User]:
    """Гасит ссылку и возвращает пользователя. `None` — ссылка недействительна."""
    if not token:
        return None

    result = await session.execute(
        select(AuthMagicLink).where(AuthMagicLink.token_hash == auth_service.token_hash(token))
    )
    link = result.scalar_one_or_none()
    if link is None or link.used_at is not None or link.expires_at <= datetime.utcnow():
        return None

    user = await session.get(User, link.user_id)
    if user is None or not user.is_active:
        return None

    link.used_at = datetime.utcnow()
    await session.commit()
    return user


async def get_or_create_telegram_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
) -> User:
    """Находит или создаёт аккаунт по Telegram ID (email не требуется)."""
    user = (
        await session.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()

    if user is None:
        user = User(telegram_id=telegram_id, telegram_username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    if username and user.telegram_username != username:
        user.telegram_username = username
        await session.commit()
    return user
