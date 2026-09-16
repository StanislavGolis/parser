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
from __future__ import annotations

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
    "/link — войти на сайт (ссылка на 10 минут)\n"
    "/status — подписка и срок\n"
    "/subscribe — тарифы и оплата\n"
    "/id — ваш Telegram ID\n"
    "/help — эта справка\n\n"
    "Запрещённый контент — кнопка «Пожаловаться» в просмотре файла.\n"
    "Правообладателям — раздел /dmca на сайте."
)

SUBSCRIBE_TEXT = (
    "Тарифы сейчас недоступны — попробуйте позже или напишите администратору."
)


def plans_text(data: Optional[dict]) -> str:
    """Витрина тарифов для `/subscribe`: цены в рублях и звёздах + условия акций.

    Данные приходят из API (`GET /api/v1/plans`) — бот и сайт показывают одни и те же
    цены, поэтому «акция включилась» не превращается в два разных ответа. Названия и
    описания акций задаются в админке, здесь они просто выводятся как есть.
    """
    if not data or not data.get("plans"):
        return SUBSCRIBE_TEXT

    lines = ["Подписка Dredger — приватные разделы, оригиналы и скачивание.\n"]

    for plan in data["plans"]:
        title = plan.get("title") or plan.get("code")
        stars = plan.get("stars_now") or plan.get("price_stars")
        if not stars:
            # Сетка продаётся только за звёзды: тариф без цены в звёздах не показываем
            continue
        base_stars = plan.get("price_stars")
        days = int(plan.get("days") or 0)
        # Вместо повторов названия («Навсегда … без срока») — то, что реально полезно:
        # цена за день у срочных тарифов и «оплата один раз» у бессрочного.
        if plan.get("is_forever") or days <= 0:
            detail = "оплата один раз"
        else:
            per_day = int(stars) / days
            shown = (
                f"{per_day:.1f}".replace(".", ",") if per_day < 10 else f"{per_day:.0f}"
            )
            detail = f"≈ {shown} ⭐ в день"
        tail = (
            f" (вместо {int(base_stars)} ⭐)"
            if base_stars and int(base_stars) != int(stars)
            else ""
        )
        lines.append(f"• {title} — {int(stars)} ⭐{tail} · {detail}")

    for promo in data.get("promos") or []:
        left: list[str] = []
        if promo.get("days_left") is not None:
            left.append(f"{promo['days_left']} дн.")
        if promo.get("paid_left") is not None:
            left.append(f"{promo['paid_left']} оплат по лимиту")
        tail = f" Осталось: {' или '.join(left)}." if left else ""
        description = ""
        if promo.get("description"):
            text = promo["description"].strip()
            description = "\n" + (text if text.endswith((".", "!", "?")) else f"{text}.")
        lines.append(
            f"\n{promo.get('title') or 'Акция'}: −{promo['percent']}% на тарифы."
            f"{description}{tail}"
        )

    lines.append("\nОплата звёздами или криптой (USDT) — кнопками ниже.")
    return "\n".join(lines)


def plans_keyboard(data: Optional[dict]) -> Optional[dict]:
    """Кнопки оплаты звёздами: свой ряд на тариф, где цена в звёздах задана.

    В `callback_data` кладём и тариф, и акцию: сервер применит ту же скидку, которую
    человек видел в счёте.
    """
    rows = []
    for plan in (data or {}).get("plans") or []:
        stars = plan.get("stars_now") or plan.get("price_stars")
        if not stars:
            continue
        rows.append(
            [
                {
                    "text": f"{plan.get('title')} — {int(stars)} ⭐",
                    "callback_data": f"buy:{plan.get('code')}:{plan.get('promo_id') or 0}",
                }
            ]
        )
    # Крипта показывается отдельной кнопкой: свой список тарифов с ценой в USDT
    if has_crypto(data):
        rows.append([{"text": "🪙 Оплатить криптой", "callback_data": "crypto:list:0"}])
    return {"inline_keyboard": rows} if rows else None


