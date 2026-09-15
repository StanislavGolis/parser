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
    "/id — ваш Telegram ID (нужен для настройки карантина)\n"
    "/help — эта справка\n\n"
    "Сайт закрытый: без подписки доступны только несколько файлов.\n"
    "Новинки и розыгрыши — в канале: кнопка «Участвовать» под постом-анонсом\n"
    "записывает вас в розыгрыш премиума (нужна подписка на канал).\n\n"
    "Если нашли запрещённый контент — нажмите «пожаловаться» в просмотре файла:\n"
    "жалоба уходит модератору, а материалы с несовершеннолетними закрываются сразу.\n"
    "Правообладателям: dmca@dredg.ru (удаление контента — в течение 48 часов)."
)

SUBSCRIBE_TEXT = (
    "Тарифы готовятся к запуску.\n\n"
    "Планируем: месяц, год и «навсегда» — оплата криптой (быстро и без блокировок). "
    "Пока доступ можно получить по заявке: напишите администратору, и мы включим его "
    "вручную."
)


def plans_text(data: Optional[dict]) -> str:
    """Витрина тарифов для `/subscribe`: цены в рублях и звёздах + условия акций.

    Данные приходят из API (`GET /api/v1/plans`) — бот и сайт показывают одни и те же
    цены, поэтому «акция включилась» не превращается в два разных ответа. Названия и
    описания акций задаются в админке, здесь они просто выводятся как есть.
    """
    if not data or not data.get("plans"):
        return SUBSCRIBE_TEXT

    lines = ["Подписка Dredger — приватные разделы, скачивание и без рекламы.\n"]

    for plan in data["plans"]:
        title = plan.get("title") or plan.get("code")
        stars = plan.get("stars_now") or plan.get("price_stars")
        if not stars:
            # Сетка продаётся только за звёзды: тариф без цены в звёздах не показываем
            continue
        base_stars = plan.get("price_stars")
        days = int(plan.get("days") or 0)
        if plan.get("is_forever"):
            term = "без срока"
        elif days >= 30 and days % 30 == 0:
            term = f"{days // 30} мес."
        else:
            term = f"{days} дн."
        tail = (
            f" (вместо {int(base_stars)} ⭐)"
            if base_stars and int(base_stars) != int(stars)
            else ""
        )
        lines.append(f"• {title} — {int(stars)} ⭐{tail}, {term}")

    for promo in data.get("promos") or []:
        left: list[str] = []
        if promo.get("days_left") is not None:
            left.append(f"{promo['days_left']} дн.")
        if promo.get("paid_left") is not None:
            left.append(f"{promo['paid_left']} оплат")
        tail = f" Осталось: {', '.join(left)}." if left else ""
        description = ""
        if promo.get("description"):
            text = promo["description"].strip()
            description = "\n" + (text if text.endswith((".", "!", "?")) else f"{text}.")
        lines.append(
            f"\n{promo.get('title') or 'Акция'}: −{promo['percent']}% на тарифы."
            f"{description}{tail}"
        )

    lines.append("\nОплата звёздами — кнопками ниже. Крипта появится позже.")
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
    return {"inline_keyboard": rows} if rows else None


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
                f"Чтобы участвовать, подпишитесь на канал {channel} и нажмите /start "
                f"giveaway_{giveaway_id} ещё раз.",
            )
            return

    data = await api_request(
        session,
        "POST",
        f"/api/v1/admin/telegram/giveaways/join?telegram_id={telegram_id}",
    )
    if not data or data.get("error"):
        await bot.send(chat_id, "Не получилось записать вас в розыгрыш. Попробуйте позже.")
        return

    status = data.get("status")
    if status == "unknown":
        await bot.send(
            chat_id,
            "Сначала заведите аккаунт: нажмите «🔓 Войти на сайт», откройте архив "
            "и вернитесь к розыгрышу.",
            keyboard=MAIN_KEYBOARD,
        )
        return
    if status == "none":
        await bot.send(chat_id, "Сейчас активных розыгрышей нет. Заглядывайте в канал!")
        return
    if status == "already":
        await bot.send(
            chat_id,
            f"Вы уже участвуете в розыгрыше «{data.get('title')}». "
            f"Итоги: {str(data.get('ends_at') or '')[:16]} UTC.",
        )
        return

    await bot.send(
        chat_id,
        f"Готово! Вы участвуете в розыгрыше «{data.get('title')}» "
        f"на {data.get('prize_days')} дн. премиума.\n"
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
            "Оплата прошла, но доступ не включился автоматически. "
            "Напишите администратору — включим вручную.",
        )
        return

    until = str(data.get("premium_until") or "")[:10]
    await bot.send(
        chat_id,
        f"Спасибо! Оплата {stars} ⭐ получена.\n"
        f"Подписка активна до {until}.\nСсылка на сайт — /link",
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



