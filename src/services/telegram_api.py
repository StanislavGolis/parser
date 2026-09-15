# src/services/telegram_api.py
"""Публикация в Telegram-канал из админки: тонкая обёртка над Bot API.

Бот-процесс (`src/tools/telegram_bot.py`) отвечает на команды через long polling,
а публикация инициируется из админки — поэтому вызовы Bot API нужны и в API-сервисе.
Обёртка держит только то, что действительно используется: фото с подписью и
inline-кнопкой, текстовый пост, удаление сообщения (для отката ошибочной публикации).
"""
import json
import logging
from typing import Optional

import aiohttp

from src.core.config import settings

log = logging.getLogger("telegram_api")

API_BASE = "https://api.telegram.org"


class TelegramError(RuntimeError):
    """Ошибка Bot API: текст от Telegram пригоден для журнала и админки."""


def is_configured() -> bool:
    """Можно ли публиковать: заданы токен бота и канал."""
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    channel = (settings.TELEGRAM_CHANNEL or "").strip()
    return bool(token and channel)


def channel_chat_id() -> str:
    """Ссылка на канал в формате, который понимает Bot API."""
    return f"@{(settings.TELEGRAM_CHANNEL or '').strip().lstrip('@')}"


async def _call(method: str, *, data: Optional[dict] = None, files: Optional[dict] = None):
    """Вызов метода Bot API: JSON или multipart, с разбором ошибок Telegram."""
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN не задан — публикация недоступна")

    url = f"{API_BASE}/bot{token}/{method}"
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if files:
            form = aiohttp.FormData()
            for key, value in (data or {}).items():
                form.add_field(key, str(value))
            for key, (name, payload, content_type) in files.items():
                form.add_field(key, payload, filename=name, content_type=content_type)
            async with session.post(url, data=form) as response:
                body = await response.json(content_type=None)
        else:
            async with session.post(url, json=data or {}) as response:
                body = await response.json(content_type=None)

    if not body.get("ok"):
        raise TelegramError(body.get("description") or "Bot API: неизвестная ошибка")
    return body.get("result")


def _reply_markup(
    button_text: str = "",
    button_url: str = "",
    buttons: Optional[list] = None,
) -> Optional[str]:
    """Inline-клавиатура: одна кнопка-ссылка или готовый набор кнопок."""
    if buttons:
        return json.dumps({"inline_keyboard": buttons})
    if not (button_text and button_url):
        return None
    return json.dumps({"inline_keyboard": [[{"text": button_text, "url": button_url}]]})


async def send_photo(
    *,
    photo: bytes,
    caption: str,
    button_text: str = "",
    button_url: str = "",
    chat_id: Optional[str] = None,
    buttons: Optional[list] = None,
) -> dict:
    """Публикует фото с подписью и (опционально) кнопками.

    Подпись обрезаем до лимита Telegram (1024 символа у фото) — иначе отправка
    отваливается целиком, а не «чуть короче».
    """
    data: dict = {
        "chat_id": chat_id or channel_chat_id(),
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    markup = _reply_markup(button_text, button_url, buttons)
    if markup:
        data["reply_markup"] = markup
    return await _call("sendPhoto", data=data, files={"photo": ("teaser.jpg", photo, "image/jpeg")})


async def send_message(
    *,
    text: str,
    button_text: str = "",
    button_url: str = "",
    chat_id: Optional[str] = None,
    buttons: Optional[list] = None,
) -> dict:
    """Отправляет текстовый пост (анонс, карантин админу и т.п.)."""
    data: dict = {
        "chat_id": chat_id or channel_chat_id(),
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    markup = _reply_markup(button_text, button_url, buttons)
    if markup:
        data["reply_markup"] = markup
    return await _call("sendMessage", data=data)


async def chat_member_count(chat_id: Optional[str] = None) -> int:
    """Сколько подписчиков в канале — метрика для триггеров розыгрышей."""
    result = await _call("getChatMemberCount", data={"chat_id": chat_id or channel_chat_id()})
    return int(result or 0)


async def is_subscribed(user_id: int, chat_id: Optional[str] = None) -> bool:
    """Подписан ли пользователь на канал (условие участия в розыгрыше).

    Бот должен быть администратором канала, иначе Telegram не даёт проверить
    участника — в этом случае считаем условие выполненным, чтобы не блокировать
    розыгрыш из-за настройки.
    """
    try:
        result = await _call(
            "getChatMember", data={"chat_id": chat_id or channel_chat_id(), "user_id": user_id}
        )
    except TelegramError:
        return True
    status = (result or {}).get("status")
    return status in ("creator", "administrator", "member", "restricted")



async def delete_message(message_id: int) -> bool:
    """Удаляет сообщение канала (откат ошибочной публикации)."""
    await _call("deleteMessage", data={"chat_id": channel_chat_id(), "message_id": message_id})
    return True
