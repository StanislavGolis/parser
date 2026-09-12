# src/api/routes/admin_auth.py
"""Вход в админку по email+паролю и восстановление пароля.

Админка работает на общем токене `ADMIN_TOKEN`. Здесь — «человеческий» вход:
админ-аккаунт (email из `ADMIN_EMAILS`) + пароль → панель получает тот же токен,
поэтому вся остальная механика админки не меняется. Забытый пароль сбрасывается
ссылкой из письма (SMTP) либо командой на сервере:
`docker compose exec -T api python -m src.cli.admin set-password --email <адрес>`.

Все ответы нейтральны: по ним нельзя понять, какие адреса являются админскими.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_rate_limit, client_ip
from src.api.schemas import (
    AdminForgotIn,
    AdminForgotOut,
    AdminLoginIn,
    AdminLoginOut,
    AdminResetIn,
    AdminResetOut,
)
from src.core.config import settings
from src.core.db import get_session
from src.services import admin_auth, mailer
from src.services import auth as auth_service

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])
logger = logging.getLogger(__name__)

GENERIC_FORGOT_DETAIL = (
    "Если адрес разрешён для админки, письмо со ссылкой отправлено. "
    "Ссылка действует 30 минут."
)


def _base_url(request: Request) -> str:
    """База для ссылок в письме: PUBLIC_BASE_URL или адрес запроса."""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    return str(request.base_url)


@router.post("/login", response_model=AdminLoginOut)
async def admin_login(
    payload: AdminLoginIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Вход админа по email+паролю → отдаём ADMIN_TOKEN для панели."""
    await check_rate_limit(client_ip(request))

    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Админ-API выключен (нет ADMIN_TOKEN)")

    email = (payload.email or "").strip().lower()
    user = await admin_auth.get_admin(session, email)
    if user is None or not user.is_active or not auth_service.verify_password(
        payload.password or "", user.password_hash
    ):
        logger.warning("Неудачный вход в админку: %s (%s)", email, client_ip(request))
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    logger.info("Вход в админку: %s (%s)", email, client_ip(request))
    return AdminLoginOut(email=email, token=settings.ADMIN_TOKEN)


@router.post("/forgot", response_model=AdminForgotOut)
async def admin_forgot(
    payload: AdminForgotIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Запрос ссылки восстановления. Ответ всегда нейтральный."""
    await check_rate_limit(client_ip(request))
    email = (payload.email or "").strip().lower()
    smtp_ready = mailer.is_configured()

    user = await admin_auth.get_admin(session, email)
    if user is None:
        # Адрес не из allowlist (или ещё не заведён) — ничего не делаем.
        logger.info("Запрос восстановления для неразрешённого адреса: %s", email)
        detail = GENERIC_FORGOT_DETAIL if smtp_ready else _no_smtp_detail()
        return AdminForgotOut(sent=False, smtp_configured=smtp_ready, detail=detail)

    if not smtp_ready:
        return AdminForgotOut(sent=False, smtp_configured=False, detail=_no_smtp_detail())

    token = await admin_auth.create_reset_token(session, user)
    link = admin_auth.reset_link(_base_url(request), token)
    sent = await mailer.send_mail(
        to=user.email,
        subject=admin_auth.RESET_SUBJECT,
        text=admin_auth.reset_email_text(link, settings.ADMIN_RESET_TTL_MINUTES),
    )
    return AdminForgotOut(sent=sent, smtp_configured=True, detail=GENERIC_FORGOT_DETAIL)


def _no_smtp_detail() -> str:
    """Подсказка, когда почта не настроена (восстановление — командой на сервере)."""
    return (
        "Почта для восстановления не настроена. Доступ можно вернуть командой "
        "на сервере: docker compose exec -T api python -m src.cli.admin "
        "set-password --email <ваш-адрес>"
    )


@router.post("/reset", response_model=AdminResetOut)
async def admin_reset(
    payload: AdminResetIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Сброс пароля по одноразовой ссылке из письма."""
    await check_rate_limit(client_ip(request))
    try:
        user = await admin_auth.consume_reset_token(
            session, payload.token, payload.password
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Пароль админа изменён по ссылке: %s (%s)", user.email, client_ip(request))
    return AdminResetOut(email=user.email)
