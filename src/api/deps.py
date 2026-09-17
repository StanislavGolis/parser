# src/api/deps.py
"""Общие зависимости API: rate limiting, admin-токен, IP-хеш, S3."""
import hashlib
import logging
from datetime import datetime, timedelta
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

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_s3() -> S3Storage:
    """FastAPI-зависимость: загрузчик S3 (кэшируется, head_bucket один раз)."""
    return S3Storage()


# Как часто обновляем «последнюю активность» сессии в БД (для карточки пользователя).
ACTIVE_TOUCH = timedelta(minutes=5)


def client_ip(request: Request) -> str:
    """IP клиента (за прокси Nginx — X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ip_hash(ip: str) -> str:
    """SHA-256 от IP для дедупликации в статистике."""
    return hashlib.sha256(ip.encode()).hexdigest()


async def check_rate_limit(ip: str, limit: Optional[int] = None, scope: str = "api") -> None:
    """Rate limiting на Redis: не более `limit` запросов/мин на IP.

    По умолчанию лимит берётся из `API_RATE_LIMIT` (корзина `api`). Медиа-файлы
    идут в отдельные корзины: превью (`preview`) — щедрая, потому что лента
    запрашивает десятки картинок на экран, а «тяжёлые» варианты и оригиналы
    (`media`) — строже. Посещения и события интерфейса пишутся в `events`, чтобы
    аналитика не выбирала лимит на списки файлов.

    При превышении отдаём 429 с `Retry-After`: клиент может подождать и повторить
    (для картинок это делает фронтенд — сам повторяет загрузку с паузой).
    """
    effective = settings.API_RATE_LIMIT if limit is None else int(limit)
    if effective <= 0:
        return

    rl_key = f"rl:{scope}:{hashlib.sha256(ip.encode()).hexdigest()}"
    try:
        pipe = redis_client.pipeline()
        pipe.incr(rl_key)
        pipe.expire(rl_key, 60)
        pipe.ttl(rl_key)
        count, _, ttl = await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        # Redis недоступен или пул исчерпан: пропускаем запрос (fail-open). Иначе один
        # сбой инфраструктуры превращался бы в 500 у всех — картинки и лента важнее,
        # чем строгость лимита.
        logger.warning("Rate limit недоступен: %s", exc)
        return

    if int(count) > effective:
        retry_after = max(1, min(60, int(ttl or 60)))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов: подождите и повторите.",
            headers={"Retry-After": str(retry_after)},
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
    """Текущий пользователь по cookie-сессии, либо None (аноним).

    Заодно ведём след сессии для админки (`last_seen_at`, хеш IP, браузер) —
    IP храним только хешем. Пишем не чаще раза в 5 минут, чтобы не делать
    запись на каждый запрос.
    """
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if not token:
        return None
    result = await session.execute(
        select(User, UserSession)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == auth_service.token_hash(token),
            UserSession.expires_at > datetime.utcnow(),
            User.is_active.is_(True),
        )
    )
    row = result.first()
    if row is None:
        return None

    user, session_row = row
    now = datetime.utcnow()
    stale = session_row.last_seen_at is None or (now - session_row.last_seen_at) > ACTIVE_TOUCH
    if stale:
        # Обновляем след сессии целиком: IP (хешем) и браузер могли измениться,
        # а у сессий, созданных до появления этих полей, они вообще пустые.
        session_row.last_seen_at = now
        session_row.ip_hash = ip_hash(client_ip(request))
        agent = request.headers.get("user-agent")
        if agent:
            session_row.user_agent = agent[:255]
        await session.commit()
    return user


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """Требует авторизацию (метки, профиль)."""
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