# src/tools/telegram_autopost.py
"""Планировщик Telegram-канала: отложенные посты, рубрики автопоста, итоги розыгрышей.

Отдельный процесс (сервис `telegram-publisher` в docker-compose) — по образцу
`telegram_bot.py`. Раз в минуту делает три вещи:

1. **расписание** — публикует посты со статусом `scheduled`, у которых наступило время;
2. **автопост** — выбирает рубрику, которой пора выйти («Свежее», «Раздел дня»,
   «Топ недели»), собирает пост и отправляет его в карантин (в ЛС админам бота), если
   автопостинг включён, сейчас не «окно тишины», суточный лимит не исчерпан и с
   прошлого автопоста прошёл достаточный интервал;
3. **розыгрыши** — подводит итоги у тех, чей срок истёк: выбирает победителей,
   выдаёт премиум и публикует пост-итоги.

Сборкой постов занимаются рубрики (`src/services/telegram_rubrics.py`), публикацией
в канал — сервис (`src/services/telegram_service.py`); воркер отвечает только за
время, порядок и выбор рубрики.

Запуск: `python -m src.tools.telegram_autopost`
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session_factory
from src.core.models import TelegramPost
from src.services import telegram_api, telegram_rubrics, telegram_service
from src.services.s3_storage import S3Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("telegram_autopost")

# Как часто просыпаемся и как долго ждём, если Telegram/БД недоступны
CHECK_INTERVAL = 60
ERROR_SLEEP = 180
# Между автопостами должно пройти не меньше этого (иначе канал «заспамится»)
MIN_GAP_HOURS = 3


async def last_publish_at(session) -> datetime | None:
    """Когда в канал уходил последний пост (для интервала между автопостами)."""
    return (
        await session.execute(
            select(TelegramPost.published_at)
            .where(TelegramPost.status == "published", TelegramPost.published_at.isnot(None))
            .order_by(TelegramPost.published_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def has_open_draft(session) -> bool:
    """Есть ли черновик, по которому админ ещё не принял решение."""
    return (
        await session.execute(
            select(TelegramPost.id).where(TelegramPost.status == "draft").limit(1)
        )
    ).scalar_one_or_none() is not None


async def run_once(s3: S3Storage) -> None:
    """Один проход планировщика: расписание, автопост, итоги розыгрышей."""
    async with async_session_factory() as session:
        # 1. Отложенные посты
        for post in await telegram_service.due_posts(session):
            published = await telegram_service.publish_scheduled(session, s3, post)
            logger.info("Отложенный пост #%s: %s", published.id, published.status)

        # 2. Автопост: выбираем рубрику, которой пора выйти, и собираем черновик
        row = await telegram_service.get_autopost(session)
        allowed, reason = await telegram_service.autopost_allowed(session, row)
        if allowed:
            gap = timedelta(hours=max(MIN_GAP_HOURS, 24 // max(1, row.posts_per_day)))
            last_at = await last_publish_at(session)
            too_soon = bool(last_at and datetime.utcnow() - last_at < gap)
            rubric = await telegram_rubrics.pick_rubric(session)
            if await has_open_draft(session):
                logger.info("Автопост пропущен: ждём решения по прошлому черновику")
            elif too_soon:
                logger.info("Автопост пропущен: раньше, чем через %s", gap)
            elif rubric is None:
                logger.info("Автопост пропущен: нет включённых рубрик, которым пора выходить")
            else:
                post = await telegram_rubrics.make_post(session, s3, rubric, row)
                if post is None:
                    logger.info("Рубрика %s: показывать нечего, пропускаем", rubric.code)
                else:
                    logger.info(
                        "Автопост: рубрика %s → пост #%s (%s)",
                        rubric.code,
                        post.id,
                        post.status,
                    )
        else:
            logger.info("Автопост недоступен: %s", reason)

        # 3. Итоги розыгрышей
        for giveaway in await telegram_service.giveaways_to_draw(session):
            winners = await telegram_service.draw_winners(session, giveaway, count=1)
            logger.info("Розыгрыш #%s: победителей — %s", giveaway.id, len(winners))
            if telegram_api.is_configured():
                await telegram_service.publish_giveaway_results(session, giveaway)


async def main() -> None:
    """Бесконечный цикл планировщика."""
    if not telegram_api.is_configured():
        logger.warning(
            "TELEGRAM_BOT_TOKEN или TELEGRAM_CHANNEL не заданы: отложенные посты "
            "и автопост не уйдут. Проверьте .env и перезапустите сервис."
        )

    s3 = S3Storage()
    logger.info("Планировщик канала запущен (шаг %s c)", CHECK_INTERVAL)
    while True:
        try:
            await run_once(s3)
        except Exception:  # noqa: BLE001 — воркер не должен умирать от одной ошибки
            logger.exception("Ошибка прохода планировщика")
            await asyncio.sleep(ERROR_SLEEP)
            continue
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
