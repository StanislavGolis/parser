# src/main.py
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.core.redis_client import redis_client
from src.parsers.dvach import DvachParser

# Текущая доска (заполняется главным циклом, читается heartbeat-таском)
CURRENT_BOARD: Optional[str] = None

HEARTBEAT_TTL = 45  # секунд; таск обновляет ключи каждые 15 сек


async def init_db():
    """Создаёт движок и фабрику async-сессий.

    Схема БД управляется Alembic (`alembic upgrade head`); create_all не используется.
    """
    engine = create_async_engine(settings.DATABASE_URL, echo=True, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session


async def parser_is_enabled() -> bool:
    return (await redis_client.get("parser:enabled")) == "1"


async def heartbeat_loop() -> None:
    """Фоновый heartbeat: ключи parser:up / parser:alive / current_board всегда свежие."""
    global CURRENT_BOARD
    try:
        while True:
            await redis_client.set("parser:up", "1", ex=HEARTBEAT_TTL + 15)
            if await parser_is_enabled():
                await redis_client.set("parser:alive", "1", ex=HEARTBEAT_TTL)
                if CURRENT_BOARD:
                    await redis_client.set("parser:current_board", CURRENT_BOARD, ex=HEARTBEAT_TTL)
            else:
                await redis_client.delete("parser:alive")
                await redis_client.delete("parser:current_board")
                await redis_client.delete("parser:progress")
            await asyncio.sleep(15)
    except asyncio.CancelledError:
        pass


async def main():
    print("[run] Запуск парсера-демона...")
    print(f"[dir] Хранилище: {settings.STORAGE_PATH}")
    print(f"[list] Доски по умолчанию: {', '.join(settings.BOARDS_TO_PARSE)}")
    print("[info] Парсинг управляется из админки: кнопка «Запустить/Остановить» (Redis parser:enabled)")
    print("-" * 50)

    async_session = await init_db()
    last_reconcile: Optional[datetime] = None

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    try:
        while True:
            try:
                if not await parser_is_enabled():
                    # На паузе: ничего не парсим, ждём кнопку в админке
                    last_reconcile = None  # при запуске снова сделаем сверку
                    print("[pause] Парсер на паузе (жду команды из админки)...")
                    await asyncio.sleep(5)
                    continue

                async with async_session() as session:
                    parser = DvachParser(session)
                    await parser.__aenter__()
                    try:
                        # Создаём доски из конфигурации заранее (первый запуск)
                        if last_reconcile is None:
                            await parser.ensure_configured_boards()

                        # Сверка данных после старта/возобновления
                        if last_reconcile is None:
                            await parser.run_reconciliation()
                            last_reconcile = datetime.utcnow()

                        # Проверка остановки между тредами (кнопка в админке)
                        async def _check_stop() -> bool:
                            return not await parser_is_enabled()

                        parser.stop_check = _check_stop

                        # Фаза A: каталоги всех парсируемых досок (дёшево,
                        # 1 запрос на доску) → очередь докачки в БД
                        plan = await parser.build_scan_plan()
                        started = datetime.utcnow()
                        budget = settings.PARSE_CYCLE_BUDGET_MINUTES

                        # Фаза B: докачка по очереди (чередование досок) — сначала
                        # свежие изменения, затем давно не сканировавшиеся (LRU).
                        # Очередь живёт в БД, поэтому перезапуск процесса её не
                        # теряет, а бюджет цикла не даёт одному циклу «залипнуть».
                        for done, (board_slug, thread_id, reason) in enumerate(plan, start=1):
                            if await _check_stop():
                                print("[stop] Парсинг остановлен командой из админки")
                                break
                            if budget > 0 and (
                                datetime.utcnow() - started
                            ).total_seconds() >= budget * 60:
                                print(
                                    f"[budget] Цикл идёт больше {budget} мин — "
                                    f"остаток очереди ({len(plan) - done + 1}) в следующем цикле"
                                )
                                break

                            global CURRENT_BOARD
                            CURRENT_BOARD = board_slug

                            await parser.scan_thread(board_slug, thread_id, reason)
                    finally:
                        parser.stop_check = None
                        await parser.__aexit__(None, None, None)
                CURRENT_BOARD = None

                # Периодическая сверка
                if (
                    settings.RECONCILE_MINUTES > 0
                    and last_reconcile
                    and (datetime.utcnow() - last_reconcile).total_seconds() / 60 >= settings.RECONCILE_MINUTES
                ):
                    async with async_session() as session:
                        parser = DvachParser(session)
                        await parser.__aenter__()
                        try:
                            await parser.run_reconciliation()
                        finally:
                            await parser.__aexit__(None, None, None)
                    last_reconcile = datetime.utcnow()

                print(f"\n[wait] Ожидание {settings.PARSE_INTERVAL} секунд до следующего цикла...\n")
                await asyncio.sleep(settings.PARSE_INTERVAL)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[err] Критическая ошибка: {e}")
                await asyncio.sleep(5)  # Пауза перед перезапуском
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass
        # Закрываем Redis-пул: иначе при остановке процесса redis-py ругается
        # «Event loop is closed» в AbstractConnection.__del__
        try:
            await redis_client.aclose()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[bye] Остановка парсера...")



if __name__ == "__main__":
    asyncio.run(main())