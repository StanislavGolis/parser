# src/core/redis_client.py
"""Асинхронный Redis-клиент (кэш, rate limiting, счётчики)."""
import redis.asyncio as aioredis

from src.core.config import settings

redis_client = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    # Пул считаем с запасом: на каждый запрос нужно 1–2 соединения (лимитер + кэш), и при
    # листании ленты десятками параллельных запросов прежних 20 не хватало — Redis отвечал
    # «Too many connections», а ручка отдавала 500.
    max_connections=200,
)