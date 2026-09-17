# src/tools/cryptobot_webhook.py
"""Вебхук Crypto Pay: адрес для настройки и факт последней доставки.

Зачем вебхук: без него премиум выдаётся только после кнопки «Я оплатил» в боте
(бот опрашивает статус счёта). С вебхуком Crypto Pay сам сообщает об оплате, и
доступ открывается за секунды.

Включить вебхук через API нельзя: у Crypto Pay нет методов `setWebhook` /
`getWebhookInfo` (поэтому здесь и нет команд установки). Адрес задаётся вручную:
@CryptoBot → Crypto Pay → My Apps → приложение → Webhooks… → «Enable Webhooks»
и вписать адрес, который печатает эта команда.

Пример:
    python -m src.tools.cryptobot_webhook info
"""
from __future__ import annotations

import argparse
import asyncio

from src.services import cryptobot


async def main() -> int:
    """Показывает адрес вебхука и когда приходило последнее уведомление."""
    parser = argparse.ArgumentParser(description="Вебхук Crypto Pay")
    parser.add_argument("action", choices=("info",), nargs="?", default="info")
    args = parser.parse_args()  # noqa: F841 — команда одна, аргумент оставлен для ясности

    if not cryptobot.configured():
        print("CRYPTOBOT_TOKEN не задан — приём крипты выключен")
        return 1

    print(f"адрес для настроек приложения: {cryptobot.webhook_url() or '— (нужен SITE_URL)'}")
    last = await cryptobot.last_webhook()
    if last:
        print(f"последнее уведомление: {last.get('at')} (счёт {last.get('invoice_id')}, "
              f"оплачен: {'да' if last.get('paid') else 'нет'})")
    else:
        print("уведомлений ещё не было — вебхук не включён в @CryptoBot "
              "(Crypto Pay → My Apps → Webhooks → Enable)")
    apps = await cryptobot.app_info()
    if apps:
        print(f"приложение: {apps.get('name')} (app_id {apps.get('app_id')})")

    # Закрываем соединения Redis: иначе на выходе asyncio ругается
    # «Event loop is closed» — мелочь, но пугает при чтении вывода.
    from src.core.redis_client import redis_client

    for closer in ("aclose", "close"):
        method = getattr(redis_client, closer, None)
        if method is None:
            continue
        try:
            await method()
        except Exception:  # noqa: BLE001
            pass
        break
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
