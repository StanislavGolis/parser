# src/api/routes/admin_users.py
"""Управление пользователями и журнал действий администратора (вкладка «Пользователи»).

Кто выполняет действие, знает только UI: он присылает заголовок `X-Admin-Actor`
с email, под которым вошёл админ. Скрипты с `ADMIN_TOKEN` пишутся как `admin-token`.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import client_ip, ip_hash, verify_admin
from src.core.config import settings
from src.core.db import get_session
from src.core.models import (
    AdminAudit,
    Board,
    DownloadStat,
    Media,
    MediaMark,
    User,
    UserSession,
    ViewStat,
)
from src.services import admin_auth, mailer
from src.services.analytics import record_audit
from src.services.premium import premium_active

router = APIRouter(prefix="/api/v1/admin", tags=["admin-users"])


def admin_actor(
    x_admin_actor: Optional[str] = Header(None, alias="X-Admin-Actor"),
) -> str:
    """Кто выполняет действие: UI присылает email, скрипты — «admin-token»."""
    return ((x_admin_actor or "").strip() or "admin-token")[:255]


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _user_out(user: User, counts: dict) -> dict:
    """Аккаунт + агрегаты (для списка и карточки)."""
    return {
        "id": user.id,
        "email": user.email,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "created_at": _iso(user.created_at),
        "premium_until": _iso(user.premium_until),
        "premium_active": premium_active(user),
        "marks_count": int(counts.get("marks") or 0),
        "views_count": int(counts.get("views") or 0),
        "downloads_count": int(counts.get("downloads") or 0),
        "last_seen_at": counts.get("last_seen_at"),
        "sessions_active": int(counts.get("sessions") or 0),
    }


@router.get("/users")
async def list_users(
    q: Optional[str] = Query(None, max_length=120),
    filter: str = Query("all", pattern="^(all|premium|without-premium|blocked|admins)$"),
    sort: str = Query("created", pattern="^(created|last_seen|marks|email)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Список аккаунтов: метки, просмотры, скачивания, когда последний раз заходил."""
    now = datetime.utcnow()
    marks = (
        select(MediaMark.user_id.label("user_id"), func.count().label("cnt"))
        .group_by(MediaMark.user_id)
        .subquery()
    )
    views = (
        select(ViewStat.user_id.label("user_id"), func.count().label("cnt"))
        .where(ViewStat.user_id.isnot(None))
        .group_by(ViewStat.user_id)
        .subquery()
    )
    downloads = (
        select(DownloadStat.user_id.label("user_id"), func.count().label("cnt"))
        .where(DownloadStat.user_id.isnot(None))
        .group_by(DownloadStat.user_id)
        .subquery()
    )
    live_sessions = (
        select(
            UserSession.user_id.label("user_id"),
            func.max(UserSession.last_seen_at).label("last_seen"),
            func.count().label("cnt"),
        )
        .where(UserSession.expires_at > now)
        .group_by(UserSession.user_id)
        .subquery()
    )

    base = (
        select(
            User,
            marks.c.cnt,
            views.c.cnt,
            downloads.c.cnt,
            live_sessions.c.last_seen,
            live_sessions.c.cnt,
        )
        .outerjoin(marks, marks.c.user_id == User.id)
        .outerjoin(views, views.c.user_id == User.id)
        .outerjoin(downloads, downloads.c.user_id == User.id)
        .outerjoin(live_sessions, live_sessions.c.user_id == User.id)
    )
    count_q = select(func.count()).select_from(User)

    conditions = []
    if q and q.strip():
        conditions.append(User.email.ilike(f"%{q.strip()}%"))
    if filter == "premium":
        conditions += [User.premium_until.isnot(None), User.premium_until > now]
    elif filter == "without-premium":
        conditions.append(or_(User.premium_until.is_(None), User.premium_until <= now))
    elif filter == "blocked":
        conditions.append(User.is_active.is_(False))
    elif filter == "admins":
        conditions.append(User.is_admin.is_(True))
    if conditions:
        base = base.where(*conditions)
        count_q = count_q.where(*conditions)

    total = (await session.execute(count_q)).scalar() or 0
    order = {
        "created": User.created_at.desc(),
        # coalesce: у аккаунтов без сессий «последний вход» пустой — берём регистрацию
        "last_seen": func.coalesce(live_sessions.c.last_seen, User.created_at).desc(),
        "marks": func.coalesce(marks.c.cnt, 0).desc(),
        "email": User.email.asc(),
    }[sort]

    rows = (
        await session.execute(
            base.order_by(order).offset((page - 1) * per_page).limit(per_page)
        )
    ).all()
    return {
        "items": [
            _user_out(
                row[0],
                {
                    "marks": row[1],
                    "views": row[2],
                    "downloads": row[3],
                    "last_seen_at": _iso(row[4]),
                    "sessions": row[5],
                },
            )
            for row in rows
        ],
        "page": page,
        "per_page": per_page,
        "total": int(total),
    }


