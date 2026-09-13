# src/services/analytics.py
"""Своя аналитика: разбор User-Agent, запись посещений, аудит, ретеншн.

Наружу ничего не уходит: IP превращается в sha256-хеш (`ip_hash`), реферер
хранится только хостом, User-Agent разбирается на устройство/браузер/ОС.
"""
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import AdminAudit, PageHit, User, UserSession

# Маркеры ботов/превью: такие хиты пишем, но в дашборде исключаем.
BOT_MARKERS = re.compile(
    r"bot|crawler|spider|slurp|yandex|google|bing|duckduck|baidu|semrush|ahrefs|"
    r"mj12|dotbot|petal|applebot|telegram|whatsapp|facebookexternalhit|preview|"
    r"curl|wget|python-requests|httpx|aiohttp|go-http-client|okhttp|monitoring|uptime",
    re.I,
)
TABLET_MARKERS = re.compile(r"ipad|tablet|kindle|silk|android(?!.*mobile)", re.I)
MOBILE_MARKERS = re.compile(r"iphone|ipod|android.*mobile|windows phone|opera mini", re.I)


def parse_user_agent(user_agent: Optional[str]) -> dict:
    """Устройство/браузер/ОС/бот из User-Agent — без внешних библиотек."""
    ua = (user_agent or "").strip()
    low = ua.lower()

    if TABLET_MARKERS.search(ua):
        device = "tablet"
    elif MOBILE_MARKERS.search(ua):
        device = "mobile"
    elif not ua:
        device = "unknown"
    else:
        device = "desktop"

    # Порядок важен: Edge и Opera тоже содержат "chrome"/"safari".
    if "edg/" in low or "edgios" in low:
        browser = "Edge"
    elif "opr/" in low or "opera" in low:
        browser = "Opera"
    elif "yabrowser" in low:
        browser = "Yandex"
    elif "firefox" in low or "fxios" in low:
        browser = "Firefox"
    elif "chrome" in low or "crios" in low:
        browser = "Chrome"
    elif "safari" in low:
        browser = "Safari"
    else:
        browser = "other" if ua else "unknown"

    if "windows" in low:
        os_name = "Windows"
    elif "android" in low:
        os_name = "Android"
    elif "iphone" in low or "ipad" in low or "ios" in low:
        os_name = "iOS"
    elif "mac os" in low or "macintosh" in low:
        os_name = "macOS"
    elif "linux" in low:
        os_name = "Linux"
    else:
        os_name = "other" if ua else "unknown"

    return {
        "device": device,
        "browser": browser,
        "os": os_name,
        "is_bot": bool(BOT_MARKERS.search(ua)),
    }


def normalize_path(raw: Optional[str]) -> str:
    """Путь страницы без query/fragment, обрезанный по длине колонки."""
    path = (raw or "/").split("#", 1)[0].split("?", 1)[0].strip() or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return path[:255]


def referrer_host(value: Optional[str], site_host: Optional[str] = None) -> Optional[str]:
    """Хост внешнего реферера; None — прямой заход или внутренний переход."""
    if not value:
        return None
    candidate = value if "//" in value else f"//{value}"
    try:
        host = (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    if site_host and host == site_host.lower():
        return None
    return host[:120]


async def record_hit(
    session: AsyncSession,
    *,
    kind: str,
    path: str,
    event: Optional[str] = None,
    session_id: Optional[str] = None,
    user: Optional[User] = None,
    ip_hash_value: Optional[str] = None,
    referrer: Optional[str] = None,
    utm_source: Optional[str] = None,
    user_agent: Optional[str] = None,
    is_new_visit: bool = False,
) -> None:
    """Пишет посещение/событие. Коммит — на вызывающей стороне."""
    ua = parse_user_agent(user_agent)
    session.add(
        PageHit(
            kind=kind,
            path=path,
            event=event,
            session_id=session_id,
            user_id=user.id if user else None,
            ip_hash=ip_hash_value,
            referrer_host=referrer,
            utm_source=(utm_source or None) and utm_source[:80],
            device=ua["device"],
            browser=ua["browser"],
            os=ua["os"],
            is_bot=ua["is_bot"],
            is_new_visit=is_new_visit,
        )
    )


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    actor: Optional[str] = None,
    target: Optional[str] = None,
    details: Optional[str] = None,
    ip_hash_value: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    """Пишет действие администратора в журнал. Коммит — на вызывающей стороне."""
    session.add(
        AdminAudit(
            actor=(actor or "admin-token")[:255],
            action=action[:64],
            target=(target or None) and str(target)[:120],
            details=details,
            ip_hash=ip_hash_value,
            user_id=user_id,
        )
    )


async def cleanup_analytics(session: AsyncSession) -> dict:
    """Ретеншн: чистит старые посещения, аудит и истёкшие сессии.

    Запускается фоновой задачей API (раз в несколько часов), чтобы таблица
    посещений не росла бесконечно.
    """
    now = datetime.utcnow()
    hits = await session.execute(
        delete(PageHit).where(
            PageHit.created_at < now - timedelta(days=settings.ANALYTICS_RETENTION_DAYS)
        )
    )
    audit = await session.execute(
        delete(AdminAudit).where(AdminAudit.created_at < now - timedelta(days=365))
    )
    sessions = await session.execute(
        delete(UserSession).where(UserSession.expires_at < now - timedelta(days=7))
    )
    await session.commit()
    return {
        "hits": hits.rowcount or 0,
        "audit": audit.rowcount or 0,
        "sessions": sessions.rowcount or 0,
    }
