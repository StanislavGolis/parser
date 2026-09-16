# src/services/cryptobot.py
"""Crypto Pay (CryptoBot): приём крипты инвойсами.

Как это работает: мы просим у Crypto Pay счёт на конкретную сумму в USDT, отдаём
человеку ссылку на оплату, а затем **сами** спрашиваем статус счёта (`getInvoices`) —
вебхук не обязателен, поэтому схема не зависит от доступности нашего домена извне.

Почему суммы фиксированные. Цена криптой хранится в тарифах (`plans.price_usdt_cents`,
правится в админке), а не считается по курсу в момент оплаты: покупатель видит ровно
ту сумму, которую заплатит, и она не «плывёт» между показом тарифа и счётом.

Идемпотентность обеспечивает `pricing.mark_paid` (ключ — `invoice_id` в
`payments.external_id`), поэтому повторная проверка статуса безопасна.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, Optional

import aiohttp

from src.core.config import settings

logger = logging.getLogger(__name__)

MAINNET = "https://pay.crypt.bot"
TESTNET = "https://testnet-pay.crypt.bot"


def base_url() -> str:
    """Адрес API: тестовая сеть включается флагом `CRYPTOBOT_TESTNET`."""
    return TESTNET if settings.CRYPTOBOT_TESTNET else MAINNET


def configured() -> bool:
    """Настроен ли приём крипты (есть токен приложения)."""
    return bool((settings.CRYPTOBOT_TOKEN or "").strip())


def cents_to_amount(cents: int) -> str:
    """Центы → сумма для API (`150` → `"1.5"`): Crypto Pay принимает строку."""
    return f"{cents / 100:.2f}".rstrip("0").rstrip(".") or "0"


async def call(method: str, payload: Optional[Dict[str, Any]] = None) -> Optional[dict]:
    """Запрос к Crypto Pay API. `None` — сеть/ошибка; словарь — ответ как есть."""
    token = (settings.CRYPTOBOT_TOKEN or "").strip()
    if not token:
        return None

    url = f"{base_url()}/api/{method}"
    headers = {"Crypto-Pay-API-Token": token}
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload or {}, headers=headers) as response:
                data = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Crypto Pay %s: %s", method, exc)
        return None

    if not isinstance(data, dict) or not data.get("ok"):
        logger.warning("Crypto Pay %s вернул ошибку: %s", method, data)
        return None
    return data


async def available() -> bool:
    """Живой ли токен: `getMe` возвращает приложение (id, имя, бот-процессор)."""
    data = await call("getMe")
    return bool(data and data.get("result"))


async def balance() -> list[Dict[str, str]]:
    """Баланс приложения по монетам (`getBalance`): `currency_code`, `available`, `onhold`.

    Деньги покупателя приходят на баланс приложения в Crypto Pay — у нас только журнал
    `payments`. Показываем оба рядом: расхождение значит, что оплата пришла, а выдача
    не сработала (или наоборот).
    """
    data = await call("getBalance")
    if not data:
        return []
    items = data.get("result") or []
    return [
        {
            "currency_code": str(item.get("currency_code") or ""),
            "available": str(item.get("available") or "0"),
            "onhold": str(item.get("onhold") or "0"),
        }
        for item in items
        if isinstance(item, dict)
    ]


async def create_invoice(
    *,
    amount_cents: int,
    title: str,
    description: str = "",
    payload: str = "",
) -> Optional[dict]:
    """Создаёт счёт и возвращает `{invoice_id, pay_url, amount, asset, status}`."""
    asset = (settings.CRYPTOBOT_ASSET or "USDT").strip().upper()
    body: Dict[str, Any] = {
        "currency_type": "crypto",
        "asset": asset,
        "amount": cents_to_amount(amount_cents),
        "description": (description or title)[:1024],
        # Через сколько минут счёт истечёт (сумма на это время фиксируется)
        "expires_in": max(60, int(settings.CRYPTOBOT_INVOICE_TTL_MINUTES) * 60),
        "allow_comments": False,
        "allow_anonymous": False,
    }
    if payload:
        body["payload"] = payload[:4096]

    data = await call("createInvoice", body)
    result = (data or {}).get("result") or {}
    if not result.get("invoice_id"):
        return None
    return {
        "invoice_id": int(result["invoice_id"]),
        "pay_url": result.get("bot_invoice_url") or result.get("mini_app_invoice_url") or "",
        "amount": result.get("amount"),
        "asset": result.get("asset"),
        "status": result.get("status"),
    }


async def get_invoice(invoice_id: int) -> Optional[dict]:
    """Статус счёта: `paid` — оплачен, `active` — ждёт оплаты, `expired` — истёк."""
    data = await call("getInvoices", {"invoice_ids": str(invoice_id)})
    items = ((data or {}).get("result") or {}).get("items") or []
    return items[0] if items else None


# ── Вебхук: мгновенная выдача вместо опроса ──────────────────────────


def webhook_token_ok(value: Optional[str]) -> bool:
    """Проверяет подпись вебхука: Crypto Pay шлёт токен приложения в заголовке.

    Заголовок — `crypto-pay-api-token`. Сравниваем постоянным по времени
    способом: угадать токен перебором по времени ответа не получится.
    """
    token = (settings.CRYPTOBOT_TOKEN or "").strip()
    sent = (value or "").strip()
    return bool(token) and secrets.compare_digest(sent, token)


def webhook_url() -> str:
    """Адрес нашего вебхука (из `SITE_URL`): Crypto Pay стучится сюда при оплате."""
    base = (settings.SITE_URL or "").strip().rstrip("/")
    return f"{base}/api/v1/billing/crypto/webhook" if base else ""


async def set_webhook(url: str, update_types: Optional[list[str]] = None) -> Optional[dict]:
    """Ставит вебхук: Crypto Pay будет присылать уведомления об оплате счёта.

    `update_types` по умолчанию только `invoice_paid` — нам не нужны события
    создания/истечения счёта, а поток уведомлений получается минимальным.
    """
    body: Dict[str, Any] = {"url": url}
    if update_types:
        body["update_types"] = update_types
    data = await call("setWebhook", body)
    return (data or {}).get("result")


async def delete_webhook() -> bool:
    """Выключает вебхук (остаётся опрос статуса по кнопке «Я оплатил»)."""
    return bool(await call("deleteWebhook"))


async def webhook_info() -> Optional[dict]:
    """Что настроено сейчас: `url`, `ip_address`, `update_types`, `last_error_*`."""
    data = await call("getWebhookInfo")
    return (data or {}).get("result")

