# src/tools/cryptobot_webhook.py
"""Вебхук Crypto Pay из командной строки: показать, включить, выключить.

Зачем вебхук: без него премиум выдаётся только после кнопки «Я оплатил» в боте
(бот опрашивает статус счёта). С вебхуком Crypto Pay сам сообщает об оплате, и
доступ открывается за секунды — покупателю ничего нажимать не нужно.

Ставится один раз при деплое (или кнопкой в админке: «Продажи» → «Кошельки»).

Примеры:
    python -m src.tools.cryptobot_webhook info
    python -m src.tools.cryptobot_webhook set
    python -m src.tools.cryptobot_webhook set --url https://dredg.ru/api/v1/billing/crypto/webhook
    python -m src.tools.cryptobot_webhook delete
"""
from __future__ import annotations

import argparse
import asyncio

from src.services import cryptobot


async def main() -> int:
    """Разбирает аргументы и выполняет команду; код возврата — для скриптов деплоя."""
    parser = argparse.ArgumentParser(description="Вебхук Crypto Pay")
    parser.add_argument("action", choices=("info", "set", "delete"))
    parser.add_argument("--url", default="", help="свой адрес вебхука (по умолчанию из SITE_URL)")
    args = parser.parse_args()

    if not cryptobot.configured():
        print("CRYPTOBOT_TOKEN не задан — приём крипты выключен")
        return 1

    if args.action == "info":
        info = await cryptobot.webhook_info()
        if info is None:
            print("Crypto Pay не ответил")
            return 1
        print(f"вебхук в Crypto Pay: {info.get('url') or 'не настроен'}")
        print(f"наш адрес:          {cryptobot.webhook_url()}")
        if info.get("last_error_message"):
            print(f"последняя ошибка:   {info['last_error_message']}")
        return 0

    if args.action == "set":
        target = (args.url or cryptobot.webhook_url()).strip()
        if not target.startswith("https://"):
            print(f"нужен https-адрес, получено: {target!r}")
            return 1
        result = await cryptobot.set_webhook(target, update_types=["invoice_paid"])
        if not result:
            print("не удалось включить вебхук")
            return 1
        print(f"вебхук включён: {target}")
        return 0

    if not await cryptobot.delete_webhook():
        print("не удалось выключить вебхук")
        return 1
    print("вебхук выключен (осталась проверка по кнопке «Я оплатил»)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
