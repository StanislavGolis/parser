# src/tools/check_mail.py
"""Проверка почты: тестовое письмо и диагностика SMTP-настроек.

Зачем отдельный инструмент. От SMTP зависят ссылки восстановления доступа,
уведомления о жалобах и обратной связи. После смены почтового провайдера (например,
переход с Gmail на Яндекс 360 для своего домена) нужно за минуту убедиться, что
письма реально уходят, а не только «настройки выглядят верно».

Запуск (внутри контейнера api):

    python -m src.tools.check_mail --show              # показать настройки (без отправки)
    python -m src.tools.check_mail --to you@example.com
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from src.core.config import settings
from src.services import mailer


async def _run(args: argparse.Namespace) -> int:
    print("Настройки почты:")
    print(f"  SMTP_HOST:     {settings.SMTP_HOST or '— (письма выключены)'}")
    print(f"  SMTP_PORT:     {settings.SMTP_PORT} ({settings.SMTP_TLS})")
    print(f"  SMTP_USER:     {settings.SMTP_USER or '—'}")
    print(f"  SMTP_FROM:     {settings.SMTP_FROM or settings.SMTP_USER or '—'}")
    # Пароль не печатаем: только факт, что он задан
    print(f"  SMTP_PASSWORD: {'задан' if settings.SMTP_PASSWORD else 'пусто'}")
    print(f"  ADMIN_EMAILS:  {', '.join(settings.admin_emails) or '—'}")
    print(f"  SMTP готов:    {'да' if mailer.is_configured() else 'нет'}")

    if not args.to:
        print("\nДля отправки теста укажите адрес: --to you@example.com")
        return 0

    if not mailer.is_configured():
        print("\nПисьмо не отправлено: SMTP не настроен (нужны SMTP_HOST/SMTP_USER/SMTP_PASSWORD)")
        return 1

    subject = "Dredger: проверка почты"
    text = (
        "Это тестовое письмо от сервиса Dredger.\n\n"
        f"Отправитель: {settings.SMTP_FROM or settings.SMTP_USER}\n"
        f"Почтовый сервер: {settings.SMTP_HOST}:{settings.SMTP_PORT} ({settings.SMTP_TLS})\n\n"
        "Если письмо пришло — почта настроена верно: ссылки восстановления доступа\n"
        "и уведомления модерации будут доходить.\n"
    )

    print(f"\nОтправляем на: {', '.join(args.to)}")
    failed = 0
    for address in args.to:
        try:
            await mailer.send_mail(address, subject, text)
            print(f"  {address}: отправлено")
        except Exception as exc:  # noqa: BLE001 — показываем причину как есть
            failed += 1
            print(f"  {address}: ошибка — {exc}")
    return 0 if failed == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка почты Dredger")
    parser.add_argument("--to", action="append", help="адрес получателя (можно несколько)")
    parser.add_argument("--show", action="store_true", help="только показать настройки")
    args = parser.parse_args()
    if not args.to:
        args.show = True
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