def has_crypto(data: Optional[dict]) -> bool:
    """Есть ли тарифы с ценой в USDT (иначе кнопку крипты не показываем)."""
    return any(
        (plan.get("usdt_now_cents") or plan.get("price_usdt_cents"))
        for plan in (data or {}).get("plans") or []
    )


def crypto_keyboard(data: Optional[dict]) -> Optional[dict]:
    """Кнопки тарифов с ценой в USDT: счёт выставляет Crypto Pay по нашей заявке."""
    rows = []
    for plan in (data or {}).get("plans") or []:
        cents = plan.get("usdt_now_cents") or plan.get("price_usdt_cents")
        if not cents:
            continue
        amount = f"{cents / 100:.2f}".rstrip("0").rstrip(".")
        rows.append(
            [
                {
                    "text": f"{plan.get('title')} — {amount} USDT",
                    "callback_data": f"cryptobuy:{plan.get('code')}:{plan.get('promo_id') or 0}",
                }
            ]
        )
    return {"inline_keyboard": rows} if rows else None


async def send_crypto_invoice(
    session: aiohttp.ClientSession, bot: BotClient, chat_id: int, plan_code: str, promo_id: int = 0
) -> None:
    """Просит у нашего API счёт в Crypto Pay и присылает ссылку на оплату."""
    data = await api_request(
        session,
        "POST",
        "/api/v1/billing/crypto",
        json={"telegram_id": chat_id, "plan_code": plan_code, "promo_id": promo_id or None},
    )
    if not data or data.get("error"):
        await bot.send(
            chat_id,
            "Приём крипты сейчас недоступен — попробуйте позже или оплатите звёздами.",
        )
        return
    if data.get("paid"):
        until = str(data.get("premium_until") or "")[:10]
        await bot.send(chat_id, f"Оплата уже получена — подписка до {until}.")
        return

    amount = data.get("amount")
    asset = data.get("asset") or "USDT"
    invoice_id = data.get("invoice_id")
    pay_url = data.get("pay_url")
    rows = []
    if pay_url:
        rows.append([{"text": f"💳 Оплатить {amount} {asset}", "url": pay_url}])
    rows.append([{"text": "✅ Я оплатил", "callback_data": f"cryptocheck:{invoice_id}"}])
    await bot.send(
        chat_id,
        f"Счёт создан: {amount} {asset}.\n"
        "Оплатите по кнопке ниже — подписка включится сразу после подтверждения.",
        keyboard={"inline_keyboard": rows},
    )


