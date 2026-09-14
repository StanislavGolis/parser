# src/tools/telegram_bot.py
"""Telegram-бот Dredger 2.0: доступ к закрытому сайту и статус подписки.

Модель: Telegram продаёт и выдаёт доступ, сайт показывает. Бот — единственный
вход на сайт (magic link), поэтому он же и «касса»:

    /start     — приветствие и что делать дальше
    /link      — одноразовая ссылка на сайт (вход)
    /status    — активна ли подписка и до какого числа
    /subscribe — тарифы (оплата подключается в фазе 4)
    /help      — короткий FAQ

Зависимостей не добавляем: бот работает на `aiohttp` через Bot API (long polling).
Пока `TELEGRAM_BOT_TOKEN` пуст, сервис не падает, а ждёт — так его можно выкатить
до получения токена у @BotFather.

Запуск: `python -m src.tools.telegram_bot`
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

from src.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("telegram_bot")

API_BASE = "https://api.telegram.org"
# Долгий опрос: держим соединение 30 секунд, как советует Bot API
POLL_TIMEOUT = 30
# Пауза, если токена нет (сервис выкачен заранее): ждём настройки
NO_TOKEN_SLEEP = 60

HELP_TEXT = (
    "Что умеет бот:\n"
    "/link — ссылка для входа на сайт (живёт 10 минут, одноразовая)\n"
    "/status — активна ли подписка и до какого числа\n"
    "/subscribe — тарифы\n"
    "/help — эта справка\n\n"
    "Сайт закрытый: без подписки доступны только несколько файлов."
)

SUBSCRIBE_TEXT = (
    "Тарифы готовятся к запуску.\n\n"
    "Планируем: месяц, год и «навсегда» — оплата криптой (быстро и без блокировок). "
    "Пока доступ можно получить по заявке: напишите администратору, и мы включим его "
    "вручную."
)


def _api_base() -> str:
    """Адрес нашего API: внутри compose — `http://api:8000` (переменная API_INTERNAL_URL)."""
    return os.environ.get("API_INTERNAL_URL", "http://api:8000").rstrip("/")


# Кнопки под полем ввода: закрытый сайт открывается только через ссылку из бота
MAIN_KEYBOARD = {
    "keyboard": [["🔓 Войти на сайт", "⭐ Статус подписки"], ["💳 Тарифы", "❓ Помощь"]],
    "resize_keyboard": True,
    "is_persistent": True,
}


# Меню команд в интерфейсе Telegram (подсказки в поле ввода)
BOT_COMMANDS = [
    {"command": "link", "description": "Ссылка для входа на сайт"},
    {"command": "status", "description": "Статус подписки"},
    {"command": "subscribe", "description": "Тарифы и оплата"},
    {"command": "help", "description": "Помощь"},
]


class BotClient:
    """Минимальный клиент Bot API через aiohttp (без внешних зависимостей)."""

    def __init__(self, token: str, session: aiohttp.ClientSession) -> None:
        self.session = session
        self.base = f"{API_BASE}/bot{token}"

    async def call(self, method: str, **payload: Any) -> Optional[Any]:
        """Вызов метода Bot API. `None` — сеть недоступна или метод вернул ошибку."""
        try:
            async with self.session.post(
                f"{self.base}/{method}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=POLL_TIMEOUT + 25),
            ) as resp:
                data = await resp.json(content_type=None)
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут: повторим в следующем цикле
            logger.warning("Bot API %s недоступен: %s", method, exc)
            return None

        if not isinstance(data, dict) or not data.get("ok"):
            description = (data or {}).get("description") if isinstance(data, dict) else None
            logger.warning("Bot API %s вернул ошибку: %s", method, description)
            return None
        return data.get("result")

    async def send(self, chat_id: int, text: str, keyboard: Optional[dict] = None) -> None:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        await self.call("sendMessage", **payload)

    async def get_updates(self, offset: Optional[int]) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = await self.call("getUpdates", **payload)
        return result if isinstance(result, list) else []


async def api_request(
    session: aiohttp.ClientSession, method: str, path: str, **kwargs: Any
) -> Optional[dict]:
    """Запрос к нашему API от имени бота (заголовок X-Bot-Token)."""
    headers = {
        "accept": "application/json",
        "X-Bot-Token": (settings.TELEGRAM_BOT_TOKEN or "").strip(),
    }
    try:
        async with session.request(
            method,
            f"{_api_base()}{path}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=25),
            **kwargs,
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                logger.info("API %s → %s (%s)", path, resp.status, data)
                return {"error": resp.status}
            return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001 — API может быть недоступен, бот продолжает работу
        logger.warning("API %s недоступен: %s", path, exc)
        return None


async def handle_message(session: aiohttp.ClientSession, bot: BotClient, message: dict) -> None:
    """Обработка одного сообщения: команды и кнопки клавиатуры."""
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    sender = message.get("from") or {}
    telegram_id = sender.get("id")
    if not text or not chat_id or not telegram_id:
        return

    username = sender.get("username")
    command = text.split()[0].split("@")[0].lower()

    # Кнопки клавиатуры приходят обычным текстом — сводим их к командам
    if text.startswith("🔓"):
        command = "/link"
    elif text.startswith("⭐"):
        command = "/status"
    elif text.startswith("💳"):
        command = "/subscribe"
    elif text.startswith("❓"):
        command = "/help"

    if command in ("/start", "/help"):
        await bot.send(
            chat_id,
            "Dredger — закрытый архив.\n\n"
            "Вход на сайт — по ссылке из бота: она одноразовая и живёт 10 минут.\n\n"
            + HELP_TEXT,
            keyboard=MAIN_KEYBOARD,
        )
        return

    if command in ("/link", "/site", "/enter"):
        data = await api_request(
            session,
            "POST",
            "/api/v1/auth/magic/issue",
            json={"telegram_id": telegram_id, "username": username},
        )
        if not data or "url" not in data:
            await bot.send(chat_id, "Не удалось выдать ссылку. Попробуйте ещё раз через минуту.")
            return
        await bot.send(
            chat_id,
            "Ссылка для входа на сайт (одноразовая, 10 минут):\n"
            f"{data['url']}\n\n"
            "Откройте её в браузере — вход произойдёт автоматически.",
        )
        return

    if command == "/status":
        data = await api_request(
            session, "GET", f"/api/v1/auth/telegram/status?telegram_id={telegram_id}"
        )
        if not data:
            await bot.send(chat_id, "Сервис недоступен, попробуйте позже.")
            return
        if data.get("error") == 404:
            await bot.send(
                chat_id,
                "Аккаунта ещё нет. Нажмите «🔓 Войти на сайт» — создадим его и пришлём ссылку.",
                keyboard=MAIN_KEYBOARD,
            )
            return
        until = (data.get("premium_until") or "")[:10]
        if data.get("premium_active"):
            await bot.send(chat_id, f"Подписка активна до {until}.\nСсылка на сайт — /link")
        else:
            await bot.send(
                chat_id, "Подписка не активна.\nТарифы — /subscribe, вход на сайт — /link"
            )
        return

    if command == "/subscribe":
        await bot.send(chat_id, SUBSCRIBE_TEXT, keyboard=MAIN_KEYBOARD)
        return

    await bot.send(chat_id, "Не понял команду.\n\n" + HELP_TEXT, keyboard=MAIN_KEYBOARD)


async def main() -> None:
    """Долгий опрос Bot API. Пока токен не задан — ждём, не выходя из процесса.

    Так сервис можно выкатить заранее: контейнер не рестартует по кругу, а просто
    спит. После добавления токена в `.env` достаточно перезапустить сервис.
    """
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN не задан — бот не запущен. Добавьте токен в .env "
            "и перезапустите: docker compose up -d telegram-gateway"
        )
        while True:
            await asyncio.sleep(NO_TOKEN_SLEEP)

    logger.info("Бот запущен (long polling), API: %s", _api_base())
    async with aiohttp.ClientSession() as session:
        bot = BotClient(token, session)
        me = await bot.call("getMe")
        if isinstance(me, dict):
            logger.info("Подключён как @%s", me.get("username"))
            # Меню команд в Telegram: появляется при вводе «/»
            await bot.call("setMyCommands", commands=BOT_COMMANDS)

        offset: Optional[int] = None
        while True:
            updates = await bot.get_updates(offset)
            for update in updates:
                # Сдвигаем offset до обработки: сбойный апдейт не должен зацикливаться
                offset = int(update.get("update_id", 0)) + 1
                try:
                    await handle_message(session, bot, update.get("message") or {})
                except Exception:  # noqa: BLE001 — бот не должен падать из-за одного сообщения
                    logger.exception("Ошибка обработки обновления")
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено вручную")



