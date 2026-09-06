# src/core/redis_client.py
"""Асинхронный Redis-клиент (кэш, rate limiting, счётчики)."""
import redis.asyncio as aioredis

from src.core.config import settings

redis_client = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
)