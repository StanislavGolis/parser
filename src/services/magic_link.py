# src/services/magic_link.py
"""Одноразовые ссылки входа (magic link) — вход на сайт без пароля.

Модель Dredger 2.0: аккаунт сайта = Telegram ID, доступ выдаёт бот. Ссылку можно
выпустить двумя путями — из бота (`POST /api/v1/auth/magic/issue` с токеном бота)
или из админки (карточка пользователя). В БД лежит только sha256 токена, срок
жизни — `MAGIC_LINK_TTL_MINUTES`, после использования ссылка гаснет.
"""
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import AuthMagicLink, User
from src.services import auth as auth_service

logger = logging.getLogger(__name__)


def login_url(token: str) -> str:
    """Готовая ссылка входа: `{сайт}/auth/magic?token=…`.

    Единственная точка формирования адреса: так ссылка из бота, из уведомления об
    оплате и из админки ведёт в одно место — страницу, которая сразу гасит токен и
    ставит сессию (а не на `/login`, где пришлось бы идти в бота за новой ссылкой).
    """
    base = (settings.SITE_URL or settings.PUBLIC_BASE_URL or "https://media-archive.example").strip()
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
    logger.info(
        "Ссылка входа выпущена: user=%s tg=%s @%s (живёт %s мин)",
        user.id,
        user.telegram_id,
        user.telegram_username or "—",
        ttl_minutes,
    )
    return token, expires_at


async def consume(session: AsyncSession, token: str) -> Optional[User]:
    """Гасит ссылку и возвращает пользователя. `None` — ссылка недействительна.

    Повторный переход по уже погашенной ссылке в пределах
    `MAGIC_LINK_REUSE_SECONDS` тоже считается входом: мессенджер открывает ссылку
    сам (превью или встроенный браузер), а человек открывает её в обычном — и
    раньше получал «ссылка уже использована», хотя вход по ней был его. Окно
    короткое и не продлевается (дата `used_at` при повторном входе не сдвигается):
    одноразовость сохраняется, дальше нужна новая ссылка из бота.
    """
    if not token:
        return None

    result = await session.execute(
        select(AuthMagicLink).where(AuthMagicLink.token_hash == auth_service.token_hash(token))
    )
    link = result.scalar_one_or_none()
    now = datetime.utcnow()
    if link is None:
        logger.warning("Ссылка входа не найдена (битый или чужой токен)")
        return None
    if link.expires_at <= now:
        logger.info("Ссылка входа истекла: user=%s", link.user_id)
        return None

    reused = link.used_at is not None
    if reused:
        grace = timedelta(seconds=max(0, settings.MAGIC_LINK_REUSE_SECONDS))
        if now > link.used_at + grace:
            logger.info(
                "Ссылка входа уже использована: user=%s (%.0f мин назад)",
                link.user_id,
                (now - link.used_at).total_seconds() / 60,
            )
            return None

    user = await session.get(User, link.user_id)
    if user is None or not user.is_active:
        logger.warning("Ссылка входа на недоступный аккаунт: user=%s", link.user_id)
        return None

    if not reused:
        link.used_at = now
        await session.commit()
    logger.info(
        "Вход по ссылке: user=%s tg=%s @%s%s",
        user.id,
        user.telegram_id,
        user.telegram_username or "—",
        " (повторный переход)" if reused else "",
    )
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
