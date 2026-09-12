# src/api/deps.py
"""Общие зависимости API: rate limiting, admin-токен, IP-хеш, S3."""
import hashlib
from datetime import datetime
from functools import lru_cache
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.db import get_session
from src.core.models import User, UserSession
from src.core.redis_client import redis_client
from src.services import auth as auth_service
from src.services.premium import premium_active
from src.services.s3_storage import S3Storage


@lru_cache(maxsize=1)
def get_s3() -> S3Storage:
    """FastAPI-зависимость: загрузчик S3 (кэшируется, head_bucket один раз)."""
    return S3Storage()


def client_ip(request: Request) -> str:
    """IP клиента (за прокси Nginx — X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ip_hash(ip: str) -> str:
    """SHA-256 от IP для дедупликации в статистике."""
    return hashlib.sha256(ip.encode()).hexdigest()


async def check_rate_limit(ip: str) -> None:
    """Rate limiting на Redis: не более API_RATE_LIMIT запросов/мин на IP."""
    if settings.API_RATE_LIMIT <= 0:
        return

    rl_key = f"rl:{hashlib.sha256(ip.encode()).hexdigest()}"
    pipe = redis_client.pipeline()
    pipe.incr(rl_key)
    pipe.expire(rl_key, 60)
    count, _ = await pipe.execute()

    if int(count) > settings.API_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Slow down.",
        )


async def verify_admin(authorization: Optional[str] = Header(None)) -> None:
    """Проверка admin-токена (Authorization: Bearer <token> или X-Admin-Token)."""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin API is disabled")

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing admin token")

    if token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")


# ─────────────────── Аутентификация пользователя ───────────────────


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Optional[User]:
    """Текущий пользователь по cookie-сессии, либо None (аноним)."""
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if not token:
        return None
    result = await session.execute(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == auth_service.token_hash(token),
            UserSession.expires_at > datetime.utcnow(),
            User.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """Требует авторизацию (метки, избранное, профиль)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return user


async def require_premium(user: Optional[User] = Depends(get_current_user)) -> User:
    """Требует активную премиум-подписку (скачивание и оригиналы).

    Порядок проверок важен для UX: аноним получает 401 («войти»),
    зарегистрированный без подписки — 403 («нужна подписка»).
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    if not premium_active(user):
        raise HTTPException(status_code=403, detail="Нужна премиум-подписка")
    return user