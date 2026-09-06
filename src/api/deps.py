# src/api/deps.py
"""Общие зависимости API: rate limiting, admin-токен, IP-хеш, B2."""
import hashlib
from functools import lru_cache
from typing import Optional

from fastapi import Header, HTTPException, Request, status

from src.core.config import settings
from src.core.redis_client import redis_client
from src.services.b2_uploader import B2Uploader


@lru_cache(maxsize=1)
def get_b2() -> B2Uploader:
    """FastAPI-зависимость: загрузчик B2 (кэшируется, head_bucket один раз)."""
    return B2Uploader()


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