@router.get("/users/{user_id}")
async def user_card(
    user_id: int,
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Карточка аккаунта: агрегаты, сессии (откуда заходил), метки, скачивания, аудит."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    async def count(model, column) -> int:
        value = (
            await session.execute(
                select(func.count()).select_from(model).where(column == user_id)
            )
        ).scalar()
        return int(value or 0)

    now = datetime.utcnow()
    sessions = (
        (
            await session.execute(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    marks = (
        await session.execute(
            select(MediaMark.created_at, Media.id, Media.original_name, Board.slug)
            .join(Media, Media.id == MediaMark.media_id)
            .join(Board, Board.id == Media.board_id)
            .where(MediaMark.user_id == user_id)
            .order_by(MediaMark.created_at.desc())
            .limit(20)
        )
    ).all()
    downloads = (
        await session.execute(
            select(DownloadStat.downloaded_at, Media.id, Media.original_name)
            .join(Media, Media.id == DownloadStat.media_id)
            .where(DownloadStat.user_id == user_id)
            .order_by(DownloadStat.downloaded_at.desc())
            .limit(20)
        )
    ).all()
    audit = (
        (
            await session.execute(
                select(AdminAudit)
                .where(AdminAudit.user_id == user_id)
                .order_by(AdminAudit.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    last_seen = max((s.last_seen_at for s in sessions if s.last_seen_at), default=None)

    return {
        **_user_out(
            user,
            {
                "marks": await count(MediaMark, MediaMark.user_id),
                "views": await count(ViewStat, ViewStat.user_id),
                "downloads": await count(DownloadStat, DownloadStat.user_id),
                "last_seen_at": _iso(last_seen),
                "sessions": len([s for s in sessions if s.expires_at > now]),
            },
        ),
        "sessions": [
            {
                "id": s.id,
                "created_at": _iso(s.created_at),
                "last_seen_at": _iso(s.last_seen_at),
                "expires_at": _iso(s.expires_at),
                "ip_hash": s.ip_hash,
                "user_agent": s.user_agent,
                "active": s.expires_at > now,
            }
            for s in sessions
        ],
        "marks": [
            {"at": _iso(r[0]), "media_id": r[1], "name": r[2], "board": r[3]} for r in marks
        ],
        "downloads": [
            {"at": _iso(r[0]), "media_id": r[1], "name": r[2]} for r in downloads
        ],
        "audit": [
            {
                "at": _iso(a.created_at),
                "actor": a.actor,
                "action": a.action,
                "details": a.details,
            }
            for a in audit
        ],
    }


class PremiumIn(BaseModel):
    """Выдать премиум на N дней; `days = null` — снять подписку."""

    days: Optional[int] = Field(None, ge=1, le=3650)


class ActiveIn(BaseModel):
    """Заблокировать или разблокировать аккаунт."""

    is_active: bool


def _public_base(request: Request) -> str:
    """Публичный адрес сайта для ссылок в письмах."""
    base = settings.PUBLIC_BASE_URL.strip()
    if base:
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


async def _load_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@router.post("/users/{user_id}/premium")
async def set_user_premium(
    user_id: int,
    payload: PremiumIn,
    request: Request,
    actor: str = Depends(admin_actor),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Выдать или снять премиум-подписку."""
    user = await _load_user(session, user_id)
    if payload.days is None:
        user.premium_until = None
        details = "подписка снята"
    else:
        user.premium_until = datetime.utcnow() + timedelta(days=payload.days)
        details = f"до {user.premium_until.date().isoformat()} ({payload.days} дн.)"
    await record_audit(
        session,
        action="user.premium",
        actor=actor,
        target=f"user:{user.id}",
        details=f"{user.email}: {details}",
        ip_hash_value=ip_hash(client_ip(request)),
        user_id=user.id,
    )
    await session.commit()
    return {
        "ok": True,
        "premium_until": _iso(user.premium_until),
        "premium_active": premium_active(user),
    }


@router.post("/users/{user_id}/active")
async def set_user_active(
    user_id: int,
    payload: ActiveIn,
    request: Request,
    actor: str = Depends(admin_actor),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Блокировка/разблокировка: при блокировке сессии удаляются."""
    user = await _load_user(session, user_id)
    user.is_active = bool(payload.is_active)
    revoked = 0
    if not user.is_active:
        result = await session.execute(
            delete(UserSession).where(UserSession.user_id == user.id)
        )
        revoked = result.rowcount or 0
    await record_audit(
        session,
        action="user.active",
        actor=actor,
        target=f"user:{user.id}",
        details=f"{user.email}: {'разблокирован' if user.is_active else 'заблокирован'}"
        + (f", сессий снято: {revoked}" if revoked else ""),
        ip_hash_value=ip_hash(client_ip(request)),
        user_id=user.id,
    )
    await session.commit()
    return {"ok": True, "is_active": bool(user.is_active), "revoked_sessions": revoked}


@router.post("/users/{user_id}/sessions/revoke")
async def revoke_user_sessions(
    user_id: int,
    request: Request,
    actor: str = Depends(admin_actor),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Выйти со всех устройств: удаляем все сессии аккаунта."""
    user = await _load_user(session, user_id)
    result = await session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    revoked = result.rowcount or 0
    await record_audit(
        session,
        action="user.sessions.revoke",
        actor=actor,
        target=f"user:{user.id}",
        details=f"{user.email}: снято сессий {revoked}",
        ip_hash_value=ip_hash(client_ip(request)),
        user_id=user.id,
    )
    await session.commit()
    return {"ok": True, "revoked_sessions": revoked}


@router.post("/users/{user_id}/reset-link")
async def create_user_reset_link(
    user_id: int,
    request: Request,
    send_email: bool = Query(True, description="Отправить ссылку письмом"),
    actor: str = Depends(admin_actor),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Одноразовая ссылка смены пароля для посетителя (TTL из настроек).

    Ссылку возвращаем в ответе — админ может передать её вручную; если SMTP
    настроен и `send_email=true`, отправляем письмо на адрес аккаунта.
    """
    user = await _load_user(session, user_id)
    token = await admin_auth.create_reset_token(session, user)
    link = admin_auth.user_reset_link(_public_base(request), token)

    sent = False
    if send_email:
        sent = await mailer.send_mail(
            user.email,
            "DREDGE: смена пароля",
            admin_auth.user_reset_email_text(link, settings.ADMIN_RESET_TTL_MINUTES),
        )
    await record_audit(
        session,
        action="user.reset-link",
        actor=actor,
        target=f"user:{user.id}",
        details=f"{user.email}: ссылка выдана" + (" и отправлена письмом" if sent else ""),
        ip_hash_value=ip_hash(client_ip(request)),
        user_id=user.id,
    )
    await session.commit()
    return {
        "ok": True,
        "url": link,
        "sent": sent,
        "smtp_configured": mailer.is_configured(),
        "ttl_minutes": settings.ADMIN_RESET_TTL_MINUTES,
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    actor: str = Depends(admin_actor),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Удаление аккаунта (метки, сессии — каскадом). Админ-аккаунты не удаляем."""
    user = await _load_user(session, user_id)
    if user.is_admin:
        raise HTTPException(
            status_code=400,
            detail="Админ-аккаунт удалить нельзя — сначала снимите флаг админа в БД",
        )
    email = user.email
    await record_audit(
        session,
        action="user.delete",
        actor=actor,
        target=f"user:{user.id}",
        details=f"{email}: аккаунт удалён",
        ip_hash_value=ip_hash(client_ip(request)),
    )
    await session.delete(user)
    await session.commit()
    return {"ok": True, "deleted": email}


@router.get("/audit")
async def audit_log(
    limit: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None, max_length=64),
    _=Depends(verify_admin),
    session: AsyncSession = Depends(get_session),
):
    """Журнал действий администраторов (свежие сверху)."""
    query = select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(limit)
    if action:
        query = query.where(AdminAudit.action == action)
    rows = (await session.execute(query)).scalars().all()
    return {
        "items": [
            {
                "at": _iso(a.created_at),
                "actor": a.actor,
                "action": a.action,
                "target": a.target,
                "details": a.details,
            }
            for a in rows
        ]
    }