async def check_crypto_payment(
    session: aiohttp.ClientSession, bot: BotClient, chat_id: int, invoice_id: int
) -> None:
    """Спрашивает у API статус счёта и выдаёт премиум, если он оплачен."""
    data = await api_request(
        session, "POST", "/api/v1/billing/crypto/check", json={"invoice_id": invoice_id}
    )
    if not data or data.get("error"):
        await bot.send(chat_id, "Не получилось проверить счёт — напишите администратору.")
        return
    if data.get("paid"):
        until = str(data.get("premium_until") or "")[:10]
        await bot.send(
            chat_id, f"Оплата получена. Подписка активна до {until}.", keyboard=MAIN_KEYBOARD
        )
        return
    if data.get("status") == "expired":
        await bot.send(chat_id, "Счёт истёк — создайте новый: /subscribe.")
    else:
        await bot.send(
            chat_id,
            "Оплата пока не поступила. Если только что перевели — попробуйте ещё раз через минуту.",
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
        payload: Dict[str, Any] = {
            "timeout": POLL_TIMEOUT,
            # `callback_query` — карантин и кнопки оплаты, `pre_checkout_query` — звёзды
            "allowed_updates": ["message", "callback_query", "pre_checkout_query"],
        }
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


async def handle_giveaway(
    session: aiohttp.ClientSession,
    bot: BotClient,
    chat_id: int,
    telegram_id: int,
    giveaway_id: int,
    username: Optional[str] = None,
) -> None:
    """Участие в розыгрыше: проверяем подписку на канал и записываем участника.

    Условие «быть подписанным» проверяет сам Telegram (`getChatMember`) — накрутка
    «привёл друга» не нужна: фейковый аккаунт без подписки не пройдёт.
    """
    channel = (settings.TELEGRAM_CHANNEL or "").strip()
    if channel:
        member = await bot.call("getChatMember", chat_id=channel, user_id=telegram_id)
        status = (member or {}).get("status") if isinstance(member, dict) else None
        if status not in ("creator", "administrator", "member", "restricted"):
            await bot.send(
                chat_id,
                f"Участие — для подписчиков {channel}. Подпишитесь и нажмите кнопку ещё раз.",
            )
            return

    data = await api_request(
        session,
        "POST",
        f"/api/v1/admin/telegram/giveaways/join?telegram_id={telegram_id}",
    )
    if not data or data.get("error"):
        await bot.send(chat_id, "Не удалось записать — попробуйте позже.")
        return

    status = data.get("status")
    if status == "unknown":
        await bot.send(
            chat_id,
            "Сначала войдите на сайт (кнопка «🔓 Войти на сайт»), потом вернитесь к розыгрышу.",
            keyboard=MAIN_KEYBOARD,
        )
        return
    if status == "none":
        await bot.send(chat_id, "Активных розыгрышей нет.")
        return
    if status == "already":
        await bot.send(
            chat_id,
            f"Вы уже участвуете: «{data.get('title')}». "
            f"Итоги: {str(data.get('ends_at') or '')[:16]} UTC.",
        )
        return

    await bot.send(
        chat_id,
        f"Готово: «{data.get('title')}», {data.get('prize_days')} дн. премиума.\n"
        f"Итоги: {str(data.get('ends_at') or '')[:16]} UTC.",
    )


async def send_stars_invoice(
    session: aiohttp.ClientSession,
    bot: BotClient,
    chat_id: int,
    plan_code: str,
    promo_id: int = 0,
) -> None:
    """Выставляет счёт на оплату звёздами.

    Сумму берём из витрины API, а не из кнопки: если акцию успели выключить, человек
    заплатит актуальную цену, а не ту, что осталась в старом сообщении.
    """
    data = await api_request(session, "GET", "/api/v1/plans")
    plan = next(
        (item for item in (data or {}).get("plans") or [] if item.get("code") == plan_code),
        None,
    )
    stars = (plan or {}).get("stars_now") or (plan or {}).get("price_stars")
    if not plan or not stars:
        await bot.send(
            chat_id, "Этот тариф пока недоступен для оплаты звёздами — загляните позже."
        )
        return

    await bot.call(
        "sendInvoice",
        chat_id=chat_id,
        title=f"Подписка Dredger — {plan.get('title')}",
        description=(plan.get("description") or f"Доступ на {plan.get('days')} дн.")[:255],
        payload=f"{plan_code}:{promo_id or 0}",
        currency="XTR",
        prices=[{"label": plan.get("title") or plan_code, "amount": int(stars)}],
    )


async def handle_pre_checkout(bot: BotClient, query: dict) -> None:
    """Telegram спрашивает подтверждение перед списанием звёзд — подтверждаем."""
    await bot.call("answerPreCheckoutQuery", pre_checkout_query_id=query.get("id"), ok=True)


async def handle_successful_payment(
    session: aiohttp.ClientSession,
    bot: BotClient,
    chat_id: int,
    telegram_id: int,
    payment: dict,
) -> None:
    """Оплата звёздами прошла: зачисляем её через API и включаем подписку.

    `payments` идемпотентен по `charge_id`: повторная доставка апдейта не продлит
    подписку второй раз.
    """
    payload = (payment.get("invoice_payload") or "").strip()
    plan_code, _, promo_raw = payload.partition(":")
    charge = payment.get("telegram_payment_charge_id") or ""
    stars = int(payment.get("total_amount") or 0)
    promo_id = int(promo_raw) if promo_raw.isdigit() and int(promo_raw) > 0 else None

    # Пишем в лог: если оплата не зачислится, у нас останется, что именно пришло
    logger.info(
        "Оплата звёздами: payload=%s stars=%s charge=%s",
        payload or "—",
        stars,
        charge or "—",
    )

    body = {
        "telegram_id": telegram_id,
        "plan_code": plan_code or "month",
        "stars": stars,
        "charge_id": charge,
        "promo_id": promo_id,
    }
    data = None
    # Две попытки: чаще всего это разовый сбой API/сети. Повтор безопасен —
    # зачисление идемпотентно по charge_id и не продлит подписку дважды.
    for attempt in (1, 2):
        data = await api_request(session, "POST", "/api/v1/billing/stars", json=body)
        if data and not data.get("error"):
            break
        logger.warning("Зачисление оплаты не прошло (попытка %s): %s", attempt, data)
        await asyncio.sleep(3)

    if not data or data.get("error"):
        await bot.send(
            chat_id,
            "Оплата прошла, но доступ не включился. Напишите администратору — включим вручную.",
        )
        return

    until = str(data.get("premium_until") or "")[:10]
    await bot.send(
        chat_id,
        f"Оплата {stars} ⭐ получена. Подписка до {until}.",
        keyboard=MAIN_KEYBOARD,
    )


async def handle_callback(
    session: aiohttp.ClientSession, bot: BotClient, callback: dict
) -> None:
    """Кнопки карантина: админ подтверждает, отклоняет или откладывает автопост.

    Данные кнопки приходят как `post:publish:<id>` — простая схема, чтобы её было
    видно в логах и легко отлаживать. Сообщение в ЛС после решения правим: иначе
    непонятно, обработана кнопка или нет.
    """
    callback_id = callback.get("id")
    data = (callback.get("data") or "").strip()
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    parts = data.split(":")
    # Оплата: кнопка «<тариф> — N ⭐» под витриной `/subscribe`
    if data.startswith("buy:") and len(parts) == 3 and chat_id:
        if callback_id:
            await bot.call("answerCallbackQuery", callback_query_id=callback_id)
        promo_id = int(parts[2]) if parts[2].isdigit() else 0
        await send_stars_invoice(session, bot, chat_id, parts[1], promo_id)
        return

    # Крипта: «🪙 Оплатить криптой» → список тарифов с ценой в USDT
    if data.startswith("crypto:") and chat_id:
        if callback_id:
            await bot.call("answerCallbackQuery", callback_query_id=callback_id)
        plans = await api_request(session, "GET", "/api/v1/plans")
        await bot.send(
            chat_id,
            "Оплата криптой (USDT). Выберите тариф — пришлю ссылку на оплату:",
            keyboard=crypto_keyboard(plans) or MAIN_KEYBOARD,
        )
        return

    # Счёт по выбранному тарифу: Crypto Pay выставляет сумму в USDT
    if data.startswith("cryptobuy:") and len(parts) == 3 and chat_id:
        if callback_id:
            await bot.call("answerCallbackQuery", callback_query_id=callback_id)
        promo_id = int(parts[2]) if parts[2].isdigit() else 0
        await send_crypto_invoice(session, bot, chat_id, parts[1], promo_id)
        return

    # «Я оплатил»: спрашиваем статус счёта у Crypto Pay и выдаём доступ
    if data.startswith("cryptocheck:") and len(parts) == 2 and chat_id:
        if callback_id:
            await bot.call("answerCallbackQuery", callback_query_id=callback_id)
        await check_crypto_payment(session, bot, chat_id, int(parts[1]))
        return

    if len(parts) != 3 or parts[0] != "post" or not chat_id:
        if callback_id:
            await bot.call("answerCallbackQuery", callback_query_id=callback_id)
        return

    action, post_id = parts[1], parts[2]
    if action not in ("publish", "reject", "later"):
        if callback_id:
            await bot.call("answerCallbackQuery", callback_query_id=callback_id)
        return

    path = {
        "publish": f"/api/v1/admin/telegram/posts/{post_id}/approve",
        "reject": f"/api/v1/admin/telegram/posts/{post_id}/reject",
        "later": f"/api/v1/admin/telegram/posts/{post_id}/later?hours=2",
    }[action]
    result = await api_request(session, "POST", path)

    done = {
        "publish": "Черновик опубликован в канале.",
        "reject": "Черновик отклонён, в канал не пошёл.",
        "later": "Отложено на 2 часа — вернусь к нему по расписанию.",
    }[action]
    if not result or result.get("error"):
        done = "Не получилось: API недоступен, попробуйте кнопку ещё раз."

    if callback_id:
        await bot.call("answerCallbackQuery", callback_query_id=callback_id, text=done)
    if message_id:
        await bot.call(
            "editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={}
        )
    await bot.send(chat_id, done)


async def handle_message(session: aiohttp.ClientSession, bot: BotClient, message: dict) -> None:
    """Обработка одного сообщения: оплата, команды и кнопки клавиатуры."""
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    sender = message.get("from") or {}
    telegram_id = sender.get("id")

    # Оплата звёздами приходит отдельным полем (текста в таком сообщении нет)
    payment = message.get("successful_payment")
    if payment and chat_id and telegram_id:
        await handle_successful_payment(session, bot, chat_id, telegram_id, payment)
        return

    if not text or not chat_id or not telegram_id:
        return

    username = sender.get("username")
    command = text.split()[0].split("@")[0].lower()
    # Deep-link из поста-анонса розыгрыша: /start giveaway_5
    start_payload = text.split(" ", 1)[1].strip() if " " in text else ""

    # Кнопки клавиатуры приходят обычным текстом — сводим их к командам
    if text.startswith("🔓"):
        command = "/link"
    elif text.startswith("⭐"):
        command = "/status"
    elif text.startswith("💳"):
        command = "/subscribe"
    elif text.startswith("❓"):
        command = "/help"

    if command == "/start" and start_payload.startswith("giveaway_"):
        try:
            giveaway_id = int(start_payload.split("_", 1)[1])
        except ValueError:
            giveaway_id = 0
        if giveaway_id:
            await handle_giveaway(session, bot, chat_id, telegram_id, giveaway_id, username)
            return

    if command in ("/start", "/help"):
        await bot.send(
            chat_id,
            "Dredger — архив. Вход на сайт — по ссылке (живёт 10 минут).\n\n" + HELP_TEXT,
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
            "Ссылка для входа (10 минут):\n" f"{data['url']}",
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
                "Аккаунта нет — нажмите «🔓 Войти на сайт».",
                keyboard=MAIN_KEYBOARD,
            )
            return
        until = (data.get("premium_until") or "")[:10]
        if data.get("premium_active"):
            await bot.send(chat_id, f"Подписка активна до {until}.")
        else:
            await bot.send(chat_id, "Подписка не активна. Тарифы — /subscribe.")
        return

    if command == "/subscribe":
        # Тарифы и кнопки оплаты берём из API: бот и сайт показывают одни и те же цены
        data = await api_request(session, "GET", "/api/v1/plans")
        await bot.send(
            chat_id, plans_text(data), keyboard=plans_keyboard(data) or MAIN_KEYBOARD
        )
        return

    if command == "/id":
        # Нужен для настройки карантина автопоста: TELEGRAM_ADMIN_CHAT_ID в .env
        await bot.send(chat_id, f"Ваш Telegram ID: {telegram_id}")
        return

    await bot.send(chat_id, "Не понял команду. Список — /help.", keyboard=MAIN_KEYBOARD)


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
                    if update.get("pre_checkout_query"):
                        await handle_pre_checkout(bot, update["pre_checkout_query"])
                    elif update.get("callback_query"):
                        await handle_callback(session, bot, update["callback_query"])
                    else:
                        await handle_message(session, bot, update.get("message") or {})
                except Exception:  # noqa: BLE001 — бот не должен падать из-за одного сообщения
                    logger.exception("Ошибка обработки обновления")
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено вручную")



