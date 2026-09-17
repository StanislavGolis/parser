# src/services/asset_sign.py
"""Подписанные ссылки на деривативы премиум-контента.

Зачем: премиум-превью нельзя отдавать из общего кэша nginx «как есть» — файл утёк бы
анонимам (parаметр `Cache-Control: private, no-store` именно это и защищает, но из-за
него каждое превью идёт в Python — см. `docs/LAUNCH.md`, «Замеры нагрузки»).

Подпись в URL закрывает обе задачи сразу:

- **доступ** — ссылку получает только тот, кому её выдал API (премиум-пользователь):
  подпись считается HMAC-SHA256 с секретом, которого у клиента нет;
- **кэш** — URL с подписью можно кэшировать (nginx отдаёт файл сам, без Python), а срок
  жизни ссылки ограничен, поэтому «утёкшая» ссылка живёт недолго.

Схема: `?v=<версия>&e=<unix>&s=<подпись>`, подпись = HMAC-SHA256(секрет,
`media_id:kind:version:exp`). `exp` округляется вверх до окна `ASSET_LINK_TTL_MINUTES`:
пока окно одно и то же, ссылка у всех зрителей совпадает, и кэш nginx переиспользуется
между ними (иначе каждый получил бы свой URL и кэш был бы бесполезен).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import Optional, Tuple

from src.core.config import settings

# Путь дериватива: /api/v1/media/<id>/asset/<kind>
ASSET_PATH_RE = re.compile(r"^/api/v1/media/(\d{1,12})/asset/([a-z_]{3,16})$")


def enabled() -> bool:
    """Включены ли подписи: нужен непустой `ASSET_LINK_SECRET`."""
    return bool((settings.ASSET_LINK_SECRET or "").strip())


def window_seconds() -> int:
    """Сколько живёт одна подпись (не меньше минуты, чтобы окно не «дрожало»)."""
    return max(60, int(settings.ASSET_LINK_TTL_MINUTES) * 60)


def _payload(media_id: int, kind: str, version: str, expires: int) -> str:
    return f"{media_id}:{kind}:{version}:{expires}"


def _digest(payload: str) -> str:
    """Подпись в base64url без выравнивания — такой формат безопасен в query."""
    secret = (settings.ASSET_LINK_SECRET or "").strip().encode()
    mac = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def sign(media_id: int, kind: str, version: str = "") -> Optional[Tuple[int, str]]:
    """Выпускает `(expires, signature)`; `None` — подписи выключены.

    `expires` округляем вверх до окна и добавляем ещё одно окно: так ссылка живёт
    минимум `ASSET_LINK_TTL_MINUTES`, но при этом остаётся одинаковой внутри окна.
    """
    if not enabled():
        return None
    window = window_seconds()
    now = int(time.time())
    expires = ((now + window) // window + 1) * window
    return expires, _digest(_payload(media_id, kind, version, expires))


def verify(
    media_id: int, kind: str, version: str, expires: Optional[str], signature: Optional[str]
) -> bool:
    """Проверяет подпись и срок: `True` — ссылку выдал наш API и она ещё жива."""
    if not enabled() or not expires or not signature:
        return False
    try:
        exp = int(expires)
    except (TypeError, ValueError):
        return False
    if exp < int(time.time()):
        return False
    expected = _digest(_payload(media_id, kind, version or "", exp))
    return hmac.compare_digest(expected, (signature or "").strip())


def verify_path(
    path: str, version: Optional[str], expires: Optional[str], signature: Optional[str]
) -> bool:
    """Проверяет подпись по адресу запроса.

    Нужна middleware закрытого режима: подписанный ассет отдаётся без сессии (иначе
    nginx не смог бы отдавать его из кэша), поэтому по одной только сессии решать
    нельзя — пропускаем лишь запросы с корректной подписью.
    """
    matched = ASSET_PATH_RE.match(path or "")
    if not matched:
        return False
    return verify(
        int(matched.group(1)),
        matched.group(2),
        (version or ""),
        expires,
        signature,
    )
