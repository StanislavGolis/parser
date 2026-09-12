# src/services/mailer.py
"""Отправка почты (только stdlib: smtplib + asyncio.to_thread).

Нужна для ссылок восстановления доступа в админку. Если SMTP не настроен
(`SMTP_HOST` пуст) — `is_configured()` возвращает False, а вызывающий код
предлагает резервный путь: восстановление командой на сервере
(`python -m src.cli.admin set-password`, см. DEPLOY.md).
"""
import asyncio
import smtplib
import ssl as ssl_module
from email.message import EmailMessage

from src.core.config import settings


def is_configured() -> bool:
    """Готова ли отправка писем (хост и креды заданы)."""
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def _send_sync(to: str, subject: str, text: str) -> None:
    """Синхронная отправка (вызывается в отдельном потоке)."""
    sender = settings.SMTP_FROM or settings.SMTP_USER
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)

    mode = (settings.SMTP_TLS or "ssl").lower()
    if mode == "ssl":
        context = ssl_module.create_default_context()
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=25, context=context
        ) as smtp:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=25) as smtp:
        smtp.ehlo()
        if mode == "starttls":
            smtp.starttls(context=ssl_module.create_default_context())
            smtp.ehlo()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)


async def send_mail(to: str, subject: str, text: str) -> bool:
    """Отправляет письмо. False — SMTP не настроен или отправка не удалась."""
    if not is_configured():
        print(f"   [mail] SMTP не настроен — письмо для {to} не отправлено")
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, text)
    except Exception as exc:  # noqa: BLE001
        print(f"   [mail] Ошибка отправки для {to}: {exc}")
        return False
    print(f"   [mail] Письмо отправлено: {to}")
    return True
