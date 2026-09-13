# src/api/routes/track.py
"""Приём посещений и событий интерфейса (своя аналитика, без внешних счётчиков)."""
import re
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip, get_current_user, ip_hash
from src.core.config import settings
from src.core.db import get_session
from src.core.models import User
from src.services.analytics import normalize_path, record_hit, referrer_host

router = APIRouter(prefix="/api/v1/hit", tags=["track"])

# Анонимный id визита из cookie dv_sid и имя события — только безопасные символы.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
EVENT_RE = re.compile(r"^[a-z0-9_.:-]{2,64}$")


class HitIn(BaseModel):
    """Что присылает фронтенд: адрес страницы, либо событие."""

    path: str = Field("/", max_length=255)
    event: Optional[str] = Field(None, max_length=64)
    session_id: Optional[str] = Field(None, max_length=40)
    # document.referrer — только на первом хите визита (дальше переходы внутренние)
    referrer: Optional[str] = Field(None, max_length=300)
    utm_source: Optional[str] = Field(None, max_length=80)
    new_visit: bool = False


class HitOut(BaseModel):
    ok: bool = True


@router.post("", response_model=HitOut)
async def track_hit(
    payload: HitIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: Optional[User] = Depends(get_current_user),
):
    """Просмотр страницы или событие интерфейса.

    Мусор тихо игнорируем (битый `session_id`, неизвестное событие): аналитика не
    должна ломать сайт. Личность не определяется — IP храним только хешем.
    """
    if not settings.ANALYTICS_ENABLED:
        return HitOut()

    await check_rate_limit(client_ip(request))

    event = payload.event if payload.event and EVENT_RE.match(payload.event) else None
    session_id = (
        payload.session_id
        if payload.session_id and SESSION_ID_RE.match(payload.session_id)
        else None
    )
    site_host = (request.headers.get("host") or "").split(":")[0]

    await record_hit(
        session,
        kind="event" if event else "page",
        path=normalize_path(payload.path),
        event=event,
        session_id=session_id,
        user=user,
        ip_hash_value=ip_hash(client_ip(request)),
        referrer=referrer_host(
            payload.referrer or request.headers.get("referer"), site_host
        ),
        utm_source=payload.utm_source,
        user_agent=request.headers.get("user-agent"),
        is_new_visit=bool(payload.new_visit),
    )
    await session.commit()
    return HitOut()
