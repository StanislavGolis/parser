# src/services/catalog_health.py
"""Здоровье каталога доски: жив ли раздел на 2ch.

2ch отдаёт `500 Not found` для удалённых разделов, но `index.json` продолжает их
перечислять (например, хентай-доски `/h`, `/ho`, `/hc`). Чтобы админ не ловил
сырую «ошибку 500», результат последней попытки чтения каталога пишется в Redis:
карточка доски показывает «каталог недоступен» с причиной ещё до нажатия
«Сканировать треды».

Пишут обе стороны: парсер (фаза A двухфазного цикла) и админ-скан доски.
Ключ живёт `TTL` и обновляется при каждой попытке, успешное чтение его снимает.
"""
import json
from datetime import datetime
from typing import Dict, Iterable

from src.core.redis_client import redis_client

# Сколько хранить отметку о недоступности каталога
TTL = 6 * 3600


def catalog_error_key(slug: str) -> str:
    """Ключ Redis с последней ошибкой каталога доски."""
    return f"board:catalog_error:{slug}"


async def mark_catalog_ok(slug: str) -> None:
    """Каталог прочитан — снимаем пометку о недоступности."""
    try:
        await redis_client.delete(catalog_error_key(slug))
    except Exception:  # noqa: BLE001 — диагностика не должна ломать парсинг
        pass


async def mark_catalog_error(slug: str, text: str) -> None:
    """Запоминаем, что каталог доски не читается (доска удалена/недоступна)."""
    try:
        await redis_client.set(
            catalog_error_key(slug),
            json.dumps({"text": text, "at": datetime.utcnow().isoformat()}),
            ex=TTL,
        )
    except Exception:  # noqa: BLE001
        pass


async def catalog_errors(slugs: Iterable[str]) -> Dict[str, str]:
    """{slug: текст ошибки} по доскам, у которых последняя попытка не удалась."""
    keys = list(slugs)
    if not keys:
        return {}
    try:
        values = await redis_client.mget([catalog_error_key(slug) for slug in keys])
    except Exception:  # noqa: BLE001
        return {}

    out: Dict[str, str] = {}
    for slug, raw in zip(keys, values):
        if not raw:
            continue
        try:
            out[slug] = json.loads(raw).get("text") or "каталог недоступен"
        except Exception:  # noqa: BLE001
            out[slug] = "каталог недоступен"
    return out
